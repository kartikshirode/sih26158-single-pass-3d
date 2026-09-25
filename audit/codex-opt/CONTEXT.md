# Context: audit and optimisation run on the local GPU pipeline

Reference material for the run described in `audit/codex-opt/PROMPT.md`. Read it once before
starting and come back when you need a fact. Where this file and the code disagree, the code
is the authority, and the disagreement goes in your log.

Everything here was checked on 2026-09-26 against branch `audit-fixes` at commit 254aa0d.

---

## 1. The target

Smart India Hackathon 2026, problem statement SIH26158: one monocular drone video from a
single flight pass (plus GPS and flight metadata when the drone wrote them) in; a
georeferenced, metrically accurate, textured 3D model out. Requirement IDs come from
`docs/01-SRS-requirements.md`:

| ID | Target |
|---|---|
| R-O1 | 3D mesh or point cloud |
| R-O2 | a 10-minute video processed in under 15 minutes |
| R-O3 | spatial accuracy 1 m or better, absolute and georeferenced |
| R-O4 | the entire visible scene |
| R-O5 | OBJ, PLY, LAS, GeoTIFF, glTF/GLB, FBX |
| R-O6 | a web or desktop viewer |

Judging weights: accuracy 30, completeness 20, speed 20, innovation 15, scalability 10,
UI 5. The judging dataset arrives on the day of the finale, so an unknown clip must never
crash the system and must never produce a confident wrong number.

**The owner's goal for this run.** A 10-minute 1080p 30 fps video, video in to textured
model out, in under 15 minutes on this laptop, with the best model this hardware and these
models can produce. That is a ratio of 1.5: wall time over clip duration must be at most 1.5.
Shorter test clips are judged at the same ratio (section 4). The owner rated the current
demo output 5/10: "performance is good but it is still missing; we are not at the peak or
the best use of the models and the resources."

## 2. Where the pipeline stands

Run `python tesseract.py run <video> --geometry local --horizon crop --name <run>`. Stages
S0 screen, S1 ingest, S2 plan, S3 geometry, S4 scale, S5 georef, S5b level, S6 export,
S7 score, S8 verdict, with content-addressed resume (`state.json`) and a degradation
ladder L0 to L5 (`src/tesseract/pipeline.py`). S3 on this machine is
`src/pipeline/local_gpu.py`:

1. MapAnything (`facebook/map-anything-apache`, bf16) on 60 spread keyframes, only to fit
   one shared pinhole camera from its point maps.
2. COLMAP 4.2: GPU SIFT (4096 features) with that camera fixed, sequential matching over 30
   neighbours plus quadratic far pairs, `global_mapper` with focal, principal point and
   distortion fixed, the S3b gate (every view registered, at most 1 px).
3. OpenMVS 2.4 CUDA: DensifyPointCloud at resolution level 1 (half size), 5 neighbour views,
   3 views to fuse, fusion filter 1, no region of interest, tower mode off.
4. ReconstructMesh at 2.5 px minimum point distance, then TextureMesh on the mesh decimated
   to 10%, seam levelling off, to `geometry/scene_tex.obj` with an MTL and a JPEG atlas.

S1 (`src/ingest/video_ingest.py`) scores about 15 frames a second, crops burned-in overlays,
letterbox bars and (with `--horizon crop`) everything above the horizon, and picks
keyframes on an optical-flow budget. `select_keyframes` bridges any stretch the gates empty.

### The demo run today (`out/runs/demo_gpu2`, 18.9 s clip, 177 keyframes)

| Stage | Seconds |
|---|---:|
| S0 screen | 1.7 |
| S1 ingest | 4.1 |
| S3 MapAnything load + inference (60 views) | 42.1 |
| S3 feature extraction | 4.6 |
| S3 sequential matching | 7.2 |
| S3 global_mapper (CPU bundle adjustment) | 85.4 |
| S3 undistort, interface, model conversion | 4.4 |
| S3 DensifyPointCloud | 51.4 |
| S3 ReconstructMesh | 60.4 |
| S3 TextureMesh (not in the stage list above; added after this run) | about 60 |
| S5b level, S6 export | 3.7 |
| **Whole run** | **268.8** (about 330 with texturing) |

Scaled budget for this clip: 1.5 x 18.9 = 28 s. The run is about 11 times over it. Some
costs are fixed per run and do not grow with clip length (MapAnything weights load in about
16 s), so the short clips also get a second figure with those broken out; section 4.

Shape checks (`tools/geometry_check.py`) on the demo: sparse ground within 3% of the
flight height of one plane 0.77, layered dense cells 0.06, largest camera step 2.2 times
the median, 7.0M dense points, mean track length 10.8, 0.49 px after the mapper.

### What the owner and the last investigation saw as still wrong

- **Far field smeared.** The houses at the far end are only seen at grazing angles, and the
  horizon crop removes the top 37% of every frame, which is most of what sees them.
- **Seams.** Seam levelling is off in TextureMesh because, on, it turned 73% of faces
  black. Nobody knows why yet; exposure differences now show at patch borders.
- **Uncovered faces.** 3.8% of textured faces are seen by no photo (orange empty colour).
- **Time.** About 11x the scaled budget on the demo. The earlier 8 to 12 minute prediction
  for a 10-minute clip (`research/09`) was made on the old pose path and no longer holds.
  global_mapper's cost on 600 views is unmeasured.
- **Exports.** The textured OBJ stays in `geometry/`. S6 writes PLY, LAS and GeoTIFF only,
  so R-O5 reads 3 of 6 on this path.
- **Georeferencing.** S5 never runs on real video (gap C-3 in `docs/09`): SRT telemetry is
  parsed in S1 but not fed to georeferencing. `data/test_flight.mp4` has an SRT and can
  exercise it.
- **Estimates.** `Geometry.S_PER_VIEW_LOCAL_*` in `src/tesseract/stages.py` still hold the
  old pose path's rates, and the ladder uses them against a 900 s budget.

Full history: `research/09-gpu-pipeline.md` (laptop setup, first optimisation passes),
`research/10-reconstruction-quality.md` (why the model was wrong, every experiment),
ADR-027 and ADR-028 in `docs/10-decision-log.md`.

## 3. Things already tried. Do not repeat without a new reason

| Tried | Result | Source |
|---|---|---|
| MapAnything input size 392 or 448 px | faster, but failed the 2 px intrinsics guard (3.75 and 2.46 px) | research/09 |
| bf16 weights (not just autocast) | dtype mismatch in the model | research/09 |
| COLMAP PatchMatch as the densifier | 488 s for its photometric pass on 129 views vs 31 s for all of OpenMVS | research/09, ADR-027 |
| global_mapper on 568 views with MapAnything poses (old path) | 337 s and a folded model | research/09 |
| MapAnything window poses + triangulation + BA | ground in stacked tilted sheets; BA to convergence and a 40-neighbour window did not help | research/10 |
| COLMAP incremental mapper, focal free or fixed | ground curled into a bowl; focal went to 576 px against 1100 px | research/10 |
| Refining principal point after the global mapper | cy wandered from 293 to 162 px | research/10 |
| OpenMVS fusion filter 2 (dense-fuse, the default) | kept 160k of 52M depths | research/10 |
| OpenMVS ROI estimation and crop | cut the far field | research/10 |
| TextureMesh with seam levelling | 73% of faces black (global only 95%, local only 66%) | research/10 |

## 4. Benchmarks and budgets

| ID | File | What it is | Duration | Scaled budget (1.5x) |
|---|---|---|---:|---:|
| B1 | `SIH DEMO.mp4` (repo root, gitignored) | real clip, letterboxed, horizon in every frame, watermark; the owner's reference | 18.9 s | 28 s |
| B2 | `data/nicosia_1080p.mp4` | real 1080p clip, 29.97 fps | 40.0 s | 60 s |
| B3 | `data/test_flight.mp4` + `data/test_flight.SRT` | synthetic render with a DJI-style SRT: the only clip with GPS | 20.0 s | 30 s |
| B4 | `out/smoke/demo_loop_10min.mp4` | B1 looped to 600 s. Loop points read as cuts, so S1 keeps one 19 s shot: a speed test for S0 and S1 only | 600 s | 900 s |
| B5 | to build | a genuinely 10-minute continuous clip, so S3 sees about 600 keyframes | 600 s | 900 s |

B5 does not exist yet. `src/ingest/make_test_video.py` renders the synthetic scene to an
H.264 1080p30 MP4 with a DJI SRT (`--seconds 600`); check how long a 600 s render takes
before committing to it, and consider a shorter render scaled up if it is too slow. An
earlier 600-view S3 test used keyframes from `data/test_flight.mp4`.

**How to report time.** For every run: wall time, the ratio R = wall time / clip duration,
and a per-stage table. For the short clips also report R with the fixed costs (model load,
process start, anything that does not grow with frames) subtracted, and extrapolate to
600 s from per-keyframe rates. The claim that finally matters is B5 end to end at R <= 1.5.

**How to judge quality** (sections 5 and 6 of PROMPT.md hold the thresholds):

- `tools/geometry_check.py <run>/geometry`: sparse_on_plane, layered_cells, step_ratio.
- The S3b figures in `geometry/local_gpu_result.json`: registered views, reprojection error,
  track length.
- A held-out view check that does not exist yet (PROMPT.md phase 1): render the textured
  mesh into keyframes left out of densify and texturing, and score it against the real
  frame. That is the closest thing to ground truth this project has for real clips.
- Pictures: `python tools/build_run_page.py <run>` writes `<run>/index.html`; headless
  Chrome takes a screenshot (section 6).
- On B3 only: absolute error against the synthetic truth, through S7 (`src/eval3d/metrics.py`).

## 5. Machine

- Windows 11 Home, Intel i7-13650HX (20 threads), 24 GB RAM, NVIDIA RTX 4060 Laptop GPU
  (8 GB, driver 596.49). Windows WDDM spills GPU memory to shared system memory silently
  instead of failing; a run that suddenly takes many times longer has probably spilled.
- About 140 GB free on C:. The owner has asked for care with disk space.
- Global Python 3.12.10, no venv: torch 2.13.0+cu130, torchvision 0.28.0+cu130, mapanything
  1.1.4, uniception, opencv, PyAV, numpy, scipy, trimesh, plyfile, pyproj, laspy, rasterio,
  python-docx. open3d is NOT installed.
- COLMAP 4.2.0 Windows CUDA build: `C:\Users\Kartik\gpu-tools\colmap\bin\colmap.exe`. It has
  no CUDA Ceres, so every bundle adjustment runs on the CPU. COLMAP 4 stores poses in
  `frames.txt`/`frames.bin`, not only `images.*`.
- OpenMVS 2.4 Windows CUDA build: `C:\Users\Kartik\gpu-tools\openmvs_cuda` (DensifyPointCloud,
  ReconstructMesh, RefineMesh, TextureMesh, InterfaceCOLMAP, TransformScene and others).
  OpenMVS writes its logs to `<Tool>-<timestamp>.log` in the working folder, not to stdout.
- Set `SIH_COLMAP` and `SIH_OPENMVS` to those two paths before any local run.
- MapAnything weights are cached under `C:\Users\Kartik\.cache\huggingface`. The DINOv2 hub
  code is cached under `C:\Users\Kartik\.cache\torch\hub`.
- Headless Chrome for page screenshots:
  `"C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --use-angle=swiftshader --enable-unsafe-swiftshader --window-size=1400,1100 --virtual-time-budget=20000 --screenshot=<png> <file:///...index.html>`
  (give it its own `--user-data-dir` under `out/codex/`).
- `.env` in the repo root holds a vast.ai API key. Never open, print, copy or use it.

## 6. Licences and data rules

- Only the Apache MapAnything checkpoint may ship. Barred from any product build: VGGT,
  MASt3R, DUSt3R, UniDepth, Inria 3DGS/2DGS, Pi3, and the CC-BY-NC MapAnything checkpoint.
  Any new model or library needs its licence checked from its own repository before it is
  used, and recorded; research-only use of a barred model is allowed for a comparison only
  if it never enters `src/`, `tools/` or a default config.
- OpenMVS (AGPL-3.0) runs unmodified, as a separate process. COLMAP is BSD.
- Compute stays on this laptop. No cloud jobs, no rented GPUs.
- `SIH DEMO.mp4` is gitignored. Frames, crops or renders of it must not be committed.

## 7. Out of scope

- `Report Template  - Grand challenge 1.docx` and `sample scenario for GC 1.pptx` in the repo
  root are for a different competition (a swarm communications challenge). Ignore them, and
  never commit them.
- The web upload path (`demo/api/`, `run_job/`, Cloud Run) and the cloud jobs
  (`mapanything_job/`, `mvs_job/`) except where a shared function they import changes.
- `master`. All work happens on the branch PROMPT.md names.

## 8. Where to look

- `.claude/codemap.md`: one entry per file. Read its Overview first; route with it, then
  read the file itself.
- `CLAUDE.md` in the repo root: the rules for keeping the codemap current.
- `docs/09-interface-contracts.md` (frames F0 to F7, units, stage contracts),
  `docs/10-decision-log.md` (ADR-001 to ADR-028), `docs/08-measurement-validation.md` (never
  print a metre that was not validated from outside the model).
- `research/09` and `research/10` for everything measured on this laptop so far.
- Tests: `src/ingest/test_srt.py`, `src/ingest/test_frames.py`,
  `src/pipeline/test_local_gpu.py`, `src/pipeline/test_colmap_export.py`,
  `src/pipeline/test_window_fuse.py`, `mvs_job/test_ba_gate.py`, `src/eval3d/test_metrics.py`,
  `src/tesseract/test_tesseract.py` (76 pass, 1 skip today), `tools/check_onboarding.py`, and
  `node --test "demo/test/*.test.js"` for the API. CI runs all of them
  (`.github/workflows/ci.yml`).
