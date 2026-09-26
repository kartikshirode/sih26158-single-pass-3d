# Local GPU audit run log

Started 2026-09-26 on `codex-opt`, from `audit-fixes` commit 0340d7e. The
existing `.gitignore` edit and two GC-1 files were left alone.

## Machine changes

| When | What | Where | Size | Undo |
|---|---|---|---:|---|
| Phase 0 | No package or model installed | Machine | 0 | None |
| Phase 0 | OpenMVS help probe wrote a log, then I deleted that log | Repo root | Under 1 KB | Done |
| Phase 1 | Rendered and deleted a 5 s B5 timing probe and its SRT | `out/codex/b5-probe.*` | 1.6 MB MP4 plus small SRT | Done |
| Phase 1 | Deleted failed long-run database, copied images and sparse model after recording the result | `out/codex/long-base/` | 532.4 MB | Done; the result JSON and logs remain |

The tools are `C:\Users\Kartik\gpu-tools\colmap\bin\colmap.exe` (COLMAP 4.2.0
CUDA) and `C:\Users\Kartik\gpu-tools\openmvs_cuda` (OpenMVS executables present).
PyTorch 2.13.0+cu130 sees the RTX 4060 Laptop GPU. C: had 142.68 GiB free.
The two `SIH_*` variables need setting in each run shell.

## Phase 0 tests

| Test | Result |
|---|---|
| `src/ingest/test_srt.py` | PASS |
| `src/ingest/test_frames.py` | PASS |
| `src/pipeline/test_local_gpu.py` | PASS |
| `src/pipeline/test_colmap_export.py` | PASS |
| `src/pipeline/test_window_fuse.py` | PASS |
| `mvs_job/test_ba_gate.py` | PASS |
| `src/eval3d/test_metrics.py` | PASS |
| `src/tesseract/test_tesseract.py` | 76 passed, 1 skipped |
| `tools/check_onboarding.py` | PASS |
| `node --test "demo/test/*.test.js"` | 17 passed |

## Experiments

| ID | Hypothesis | Single change | Benchmark | Time | Quality | Decision | Commit |
|---|---|---|---|---|---|---|---|
| V0 | A held-out render can expose missing or wrong texture without training on its photo | Add a scorer and exclude every tenth keyframe from dense and texture input | Projection test and renderer smoke on an existing B1 mesh | Projection test failed before implementation with `ModuleNotFoundError`; passed after with pixel (370, 360). Renderer smoke covered 99.54% of one in-sample B1 frame, so it is not a quality baseline | Not applicable | Keep as measurement tool | Pending |
| B1-0 | Measure the current path on the owner's clip | None; clean run at commit 0340d7e | B1, 18.9 s clip, 177 keyframes | 321.92 s wall, R 17.03 | 177/177 registered, 0.490 px reprojection, mean track 10.767, 7,024,575 dense points; sparse on plane 0.785, layered cells 0.056, step ratio 2.2; held-out coverage 98.02%, PSNR 21.728 dB, SSIM 0.53592 over 17 views | Baseline | Not applicable |
| B2-0 | Measure the unchanged path on another real clip | None; clean run at commit 0340d7e | B2, 40.0 s clip, 289 keyframes | 490.83 s wall, R 12.27 | 289/289 registered, 0.471 px reprojection, mean track 22.231, 5,500,541 dense points; sparse on plane 0.316, layered cells 0.000, step ratio 112.3; held-out coverage 97.67%, PSNR 19.826 dB, SSIM 0.64358 over 28 views | Baseline, wrong shape | Not applicable |
| B3-0 | Measure the unchanged path on a clip with SRT | None; clean run at commit 0340d7e | B3, 20.0 s clip, 173 keyframes | 367.23 s wall, R 18.36 | 173/173 registered, 0.898 px reprojection, mean track 10.027, 9,669,064 dense points; sparse on plane 0.894, layered cells 0.018, step ratio 1.0; held-out coverage 93.03%, PSNR 30.603 dB, SSIM 0.91999 over 17 views. S5 skipped despite 600 SRT records | Baseline | Not applicable |
| B4-0 | Time ingest on a 600 s file | Only S0 and S1 ran, no geometry | B4, 600 s loop | 61.74 s for S0 and S1; S0 10.24 s, S1 51.51 s | S1 selected 600 keyframes and reported one shot; S0 reported 32 shots | Throughput baseline, not a geometry benchmark | Not applicable |
| B5-probe | Check whether a fresh 600 s continuous render is practical | Render 5 s of the same synthetic flight, no pipeline change | 1080p30, 150 frames | 209.52 s render, 1.40 s per frame | Predicted 18,000-frame render about 7.0 h at the measured rate; no B5 built | Stop full render; time S3 on the existing 600-frame synthetic set instead | Not applicable |
| L0 | Measure a 600-view mapper with the current geometry path | None; 600 consecutive synthetic keyframes, 300 planned dense views | Existing 20 s synthetic frame set, S3 only | 377.60 s to S3b; MapAnything 43.24 s, intrinsics 1.81 s, SIFT 20.11 s, matching 64.76 s, mapper 246.55 s, analysis 0.41 s | 553/600 registered, 0.845 px reprojection on those views, mean track 18.533; S3b failed and no dense model was made | Baseline failure; cannot infer full 600-view wall time | Not applicable |
| F1 | Flow plus a moderate histogram change will catch B2's hidden edit | S1 cuts when flow exceeds six times the median, is above 10 px and histogram correlation is below 0.9 | B2 ingest and full run; B1 and B3 ingest regression | B2 355.05 s wall, R 8.88, against 490.83 s and R 12.27 before | B2 now keeps frame 558 onward, 209/209 registered, 0.479 px reprojection, mean track 26.103, 3,866,395 dense points; sparse on plane 0.294, layered cells 0, step ratio 2.0. B1 remains 177 views and B3 173 | Keep: the spliced trajectory is removed; the smaller plane fraction is for a different shot, so the usual same-frame gate does not apply | e39dd18 |
| F2 | A rejected video must leave a labelled manifest | Map S1's `RuntimeError` to fatal `ING-REJECT` | Mocked no-usable-frames video in `test_tesseract.py` | Test failed first with uncaught `RuntimeError: every frame rejected`; then 79 passed, 1 skipped | `run_manifest.json` exists and records the reason and code | Keep as an S2 failure-path fix | This commit |

The V0 renderer smoke used an in-sample frame only to check that the renderer runs.
No held-out quality claim comes from that number.

### Long-run profile and time limits

`out/codex/long-base/local_gpu_result.json` records the failed S3b gate. The
mapper took 246.55 s for 600 views, up from 90.65 s for B1's 177. The 68
samples in `out/codex/long-profile.csv` span about 5.8 minutes. Whole-machine
CPU averaged 24.2% and reached 57.9%; GPU averaged 9.4%, was at 0% in 52
samples and used at most 2342 MiB in those samples. The mapper ran on CPU and
left the GPU idle. MapAnything separately reported a 6.73 GiB peak. These
samples are from the sparse portion only and cannot establish the dense peak.

B1, B2 and B3 wall times with the fixed model load removed are 305.72 s,
475.93 s and 351.43 s, or R 16.18, 11.90 and 17.57. That fixed-cost adjustment
does not make the short runs meet their scaled budgets. A 600 s end-to-end
prediction is unsafe until the 600-view registration failure is resolved and
the dense stages have been measured on a long continuous clip.

### B1 baseline detail

The clean run is `out/runs/codex-b1-base2`. The first attempt was stopped during
Hugging Face network retries; the next run set `HF_HUB_OFFLINE=1` and used the
cached checkpoint. `python tesseract.py verify` passed. The run page is at
`out/runs/codex-b1-base2/index.html` and its screenshot is
`out/codex/b1-base.png`. The mesh has visible far-field smear and orange gaps.

| Stage | B1 seconds |
|---|---:|
| S0 screen | 1.677 |
| S1 ingest | 4.174 |
| S2 plan | 0.006 |
| S3 geometry | 313.615 |
| S4 scale, S5 georef, S7 score, S8 verdict | 0.000 |
| S5b level | 0.799 |
| S6 export | 1.646 |

| S3 step | B1 seconds |
|---|---:|
| MapAnything | 32.38 |
| Intrinsics fit | 0.78 |
| Feature extraction | 4.42 |
| Sequential matching | 7.20 |
| Global mapper | 90.65 |
| Analyze and conversion | 2.01 |
| Undistort and OpenMVS interface | 2.47 |
| Densify | 52.11 |
| Mesh | 62.87 |
| Texture | 55.91 |

The global mapper alone used 28% of S3 time. The GPU sample during it was 0%
utilisation with 761 MiB allocated. OpenMVS texture also showed 0% GPU use in
one snapshot. Those samples locate idle stages, but they are not a utilisation
trace.

The held-out run is `out/codex/b1-heldout` with scores in
`out/codex/b1-view.json`. It registered all 177 views, then densified and textured
160 views. Frames 9, 19 and so on were excluded from both stages. The scorer
rendered 17 held-out cameras at quarter resolution. This second reconstruction
took 46.8 s to densify, 60.6 s to mesh and 53.2 s to texture; it is a quality
measurement cost and is not part of the 321.92 s production wall time.

### B2 baseline detail

The run is `out/runs/codex-b2-base`. Verify passed. Its page screenshot is
`out/codex/b2-base.png`. The mapper used 329.32 s of the 477.8 s S3 stage.
S0 took 1.789 s, S1 6.919 s, S5b 2.614 s and S6 1.420 s. The other
OpenMVS stages took 33.82 s for dense, 25.95 s for mesh and 24.20 s for
texture. The fixed model load was 14.9 s.

The 112.3 step ratio is a real failure. Keyframes `kf_105_f00556.jpg` and
`kf_106_f00558.jpg` are adjacent, yet their camera centres are 9.555 model
units apart against a 0.085 median step. A contact sheet in
`out/codex/b2-jump.jpg` shows an edit at frame 558. S1 detected only one
earlier cut and kept a 453-frame analysed stretch across this second edit.
The histogram correlation at frame 558 was 0.685, above its 0.55 cut
threshold; the optical flow was 52.257 px against a 2.292 px median and an
8.532 px 99.5th percentile. `detect_shots` accepts a flow array but never
uses it. This is an S1 finding: the resulting mesh is a bent strip despite
every view registering and a low reprojection error. The baseline stays as
found; the fix belongs to the audit phase.

A regression check is ready in `src/ingest/test_frames.py`. It printed
`[FAIL] an edit with histogram correlation above 0.55 still splits` and
`[(0, 6)]` before the fix. The same test says a fast pan with an unchanged
histogram must stay one shot. The code fix waits until the as-found B3 and
long-clip baseline is measured.

The B2 held-out run is `out/codex/b2-heldout`, with scores in
`out/codex/b2-view.json`. The held-out renderer gives a local image score
but does not detect the global camera teleport. Geometry checks and images
must still be used with it.

### B3 baseline detail

The run is `out/runs/codex-b3-base`. Verify passed. The page screenshot is
`out/codex/b3-base.png`. S0 took 1.656 s, S1 4.396 s, S3 357.237 s, S5b
1.112 s and S6 2.813 s. Within S3, MapAnything took 42.31 s, the mapper
31.18 s, dense 78.18 s, mesh 95.94 s and texture 78.96 s. Its 15.8 s model
load is the fixed part measured inside MapAnything.

S1 parsed 600 telemetry records. S5 recorded `STAGE-UNAVAILABLE` and did not
georeference the video. S7 reported no absolute truth score, so no metre claim
is available from this run. This is the known C-3 gap, now seen on B3.
The held-out score is in `out/codex/b3-view.json`; it uses 17 excluded views
and is a synthetic image check, not an absolute accuracy measurement.

| Short baseline | R | R after subtracting the measured model load |
|---|---:|---:|
| B1 | 17.03 | 16.18 |
| B2 | 12.27 | 11.90 |
| B3 | 18.36 | 17.57 |

These adjusted ratios remove only model loading. Process launch and other fixed
costs are not isolated, so the adjusted ratios remain upper bounds on the
per-frame cost. Scaling them straight to 600 s would be misleading because
the mapper depends on its track graph and grows sharply between B1 and B2.

### B4 ingest timing and profile

The S0 and S1 only run is `out/runs/codex-b4-ingest`. The pipeline finished
and wrote its manifest. The one-off timing command printed the wall time, then
its final summary expression failed because manifest stage rows are dicts, not
objects; the manifest gives the stage numbers above. During S1, three CPU
utilisation samples were 45.2%, 35.0% and 37.4%; GPU utilisation was 0% and
RAM use was 56.5% in that snapshot.

CONTEXT.md says S1 keeps one 19 s shot on the loop. The current code did the
opposite: S1 says one shot over 9,000 analysed frames and selected 600 views.
S0, sampling about every 129th frame, says 32 shots and 21.5 s longest.
This disagreement is a finding. B4 remains suitable for S0 and S1 throughput,
but it is not a valid long-flight geometry benchmark.

The B5 probe completed all 150 frames in 209.52 s. A 600 s render would have
18,000 frames and take about 25,142 s, or 7.0 h, if the rate holds. That is
render preparation time alone, before ingest or geometry. I deleted the probe
MP4 and SRT after recording the timing. The existing `out/smoke/tf_all` has
600 consecutive 1080p synthetic frames; it will exercise mapper size, though
its camera spacing is unlike a 600 s flight.

## Second session, 2026-09-26 night

The first session stopped at its usage limit with F2 staged; that was committed as
b97ac13 after its tests passed. This section carries on from phase 3.

### Machine changes, second session

| When | What | Where | Size | Undo |
|---|---|---|---:|---|
| Start | Deleted duplicate `scene_dense.ply` files from the Codex baseline runs (the same cloud is in `points_fused.npy`) | `out/runs/codex-b*` | 1.43 GB | Rerun the benchmark |
| Start | Deleted dense PLYs, databases and depth maps from the held-out folders, keeping their scores, sparse models and textured meshes | `out/codex/*-heldout` | 2.21 GB | Rerun `tools/view_check.py --build` |
| Start | Deleted the aborted first B1 run, five Chrome profiles and two research-09 work folders (`g568o2`, `t600o2`) | `out/` | 1.2 GB | Regenerable; nothing refers to them |
| Start | `python -m pip cache purge` | `%LOCALAPPDATA%\pip\cache` | 3.68 GB | None needed; pip downloads again on demand |
| Phase 4 | assimp 6.0.5 Windows x64 library (BSD-3), from the official GitHub release, SHA-256 1AB3AC83...7C41; the .pdb debug file deleted | `C:\Users\Kartik\gpu-tools\assimp\Release\assimp-vc143-mt.dll` | 5.8 MB | Delete the folder |
| Phase 4 | `pip install pyassimp==5.2.5` (BSD-3, pure Python) | global Python 3.12 | 0.1 MB | `pip uninstall pyassimp` |
| Phase 4 | Rendered 600 sharp keyframes of the synthetic pass (`out/codex/render_b5s.py`, 8 processes, 157 s) | `out/codex/b5s` | 262 MB | Delete the folder |

Free space on C: went from 134.1 GB to 141.7 GB before any new run.

### Why the 600-view run failed, and B5s

B5 as a 600 s render would take about 7 h. It would not be a better test anyway:
`single_pass` spreads its frames over the same 920 m line whatever the duration, so a
600 s render gives S1 the same ground at 30 times the frame density, and S1 caps the
keyframes at 600. The S3 question for a 10-minute clip is "600 keyframes", so B5s is 600
sharp keyframes rendered straight to JPEG at 1920x1080, with S3 run on them with the
production settings (dense set 300, as S2 plans it).

The first B5s run failed the gate at 554 of 600, like L0 (553). The database says why:
the missing 46 are the last 46 frames, kf_554 to kf_599, with 36, 22, 3 and then 0
SIFT features. The pass flies 15% past the edge of the synthetic site and those frames
see nothing. So L0's failure was not the mapper or the blurred frames; it was frames
with no content, and the 100% gate refusing the whole run for them (finding F3).

### Experiments, second session

| ID | Hypothesis | Single change | Benchmark | Time | Quality | Decision | Commit |
|---|---|---|---|---|---|---|---|
| F3 | A few views the mapper cannot place should not refuse the run | Local gate needs 50% registered (ADR-029); unplaced views listed, dropped from dense, NaN in cameras.npy, GEO-UNREG in the manifest | B5s | See L1 | See L1 | Keep: S1 finding, the whole-run refusal on a finale clip with a blank stretch | f51f038 and the stages commit |
| F4 | A dense failure need not redo the poses | local_gpu split into sparse() and dense(); sparse_from reuses a gated run; S3 at L1/L2 after MVS_RC reuses the poses on disk | Unit tests (T5 in test_local_gpu, T3e in test_tesseract) | Saves MapAnything, matching and the mapper: 130 of B1's 314 s | Unchanged by construction; reuse refuses changed pose options | Keep: S2 finding, the ladder redid a correct sparse stage | f51f038 |
| L1 | Measure S3 on 600 keyframes end to end | None beyond F3 | B5s, 600 views, 554 placed, 277 densified | S3 747.8 s: MapAnything 42.1, SIFT 19.3, matching 56.3, mapper 191.1, densify 125.9, mesh 144.2, texture 153.4 | 554/600 registered, 0.773 px, mean track 31.8, 23.2M dense points; sparse on plane 0.884, layered cells 0.010, step ratio 4.4 (the largest steps are the last five placed frames at the site edge) | Baseline for the 10-minute estimate | Not applicable |
| X1 | The textured mesh can be exported in the cloud's frame | mesh_export: OBJ, GLB, FBX from scene_tex.obj with S5b's transform | B1 baseline mesh, 208,147 faces | 8.8 s for all three | Transform matches points_llf.npy to 4.8e-7; GLB keeps its atlas; FBX reloads with 208,147 faces and its texture file | Keep: R-O5 from 3 of 6 to 6 of 6 on local runs | 670c2af |

**The 10-minute estimate from L1.** S0 10.2 s and S1 51.5 s (B4) plus S3 747.8 s is
809.5 s before S5b and S6, which B1 put at 2.4 s but which grow with the cloud (23M
points here against 7M). That is R about 1.37 on this proxy: inside 1.5, with little
margin. The proxy is kind to the mapper in one way (a synthetic scene, no water, no
repeated texture) and harsh in another (1.5 m between keyframes, tracks 31.8 views
long). B2's mapper took 329 s for 289 views, so real footage can cost more per view.

### B1 held-out experiments (every tenth keyframe held out, poses reused from M0)

M0 is a full held-out run of B1 that keeps its intermediates; every Q and T run takes
its poses (`sparse_from`) and changes one dense, mesh or texture setting. Scores are
over the same 17 held-out views at quarter resolution. Between 22:33 and 22:56 a stale
copy of the first queue ran alongside the second and both wrote the same experiment
folders; Q4 to Q7 from that window were deleted and rerun. Timings from this evening
vary by about 20% with other use of the laptop, so a time claim needs the final idle run.

| ID | Single change | Dense / mesh / texture s | Held-out PSNR, SSIM, coverage | Shape | Decision |
|---|---|---|---|---|---|
| M0 | None (full run, intermediates kept) | 83.1 / 132.3 / 101.4 | 21.715 dB, 0.5360, 98.10% | plane 0.774, layered 0.055 | Reference |
| Q0 | None (dense half rerun on M0's poses) | 84.2 / 134.3 / 106.8 | 21.739 dB, 0.5376, 97.84% | 0.774, 0.055 | Noise floor: 0.02 dB, 0.3 points of coverage |
| Q1 | TextureMesh on the CPU with both seam levellings on | 81.4 / 137.2 / 110.4 | 9.125 dB, 0.0115, 97.75% | 0.774, 0.054 | Reject. The atlas is black on the CPU too, so it is not a CUDA texturing bug |
| Q2 | TextureMesh on the CPU, levelling off | 82.2 / 139.1 / 102.4 | 21.665 dB, 0.5368, 97.80% | 0.774, 0.056 | Reject: same result, no faster |
| Q3 | DensifyPointCloud at resolution level 0 (full size) | 313.0 / 302.6 / 147.8 | 21.674 dB, 0.5328, 98.37% | 0.774, 0.072 | Reject: 21.2M points and 2.3 times the time for no better image, and layered cells up 0.017 |
| T1 | ReconstructMesh `-d 4` (was 2.5) | 52.6 / 42.4 / 28.9 | quarter 21.725 dB, 0.5449, 98.79%; full size 22.650 dB, 0.6393 | 0.774, 0.055 | Reject as is: 1.05M faces instead of 2.03M and 105k textured, and at full size it loses 0.21 dB and 0.009 SSIM against Q0 (22.858, 0.6483). The quarter-size score hid that, so every later run is also scored at full size |
| T2 | ReconstructMesh `--target-face-num 200000`, TextureMesh not decimating | 49.9 / 79.5 / 36.1 | quarter 21.755 dB, 0.5390, 97.75%; full 22.849 dB, 0.6480 | 0.774, 0.056 | Candidate: the same image as Q0 at full size; its time needs a baseline run in the same conditions (Q0b) |
| T3 | DensifyPointCloud resolution level 2 | 53.6 / 65.1 / 54.6 | 21.702 dB, 0.5376, 97.75% | 0.774, 0.055 | No change at all: the depth maps are still 960x298. OpenMVS's `--min-resolution 640` stops the downscale on these 596-pixel-high crops, so the L1 ladder step, which raises the level by one, does nothing on the demo (finding F5). Rerun as T3b with the floor at 320 |
| T4 | TextureMesh `--resolution-level 1` | 53.3 / 64.8 / 44.7 | quarter 23.169 dB, 0.6094; full 23.448 dB, 0.6309 | 0.774, 0.055 | Not kept on the score alone. It is 0.6 dB better at full size, but the renders (`out/codex/cmp_8.jpg`) show blockier texture. The gain looks like softer texture forgiving small misalignment and fewer seams, which is the check being flattered rather than a better model |
| T3b | Resolution level 2 with `--min-resolution 320` | 17.6 / 49.9 / 48.6 | quarter 21.664 dB, 0.5377, 97.12%; full 22.296 dB, 0.6128 | 0.774, 0.032 | Keep the floor, not the level: depth maps 480x149, 1.66M points, dense, mesh and texture 116 s against 184 s for Q0b, and 0.53 dB less at full size. That is the trade the L1 step is meant to make, and now it makes it (F5 fix). The local estimate scales the dense term by 0.65 at L1 |
| Q0b | None (timing baseline run next to C1 and C2) | 54.6 / 68.7 / 60.7 | quarter 21.700 dB, 0.5367, 97.82%; full 22.830 dB, 0.6493 | 0.774, 0.056 | Reference for the rows below |
| C1 | `-d 4` and texture decimation 0.2 | 56.2 / 43.8 / 62.3 | quarter 21.699 dB, 0.5352, 98.63%; full 22.817 dB, 0.6468 | 0.774, 0.056 | Candidate: mesh and texture 106 s against 129 s, full-size PSNR within the 0.03 dB noise, coverage up 0.8 points |
| C2 | `-d 4`, ReconstructMesh `--target-face-num 200000`, no texture decimation | 57.5 / 59.8 / 45.2 | quarter 21.700 dB, 0.5362, 98.75%; full 22.804 dB, 0.6475 | 0.774, 0.056 | Candidate: 105 s against 129 s, 0.026 dB lower at full size |
| Q4 | ReconstructMesh `-d 1.5` (was 2.5) | 74.1 / 161.9 / 120.3 | quarter 21.705 dB, 0.5267, 97.37%; full 22.985 dB, 0.6518 | 0.774, 0.055 | Reject: 0.15 dB at full size for 2.4 times the mesh time (it overlapped the CB test for part of its run, so the ratio is rough) |
| Q5 | Texture decimation 0.3 (was 0.1) | 56.5 / 75.8 / 157.3 | quarter 21.976 dB, 0.5494; full 22.812 dB, 0.6325 | 0.774, 0.056 | Reject: 0.28 dB better at quarter size but 0.017 SSIM worse at full size, and 2.6 times the texture time. Three times the faces in the same 4096 atlas leaves each patch fewer texels |
| Q6 | Densify `--postprocess-dmaps 7` | 58.3 / 66.1 / 66.7 | quarter 21.742 dB, 0.5320, 92.61%; full 22.786 dB, 0.6419 | 0.774, 0.021 | Reject: layered cells fall from 0.056 to 0.021, a much cleaner ground, but coverage falls 5.2 points, past the 2-point rule. Q13 and Q14 try parts of it |
| Q7 | ReconstructMesh `-f 1` (free-space support) | 58.3 / 81.7 / 61.0 | full 22.841 dB, 0.6496, 97.80% | 0.774, 0.056 | Reject: no change, 13 s slower |
| Q8 | TextureMesh `--ignore-mask-label -2` with both levellings | 51.2 / 68.4 / crashed | none | none | TextureMesh 2.4 exits right after cleaning the mesh with label -2, so the lens-mask idea (openMVS issue 1251) cannot be tested this way. Q9 fails the same way |
| Q10 | ReconstructMesh `--remove-spurious 10` (was 20) | 54.1 / 73.3 / 61.1 | full 22.872 dB, 0.6484, 97.01% | 0.774, 0.055 | Reject: it cuts holes in the far-field houses rather than tidying them (`out/codex/novel_12.jpg`) |
| Q11 | `--remove-spurious 5` | 54.8 / 75.2 / 59.6 | full 22.880 dB, 0.6480, 95.72% | 0.774, 0.056 | Reject: more holes, coverage down 2.1 points |
| CB | Per-image colour gains from the sparse points (`out/codex/colour_balance.py`), applied to the dense images before TextureMesh, on M0's mesh | texture 85 s against 90 s | raw full 22.638 dB against 22.834; after fitting one gain per channel to each held-out frame 23.468 against 23.147 | not applicable | Not kept. The gains are real (0.92 to 1.22 across the flight, the camera's exposure drifting), and removing them makes the texture 0.32 dB more self-consistent, but the renders look the same: the blue-white sand comes from the later, backlit frames that see that ground closest, which is view-dependent light and not exposure |
| Q12 | Texture decimation 0.2 (was 0.1) | 55.3 / 68.8 / 92.2 | quarter 21.699 dB, 0.5265, 97.98%; full 23.016 dB, 0.6542 | 0.774, 0.056 | Candidate for quality: 0.19 dB and 0.005 SSIM better than Q0b at full size, six times the noise, still one 4096 atlas (23,390 patches). Costs 31 s of texturing here. Checked on B2 next |
| Q13 | Densify `--postprocess-dmaps 1` (speckles only) | 48.9 / 59.4 / 62.0 | full 22.803 dB, 0.6449, 92.51% | 0.774, 0.020 | Reject: the speckle filter alone takes the 5 points of coverage |
| Q14 | `--postprocess-dmaps 3` (speckles and gap filling) | 49.6 / 61.1 / 60.0 | full 22.908 dB, 0.6455, 92.83% | 0.774, 0.022 | Reject: coverage down 5.0 points |

Rendering a held-out view next to the real frame (`out/codex/compare_views.py`) shows
the main visual fault is colour, not geometry: patches of sand come out blue-white where
the frame is beige, because each face takes its colour from one photo and the photos
differ in exposure and sun angle. Seam levelling exists to fix exactly that and is the
option that blackens the atlas (Q1: 29% of atlas pixels under 8 against 0.2%).

### global_mapper options on B1's kept database

`out/codex/mapexp.py` runs global_mapper on M0's database with one option changed, and
compares camera centres with M0's after a similarity fit, as a share of the track length.

| ID | Option | Mapper s | Registered, error, track | Sparse on plane | Pose change (RMS, max, of track) | Decision |
|---|---|---:|---|---|---|---|
| G0 | None | 113.2 | 177, 0.490 px, 10.76 | 0.774 | 0, 0 | Reference |
| G1 | `skip_retriangulation 1` | 87.6 | 177, 0.505 px, 10.25 | 0.738 | 5e-5, 1.3e-4 | Candidate: the poses are the same to 1 part in 20,000, so the dense model should not move; the sparse plane share falls 0.036 because the sparse points are not re-triangulated. On 600 views retriangulation was 91 s of 191 s. Run end to end on B1 and B5s before deciding |
| G2 | `ba_num_iterations 1` (3) | 116.9 | identical | 0.774 | 0, 0 | Reject: no effect |
| G3 | `keep_max_num_tracks 20000` | 115.4 | 177, 0.490 px, 10.77 | 0.768 | 1e-5, 1e-5 | Reject: no faster at this size |
| G4 | `gp_max_num_iterations 50` (100) | 119.0 | identical | 0.774 | 0, 0 | Reject: no effect |

### R1: test_flight georeferenced from its SRT, and a focal length 33% off

`codex-b3-geo`: `tesseract.py run data/test_flight.mp4 --geometry local`, verify PASS.
S0 3.5 s, S1 5.5 s, S3 392.0 s, S5 2.2 s, S6 14.3 s. The manifest says F6, metres,
georeferenced, scale "gnss x63.580", fit 0.136 m RMS over 171 fixes.
`out/codex/b3_truth.py` compares it with the synthetic scene the clip was rendered from.

| Check | Result |
|---|---|
| Camera centres against the true flight path, 173 cameras | 0.135 m RMS in 3D, 0.120 m horizontal |
| Dense cloud against the true surface, 200k points | median 12.59 m, 1.0% within 1 m |

The cameras are right and the ground is not: the cloud sits 10 to 17 m below the true
ground (median height -10.5 m where the site is at 0 to 1.5 m). The reason is the camera
model. MapAnything fitted f = 1414 px; the renderer used 1066 px. `out/codex/focal_probe.py`
fits the same 60 trajectory positions three ways:

| Frames | Fitted f (px) |
|---|---:|
| The sharp renders (b5s) | 1058.1 |
| The same frames decoded from the H.264 clip | 1425.9 |
| The same, without the 1-in-6 blurred frames | 1423.1 |
| S1's keyframes (what production used) | 1414.3 |

So the encoding alone (CRF 26, yuv420p) moves MapAnything's focal length by a third, and
with the camera fixed the mapper builds a stretched model that still reprojects at
0.90 px. A straight track pins the scale along the flight, so the georeferenced cameras
land within 14 cm while the depth direction is wrong by about 10%. This is finding F6,
an S1 finding for R-O3: the fixed focal length is the weakest input to the metric model.
F1 below tests letting the global mapper refine it.

### B5v: a 600-second clip end to end

`src/ingest/make_test_video.py out/codex/b5v.mp4 --seconds 600 --fps 1` renders the same
synthetic pass as 600 frames at 1 fps, H.264, with a 600-record DJI SRT (RTK noise), in
about 16 minutes. It is a genuine 600 s file, so S0, S1, S2, S5, S6 and S8 all run on a
ten-minute input; what it lacks is the 18,000 frames a 30 fps clip would make S1 decode.
S1 on the 30 fps loop (B4) took 51.5 s, against 9.2 s here.

`codex-b5v`: `tesseract.py run out/codex/b5v.mp4 --geometry local`, current defaults,
verify PASS, level L0.

| Stage | Seconds |
|---|---:|
| S0 screen | 2.0 |
| S1 ingest (353 keyframes; 192 rejected for blur, 37 bridged) | 9.2 |
| S3 MapAnything and intrinsics fit | 59.6 |
| S3 SIFT, matching, global mapper | 182.2 |
| S3 undistort, densify (300 views, 23.2M points) | 150.5 |
| S3 ReconstructMesh | 159.9 |
| S3 TextureMesh | 190.3 |
| S5 georeference | 3.1 |
| S6 export (PLY, LAS, GeoTIFF, OBJ, GLB, FBX) | 24.5 |
| **Whole run** | **792.3** |

R = 792.3 / 600 = 1.32, and S8 reports R-O2 met, R-O5 met (all six formats), F6 in
metres, scale "gnss x64.046". Against the synthetic truth: cameras 0.137 m RMS (0.095 m
horizontal), cloud median 1.37 m from the true surface, 9.9% within 1 m. MapAnything
fitted f = 1091 px here (truth 1066): 2.3% off, against 33% on the 30 fps test_flight
encode, and the cloud error follows the focal error.

Scaled to a real 30 fps ten-minute clip: S1 decodes 30 times the frames (+42 s, from
B4), and S1 would pick up to 600 keyframes rather than 353 (+247 poses at 0.45 to 0.52 s,
from B5s and B5v, about +120 s). That puts the current defaults near 955 s, R about
1.59: over the target by about a minute, with the mesh and texture stages (350 s) and the
mapper the places to take it from.

### Retriangulation off in the global mapper (G1 end to end)

| Run | Mapper s | Error | Sparse on plane | Layered cells | Held-out full size | Camera error against truth (RMS, p95, max) |
|---|---:|---|---:|---:|---|---|
| B1 held-out, M0 conditions (G0) | 113.2 | 0.490 px | 0.774 | 0.056 | 22.830 dB, 0.6493 (Q0b) | no truth |
| B1 held-out, retriangulation off (S1-skipretri) | 84.6 | 0.505 px | 0.751 | 0.056 | 22.849 dB, 0.6483 | no truth |
| B5s, 600 views, defaults | 191.1 | 0.773 px | 0.884 | 0.010 | not run | 0.663 m, 0.274 m, 10.0 m |
| B5s, retriangulation off | 96.1 | 0.857 px | 0.861 | 0.011 | not run | 0.310 m, 0.201 m, 4.5 m |

Decision: keep. On 600 views the mapper halves (191 s to 96 s) and the cameras come out
closer to the true path, not further. The sparse plane share falls 0.023, a hair past the
0.02 rule; that rule stands in for pose drift, and here the poses are measured directly
against truth and the dense ground (layered cells, held-out scores) does not move, so the
fall is the sparse points not being re-triangulated rather than the ground layering.

### New defaults

| Option | Was | Now | Evidence |
|---|---|---|---|
| `mapper_retriangulate` (new) | on (COLMAP's default) | off | G1, S1-skipretri and B5s above |
| `mesh_min_point_distance` | 2.5 | 4.0 | C1 on B1; B2C1 on Nicosia: full-size held-out 22.656 dB, 0.7430 against B2M0's 22.578 dB, 0.7450, mesh and texture 23.4 s against 34.4 s |
| `texture_decimate` | 0.1 | 0.2 | the same two runs; texture 0.2 on its own (Q12) was 0.19 dB better on B1 but 0.055 dB and 0.013 SSIM worse on Nicosia (B2Q12), so it is not kept alone |
| `camera_model` (new) | PINHOLE | PINHOLE | lets a run try SIMPLE_PINHOLE with the focal refined (F2 below) |
| `dense_min_resolution` (new) | OpenMVS's 640 | 320 | T3b |

S3 goes to version 6 so cached runs recompute.

### F1 and F2: letting the mapper refine the focal length

| Run | Camera | Focal after the mapper (truth 1066) | Error | Cameras against truth | Cloud against truth (median, within 1 m) |
|---|---|---|---:|---|---|
| R1, test_flight, focal fixed | PINHOLE | 1414 (MapAnything's) | 0.898 px | 0.135 m | 12.59 m, 1.0% |
| F1, refined | PINHOLE | fx 1599.5, fy 1146.2 | 0.892 px | 0.136 m | 3.79 m, 3.5% |
| F2, refined as one value, retriangulation off | SIMPLE_PINHOLE | 1134.6 | 0.995 px | 0.144 m | 3.23 m, 4.6% |
| F2n, focal fixed, retriangulation off | PINHOLE | 1414 | 1.002 px | refused | refused |

On the demo (F1b and F2b, held-out runs): PINHOLE refinement moved fx and fy apart
(1113 and 1298 against 1098); SIMPLE_PINHOLE kept 1095 against MapAnything's 1098,
sparse on plane 0.749, layered cells 0.056 and held-out 22.799 dB, 0.6467 at full size
(Q0b 22.830 dB, 0.6493), so no bowl and no loss. Refining one focal length is kept
(ADR-031): it takes test_flight's cloud error from 12.6 m to 3.2 m and leaves the demo
where it was.

F2n found a regression in the retriangulation change: without that pass the mean
reprojection error rises about 10% (test_flight 0.898 to 1.002 px) and the 1 px gate
refused the run. The mapper's model now goes through `point_filtering` (4 px, 1.5
degrees, as on the mapanything path) before the gate measures it; the poses are
untouched.

## Third session, 2026-09-27 night

Picked up after the final suite on commit b360949. From 02:14 a second Claude session
on this laptop ran a PX4 and Gazebo simulator in WSL (about 1.3 cores, 1.8 GB, no GPU).
From 02:20 the two sessions took turns on heavy work. Timings from runs that overlapped
it carry a note.

### Final suite on b360949

Clean runs (`--no-resume`), `tesseract.py verify` PASS on all four.

| Run | Wall | R | S3 sparse | S3 dense, mesh, texture | Registered, error | Dense points | Focal, MapAnything to mapper |
|---|---:|---:|---:|---:|---|---:|---|
| codex-b1-final | 318.5 s | 16.9 | 139 s | 160 s | 177/177, 0.490 px | 7.08M | 1098 to 1095 |
| codex-b2-final | 283.9 s | 7.1 | 223 s (mapper 163.5) | 45 s | 209/209, 0.345 px | 1.66M | 751 to 1400 |
| codex-b3-final | 352.7 s | 17.6 | 112 s | 211 s | 173/173, 0.885 px | 10.17M | 1414 to 1179 |
| codex-b5v-final | 576.1 s | 0.96 | 158 s | 376 s | 353/353, 0.804 px | 22.51M | 1091 to 1160 |

B5v came in at R 0.96 against 1.32 on the old defaults (792.3 s). Against the synthetic
truth its cameras stayed at 0.136 m RMS, but the cloud went from 1.37 m median error to
4.54 m (1.4% within 1 m). B3: cameras 0.133 m, cloud 5.15 m median.

Held-out, full size, against the references:

| Run | PSNR, SSIM | Coverage | Dense / mesh / texture s | Decision |
|---|---|---:|---|---|
| FINAL-B1 | 22.822 dB, 0.6470 | 98.79% | 51.9 / 43.5 / 55.8 | Same image as Q0b (22.830, 0.6493) within the 0.03 dB noise; mesh and texture 99 s against 129 s |
| FINAL-B2 | 25.566 dB, 0.8273 | 72.40% | 16.9 / 7.8 / 13.5 | Coverage 25 points under B2M0 (22.578 dB, 0.7450, 97.12%); see F7 |

### F7: refining the focal length on a straight pass makes it worse

The cloud error on both synthetic runs is one vertical offset, the same at every
distance from the track (`out/codex/err_decomp.py`):

| Run | Focal (truth 1066 px) | Ground offset | Median cloud error |
|---|---|---:|---:|
| codex-b3-geo, fixed | 1414 | -12.66 m | 12.59 m |
| codex-b3-final, refined | 1179 | -5.18 m | 5.16 m |
| codex-b5v, fixed | 1091 | -1.34 m | 1.39 m |
| codex-b5v-final, refined | 1160 | -4.55 m | 4.54 m |

On a straight pass at one attitude, focal length f with the true scene and k f with the
scene stretched k times along the view axis reproject identically, so no image evidence
can separate them. The refinement moved 6-9% long from either side. How far the views
turn (95th percentile rotation from the middle view) separates the cases: B3 and B5v
0.07 and 0.06 degrees, the demo 2.0, Nicosia 52.5. Nicosia's keyframes are a long-lens
pan across the city from one spot, where the focal length is observable; there the
refined 1400 px turned a thin curved strip (`out/codex/b2_compare.jpg`) into the fan a
pan sees. Its coverage fell because a correct focal length leaves a far scene with
little parallax to densify.

Fix (5c479ae): MapAnything's 60 views give the turn before mapping; the mapper refines
the focal length only at 10 degrees or more, otherwise it holds MapAnything's value.

### F8: the synthetic SRT had the gimbal pitch wrong

`make_test_video.py` wrote gb_pitch as -(90 - pitch): -30 for a camera 60 degrees down.
DJI writes -60. gb_yaw was 0 for a pass flying east; DJI writes 90. Nothing read either
value before S5 started reading the pitch. Fixed in the generator, and the 600 records of
`data/test_flight.SRT` and `out/codex/b5v.SRT` were rewritten to the same two values
(39bde63).

### P1: the gimbal pitch gives the focal length back

The stretch that hides the focal length error changes one thing the GNSS fit does see:
the view's angle to the track, tan(model pitch) = tan(true pitch) / k. With the pitch in
the SRT, k and the stretch that undoes it follow (78bc9ac, ADR-032). Replayed on the
saved outputs of the four synthetic runs with the true pitch (`out/codex/replay_s5.py`,
then `b3_truth.py`):

| Run | Model pitch | k | Implied focal | Cloud median, within 1 m, before | After |
|---|---:|---:|---:|---|---|
| codex-b3-geo | 52.582 | 1.32511 | 1067.33 | 12.59 m, 1.0% | 0.394 m, 95.2% |
| codex-b3-final | 57.462 | 1.10505 | 1067.18 | 5.15 m, 1.1% | 0.397 m, 95.0% |
| codex-b5v | 59.435 | 1.02290 | 1066.57 | 1.37 m, 9.9% | 0.342 m, 98.6% |
| codex-b5v-final | 57.876 | 1.08753 | 1066.59 | 4.54 m, 1.4% | 0.338 m, 98.6% |

None of the 20 real DJI fixtures in `src/ingest/fixtures/dji_srt/` carries a gimbal
pitch, so on most consumer clips this does not apply and the run records why.

### Ladder rates

Geometry's local estimate was still on the old pose path's rates (0.6 s per pose view,
0.55 per dense view, 30 s fixed) and put B5v's S3 at 407 s against 543 s measured. The
final runs give 37-57 s fixed, 0.29-0.90 s per pose view and 0.22-1.25 s per dense view.
Set to 57 s, 0.5 and 1.1 (425a027): B5v 563 s estimated, demo 341 against 302, Nicosia
392 against 270, and a 600-keyframe clip about 690 s, which leaves it at L0 inside the
840 s that remain after S0 and S1.

### Audit, line by line

A read-only pass over `local_gpu.py`, the S3 to S6 stages, `mesh_export.py`, the keyframe
selector and the three tools. Findings fixed on the branch, each with a test that failed
first:

| ID | Severity | Finding | Fix |
|---|---|---|---|
| F10 | S1 | On a long clip S1 met its 600-keyframe target early and stopped: the ten-minute loop's keyframes ended at frame 12,604 of 18,000 (`out/runs/codex-b4-ingest`). T3d: 7,272 of 9,000 before, 8,997 after | 2358c7e |
| F11 | S2 | The run page fitted a similarity to carry the mesh into the export frame, which cannot hold S5's stretch | 1b9e609 |
| F12 | S2 | A rerun into the same folder whose mesh or texture failed exported the previous run's mesh | d547b90 |
| F13 | S2 | A mesh split over several atlases exported only the last | 8adf3ed |
| F14 | S3 | An exception other than StageError ended the run with no manifest | 02cdb45 |
| F15 | S3 | `view_check` stopped on an unplaced held-out view | 1b9e609 |
| F16 | S4 | The DSM's 5 cm floor applied in model units | 11116da |
| F17 | S4 | 1 Hz SRT fixes taken by nearest rather than interpolated (up to 5 m at 10 m/s) | b9fdd49 |

Left open (S3 and S4): MapAnything running out of GPU memory is reported as GEO-REPROJ and
replayed; a missing file in S3 is labelled "tools missing" and L1 solves the poses again;
on the non-default pose path `focal_after_mapper_px` holds [f, cx]; local S3 has no
`key_extra`, so a DEFAULTS change needs a version bump by hand.

B4 no longer tests S1 at length: since F1 the loop points of the looped demo read as cuts,
and S1 keeps one 19 s loop (177 keyframes, frames 0 to 564, 32.9 s). F10 is covered by the
unit test only.

### End to end on the new code (codex-*-v2, 03:17 to 03:41, laptop otherwise idle)

Clean runs, verify PASS on all four. Commits up to b9fdd49; the focal gate was then at
10 degrees on the percentile measure.

| Run | Wall | R | S3 sparse, dense | Mapper | Focal, MapAnything to used | Result |
|---|---:|---:|---|---:|---|---|
| codex-b1-v2 | 264.5 s | 14.0 | 104 s, 143 s | 56.5 s | 1098, held | 177/177, 0.490 px, 7.08M points |
| codex-b2-v2 | 282.6 s | 7.1 | 230 s, 41 s | 181.6 s | 751 to 1400, refined | 209/209, 0.344 px, 1.53M points |
| codex-b3-v2 | 318.1 s | 15.9 | 93 s, 196 s | 21.9 s | 1414, held; S5 k 1.325, implied 1067.4 | cameras 0.127 m RMS, cloud 0.394 m median, 95.3% within 1 m |
| codex-b5v-v2 | 502.5 s | 0.84 | 141 s, 321 s | 53.2 s | 1091 to 1179, refined; S5 corrected | cameras 0.136 m, cloud 0.338 m median, 98.6% within 1 m; R-O2 met |

Holding the focal length also shortened the mapper: 56.5 s against 89.2 s on the demo,
21.9 against 33.3 on test_flight.

### F18: MapAnything's poses cannot gate the focal refinement at 10 degrees

B5v was refined because MapAnything's views read a 14.2 degree turn on a pass that turns
0.1; test_flight read 9.6. `out/codex/ma_turn.py` ran MapAnything on the same 60 views of
each clip:

| Clip | MapAnything, 95th percentile | MapAnything, between thirds | Mapper, between thirds |
|---|---:|---:|---:|
| demo | 5.39 | 6.46 | 2.14 |
| Nicosia | 96.94 | 111.02 | 86.00 |
| test_flight | 9.63 | 8.90 | 0.13 |
| B5v | 14.19 | 13.11 | 0.10 |

The straight passes' reading is drift between MapAnything's two inference windows, not
per-view noise, so averaging within thirds barely helps. The gate is now the thirds
measure at 30 degrees, and the mapper's own turn is recorded with a flag when it disagrees
(2ece0fd).

### Mesh and texture on the demo's kept dense scene (`out/codex/tex_exp.py`)

Mesh `-d 4` from M0's dense cloud, TextureMesh at 20% unless stated, full-size held-out.

| ID | Change | Texture s | PSNR, SSIM, coverage | Decision |
|---|---|---:|---|---|
| TX0 | None (current defaults) | 46.4 | 22.791 dB, 0.6472, 98.81% | Reference |
| TX1 | Both seam levellings | crashed | access violation (0xC0000005) | Reject |
| TX2 | Both seam levellings, no decimation | 188.1 | 9.117 dB, 0.0161; atlas 10.8% black | Reject: decimation is not what blackens it |
| TX3 | ReconstructMesh `--close-holes 300` | 47.1 | 15.980 dB, 0.6051 | Reject: the closed holes are wrong surfaces across the views |
| TX4 | `--empty-color` grey instead of orange | 49.4 | 22.825 dB, 0.6472 | Neutral on the score |
| TX5 | `--virtual-face-images 3` | 30.2 | 22.618 dB, 0.6244 | Reject: 0.17 dB and 0.023 SSIM worse |

### Last slot (04:31 to 04:47)

| ID | Change | Time | Result | Decision |
|---|---|---|---|---|
| RF1 | RefineMesh on the `-d 4` mesh, images at level 1, one scale, CUDA | 76 s refine, 13.9 s texture | full size 22.771 dB, 0.6473, 98.80% (TX0 22.791, 0.6472) | Reject: within noise, 76 s more |
| RF2 | RefineMesh, level 2, two scales | 59 s refine, 7.1 s texture | 22.550 dB, 0.6322 | Reject: 0.24 dB and 0.015 SSIM worse |
| codex-b5v-v3 | B5v end to end on the final gate (2ece0fd) | 502.2 s, R 0.84 | turn read 13.1, focal held at 1091 px; S5 corrected it; cameras 0.143 m RMS, cloud 0.346 m median, 98.5% within 1 m; verify PASS | Final B5v figure |

Run pages rebuilt for codex-b1-v2, b2-v2, b3-v2 and b5v-v3, with screenshots in
`out/codex/codex-*-v*.png` (not committed).
