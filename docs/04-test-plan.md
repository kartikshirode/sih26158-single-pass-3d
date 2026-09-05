# Test and Verification Plan
## SIH26158 — Single-Pass Drone Video to Accurate 3D Model Generation System

Version 1.0 — 2026-09-04. Every test ID here is referenced by `01-SRS-requirements.md`.

---

## 1. Principle

Accuracy (30%) + Completeness (20%) + Speed (20%) = **70% of the score, and all three are
objectively measurable.** So they are measured, continuously, by a harness that was built and
unit-tested *before* the pipeline it will judge. Design choices are then experiments rather than
opinions.

**Rule adopted for the whole project:** no accuracy or completeness figure is ever quoted unless it
came out of `src/eval3d/`. No hand-computed numbers in slides.

---

## 2. Test levels

| Level | What | Runs |
|---|---|---|
| L1 Unit | Pure functions: metrics, transforms, parsers, CRS maths | Every commit |
| L2 Component | One stage in isolation against a synthetic fixture | Every commit |
| L3 Integration | Full pipeline on a short synthetic clip | Every commit (smoke) |
| L4 System | Full pipeline on a full-length dataset, timed | Nightly / before milestones |
| L5 Acceptance | The PS's own targets, on unseen data | Phase gates + finale rehearsal |

---

## 3. Test register

### 3.1 Accuracy — R-O3, R-C5, R-C8 (30% of score)

| ID | Test | Method | Pass criterion |
|---|---|---|---|
| **T-ACC-01** | Absolute georeferenced accuracy | `evaluate(..., align=False)` vs GT in a real CRS | RMSE ≤ 1 m **with RTK**; otherwise report truthfully (see §5) |
| **T-ACC-02** | Shape accuracy | `evaluate(..., align=True, align_with_scale=False)` | RMSE ≤ 1 m |
| **T-ACC-03** | GNSS-noise robustness | EXP-05 sweep over GNSS classes and outlier rates | Error bounded, degrades gracefully |
| **T-ACC-04** | **Geoid correction** | Known control point, ellipsoidal vs orthometric | Vertical error < 0.1 m from this cause alone |
| **T-ACC-05** | **Metric scale** | Scale diagnostic from the harness | \|scale − 1\| < 1000 ppm |
| **T-ACC-06** | CRS/UTM zone selection | Track centroids across India (zones 42N–47N) | Correct EPSG chosen every time |

> **T-ACC-05 exists because of a specific benchmark trap.** The Tanks-and-Temples protocol aligns
> with a 7-DoF similarity (`with_scaling=True`), which *forgives scale error*. A model uniformly 5%
> too small scores **0.000 m** under that protocol and **1.083 m** under ours. Our aligner fits no
> scale, and reports the scale error as a first-class number. ETH3D, by contrast, performs no
> alignment at all — the closer analogue for absolute accuracy, and what our "absolute" mode
> reproduces.

### 3.2 Completeness — R-O4, R-F1…F5, R-C1, R-C7 (20% of score)

| ID | Test | Method | Pass criterion |
|---|---|---|---|
| **T-COMP-01** | Coverage vs observable ceiling | Recall from the harness, denominator = *observable* surface (EXP-08) | ≥ 90% of what was observable |
| **T-COMP-02** | Inferred geometry is labelled | Every face carries observed/inferred confidence | 100% tagged; viewer can hide inferred |
| **T-CONT-01…05** | Content classes present (terrain, facades+roofs, roads, vegetation, texture) | Per-class recall via labelled synthetic scene | Each class reconstructed where observable |

> **Completeness is reported against two denominators**, always: (a) surface the flight could
> physically observe, and (b) the whole scene. EXP-08 shows a nadir pass observes only 14.3% of
> along-track facade surface — reporting (b) alone would penalise us for physics, and reporting
> (a) alone would hide a real limitation. Both, labelled.

### 3.3 Speed — R-O2, R-C6 (20% of score)

| ID | Test | Method | Pass criterion |
|---|---|---|---|
| **T-PERF-01** | End-to-end wall clock | 10-min 4K video, single 24 GB GPU, cold start | **< 900 s** |
| **T-PERF-02** | Per-stage budget | Run manifest timings vs architecture §3 allocation | No stage over budget without a recorded decision |
| **T-PERF-03** | Scalability | 1, 5, 10, 20, 30-min inputs | Roughly linear; no memory blow-up |
| **T-PERF-04** | Degradation ladder | Each quality preset timed in advance | Every preset's runtime known before the finale |

### 3.4 Robustness — R-C1…C4, R-NF4

| ID | Test | Method | Pass criterion |
|---|---|---|---|
| **T-ROB-01** | Single-pass / low overlap | Synthetic single strip | Completes; degrades gracefully, never crashes |
| **T-ROB-02** | Motion blur & compression | Inject blur + heavy re-encode | Blurred frames rejected; accuracy holds |
| **T-ROB-03** | Illumination variation | Exposure ramps and shadows | No visible texture seams; geometry unaffected |
| **T-ROB-04** | Dynamic objects | Synthetic moving vehicles/people | Moving objects absent from final geometry |
| **T-ROB-05** | **Unknown metadata schema** | ≥4 synthetic schema variants + one malformed | Correct auto-detection; clear error, never a crash |
| **T-ROB-06** | Missing optional inputs | Drop IMU / baro / intrinsics / RTK individually | Runs; documented accuracy degradation |
| **T-ROB-07** | Adversarial input | 0-byte file, 1-frame video, GPS all-identical, no GPS | Graceful, explicit failure |
| **T-ROB-08** | **Input admissibility (R-C9)** | 4 real clips: city vista, castle flyover, temple orbit, wildlife overpass | Verdict + reason per clip; the three unreconstructable ones rejected before inference |

### 3.5 Output and interface — R-O5, R-O6, R-F6…F8

| ID | Test | Pass criterion |
|---|---|---|
| **T-EXPORT-01** | Mesh **and** point cloud produced |
| **T-EXPORT-02** | All six formats written: OBJ, PLY, LAS, GeoTIFF, GLB/glTF, FBX |
| **T-EXPORT-03** | **Third-party readback**: outputs open correctly in CloudCompare / QGIS / MeshLab, georeferenced in the right place |
| **T-EXPORT-04** | LAS carries a valid CRS; GeoTIFF has correct geotransform |
| **T-UI-01** | Viewer loads and displays the model |
| **T-UI-02** | Measurement: distance/area/height within tolerance of GT |
| **T-UI-03** | Inferred vs observed geometry visually distinguishable |

> **T-EXPORT-03 is deliberately a third-party test.** A file our own code writes and our own code
> reads proves very little. Georeferencing bugs surface the moment a real GIS puts the model on a
> basemap.

### 3.6 Non-functional

| ID | Test | Pass criterion |
|---|---|---|
| **T-NF-01** | Determinism (R-NF1): same input twice | Byte-identical geometry, or within a stated epsilon |
| **T-NF-02** | Run manifest completeness (R-NF3) | git SHA, config hash, per-stage timings, input checksums |
| **T-NF-03** | **Offline operation** (R-NF6) | Full run with networking disabled |
| **T-NF-04** | **Licence audit** (R-NF5) | Every dependency's licence recorded and compatible with the stated end use |

---

## 4. Current status

| Component | State |
|---|---|
| `src/eval3d/metrics.py` | **Implemented, 21/21 unit checks passing** |
| `src/eval3d/gnss.py` | **Implemented**, self-tuning robust Sim(3) |
| `src/simscene/` | **Implemented**, occlusion verified against analytic cases |
| EXP-01 classical cost | **Run** — `research/exp01-results.txt` |
| EXP-05 GNSS accuracy | **Run** — `research/exp05-results.txt` |
| EXP-08 coverage ceiling | **Run** — `research/exp08-results.txt` |
| **S1 video ingestion** | **NOT EXERCISED &mdash; no video has ever been decoded** (see below) |
| Everything else | Phase B |

### 4.0 The untested stage

`grep` across `src/` finds no video decode of any kind: no `.mp4` opened, no `VideoCapture`, no
`av.open`, no ffmpeg call. Both runs to date consumed either an in-memory synthetic flight or
still JPEGs with GPS EXIF. **T-ROB-02 (motion blur), T-ROB-05 (unknown metadata schema) and
T-ROB-07 (adversarial input) have therefore never been executed**, and S1's time budget of 120 s
is an allocation rather than a measurement.

This is the single largest gap between what is specified and what is verified. It cannot be
closed without a real drone video carrying per-frame GPS; NTRO has released none
(*"Dataset Link: Will be provided real time"*). The interim mitigation is a synthetic
SRT/metadata fixture suite, which tests the parsers but not the decode path or real blur.

### 4.1 Defects found by these tests so far

Recorded because "the tests found real bugs" is the evidence that the tests are worth having.

| # | Defect | Found by | Resolution |
|---|---|---|---|
| D1 | Z-buffer built from query points alone failed to detect occlusion — a fully hidden wall reported **70.6% visible** | Analytic two-wall fixture | Separate dense occluder cloud; now 0.0%, partial-occlusion case 0%/100% |
| D2 | Coverage scored against the whole scene measured scene size, not reconstruction (198 m swath over an 800 m scene caps any algorithm at ~25%) | Sanity-checking an implausible 22.6% | Report within the overflown corridor, whole-scene alongside |
| D3 | Fixed RANSAC threshold below the noise floor was **worse than no RANSAC** (5.29 m vs 4.08 m) | Threshold sweep | Self-tuning MAD-derived threshold |
| D4 | Architecture claimed RANSAC improves accuracy; measurement showed it does not — it bounds the worst case | EXP-05 | Claim corrected in the architecture doc |
| D5 | Test asserted ICP recovers a 5 m offset on flat terrain; it recovers 1.1 m because a flat plane slides freely | Failing test T2 | Test scene given vertical structure; ambiguity documented as T2b |

---

### 4.6 T-ROB-08 — input admissibility · RUN 2026-09-05 · PASS

`python src/ingest/screen.py` on four real clips. No GPU time was spent on any of them.

| Clip | Sky | Horizon | Shots | Longest shot | Verdict |
|---|---|---|---|---|---|
| Nicosia city vista (CC BY 3.0) | 51.8% | 100% | 2 | 30.3 s | **REJECT** — unbounded depth; two spliced passes |
| Toolse castle (CC BY-SA 4.0) | 18.9% | 100% | 4 | 40.0 s | **REJECT** — unbounded depth |
| Baha'i Temple orbit (CC BY 3.0) | 60.1% | 5.7% | 8 | 14.0 s | **REJECT** — mostly sky; heavily cut |
| **Kolu wildlife overpass (CC0)** | **11.0%** | 22.7% | **1** | **51.8 s** | **ACCEPT** |

The watermark detector fired only on Nicosia — 0.108% of pixels, resolved to a 4.7%
bottom crop. The other three clips carry no burned-in overlay, and it correctly
reported none rather than trimming an edge for nothing.

**What this test would have caught.** All of it. The Nicosia reconstruction was run,
downloaded, analysed and presented before any of these properties were measured; the
resulting cloud had a PCA flatness ratio of 0.194 and no recognisable structure. The
verdict above takes 40 s of CPU per clip.

**Defect it exposed (fixed).** `sky_fraction` measured only the upper 60% of the frame
while dividing by the full frame area, so it could never exceed 0.60 and scored a full
horizon vista at 0.445 — under the then-current 0.75 threshold. The metric did not mean
what its name said. Now whole-frame, with the threshold at 0.15.

### 4.7 T-E2E-01 — video in, mesh out · RUN 2026-09-05 · PASS

The first end-to-end run on real footage, from an H.264/VP9 file to a mesh, with no
stage simulated.

| Stage | Result |
|---|---|
| S1 ingest | 1,562 frames → 45 keyframes, 1 shot, 356 horizon + 529 sky/flare + 787 blur rejected |
| S3 geometry | MapAnything Apache, 45 views jointly, Cloud Run 8 vCPU — **515 s, 11.4 s/view, 45/45 camera poses** |
| S3 filter | 6,853,140 → 4,797,198 (conf ≥ 2.533) → 4,094,279 (SOR) → **951,052** (voxel 0.0357) |
| S5 surface | 2,413,961 vertices, **4,850,697 triangles** (Poisson depth 10, 6% density trim) |
| Viewer | 5.9 MB self-contained WebGL page, 160k triangles + 220k points |

**Visual verification.** Lane markings, the vegetated bridge deck, the noise wall and
the embankment lines are all legible in plan. The height-coloured plan puts the deck
above both carriageways, which is the correct topology.

**The hole under the deck is correct behaviour, not a defect (R-C7).** Confidence gate
swept at 0 / 15 / 30 / 45 %: footprint fills 47.0 / — / 43.4 / 39.7 % of bbox cells and
the hole is the same shape at every setting, including 0. It is the underpass, which a
drone flying above never observes, and Poisson's density trim leaves it open rather
than closing over unobserved space.

**Defects this run exposed (all fixed):**

| Defect | Why it mattered |
|---|---|
| SOR queried k=9 against the full cloud | 7M points ≈ 1 GB of distances and indices alone; would have thrashed or crashed. Tree and threshold now come from a 400k subsample, final test runs in slices |
| Poisson normals oriented by an SVD axis | **The sign of a principal axis is arbitrary**, so half the time the surface is built inside out — and two-sided shading in both renderers hides it completely. `cameras.npy` was already being saved and never read |
| Voxel sized to a constant 2.5 pts/cell | Occupancy depends on how many views see a patch; 45 keyframes over 52 s is far more than the 3 that constant was tuned on, so it left unmerged copies of the surface standing. Now sized from one view's grid spacing |
| Model frame assumed gravity-aligned | It is not — its Y is the camera's down, and this is a steep oblique. The "plan" view was not a plan. Now rotated into the terrain's principal plane, sign fixed by the cameras |
| Mesh subsampled by random triangle for display | Random triangles are not a surface; shading collapsed to dark speckle. Quadric decimation instead |
| Confidence gate reported when the channel was constant | Would have printed "dropped 30%" for a gate that never fired. Now detected and reported as skipped |

## 5. The accuracy claim we are permitted to make

This is written down so nobody is tempted to overstate it under deadline pressure.

EXP-05 measured absolute georeferencing error at **~4.1 m with consumer GNSS** and **~0.097 m with
RTK**, and showed the error is **flat from 50 to 2400 keyframes** — the correlated bias does not
average away.

Therefore:

- **If the supplied dataset carries RTK/PPK** → claim ≤ 1 m absolute, evidenced by T-ACC-01.
- **If it does not** → claim ≤ 1 m *relative/shape* accuracy (T-ACC-02), and state the absolute
  georeferencing error separately and plainly. This is what "metric accuracy without GCPs"
  conventionally means, and it is defensible.
- **Never** quote the ICP-aligned number as if it were absolute. On a model with a real 2.68 m
  offset, alignment reports 0.21 m — flattering by 12.8×.

The harness prints both numbers side by side specifically so that this cannot happen by accident.
