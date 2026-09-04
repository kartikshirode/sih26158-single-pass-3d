# Build Plan and Software Development Lifecycle
## SIH26158 — Single-Pass Drone Video to Accurate 3D Model Generation System

Version 1.0 — 2026-09-04.

---

## 1. The calendar drives everything

SIH 2026 was launched 2026-08-21. Today is **2026-09-04**.

| Phase | Window | What is actually due |
|---|---|---|
| Internal (college) hackathon | **September 2026** | Team selection; SPOC picks 30 teams + 5 waitlist |
| Idea submission | Sept–Oct 2026 | **Idea PPT + video demonstration**, uploaded by the SPOC |
| National screening | October 2026 | Evaluation of the submitted idea |
| Shortlist announced | November 2026 | Teams selected for the finale |
| **Grand finale** | **December 2026** | **36-hour on-site hackathon at a nodal centre** |

**The single most important planning consequence:** the near-term deliverable is **not a finished
system** — it is an *idea submission that survives screening*. Building the whole pipeline before
October is the wrong allocation. Building a **credible thin slice plus rigorous evidence** is the
right one.

Equally: at the finale the dataset arrives on the day and you get **36 hours**. A system that needs
a week of tuning per scene loses. Everything must be automated and parameterised by then.

> **Verify these dates with your SPOC before committing.** They come from secondary reporting;
> sih.gov.in publishes the authoritative flow in `SIH26_Process_Flow.png` and
> `SIH 2026 Guidelines.pdf`. Dates are the one thing here I would not act on unconfirmed.

---

## 2. Three phases with different definitions of done

### Phase A — Evidence and thin slice (now → early October) · **screening**

**Goal:** be able to say, with numbers, *"we know exactly what this problem requires, we have
measured the hard parts, and here is a working slice."*

| # | Deliverable | Status |
|---|---|---|
| A1 | Requirements spec with full traceability | **DONE** — `01-SRS-requirements.md` |
| A2 | Architecture with the 900 s budget allocated | **DONE** — `02-architecture.md` |
| A3 | Licence register, primary-source verified | **DONE** — `research/01-licensing-findings.md` |
| A4 | **Evaluation harness, unit-tested** | **DONE** — `src/eval3d/`, 21/21 checks pass |
| A5 | **EXP-05: achievable accuracy vs GNSS class** | **DONE** — `research/exp05-results.txt` |
| A6 | EXP-01: cost of the classical baseline | **DONE (partial)** — component-cost lower bound measured; a full timed ODM run on a GPU is still outstanding |
| A7 | Synthetic scene + flight generator (GT without a drone or GPU) | **PARTIAL** — scene, flight and visibility done (`src/simscene/`); **still needs rendered frames + GPS-tagged output**, which A8 depends on |
| A8 | Thin slice: short clip → georeferenced point cloud → exports → viewer | To do |
| A9 | Idea PPT + demo video | To do |

**Phase A exit criteria:** A6–A9 complete; every claim in the PPT traceable to a run in
`research/`; the demo video shows real output, not a mock.

### Phase B — Full pipeline (October → November) · *if shortlisted*

| # | Deliverable |
|---|---|
| B1 | Ingestion: metadata auto-detection across ≥4 synthetic schema variants (R-NF4) |
| B2 | Keyframe selection with blur/baseline/coverage scoring (R-C2) |
| B3 | MapAnything chunked inference + inter-chunk pose graph (R-C1) |
| B4 | Georeferencing: robust Sim(3) → GPS-prior BA → UTM + geoid (R-C5, R-C8) |
| B5 | Dynamic masking, both layers (R-C4) |
| B6 | Meshing + texturing (R-F5, R-C3) |
| B7 | Occlusion closure with confidence tagging (R-C7) |
| B8 | All six export formats (R-O5) — note the FBX licence trap, §5 |
| B9 | Viewer (R-O6) — deliberately small, 5% of score |
| B10 | End-to-end timing on the target GPU, proving < 900 s (R-O2) |
| B11 | EXP-02/03/04/06/07 complete |

### Phase C — Finale readiness (November → December) · 36 hours

| # | Deliverable |
|---|---|
| C1 | **Runbook**: unknown dataset → result, with decision points and fallbacks |
| C2 | Offline bundle: containers, weights, sensor DBs pre-cached (R-NF6 — assume no internet) |
| C3 | Degradation ladder: if too slow, exactly which knob to turn, pre-measured |
| C4 | Dry runs on ≥3 unseen datasets, timed end to end |
| C5 | Presentation + measurement demo |

---

## 3. Compute strategy — planned around a verified blocker

**GCP is the intended production target, and GPU quota there is currently denied.** Established
empirically 2026-09-04 (`01-SRS` §9): every request auto-denies in seconds with
`ineligibilityReason: NOT_ENOUGH_USAGE_HISTORY`, on Compute Engine *and* Cloud Run, at 4 GPUs and
at 1. There is no human reviewer to appeal to.

### 3.1 The ladder (use the highest rung available)

| Rung | Resource | Status | Use for |
|---|---|---|---|
| 1 | **GCP L4 / H100, `asia-south1` (Mumbai) ONLY** | **BLOCKED** — quota 0 | Production target; timed benchmark of record |
| 2 | **Baramati HPC cluster** (VPKBIET) | **AVAILABLE NOW** | All Phase B development |
| 3 | Colab / Kaggle free GPU | Available | Model smoke tests only — **not** for ≤1 m deliverable data (R-NF8) |
| 4 | This laptop (Intel Arc, no CUDA) | Available | All CPU work — harness, ingestion, geo, export |

> **R-NF8 narrows the ladder.** Indian geospatial regulation requires data at or finer than 1 m to
> be stored and processed in India, so `asia-southeast1` (Singapore) — the nearest region where
> Cloud Run L4 exists — is **excluded**. An India-resident GPU means Compute Engine L4 in
> `asia-south1` (or H100 in `asia-south1-c`), which is precisely the denied quota. **Baramati is
> physically in India and therefore compliant**, which promotes it from stopgap to a defensible
> production answer for this customer.

### 3.2 Unblocking GCP (start now; it is slow, not hard)

`NOT_ENOUGH_USAGE_HISTORY` is a spend/history gate, so the fix is history:

1. Run ordinary **billed non-GPU** workloads on `agentbillboard` continuously (the CPU stages of
   this very project — ingestion, georeferencing, export — belong on Cloud Run/Batch anyway).
2. Re-request monthly. Requests are already filed and will be re-evaluated.
3. In parallel apply for **Google Cloud credits** (startup / education / research programmes),
   which usually carry quota with them.
4. Keep a costed fallback: a spot A100 hour elsewhere is inexpensive, and the finale demo must not
   depend on a quota decision outside our control.

**Design consequence, and it is a good one:** because rung 1 may never arrive, the architecture
targets **a single 24 GB-class GPU**, and every CPU-capable stage is kept CPU-capable. That is
also the more credible engineering answer — a field mapping system that needs eight GPUs is not
deployable by NTRO in the field.

### 3.3 Baramati specifics (from the verified handoff doc)

- `sbatch` only — **`srun` is broken** (`Job credential expired`; clock skew on the login node).
- Only the **`torch-gpu`** conda env works — the cards are sm_120 Blackwell and the other envs
  are built for sm_50–sm_90 and fail with "no kernel image available". `torch.cuda.is_available()`
  returns True on the broken envs, so **smoke-test with a real matmul**.
- MIG slices are **18–24 GB** — enough for chunked MapAnything and DA3; not enough for a large
  single forward pass. This validates the chunking design (architecture §5) rather than fighting it.
- Campus network only.

---

## 4. Engineering practice (the "professional SDLC" part, made concrete)

Not a Gantt chart — the things that actually raise quality and that a judge can audit.

| Practice | Implementation |
|---|---|
| **Traceability** | Every requirement has an ID; every ID has a test ID; every claim cites a run |
| **Test-first on the measurable** | The evaluation harness was built and unit-tested *before* the pipeline, so architecture choices are experiments, not opinions |
| **Experiments over assertions** | EXP-01…07 registry (architecture §9); results land in `research/` |
| **Reproducibility (R-NF1)** | Pinned versions, fixed seeds, run manifest with git SHA + config hash + per-stage timings |
| **Licence gate (R-NF5)** | No dependency added without recording its licence and end-use compatibility |
| **Assumption register** | `01-SRS` §8 — unknowns are written down, never silently assumed |
| **Honest reporting** | Both absolute and aligned accuracy, always. Inferred geometry always tagged |
| **CI** | `pytest` on the harness + a synthetic end-to-end smoke test on every commit |
| **Config over code (R-NF2)** | Quality/speed knobs are parameters, so the finale degradation ladder needs no code edits |

### 4.1 Repository layout

```
sih26158/
  docs/     01-SRS-requirements.md  02-architecture.md  03-plan-sdlc.md  04-test-plan.md
  src/
    eval3d/       metrics.py  gnss.py  test_metrics.py      # DONE, tested
    ingest/       decode, metadata parsers, keyframing
    geometry/     chunking, model wrapper, pose graph
    georef/       sim3, BA, CRS + geoid
    surface/      mesh, texture, completion
    export/       obj/ply/las/geotiff/glb/fbx writers
    experiments/  exp01..exp07
  viewer/   three.js / Potree front-end
  data/     synthetic scenes, downloaded benchmarks
  research/ verified findings + experiment outputs
```

---

## 5. Known traps already identified (do not rediscover these)

| Trap | Consequence | Mitigation |
|---|---|---|
| **VGGT AUP bans military/espionage use** | Core model illegal for the actual customer | MapAnything (Apache-2.0) — also technically better |
| **MapAnything Apache ckpt trained on 6 datasets vs NC on 13** | Deployable weights likely weaker | EXP-02 measures the gap; ship Apache, report honestly |
| **Consumer GPS caps absolute accuracy at ~4 m** | R-O3 unreachable without RTK | Report relative + absolute separately (EXP-05) |
| **ICP alignment hides georeferencing error (12.8× flattering)** | Looks like a pass, is a fail | Harness always reports both |
| **ICP slides freely on flat terrain** | Aligned metric untrustworthy on flat scenes | Documented in `test_metrics.py` T2b |
| **RANSAC threshold below the noise floor is worse than no RANSAC** | 5.29 m vs 4.08 m | Self-tuning MAD threshold |
| **Ellipsoidal vs orthometric height** | Tens of metres of vertical error | Explicit single conversion + assertion test |
| **Ultralytics YOLO is AGPL-3.0** | Network copyleft on a hosted service | Prefer permissive detectors; geometric layer is licence-free |
| ~~FBX has no permissive writer~~ **— WRONG, corrected** | Would have forced a GPL dependency | **assimp (BSD-3) writes FBX** (`"fbx"`/`"fbxa"`, FBX 2016+). Decoys: FBX2glTF wraps the Autodesk SDK and converts the wrong way; ufbx is import-only |
| **Data at ≤1 m must be processed in India** | Foreign cloud regions are excluded | asia-south1 only; Baramati is compliant (R-NF8) |
| **PROJ silently skips the geoid** when the grid is missing, or when z is omitted | 24–98 m vertical error in India | `allow_ballpark=False` + `TransformerGroup.best_available` assert; ship the EGM2008 grid |
| **EGM96 vs EGM2008 differ by 1.68 m at Amritsar** | Model choice alone blows the 1 m budget | Fix on EGM2008 / EPSG:9518 and state it |
| **UTM scale error ≈0.6 m per km** across India | Fitting in UTM bakes in projection error | Fit in local ENU; project to UTM last |
| **DJI `abs_alt` is barometric, not GNSS** (constant to the mm) | A fake correlated height constraint in BA | Never use as an independent height observation |
| **ODM stamps video frames `Model: "Unknown"`** | Every frame reconstructs from a generic focal prior | Write true Make/Model, or pass `--cameras` |
| **Mavic 3 intrinsics filed under `Hasselblad L2D-20c`** | A `"DJI "+model` lookup misses it | Key the sensor DB on Make AND Model |
| **decord is abandoned** (HEAD 2022, 221 open issues) | Dead dependency | Use PyAV; torchcodec for CUDA |
| **Open3D has no Python 3.13 wheels** | Environment breaks | Pin **Python 3.12** (MapAnything specifies 3.12 anyway) |
| **Cloud Run L4 not in asia-south1** despite the quota API listing it | Wasted debugging | Use asia-southeast1; trust deploy errors over the quota API |
| **ODM's video wiki page is from 2018 (ORB_SLAM2)** | Wrong flags | Read `opendm/config.py`: `--video-limit` (500), `--video-resolution` (4000) |

---

## 6. Risk register

| # | Risk | P | Impact | Response |
|---|---|---|---|---|
| R1 | No GPU for the timed benchmark | High | High | Ladder §3.1; Baramati now; build history on GCP |
| R2 | Dataset has no RTK → cannot claim ≤1 m absolute | High | High | Dual reporting; raise with organisers early |
| R3 | Pure-nadir flight → facades unobservable (R-F2) | Medium | High | Bounded labelled completion; state the physics |
| R4 | Unknown metadata schema on the day | Medium | High | Chain-of-responsibility parsers + synthetic schema tests |
| R5 | 900 s exceeded on real 4K | Medium | High | Pre-measured degradation ladder (C3) |
| R6 | Apache weights materially weaker | Medium | Medium | EXP-02; report the gap |
| R7 | Team bandwidth during semester | Medium | Medium | Phase A is small and already largely done |
| R8 | Finale venue has no internet | Medium | High | Offline bundle (C2) — assume none |

---

## 7. Immediate next actions

1. **Ask the organisers / SPOC** (blocking on claims, not on work): does the dataset include
   RTK/PPK? Is "≤1 m" absolute or relative? Is evaluation against a LiDAR/survey reference? Is the
   pass nadir or oblique? *(Assumption register A1–A5.)*
2. **A6** — time the classical baseline; convert architecture §1 from argument to evidence.
3. **A7** — synthetic scene + flight generator, so accuracy claims exist before December.
4. **A8** — thin slice end to end, even at low quality.
5. Start **billed CPU usage on `agentbillboard`** today; it is the only thing that unblocks GCP GPU
   quota, and it needs calendar time to accrue.
6. Verify the SIH dates with the SPOC against the official guidelines PDF.
