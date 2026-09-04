# System Architecture
## SIH26158 — Single-Pass Drone Video to Accurate 3D Model Generation System

Version 1.0 — 2026-09-04. Traces to `01-SRS-requirements.md`.

---

## 1. The decision that determines everything: the 900-second budget

R-O2 says **< 15 minutes for a 10-minute video**. That is **900 seconds** of wall clock, for a
video containing roughly **18,000 frames** at 4K/30fps.

This single number eliminates the obvious approach.

| Candidate spine | Verdict |
|---|---|
| Full classical photogrammetry (COLMAP/ODM: SIFT → exhaustive match → incremental SfM → MVS) | **Rejected.** This workload is conventionally measured in *hours*. GLOMAP is ~an order of magnitude faster than COLMAP and FastMap claims up to 10× faster again — still not 900 s including dense + mesh + texture. |
| Per-scene neural training (NeRF / 3D Gaussian Splatting) | **Rejected as the geometry path.** Per-scene optimisation plus mesh extraction spends the budget twice over. Retained only as an optional visualisation branch. |
| **Learned feed-forward geometry + classical export tail** | **Selected.** A transformer regresses cameras and dense metric geometry in a bounded number of forward passes. Cost is roughly linear in frame count and predictable. |

**Therefore: the spine is a feed-forward multi-view geometry model, and classical photogrammetry
tooling is demoted to the refinement-and-export tail, where it is fast and unmatched.**

This conclusion is forced by arithmetic, and it will be *measured* not asserted — the baseline
experiment (EXP-01, §9) times the classical pipeline explicitly so the design record contains
evidence rather than an argument.

---

## 2. Model selection: MapAnything, and why not VGGT

| | VGGT | **MapAnything** | Pi3 | Depth Anything 3 |
|---|---|---|---|---|
| Code licence | custom AUP | **Apache-2.0** | — | Apache-2.0 |
| Weights licence | NC / "commercial except military" | **Apache-2.0** (`-apache` ckpt) | non-commercial | Apache-2.0 (BASE/SMALL/METRIC-LARGE) |
| **Usable for NTRO** | **NO** | **YES** | NO | YES |
| Metric scale | no (scale-ambiguous) | **yes, native** | no | metric variant |
| Accepts priors | no | **intrinsics, poses, depth, is_metric_scale** | no | pose-conditioned |

**Primary technical reason for MapAnything** (this is the load-bearing argument):

1. **It outputs metric geometry natively.** Its factored representation is depth maps + ray maps +
   camera poses + *an explicit metric scale factor*. VGGT and Pi3 are scale-ambiguous, so metric
   scale has to be bolted on afterwards from GPS alone. R-O3 is a metric requirement; starting
   metric is a structural advantage.
2. **It accepts geometric priors as first-class input** — `intrinsics` (or `ray_directions`),
   `camera_poses`, `depth_z`, and `is_metric_scale` flags. This is precisely the injection point
   for GPS, IMU, barometric altitude, and known intrinsics (R-I2–R-I7). No other candidate exposes
   this cleanly. *Constraint: intrinsics and ray_directions are mutually exclusive (redundant).*
3. It covers uncalibrated SfM **and** calibrated MVS **and** depth completion in one model, which
   collapses several pipeline stages into one.

**Secondary reason — deployment legality (R-NF5).** VGGT's AUP bans *"Military, warfare, nuclear
industries or applications, espionage"*. For an NTRO deliverable that is disqualifying. This is a
genuine finding and belongs in the submission, but note the ordering: MapAnything wins on
technical merit first, and is *also* legally clean. The architecture does not collapse if a judge
reads the licence differently.

> **Honest caveat, to be measured not assumed.** The Apache checkpoint is trained on six datasets;
> the CC-BY-NC checkpoint on thirteen. The Apache weights are therefore likely **weaker**. Plan:
> benchmark both (EXP-02), use the NC checkpoint only for internal ablation, and report the
> **Apache** configuration as the deployable system. If the gap is material, say so openly.

---

## 3. Pipeline overview

```
                 video + GPS + flight metadata (schema unknown until event)
                                     |
  ┌──────────────────────────────────▼──────────────────────────────────┐
  │ S1  INGEST & CONDITIONING                              budget 120 s │
  │  demux → NVDEC decode → metadata auto-detect (SRT/CSV/EXIF/log)     │
  │  → time-sync GPS to frames → blur & redundancy-aware keyframing     │
  │  → intrinsics resolution (EXIF/SRT + sensor DB, else self-calib)    │
  │  OUT: ~600 keyframes + per-frame pose prior + K                     │
  └──────────────────────────────────┬──────────────────────────────────┘
                                     |
  ┌──────────────────────────────────▼──────────────────────────────────┐
  │ S2  MASKING                             (overlapped with S1/S3)     │
  │  dynamic-object segmentation → per-frame validity mask (R-C4)       │
  └──────────────────────────────────┬──────────────────────────────────┘
                                     |
  ┌──────────────────────────────────▼──────────────────────────────────┐
  │ S3  GEOMETRY  (the spine)                              budget 400 s │
  │  chunk keyframes (≈48 views, ≈8 overlap) → MapAnything per chunk    │
  │  with GPS/intrinsics priors → per-chunk metric points + poses       │
  │  → inter-chunk Sim(3) via shared frames → global pose graph         │
  │  OUT: globally consistent metric point cloud + camera trajectory    │
  └──────────────────────────────────┬──────────────────────────────────┘
                                     |
  ┌──────────────────────────────────▼──────────────────────────────────┐
  │ S4  GEOREFERENCE                                        budget 60 s │
  │  robust Sim(3) trajectory→GPS (RANSAC+Umeyama) → ENU → UTM          │
  │  → ellipsoid-to-geoid height correction → optional GPS-prior BA     │
  │  OUT: model in a real CRS, with an uncertainty estimate             │
  └──────────────────────────────────┬──────────────────────────────────┘
                                     |
  ┌──────────────────────────────────▼──────────────────────────────────┐
  │ S5  SURFACE, TEXTURE, COMPLETION                       budget 250 s │
  │  outlier filter → normals → Poisson/TSDF mesh → texture from best   │
  │  views → occlusion closure, confidence-tagged (R-C7)                │
  └──────────────────────────────────┬──────────────────────────────────┘
                                     |
  ┌──────────────────────────────────▼──────────────────────────────────┐
  │ S6  EXPORT & VIEW                                       budget 60 s │
  │  OBJ · PLY · LAS · GeoTIFF(DSM+ortho) · GLB/glTF · FBX  + viewer    │
  └─────────────────────────────────────────────────────────────────────┘
                                             reserve 10 s   TOTAL 900 s
```

---

## 4. S1 — Ingest and conditioning

### 4.1 Keyframe selection — the most important lever in the system

18,000 frames → **~600 keyframes**. Nothing else in the design changes runtime as much.

The 600 figure is not arbitrary: OpenDroneMap's own `--video-limit` defaults to **500** frames
extracted from video, which is a tuned prior from the people who have done this longest. We take
that as the anchor and treat 400–800 as the tuning band (EXP-03).

Selection is a scored trade-off, not uniform sampling:

| Signal | Purpose | Requirement |
|---|---|---|
| **Sharpness** (variance of Laplacian / Tenengrad) | reject motion-blurred and compression-smeared frames | R-C2 |
| **Baseline** (GPS-derived translation since last keyframe) | guarantee triangulation geometry; avoid degenerate near-zero-baseline pairs | R-O3 |
| **Coverage / overlap** | maintain sufficient consecutive overlap for the model to link views | R-O4 |
| **Exposure stability** | prefer frames without abrupt exposure change | R-C3 |

Rejecting blurred frames *is* the mitigation for R-C2: rather than de-blurring, we exploit the
enormous redundancy of a 30 fps video and simply keep the sharp frames. A 10-minute video gives us
30× more candidates than we need — this is the cheapest robustness win available.

### 4.2 Metadata auto-detection (R-NF4)

Because the dataset schema is unknown until the event, ingestion is a **chain of responsibility**:
try DJI SRT sidecar → embedded subtitle track → per-frame EXIF (if frames supplied) → flight-log
CSV → MAVLink/ULog → user-supplied CSV. First parser that yields a plausible monotonic track with
sane lat/lon/alt wins. Every parser normalises to one internal schema:

```
FrameTelemetry: t_us, lat, lon, alt_ellipsoid, alt_rel, alt_baro?,
                yaw?, pitch?, roll?, focal_mm?, fov?, iso?, shutter?, quality_flags
```

If GPS is sparser than frames (common — some drones log at 1 Hz against 30 fps video), it is
interpolated in **ENU**, never in raw lat/lon degrees, and with an explicit time offset estimated
by correlating GPS speed against visual optical-flow magnitude.

### 4.3 Intrinsics when unknown (R-I6)

Ladder, in order: explicit user input → SRT/EXIF focal length + sensor-size database →
`f_px = f_mm × image_width_px / sensor_width_mm` → fall back to the model's own intrinsics
estimation → last resort, self-calibration during bundle adjustment.

---

## 5. S3 — Geometry spine and the chunking strategy

A 10-minute flight cannot go through one forward pass. Documented memory-efficient inference
reaches ~2000 views only at ~140 GB; our target is a single 24 GB-class GPU.

**Sliding chunks with overlap:**
- chunk size ≈ 48 keyframes, stride ≈ 40 → **8 shared frames** between neighbours
- ~600 keyframes → **~15 chunks**
- each chunk is internally globally-consistent (the model solves all views jointly)
- neighbouring chunks are stitched by a Sim(3) estimated from their shared frames' poses,
  then the whole chain is refined in a pose graph

**Why overlap-stitching rather than sequential chaining:** chaining accumulates drift linearly. A
pose graph with GPS as an absolute anchor at every node bounds drift globally — the classic
SLAM insight, and the reason a single pass over a 3 km flight does not bend.

Priors passed to every chunk: resolved intrinsics, GPS-derived `camera_poses` where trustworthy,
and `is_metric_scale`. This is where R-I2–R-I7 physically enter the geometry.

---

## 6. S4 — Georeferencing: where ≤ 1 m is won or lost

### 6.1 Two-stage approach

1. **Robust similarity fit.** Estimate Sim(3) mapping the reconstructed camera trajectory onto the
   GPS track using **RANSAC + Umeyama with a self-tuning (MAD-derived) inlier threshold**.
   *(Implements R-C5.)*

   > **Corrected by measurement (EXP-05).** The intuitive claim "RANSAC is more accurate" is
   > **false here** and the code says so explicitly. At realistic 0–2% wild-fix rates RANSAC is a
   > fraction of a percent *worse* than plain least squares — robustness costs efficiency. What it
   > actually buys is a **bounded worst case**: its error stays flat near 4.1 m however bad the GPS
   > gets, while least squares degrades without limit (5.4 m at a 35% outlier rate). For a system
   > whose input dataset is unknown until the day, that bound is the property worth paying for.
   >
   > A second, sharper lesson: **a fixed threshold below the noise floor is worse than no RANSAC
   > at all.** A hard-coded 1 m threshold scored 5.29 m against least squares' 4.08 m, because it
   > discarded 93% of good data to fit a lucky subset. The threshold is therefore derived from the
   > observed residual scale (1.4826 × MAD), never hard-coded.
2. **GPS-prior bundle adjustment.** Refine with GPS as a *weighted prior* on camera centres —
   weighted by reported DOP/accuracy — rather than as a hard constraint. GPS is noisy;
   photogrammetry gets relative geometry far more precisely than GNSS gets absolute position. The
   correct fusion trusts vision for shape and GPS for placement.

### 6.2 The vertical trap

GNSS altitude is **ellipsoidal (WGS84)**. Maps, DSMs and most reference data are **orthometric
(geoid)**. Over India the geoid separation is large — tens of metres — so ignoring or
double-applying it destroys the ≤1 m vertical budget by an order of magnitude while horizontal
error still looks fine. The conversion is applied explicitly and once, and asserted in tests
(T-ACC-04). Horizontal work is done in **UTM** (India spans zones 42N–47N), selected automatically
from the track centroid.

### 6.3 Accuracy budget (to be validated, not assumed)

**Measured, not estimated.** EXP-05 (`src/experiments/exp05_gps_noise.py`) simulates a 600-keyframe
single pass with a physically-motivated GNSS error model (Gauss–Markov correlated bias +
random walk + white noise), 40 trials per condition:

| GNSS class | RMSE 3D | RMSE H | RMSE V | R-O3 (≤ 1 m)? |
|---|---|---|---|---|
| Consumer | **4.12 m** | 2.42 m | 3.07 m | **FAIL** |
| SBAS | 1.86 m | 1.10 m | 1.37 m | **FAIL** |
| **RTK/PPK** | **0.097 m** | 0.078 m | 0.058 m | **PASS** |

**Three findings that change what we may claim:**

1. **Absolute ≤ 1 m is unreachable from consumer GPS — the limit is the sensor, not the
   algorithm.** No fitting method recovers accuracy the input never contained.
2. **More frames do not help.** Sweeping 50 → 2400 keyframes leaves error flat at ~4 m while a
   1/√N model would predict 3.9 → 0.6 m. The correlated bias does not average away over a single
   10-minute flight. *Any claim of "we average hundreds of GPS fixes, so we are sub-metre" is
   false, and this experiment exists to stop us making it.*
3. **Vertical is consistently the worst axis** (~1.7× horizontal) because satellites are only ever
   above the receiver. Altitude governs the budget — hence fusing barometric altitude (R-I5).

Remaining budget terms: relative visual geometry ≪ 1 m over a chunk; geoid mishandling would
contribute tens of metres and must be exactly zero.

**Consequence, stated plainly and repeated in every deliverable:**
(a) if the supplied dataset carries **RTK/PPK** (R-I7), ≤ 1 m absolute is comfortably achievable;
(b) if it does not, we report **relative/shape accuracy ≤ 1 m** — achievable, and what "accuracy
without GCPs" conventionally means — and state the absolute georeferencing error separately and
truthfully. The harness prints both, always. We will not hide behind the aligned number: on a
model with a real 2.68 m offset, ICP alignment reports **0.21 m**, flattering by 12.8×.

---

## 7. S5 — Surface, texture, and bounded completion

- **Outlier removal** → statistical + GPS-consistency filtering.
- **Meshing** → screened Poisson (watertight, handles noise) for structures; 2.5D grid for terrain
  and for the DSM/orthophoto products.
- **Texturing (R-F5, R-C3)** → per-face best-view selection scored on sharpness, viewing angle and
  distance, with exposure normalisation and seam levelling across the illumination changes of a
  single pass.
- **Occlusion closure (R-C7, bounded)** → detect vertical discontinuities at building edges;
  extrude footprints down to terrain (LoD1-style) to close walls the nadir pass never saw. **Every
  inferred face is tagged** `confidence=inferred` and is separately toggleable in the viewer and
  colour-coded in exports. Observed and invented geometry are never silently mixed.

---

## 8. Cross-cutting: dynamic objects, and the two-layer defence (R-C4)

1. **Semantic** — segment vehicles/people/animals per keyframe and mask them out before geometry.
2. **Geometric** — multi-view consistency: a static point reprojects consistently across views; a
   moving one does not. Points failing consistency are discarded regardless of semantic class.

The geometric layer is the important one: it needs no class list and therefore catches
animals, debris, and moving objects no detector was trained on. Semantics alone would be brittle
against exactly the unknown-dataset condition we face.

*Licence note:* the popular Ultralytics YOLO family is **AGPL-3.0**, which carries network-copyleft
obligations for a hosted service. Detector choice must respect R-NF5; the geometric layer is
licence-free and is the fallback.

---

## 9. Experiment register (design decisions become measurements)

| ID | Question | Method | Decides |
|---|---|---|---|
| **EXP-01** | Can classical actually hit 900 s? | Time ODM/COLMAP at fastest usable preset on 500–600 frames | Justifies §1 by evidence |
| **EXP-02** | Apache vs NC checkpoint quality gap | Both on identical scene; compare via harness | What we can honestly ship |
| **EXP-03** | Keyframe count vs accuracy/time | Sweep 300/450/600/800 | The main runtime lever |
| **EXP-04** | Chunk size / overlap vs drift | Sweep 32/48/64 views, 4/8/12 overlap | Global consistency |
| **EXP-05** | GPS noise vs final accuracy | Inject 1/3/5 m noise on synthetic data | R-C5 robustness curve |
| **EXP-06** | Does masking dynamics measurably help? | Ablate both layers | Justifies R-C4 cost |
| **EXP-07** | Geoid correction correctness | Assert against known control | Prevents the §6.2 failure |

Every experiment is scored by the **already-built and unit-tested** harness in `src/eval3d/`,
so results are comparable across the whole project.

---

## 10. Compute placement

Target is a single 24 GB-class GPU (L4/A100) — the deployable unit is deliberately **one GPU**,
because "needs 8 GPUs" is not an operationally credible answer for a field mapping system.

GCP is the intended production home, but **GPU quota is currently denied on the team's account**
(verified — `01-SRS` §9). The compute strategy and its fallbacks are in `03-plan-sdlc.md`.

---

## 11. Architectural risks, stated up front

| Risk | Severity | Mitigation |
|---|---|---|
| Non-RTK GPS makes absolute ≤1 m physically unreachable | **High** | §6.3 — report both numbers honestly; use RTK when supplied |
| Pure-nadir flight makes facades (R-F2) unobservable | **High** | Bounded, labelled completion (§7); state the physical limit |
| Apache checkpoint materially weaker than NC | Medium | EXP-02; ship Apache, report the gap |
| No GPU quota blocks timed benchmarking | **High** | Fallback ladder in `03-plan-sdlc.md` |
| Unknown metadata schema on the day | Medium | Chain-of-responsibility ingestion (§4.2) + a synthetic-format test suite |
| 900 s exceeded on 4K | Medium | Keyframe count and working resolution are configuration, not code (R-NF2) |
