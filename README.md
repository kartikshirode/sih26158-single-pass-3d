# SIH26158 — Single-Pass Drone Video to Accurate 3D Model

Smart India Hackathon 2026 · **National Technical Research Organisation** · Software · Drone/Robotics

Convert **one** monocular drone video from a **single flight pass**, plus its GPS track and flight
metadata, into a **georeferenced, metrically accurate, textured 3D model** — in under 15 minutes
for a 10-minute video.

---

## Start here

| Document | What it is |
|---|---|
| [`docs/01-SRS-requirements.md`](docs/01-SRS-requirements.md) | Requirements, fully traced to the official PDF |
| [`docs/02-architecture.md`](docs/02-architecture.md) | Architecture and the 900-second budget |
| [`docs/03-plan-sdlc.md`](docs/03-plan-sdlc.md) | Build plan against the real SIH calendar |
| [`docs/04-test-plan.md`](docs/04-test-plan.md) | Test register + defect log |
| [`docs/report.html`](docs/report.html) | Published findings report |

**The targets are not on the sih.gov.in portal.** Its listing contains the literal placeholder
*"Add 'Desired Output' and 'Evaluation Criteria' table here"*. The binding numbers exist only in
the linked Drive PDF (kept here as `docs/SIH26158.pdf`, no text layer — read it as images):

| Target | Value | | Criterion | Weight |
|---|---|---|---|---|
| Spatial accuracy | **≤ 1 m** | | Reconstruction accuracy | 30% |
| Processing time | **< 15 min / 10-min video** | | Model completeness | 20% |
| Reconstruction | 3D mesh or point cloud | | Processing speed | 20% |
| Formats | OBJ · PLY · LAS · GeoTIFF · glTF · FBX | | Innovation | 15% |
| Coverage | entire visible scene | | Scalability | 10% |
| Visualisation | web or desktop viewer | | User interface | 5% |

Accuracy + completeness + speed is **70% of the score, and all three are measurable** — which is
why the evaluation harness was built and unit-tested *before* the pipeline it judges.

---

## Findings that changed the design

Each is measured or verified from a primary source, not assumed. Full write-ups in `research/`.

**1. The obvious model is licensed out of this job.** VGGT's Acceptable Use Policy prohibits
*"Military, warfare, nuclear industries or applications, espionage"* — both checkpoints. The
customer is India's technical intelligence agency. **MapAnything** replaces it and wins on merit
anyway: Apache-2.0 throughout, natively metric where VGGT is scale-ambiguous, and it accepts
`intrinsics` / `camera_poses` / `depth_z` / `is_metric_scale` as first-class priors.

**2. A single straight pass is geometrically degenerate** — the most consequential result here.
Near-collinear camera centres cannot constrain rotation *about* the flight axis, so an
unrestricted Sim(3) fit nails the trajectory and throws the scene hundreds of metres:

| | trajectory | **scene** |
|---|---|---|
| Straight pass, full 7-DOF | 3.9 m | **311 m** |
| Straight pass, yaw-only (gravity) | 3.5 m | **3.7 m** |
| RTK, full 7-DOF | 0.042 m | **267 m** |
| RTK, yaw-only | 0.038 m | **0.041 m** |

Error grows monotonically with distance from the flight line (216 m → 725 m). Centimetre GPS buys
nothing, because the error lives in a direction the data does not constrain. **So "IMU: optional"
in the problem statement is misleading** — for a single straight pass a vertical reference is
required, or the problem is under-determined.

**3. ≤1 m absolute is unreachable from consumer GPS, at any frame count.** ~4.1 m measured;
error is *flat* from 50 to 2400 keyframes while 1/√N would predict 3.9 → 0.6 m. The correlated
GNSS bias does not average away. RTK reaches 0.097 m.

**4. Facades cap completeness, and the lever is capture, not code.** Within the overflown
corridor: nadir sees 14.3% of along-track facade, 60° sees 52.0% — but 60° and 45° are identical,
because forward tilt saturates. A *sideways* tilt or wider lens buys more than any model choice.

**5. Indian law decides where this can run.** The DST Geospatial Data Guidelines (15 Feb 2021) set
a 1 m / 3 m threshold; finer data must be **stored and processed in India**. That excludes
`asia-southeast1` — the only region where Cloud Run L4 exists for us — and makes the in-India
Baramati cluster the compliant answer.

**6. Two silent ways to lose the vertical budget.** Geoid separation runs −24.3 m (Leh) to
−98.2 m (Kanyakumari), and EGM96 vs EGM2008 differ by **1.68 m at Amritsar** — model choice alone
exceeds the requirement. PROJ returns height *unchanged and raises nothing* when the grid is
missing. Separately, UTM is not a metric frame: ~0.6 m/km scale error across India, so the fit is
done in local ENU and projected last.

---

## Running it

```bash
pip install -r requirements.txt
python src/eval3d/test_metrics.py                 # 21 checks
python src/pipeline/run_demo.py out/demo          # end-to-end, CPU, seconds
```

Experiments (`research/*-results.txt` holds recorded output):

```bash
python src/experiments/exp01_classical_cost.py           # why classical SfM can't be the spine
python src/experiments/exp05_gps_noise.py                # achievable accuracy vs GNSS class
python src/experiments/exp08_coverage_ceiling.py         # what one pass can physically see
python src/experiments/exp09_straight_line_degeneracy.py # the degeneracy and its fix
```

Viewer: copy `model.glb` + `run_manifest.json` beside `viewer/index.html`, serve over HTTP.

### On GCP (Mumbai — required, not preferred; see finding 5)

```bash
gcloud run jobs execute sih26158-pipeline    --region=asia-south1   # full pipeline
gcloud run jobs execute sih26158-mapanything --region=asia-south1   # MapAnything, CPU
```

---

## Measured results

End-to-end on Cloud Run, `asia-south1`:

| GNSS | absolute | shape | completeness | runtime | R-O3 |
|---|---|---|---|---|---|
| Consumer | 2.260 m | 1.058 m | 8.8% | 7.3 s | FAIL |
| **RTK/PPK** | **0.098 m** | 0.085 m | **100%** | 2.9 s | **PASS** |

MapAnything (Apache checkpoint, 1.228 B params) on 8 vCPU: **6.4–8.1 s per view**. Extrapolated to
600 keyframes that is ~75 min against a 900 s budget — **5× too slow on CPU**, which is the
deployment-sizing answer: one L4/A100 clears it, and there is **no CPU-only fallback** for a
full-length job.

---

## What is real, and what is not

Stated plainly, because the distinction is the difference between evidence and decoration.

**Real:** the georeferencing maths, CRS and EGM2008 geoid handling, every export writer, the
scoring harness, the timings, and the MapAnything CPU benchmark. Exports are verified by readback —
LAS carries EPSG:32643 and the GeoTIFF reprojects to 28.6139 N, 77.2090 E.

**Simulated:** the learned geometry stage in the demo. There is no GPU quota on this GCP account
(verified across Compute Engine, Cloud Run *and* Vertex AI), so the demo substitutes geometric
sensing for the depth model.

**Known limit:** the synthetic renderer is **not** adequate to evaluate a learned model's
accuracy — the domain gap to real imagery is too wide (see `research/exp10-mapanything-cpu.md`).
It *is* valid for georeferencing, exports, scoring, timing and coverage geometry, which turn on
geometry rather than photometric realism. Closing the learned-model gap needs real UAV footage.

---

## Open questions for the organisers

These change what may legitimately be claimed:

1. Does the dataset include **RTK/PPK** corrections? (Decides whether ≤1 m absolute is claimable.)
2. Is "≤ 1 m" **absolute or relative**?
3. Is evaluation against a **LiDAR / multi-pass survey** reference?
4. Is the single pass **nadir or oblique**? (Sets the completeness ceiling.)

## Layout

```
docs/        SRS, architecture, SDLC plan, test plan, published report
src/eval3d/  evaluation harness + GNSS model (CPU-only, unit-tested)
src/simscene/ synthetic scene, flight, visibility, CPU rasteriser
src/pipeline/ end-to-end demo
src/experiments/ EXP-01, 05, 08, 09
research/    verified findings + recorded experiment output
viewer/      three.js viewer with measurement
```
