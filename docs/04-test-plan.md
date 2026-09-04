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
| Everything else | Phase B |

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
