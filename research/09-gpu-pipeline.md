# 09 · GPU pipeline on one laptop

Started 2026-09-25. Goal: a 10-minute 1080p30 drone video in, a 3D model out, on one
machine, in 30 minutes (±10); stretch goal 15 minutes. Until now every run used CPU only,
because the GCP account has no GPU quota (`docs/06`). This file records what was
installed on the machine, what was measured, what changed in the code and why, the two
optimisation passes, the two reviews, and the prediction for the full-length run.

The 10-minute run itself has **not** been executed. The prediction in section 8 comes
from smoke tests: S0 and S1 were timed on a real 10-minute file (the demo clip looped),
and S3 on 568 and 600 views, which is the view count a 10-minute clip produces.

**Superseded in part (same day).** The models this pose path built were wrong in shape:
the ground came out in stacked, tilted sheets. `research/10-reconstruction-quality.md`
traces it and replaces the pose step with COLMAP's global mapper. S3 on the demo went
from 134 s to 259 s, so the section 8 prediction no longer holds until it is measured
again on the new path.

## 1. Changes made to this machine

Everything installed or changed for this work, and whether it has been undone. Nothing
outside this list was touched.

| # | Change | Where | Size | Reverted? | How to revert |
|---|---|---|---|---|---|
| 1 | Global Python 3.12: `torch 2.13.0+cpu` replaced by `torch 2.13.0+cu130`, and the already broken `torchvision 0.21.0+cu124` by `torchvision 0.28.0+cu130` | `C:\Users\Kartik\AppData\Local\Programs\Python\Python312` | ~3 GB | No, the pipeline needs it | `pip install torch==2.13.0 torchvision --index-url https://download.pytorch.org/whl/cpu` |
| 2 | Global Python: `uniception 0.1.7` and `mapanything 1.1.4` (editable, `--no-deps`), plus `hydra-core`, `natsort`, `python-box`, `plyfile`, `trimesh`, `jaxtyping`, `termcolor` | same | small | No | `pip uninstall mapanything uniception` and the others |
| 3 | Global Python: `pyproj 3.7.2`, `laspy 2.7.0`, `rasterio 1.5.1`, the pins in `requirements.txt`, for S6 export | same | ~60 MB | No | `pip uninstall pyproj laspy rasterio` |
| 4 | MapAnything source checkout | `C:\Users\Kartik\gpu-tools\map-anything` (commit `3d10cf7`) | small | No | delete the folder after item 2 |
| 5 | MapAnything Apache weights and the DINOv2 hub code | `C:\Users\Kartik\.cache\huggingface\hub\models--facebook--map-anything-apache` (4.6 GB), `C:\Users\Kartik\.cache\torch\hub\facebookresearch_dinov2_main` | 4.7 GB | No | delete both folders |
| 6 | COLMAP 4.2.0 Windows CUDA build (prebuilt, unzipped) | `C:\Users\Kartik\gpu-tools\colmap` | 742 MB | No | delete the folder |
| 7 | OpenMVS 2.4.0 Windows CUDA build (prebuilt, unpacked) | `C:\Users\Kartik\gpu-tools\openmvs_cuda` | 69 MB | No | delete the folder |
| 8 | The archives for items 6 and 7, and the non-CUDA OpenMVS build | `C:\Users\Kartik\gpu-tools` | 0.4 GB | Yes, deleted after unpacking | none needed |
| 9 | A `pip freeze` of the global environment taken before item 1 | `C:\Users\Kartik\gpu-tools\pip_freeze_before_2026-09-25.txt` | small | Kept as the revert reference | none |
| 10 | Test data: the demo clip looped to 10 minutes, keyframe sets and smoke outputs | `out\smoke\` in this repo (gitignored) | ~3 GB | No, kept for the full run; the two largest work folders (7.8 GB) were deleted once their timings were saved | delete `out\smoke` |
| 11 | Removed: the temporary virtual environment an earlier session made for the CPU tests | `C:\Users\Kartik\AppData\Local\Temp\sihv` | 620 MB freed | It was itself a temporary change; the global Python now runs every test | recreate with `python -m venv` if ever needed |

Not changed, although the plan allowed it: Docker Desktop (it failed to start when
checked, and nothing here needs it), the WSL2 memory cap (`.wslconfig` still does not
exist), the power plan (Best performance was already set), and the vast.ai account (no
instance created, no money spent). The tools are found through two environment variables
set per shell, never written to the system: `SIH_COLMAP` and `SIH_OPENMVS` (section 9).

One process was killed by name during the work (`taskkill /IM python.exe`, to stop a
stalled smoke run). Only that run's process was alive at the time; later stops used the
process id.

## 2. The machine

Lenovo 83JJ: i7-13650HX (14 cores, 20 threads), 24 GB RAM, RTX 4060 Laptop GPU with 8 GB,
NVIDIA driver 596.49 (CUDA 13.2), Windows 11, Power mode "Best performance" on mains power.
About 126 GB free on C: at the end.

## 3. The demo clip

`SIH DEMO.mp4`: 1920x1080, H.264 Main, 30 fps constant, 18.9 s, 568 frames, 19.7 Mbps,
re-encoded by Clipchamp. No drone metadata and no SRT, so no georeferencing and no metric
scale. One continuous oblique orbit over a construction site with sky in the top ~15% of
every frame, a burned-in "STRUDWICKDRONESERVICE.com" watermark, and 34 black rows above
and below the picture. It is third-party footage: fine for local tests, and none of its
output goes into the repo or the demo site (`docs/16`).

Checking it found a real defect before any GPU work: the screener accepted the clip with
sky 0.0 and horizon 0.0. The sky test anchored on the top edge, which was a black bar.
Fixed in `9fb9071` (section 5).

## 4. Baseline

What the pipeline cost before any of this work, on the same laptop.

| Stage | How measured | Time |
|---|---|---|
| S0 screen | as-found code on the 10-minute loop | 22.4 s |
| S1 ingest | as-found code on the 10-minute loop | 401.6 s, 10.7 GB peak |
| S3 geometry, CPU path | Kolu record, 45 views, 8 vCPU (`research/run-evidence`) | 11.45 s/view poses, 391 s exhaustive matching (grows with views squared), 2071 s densify, 1078 s texture |
| S3 geometry, first GPU draft | `local_gpu.py` as first written, 568 demo views | 983 s: poses 139, SIFT 17, matching 200, triangulation 146, BA 311, densify 92, mesh 46 |

The first GPU draft already put a 10-minute clip at roughly 24 minutes, inside the 30 ± 10
target. The two passes below bring it under the 15-minute stretch goal.

What the GPU made possible, measured on this laptop:

- **MapAnything** in bf16: 0.12 to 0.15 s per view at 518x168, 0.22 to 0.25 at 518x294.
  The weights alone take 4.62 GiB of the 8. EXP-11 measured 0.55 s per view on a T4.
- **COLMAP** GPU SIFT: 0.03 s per image.
- **OpenMVS** CUDA densify: 0.31 s per view at 967x297, against 46 s per view on 8 vCPU.
- **COLMAP PatchMatch** (ADR-023's proposal), same 129 views and resolution: 3.8 s per
  view for the photometric pass alone (488 s), with a geometric pass of the same length
  still to run. OpenMVS did the whole densify in 31 s. Stopped, and OpenMVS kept
  (ADR-027).

## 5. Optimisation 1

| Change | Why | Effect |
|---|---|---|
| Sequential matching instead of exhaustive | exhaustive grows with views squared, about 19 h at 600 | built in from the start |
| DIS optical flow instead of Farneback in S1 | Farneback was 60% of S1's per-frame cost (14.4 of 24 ms) | same mean motion; keyframes moved by at most two frames |
| Score about 15 frames a second in S1 | keyframes are ~30 frames apart on a 10-minute clip | S1 240 s to 108 s |
| Frame-threaded decoding in S0 and S1 | the decoder was single-threaded | S0 22 s to 10 s |
| One sky mask for both sky and horizon | each built its own | 3 ms per frame |
| Second pass crops as it decodes; analysis copies freed | crops were views keeping every full frame alive | peak 10.7 GB to 4.3 GB |
| 4096 SIFT features, one triangulation refinement, 10 BA iterations | BA's cost was flat after 10 iterations (0.3587 px against 0.3582 at 100) | matching, triangulation and BA 657 s to 150 s on 568 views, 0.49 px against 0.46 |
| Point filtering after BA | a few near-zero-depth points made the mean error 2.0e149 px | 0.36 px on 129 views |
| MapAnything windows sized to the GPU; view dicts copied per window | finished windows' images stayed on the GPU, and at 518x294 the driver spilled into shared memory and the run stalled | peak 6.73 GiB on 600 uncropped views |
| Letterbox-aware sky, horizon and overlay detection | the defect in section 3 | watermark and bars cropped off |

After optimisation 1: S0 + S1 118 s on the 10-minute loop; S3 460 s on 568 cropped views
and 634 s on 600 uncropped views.

## 6. Review 1 and its fixes

One reviewer read the four commits of optimisation 1. Eight findings, all fixed in
`76d98ca`, `02a6b2c` and `b886f24`:

1. `colmap_export` refuses a bad camera with `SystemExit`, which bypassed the ladder and
   ended the process with no manifest. Now a `SparseError`, mapped to a `StageError`.
2. S1 never cleared `keyframes/`, so re-running a clip with other settings mixed two
   keyframe sets into one reconstruction. S1 now clears it.
3. The variable-frame-rate flag called almost every clip variable once S1 scored every
   second frame.
4. One dark sample could bring the letterbox edges back into the overlay mask.
5. A sparse failure (S3b gate, intrinsics, no GPU) was recomputed at L1 and L2 only to fail
   again. It is now replayed.
6. A meshing failure failed all of S3. It is now recorded and the dense cloud kept.
7. The second-pass crop kept the full frame alive for a top-and-bottom crop.
8. Keyframes sorted as strings put the 1000th between the 100th and the 101st.

## 7. Optimisation 2

| Change | Effect |
|---|---|
| S1 scans time segments on threads (constant-rate clips of a minute or more), threaded crop re-scoring, threaded second pass and JPEG writes | S1 108 s to 55 s on the 10-minute loop, identical keyframes |
| DIS flow from a fresh object per pair | one object carries state between calls: 1.17 px after a run of calls against 3.41 px fresh on a small test clip, so threads disagreed at segment starts; on the demo's 480x270 frames the two agree exactly |
| Sequential matching with 6 neighbours instead of 10 | 135 s to 43 s on 600 uncropped views, 0.63 px against 0.64 |
| Five views per depth map instead of eight | densify 107 s to 96 s |
| Mesh minimum point spacing 2.5 px instead of 1.5 | 91 s and 4.0M faces to 60 s and 2.6M |

Tried and rejected:

| Idea | Result |
|---|---|
| MapAnything at 392 or 448 px | 1.9x and 1.4x faster, but the intrinsics fit failed its 2 px guard (3.75 and 2.46 px); 518 kept |
| MapAnything weights cast to bf16 | not supported: a float and a bf16 tensor met in a linear layer |
| Densify resolution level 2 | identical output: the 640 px minimum resolution clamps it |
| Densify without normals, or one geometric pass | normals changed nothing; one pass saved 15 s but dropped 5% of points and the geometric check that filters noise |
| COLMAP global mapper instead of MapAnything poses | 337 s for 129 views, and the model came out folded |

Review 2 read the review-1 fixes and optimisation 2. It confirmed the review-1 fixes and
found three things in the threaded scan, all fixed and covered by a test:

1. With a first timestamp other than 0, `t - t_first` lands just under whole seconds, so
   the sequential scan started one frame later than the threaded one and every scored
   frame shifted by one. Both limits now allow a microsecond of slack; the test encodes
   a clip whose first frame is at 2/30 s and fails on the old code.
2. A seek that landed past a segment's flow reference frame would have left that
   segment's first flow at 0 without falling back. It now falls back.
3. After a threaded scan the frame numbers come from timestamps, but the sequential
   second pass, the fallback when the threaded one fails, counted decoded frames. It now
   numbers by timestamp too.

A meshing failure now also reaches the run's facts (`mesh_error`), not only
`local_gpu_result.json`.

After optimisation 2 and the review-2 fixes: S0 + S1 63 s on the 10-minute loop (9.8 s
and 53.3 s, 5.9 GB peak, the same 600 keyframes as before); S3 511 s on 600 uncropped
views (0.63 px after BA, 4.47M dense points) and 420 s on 568 cropped views (0.46 px,
1.40M).

## 8. Prediction for a 10-minute 1080p30 clip on this laptop

| Stage | Uncropped 16:9 | Cropped like the demo | Source |
|---|---:|---:|---|
| S0 screen | 10 s | 10 s | measured on the 10-minute loop |
| S1 ingest + keyframe JPEGs | 58 s | 57 s | measured on the 10-minute loop |
| S3 poses (MapAnything) | 254 s | 140 s | 600-view smokes |
| S3 SIFT, matching, triangulation, BA | 86 s | 177 s | 600-view smokes |
| S3 densify, undistort, mesh | 162 s | 115 s | 300 dense views |
| S3 other (intrinsics, model conversion) | 6 s | 9 s | |
| S4 to S8 | 5 s | 5 s | demo run, scaled to 4.5M points |
| **Total** | **~581 s (9.7 min)** | **~513 s (8.6 min)** | |

The cropped column scales the 568-view smoke to 600 views and 300 dense views.

The uncertainty is mostly in the sparse and dense stages, because the smokes used
consecutive frames and a real 10-minute clip's keyframes are about a second apart.
Matching alone moved between 43 s and 96 s across the two smoke clips. Allowing +60 s for
matching, ±30 s for densify, +15 s for a cold model load and 5% for heat over a sustained
run, the prediction is **8 to 12 minutes**, against the 30-minute target and inside the
15-minute stretch goal. No vast.ai machine is needed.

The first-draft S3 estimate in `stages.py` would have put a 10-minute clip at 915 s and
stepped it down the ladder inside the 900 s budget; the measured rates put it at 555 s.

## 9. Running it

```powershell
$env:SIH_COLMAP = "C:\Users\Kartik\gpu-tools\colmap\bin\colmap.exe"
$env:SIH_OPENMVS = "C:\Users\Kartik\gpu-tools\openmvs_cuda"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
python tesseract.py run <video.mp4> --geometry local --horizon crop --name <run>
python tesseract.py verify out\runs\<run>
```

`--horizon crop` keeps clips that show the horizon (the demo does) by cutting the sky off
instead of refusing them. The run writes `out\runs\<run>\geometry\` (dense cloud
`scene_dense.ply`, mesh `scene_dense_mesh.ply`, `local_gpu_result.json` with every
stage's time) and the usual exports and QA report. Geometry alone can be run on a
keyframe folder with `python src\pipeline\local_gpu.py <keyframes> --work <dir>`.

## 10. Record of runs

| Run | Views | S3 time | BA error | Dense points |
|---|---|---:|---:|---:|
| `g1`, first draft, 129 demo views | 129 | 216 s | 0.36 px | 0.71M |
| `g568`, first draft | 568 | 983 s | 0.46 px | 1.53M |
| `g568o1`, optimisation 1 | 568 | 460 s | 0.46 px | 1.40M |
| `t600o1`, optimisation 1, uncropped | 600 | 634 s | 0.65 px | 4.39M |
| `t600o2`, optimisation 2, uncropped | 600 | 511 s | 0.63 px | 4.47M |
| `g568o2`, optimisation 2 | 568 | 420 s | 0.46 px | 1.40M |
| `demo_gpu`, full tesseract run on the 19 s demo, 140 s end to end | 134 | 133 s | 0.44 px | 0.93M |

Every run passed the S3b gate (every view registered, at most 1 px after BA). The
uncropped views are the synthetic `data/test_flight.mp4` rendered scene; they measure time
at full 16:9 frame size, not reconstruction quality. The timing records
(`local_gpu_result.json` of each run, and the S0/S1 benchmark lines) are in
`research/run-evidence/gpu-2026-09-25/`; no geometry or imagery from the demo clip is kept
in the repo.
