# Research program

Version 1.0 — 2026-09-16. The open technical questions, turned into experiments with pass
and kill criteria written **before** they run.

---

## 1. Rules of the program

1. **Pre-register.** An experiment's question, method, metric and pass/kill criterion are
   written here before the first run. Changing the criterion after seeing the result is a new
   experiment, with a new ID.
2. **Negative results ship.** Every run lands in `research/` with its output, including the
   ones that disprove what we hoped. The sharding result (`docs/06` §7) and the plausibility
   band (`docs/08`) are the precedents.
3. **No tuning on the test.** A clip used to choose a threshold is a development clip from then
   on. Claims need a held-out clip (§4).
4. **Label the unit.** Every length is either scale-free (a ratio), model units, or metres
   with a scale status (`docs/09` §2).
5. **Licence first.** No model or library enters an experiment destined for the product until
   its licence is in `docs/11` §5.
6. **Score with the harness.** `src/eval3d/` or `src/analysis/compare_mvs.py`, never by hand.

### 1.1 Maturity gates

| Gate | Meaning | Evidence required |
|---|---|---|
| **G0** | Idea | A written hypothesis and a falsifying test |
| **G1** | Works once | Measured on one real clip |
| **G2** | Works twice | Measured on two unrelated real clips |
| **G3** | Generalises | Measured on a held-out clip nobody tuned on |
| **G4** | Operational | Timed end to end on unseen data inside the finale runbook (`docs/17`) |

A result may be *presented* at G2. It may be *claimed as a capability* only at G3.

---

## 2. Tracks

Ordered by expected score impact (weights from the PS: accuracy 30, completeness 20, speed 20).

| Track | Question | Score it moves | Gate today |
|---|---|---|---|
| **R1 Metric truth** | Can every metre be trusted, and how do we know? | Accuracy 30 | G1 (EXP-14, Kolu only) |
| **R2 Speed** | Can a 10-min video finish in ≤ 600 s on one GPU? | Speed 20 | G0 |
| **R3 Real georeferencing** | Does S5 work on a real clip with GNSS? | Accuracy 30 | G0 (synthetic only) |
| **R4 Surface quality** | Can we get texture and keep MVS detail and coverage? | Completeness 20, UI 5 | G2 (detail), G0 (texture) |
| **R5 Completeness** | How much of the observable surface do we recover, and how do we label inference? | Completeness 20, Innovation 15 | G0 |
| **R6 Robustness** | Does an unknown clip ever crash us? | All | G1 (S0 screen) |
| **R7 Model** | Is there a better licence-clean geometry or scale model? | Accuracy 30, Innovation 15 | G1 |

---

## 3. Experiment register

Status: **Done** · **Next** (start this sprint) · **Queued** · **Blocked** (named dependency).

### R1 — Metric truth

| ID | Question | Method | Pass | Kill | Status |
|---|---|---|---|---|---|
| **EXP-14** | Is the Kolu scale right? | Lane width + ecoduct waist in the export frame | — | — | **Done**: 5.3–5.8× too small (`docs/08`) |
| **EXP-14b** | Is the Village scale right? | Same method. The clip is an Arizona construction site; candidate rulers are US lane width (12 ft = 3.66 m, typical — verify for the site), parking-stall width and vehicle length | Two rulers agree within 10% | No two independent rulers are visible → mark the clip permanently `unvalidated` | **Next** |
| **EXP-15** | Does an aerial-adapted metric-depth model give an independent scale? | AerialMetric's MoGe-2 LoRA (and DA3METRIC-LARGE as control) on Kolu keyframes. Compare its implied scale with MapAnything's and with the EXP-14 bracket | Within the 5.3–5.8 bracket | > 20% outside it on Kolu | **Next** — verify the weights' licence first |
| **EXP-17** | Do priors fix MapAnything's scale at source? (H3) | Re-run S3 on Kolu passing the true intrinsics (from the BA fit, rescaled to F1) and `is_metric_scale` flags | Factor within 10% of 1 after priors | Factor unchanged within 10% | **Next** — needs GAP C-5 |
| **EXP-17b** | How does the scale error grow with altitude? (H1) | Clips with SRT `rel_alt` at 10 / 30 / 60 / 100 m; factor vs true altitude | A monotone curve with < 10% scatter, so it can be corrected | No relationship → treat scale as unknown without GNSS | Blocked on R3 data |
| **EXP-17c** | Is the error per view or from joint inference? (H4) | Save `metric_scaling_factor` per view (GAP C-4); report its spread | — | — | Queued |
| **S5 check** | Can the pipeline catch a wrong scale automatically? | Footprint from intrinsics and camera height vs detected lane pitch or vehicle length | Flags Kolu at the pre-fix scale; passes the calibrated one | False-alarm rate > 10% on admissible clips | Queued |

### R2 — Speed

| ID | Question | Method | Pass | Kill | Status |
|---|---|---|---|---|---|
| **EXP-16** | Which GPU densifier? (ADR-023) | COLMAP PatchMatch vs OpenMVS CUDA on Kolu, same poses, on a Baramati card | COLMAP within 10% of OpenMVS on `compare_mvs` metrics, and faster | COLMAP > 25% worse on 6–25 cm residual | Blocked on Baramati access |
| **EXP-19** | What does sparse SfM cost at 600 keyframes? | Sequential matcher (overlap 10–20) + GLOMAP vs COLMAP mapper, on a 600-frame synthetic-texture or survey sequence | ≤ 120 s for match + global SfM | > 300 s → keep MapAnything poses and BA only | Queued |
| **EXP-03** | How many keyframes does quality need? | Sweep 150 / 300 / 450 / 600 on a long clip; relief, residual, coverage | Knee identified; ≤ 450 holds 95% of the 600 quality | — | Blocked on a 10-min clip |
| **T-PERF-04** | What does each quality preset cost? | Time `--resolution-level 0/1/2` and keyframe budgets on Kolu, CPU and GPU | Every preset timed before the finale | — | Queued |
| **EXP-25** | Does the full pipeline hit 600 s? | 10-min 4K clip, one 24 GB GPU, cold start, end to end | **≤ 600 s** | > 900 s with the fastest preset → escalate to a two-GPU design | Blocked on EXP-16 and data |

### R3 — Real georeferencing

| ID | Question | Method | Pass | Kill | Status |
|---|---|---|---|---|---|
| **EXP-21** | Does S1→S5 work on a real single pass with telemetry? | A single straight pass with the DJI SRT sidecar enabled, over ground with **surveyed check points** or a public map feature of known position | Absolute error reported both ways (T-ACC-01/02); consistent with EXP-05's consumer figure (~4 m) | Parser fails, or the 5-DOF fit diverges | **Blocked on data** — the single largest gap |
| **EXP-21r** | Same, with RTK | RTK-equipped airframe, same site | ≤ 0.15 m absolute | > 1 m → EXP-05 model is wrong; investigate | Blocked on hardware |
| **EXP-07** | Is the geoid correction right? | Known control point, ellipsoidal vs orthometric, `allow_ballpark=False` | < 0.1 m from this cause | — | Queued (unit-testable today) |

**Data acquisition for R3.** Indian footage finer than 1 m must be processed in India
(ADR-010). Flying needs compliance with the Drone Rules, 2021 and the Digital Sky airspace
map — **verify current registration and zone requirements before any flight**. Enable
"Video Subtitles" on DJI aircraft so the `.SRT` is written. Record the flight log as well;
the embedded `djmd` track is the fallback (`research/02-ingestion-export-findings.md` §3).

### R4 — Surface quality

| ID | Question | Method | Pass | Kill | Status |
|---|---|---|---|---|---|
| **EXP-20** | Why does `TextureMesh` fail in 0.2 s? | Recovered from Cloud Logging: `unable to open file '/tmp/mvs/scene_dense_mesh.mvs'`. At 2.4.0 `ReconstructMesh` skips its `.mvs` for an interface-format input by design and writes only the `.ply`; `run_mvs.py` handed `TextureMesh` the file that was never written. Fix: keep `scene_dense.mvs` as the scene and pass the mesh with `--mesh-file` | A textured OBJ on Kolu | — | **Done 2026-09-22.** Execution `sih26158-mvs-lskpr`, image `mvs:v5`: `TextureMesh` rc=0 in 1,078.1 s, a 239.9 MB OBJ with an 8192 x 8192 atlas (`gs://sih26158-mumbai/mvs/kolu_tex_out/`), same poses as before (0.365 px after BA). Record: `research/run-evidence/kolu_tex_mvs_result.json`. Texturing adds 1,078 s to the L0 wall clock on 8 vCPU; the 2,078.7 s speed figure is the run without it. **Second finding, same day:** that atlas rendered black. TextureMesh's *local* seam levelling at 2.4.0 blanks every chart interior (83% of face centroids near-black with it on, 0.8% with `--local-seam-leveling 0`; global levelling alone is fine), and the 1.9M-face mesh gives charts a few texels wide that no decimation can rescue. The served model is a 300k-face decimation textured against the sparse scene in the job's `MESH_BLOB` mode (executions `sih26158-mvs-dt5t5` / `-tmw4m`, 388 s each; `mvs:v7`). A third finding fell out: the second pass over the same poses came back **1.33x larger** in model units (0.87 degrees rotated; 0.034 units RMSE once aligned by scaled ICP), so a COLMAP gauge is per run and the docs/08 factor is tied to the run it was measured on. The served mesh is aligned into that run's frame (`tools/pack_textured.py`, `out/kolu_tex_mvs/align_to_kolumvs3d.json`) |
| **EXP-26** | Can coverage be recovered without losing detail? | `--number-views-fuse 2` and `RefineMesh` on Village (83% coverage today) | ≥ 95% of baseline cells, ≤ 10% worse residual at 6–25 cm | Residual > 20% worse | Queued |

### R5 — Completeness

| ID | Question | Method | Pass | Kill | Status |
|---|---|---|---|---|---|
| **EXP-22** | Observable-surface completeness on real data | EXP-08's denominator on H3D or UseGeo, using one simulated strip of the survey | Recall ≥ 90% of observable within τ | — | Queued |
| **EXP-27** | Bounded occlusion closure (R-C7) | Footprint extrusion for buildings, every inferred face tagged | 100% of inferred faces tagged; viewer can hide them | Tagging leaks (any inferred face untagged) | Queued |
| **Capture note** | What should the operator fly? | Already measured: forward tilt saturates at 60° = 45°; a sideways tilt or wider lens buys cross-track facades (EXP-08) | Ship as operator guidance in `docs/17` | — | Done (synthetic) |

### R6 — Robustness

| ID | Question | Method | Pass | Kill | Status |
|---|---|---|---|---|---|
| **EXP-23** | Does any telemetry schema crash S1? | `src/ingest/test_srt.py`: 20 real DJI files (MIT, `fixtures/dji_srt`) across five format families, plus 21 fuzz deformations (unit flips, `longtitude`, missing `rel_alt`, CRLF/BOM, UTF-16, binary, truncation, no `-->`, off-planet, NaN, 1 MB line). Findings in `research/04-dji-srt-formats.md` | 0 crashes; every file → parsed or empty | — | **Done 2026-09-22**: 65 checks pass. Found two silent bugs: the longitude pattern only matched the Mavic 2 misspelling (every modern file parsed to nothing), and keyframe lookup was positional (wrong by 30x on 1 Hz files) |
| **EXP-06** | Does masking dynamic objects measurably help? | Ablate the geometric-consistency layer on a clip with traffic | Moving vehicles absent from the dense cloud | — | Queued |
| **T-ROB-02** | Blur and compression on amateur footage | Real handheld-quality clip; heavy re-encode | Blur gate rejects; accuracy holds | — | Blocked on data |

### R7 — Model

| ID | Question | Method | Pass | Kill | Status |
|---|---|---|---|---|---|
| **EXP-02** | How much weaker is the Apache checkpoint? | Apache vs NC MapAnything on Kolu: poses (BA residual), scale factor, coverage. NC for internal ablation only | Gap measured and published | — | Queued |
| **EXP-18** | Can any licence-clean feed-forward model resolve below its patch? | MoGe-2, DA3 (Apache checkpoints) on Kolu; the `docs/05` §1 growth test | Break-point below 14 px | Same patch floor → MVS stays the geometry path | Queued |

---

## 4. Data plan

| Set | Role | What it holds | Status |
|---|---|---|---|
| **Kolu** (CC0) | Development | 52 s oblique pass, no GNSS, two rulers | In use; **not** a held-out clip any more |
| **Village / ytd** (third-party YouTube) | Development only | Portrait construction site, watermark | Pipeline testing only — rights are not clear for deliverables |
| **Synthetic** (`src/simscene`) | Georef, CRS, coverage, timing | Ground truth by construction | Valid for geometry, **not** for learned models (EXP-10) |
| **Held-out A** | Claims | A single pass with SRT and a surveyed check point | **To acquire** (EXP-21) |
| **Held-out B** | Claims | A LiDAR-referenced aerial site (H3D / UseGeo, strip-subsampled) | **To download** |
| **Finale** | The real test | NTRO's, unseen | Arrives on the day |

**Rules.** A held-out set is opened once per milestone and its results are recorded whether
good or bad. Footage used in any deliverable needs rights the team holds (T-ROB-09).

---

## 5. This sprint

In order, each unblocked today:

1. **EXP-23** — telemetry fuzzing. No data needed; closes the largest robustness risk.
2. **GAP C-4, C-5** — persist `metric_scaling_factor`; plumb priors into S3.
3. **EXP-17** — priors on Kolu. The cheapest possible fix for the scale error.
4. **EXP-14b** — Village ruler.
5. **EXP-15** — independent scale witness, after the licence check.
6. **EXP-20** — `TextureMesh` diagnosis.
7. Acquire **Held-out A** (EXP-21) — it unblocks R3 and half of R1.
