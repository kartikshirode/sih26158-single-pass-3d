# Engineering handbook

Version 1.0 — 2026-09-16. Read this before your first commit. It covers the setup you need,
how to run each stage, the conventions the codebase already follows, how changes get
reviewed, and the traps that have already cost this project time.

---

## 1. Environment

### 1.1 What is pinned, and what this machine actually has

| | Pin | The development laptop, 2026-09-16 |
|---|---|---|
| Python for `src/`, `tools/` | **3.12** (ADR-018) | default `python` is **3.13.2** — most scripts run, but it is off-pin |
| open3d | needs ≤ 3.12 | only in **Python 3.11** (open3d 0.19.0); `tools/finish_mvs.py` hard-codes that interpreter |
| MVS image Python | 3.11 (conda-forge, ships with COLMAP) | container only |
| COLMAP, OpenMVS, assimp | container only | not on this machine |
| ffmpeg | any | miniconda's build; `h264_mf` is the available H.264 encoder (no libx264) |
| GPU | none required | Intel Arc, no CUDA — cannot run the GPU stages |

**Fix the drift (tracked in `docs/18`):** create a 3.12 virtual environment with open3d,
and replace the hard-coded interpreter in `finish_mvs.py` with `sys.executable`.

```bash
py -3.12 -m venv .venv && .venv/Scripts/activate      # Windows; python3.12 -m venv on Linux
pip install -r requirements.txt
pip install opencv-python-headless av matplotlib open3d python-pptx
```

### 1.2 Windows specifics

- Use **Git Bash** or PowerShell, not `cmd`. Set `PYTHONIOENCODING=utf-8`; several scripts
  print Unicode (`build_all.py` sets it for its children).
- **MSYS rewrites `/`-leading arguments** into `C:\…` paths. Set `MSYS_NO_PATHCONV=1`
  when passing a URL path or a GCS object path as an argument.
- Heredocs containing apostrophes break in Git Bash; write the file instead.

---

## 2. Repository map

```
src/
  tesseract/     the pipeline: contracts, scale service, orchestrator, stages, CLI
  ingest/        screen.py (S0), video_ingest.py (S1), make_test_video.py (SRT fixtures)
  pipeline/      colmap_export.py, gravity.py, fuse_mesh.py, window_fuse.py,
                 render_views.py, export_formats.py (S6), run_demo.py (synthetic E2E)
  eval3d/        metrics.py, gnss.py, test_metrics.py        ← the harness (21 checks)
  simscene/      synthetic scene, flight, visibility, rasteriser
  analysis/      compare_mvs.py (the MVS-vs-baseline measurements), spectrum*, qual, scale2
  experiments/   exp01, 05, 08, 09, 13, 14                   ← research/ holds their output
mapanything_job/ S3 container (CPU torch, Apache weights baked in)
mvs_job/         S3b + S4 + S6 container (COLMAP, OpenMVS, assimp); single and sharded
tools/           finish_*.py (pull + render + viewer), build_* (demo, gallery, Q&A, deck),
                 check_design.py, check_wiring.py, design_system.{css,py}
demo/            the deployed replay (Vercel project tesseract-demo)
docs/            this suite — start at docs/README.md
research/        findings and recorded experiment output
out/             every run artefact — gitignored, regenerable
```

---

## 3. Running things

| Task | Command | Where |
|---|---|---|
| Everything, one clip | `python tesseract.py run <video> [--adopt out/<run>] [--calibration-run <run>]` | local |
| Everything, no data | `python tesseract.py run synthetic --gnss rtk` | local, seconds |
| Screen only | `python tesseract.py screen data/cand/*.webm` | local |
| Calibrate from a known length | `python tesseract.py calibrate <run> --points X1 Y1 Z1 X2 Y2 Z2 --length 21.0 --what "ecoduct waist"` | local |
| Check a finished run | `python tesseract.py verify out/runs/<run>` | local |
| Pipeline tests | `python src/tesseract/test_tesseract.py` | local, ~1 min |
| Harness tests | `python src/eval3d/test_metrics.py` | local |
| The console, in a real browser | `python tools/test_console.py [--shots DIR]` | local, CI |
| docs/00 figures vs their sources | `python tools/check_onboarding.py` | local, CI |
| Synthetic end to end | `python src/pipeline/run_demo.py out/demo` | local, seconds |
| Screen clips | `python src/ingest/screen.py data/cand/*.webm` | local, ~40 s/clip |
| Ingest a clip | `python src/ingest/video_ingest.py <video> --out out/kf_<run> --n 45 [--skip s --end s] [--horizon crop]` | local |
| MapAnything (S3) | `gcloud run jobs execute sih26158-mapanything --region=asia-south1` (inputs under `gs://sih26158-mumbai/mapanything/<run>_input/`) | Cloud Run |
| BA + MVS + export | `gcloud run jobs execute sih26158-mvs --region=asia-south1` with `KF_PREFIX`, `MA_PREFIX`, `OUT_PREFIX` | Cloud Run |
| Pull, render, viewer | `RUN=kolu GCS_PREFIX=mvs/kolu_out BASELINE=kolu3d python tools/finish_mvs.py` | local (needs open3d) |
| Exports only | `python src/pipeline/export_formats.py out/<run>mvs3d --cameras out/<run>_raw/cameras.npy` — applies the run's calibration if one exists; `--no-scale` for model units | local (needs open3d; Blender or assimp for FBX) |
| MVS vs baseline | `python src/analysis/compare_mvs.py --baseline … --mvs … --json out/ppt/measure_<run>.json` | local |
| Scale audit | `python src/experiments/exp14_scale_audit.py` | local, ~1 min |
| Demo, all pages | `python tools/build_all.py` | local |
| Deploy the demo | `cd demo && vercel deploy --prod --yes` | see §6 |
| Baramati GPU | `sbatch` only; the `torch-gpu` env only; smoke-test with a real matmul | see the cluster's `CONTEXT.md` |

**Diagnosing a stuck GCP job:** read `compute.instances.insert` in Cloud Logging first. Batch
reports scheduling states, not the API error underneath, and the regional quota view does
not show the global `CPUS-ALL-REGIONS` cap (`docs/03` §3.1).

---

## 4. Conventions

These are the conventions the code already follows. Match them.

### 4.1 Code

- **Comments record the reason, usually the defect that forced the line.**
  `fuse_mesh.py`, `export_formats.py` and both Dockerfiles are the model. A comment that
  restates the code is noise; a comment that says *"the sign of a principal axis is
  arbitrary, so half the time the surface is built inside out"* stops the next person
  from undoing the fix.
- **Fail loudly, and say what was skipped.** A gate that did not fire is reported as
  skipped, not as passed (`fuse_mesh` conf gate). A missing input stops the build rather than
  falling back to a stale constant (`build_sih_ppt.py`).
- **Name the frame and the unit** in variables and JSON fields: `P_enu`, `V_llf`,
  `camera_above_ground_model`. See `docs/09` §1.
- **Never hard-code a data-dependent threshold.** Derive it from the clip (blur percentile,
  MAD-scaled RANSAC threshold) and record the value used.
- **Persist what downstream needs**, not what you use (R-NF9).
- **Dtypes are part of the interface:** `float32` points, `uint8` colours, `float64` cameras.
- **Deterministic by default:** seeded RNGs (`seed=0`), sorted file lists.
- Type hints on public functions; `from __future__ import annotations`; the standard library
  and numpy before any new dependency.

### 4.2 Documents

- Numbers come from a file, and the document names it.
- Tables over paragraphs for anything that is compared.
- A corrected claim is marked **CORRECTED** with the date, and the old reasoning is kept
  (`docs/05` §6 is the model). Do not silently rewrite history.

### 4.3 Commits

The history uses one idiom: an imperative summary that says **what changed and why it
matters**. Two real examples:

```
Make the intrinsics fit survive a second clip: mask, robust fit, median aggregate
Measure the sharded run: 7% slower than the single task, and why
```

One logical change per commit. Contract changes land with their code and their line in
`docs/09`.

### 4.4 Branches

`master` is the integration branch of the private repo `mandarwagh9/sih26158-single-pass-3d`.
Work on a topic branch and merge after review (§5). The demo deploys separately (§6), so a
push never changes what judges see.

---

## 5. Review

Every change that touches a stage, a public number, or a contract gets a second reader.

**The reviewer's checklist**

1. **Audit the diff, not the description.** The worst defects found in this family of
   projects were introduced by an earlier fix.
2. **Reproduce before fixing.** A bug report is a hypothesis until it reproduces.
3. Does any length lack a unit status? Does any "metre" come from an unvalidated scale?
4. Does a new check actually *measure* the thing its name says? (`sky_fraction` capped at
   0.60; the plausibility band that passed a 5.5× error.)
5. Could a default silently change a result — a threshold, a crop, an averaging step, a CRS?
6. Does the change add a dependency? Is its licence in `docs/11` §5?
7. Do the regression thresholds (`docs/14` §2.4) still hold on Kolu?

---

## 6. The demo deployment

- Build with `python tools/build_all.py`; it fails if a page drifts off the design system,
  a script loses an element, or a figure disappears from its source.
- Deploy from `demo/` with `vercel deploy --prod --yes`. Git integration is **off** on
  purpose.
- **Only the auto-assigned production domain is public** (`tesseract-demo.vercel.app`).
  A manually set `*.vercel.app` alias serves a login wall, and a `200` from curl proves
  nothing — check it in a signed-out browser.
- `.env.local` holds a Vercel OIDC token. It is excluded by `.vercelignore`. Back it up
  before any `vercel blob` command, which can overwrite it.
- The pages must open from `file://`: no `<link>`, fetch, ES modules or workers. Colours
  never appear as `fill="#…"` in JS-built SVG; use the `.m-*` classes.

---

## 7. Trap register

Promoted from `docs/03` §5, plus what was found since. Read it once; it is cheaper than
rediscovering any of these.

| Trap | Consequence | Defence |
|---|---|---|
| **Scale "validated" by a plausibility band** | Kolu shipped 5.5× too small (`docs/08`) | External ruler or GNSS only (ADR-014) |
| **`metric_scaling_factor` not saved** | The one channel a scale audit needs is gone | GAP C-4 |
| **Priors never passed to MapAnything** | Scale and intrinsics left to the model | GAP C-5 |
| **"ENU" that is not east–north** | A GIS user trusts a heading that does not exist | The manifest now says `frame: "LLF"` (`docs/09` §1.1) |
| **Figure re-grep ≠ correctness** | A wrong source keeps a wrong number "verified" | Claims ledger (`docs/14` §4) |
| VGGT AUP bans military/espionage | Core model illegal for NTRO | MapAnything Apache (ADR-002) |
| Apache MapAnything trained on 6 datasets, not 13 | Probably weaker | EXP-02 |
| Consumer GNSS caps absolute at ~4 m | R-O3 unreachable without RTK | Report both numbers |
| ICP alignment flatters 12.8× | Looks like a pass | Harness reports both |
| 7-DoF fit on a straight pass | Scene thrown 267–311 m | 5-DOF only (ADR-008) |
| RANSAC threshold below the noise floor | Worse than no RANSAC | MAD-derived threshold |
| PROJ skips the geoid silently | 24–98 m vertical error in India | `allow_ballpark=False`, grid check |
| EGM96 vs EGM2008 differ 1.68 m (Amritsar) | Blows the budget alone | EPSG:9518 |
| UTM ≈ 0.6 m/km scale error | Baked into the fit | Fit in ENU, project last |
| DJI `abs_alt` is barometric | Fake correlated height constraint | Never a BA observation |
| DJI unit encodings flip silently; `longtitude` | Wrong values, no error | EXP-23 fuzz suite |
| ODM stamps video frames `Model: "Unknown"` | Generic focal prior | Write true Make/Model |
| Mavic 3 filed as `Hasselblad L2D-20c` | Sensor lookup misses | Key on Make **and** Model |
| decord is abandoned | Dead dependency | PyAV |
| open3d has no 3.13 wheels | Environment breaks | Python 3.12 (§1.1 drift) |
| OpenMVS prebuilt needs GLIBC 2.38 | Won't load on Ubuntu 22.04 | ubuntu:24.04 base |
| OpenMVS tools exit non-zero on `--help` | Exit-code test cannot fail | Grep the loader error |
| COLMAP conda may resolve a CUDA build | Pulls an unusable toolkit | Pin the CPU build |
| COLMAP dense stereo is CUDA-only | Unavailable on CPU | OpenMVS on CPU (ADR-005) |
| `TextureMesh` fails in 0.2 s | No textured export | Per-vertex colour (ADR-016), EXP-20 |
| Sharding into thin tasks | 7% slower, 21% less precise | 2 × 8 vCPU (ADR-012) |
| Global CPU quota hidden behind regional view | Jobs queue for hours | Read Cloud Logging |
| Cloud Run L4 listed in asia-south1 but not deployable | Wasted debugging | Trust the deploy error |
| Stale keyframes from a previous run | 45 keyframes silently became 90 | Clear or refuse a dirty output dir |
| Horizon measured from the opening frames | Under-crops; hides a static watermark | Sample across the whole shot |
| Sky mask counts pale ground as sky | Near-nadir views rejected | Sky must touch the top edge |
| Title cards pass a sharpness test | Credits reconstructed | Slate gate |
| Random-triangle decimation for display | Speckled shading | Quadric decimation |
| Principal-axis sign is arbitrary | Inside-out surface, hidden by two-sided shading | Orient by cameras |
| Mean of per-view intrinsics | One collapsed view drags it | Median |
| Automation browser tab is hidden | Video never loads; rAF gives 0 frames | Not a page bug; test by hand |
| Vercel vanity alias is auth-gated | Judges hit a login wall | Use the production domain |
