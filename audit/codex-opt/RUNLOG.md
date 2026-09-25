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
| F1 | Flow plus a moderate histogram change will catch B2's hidden edit | S1 cuts when flow exceeds six times the median, is above 10 px and histogram correlation is below 0.9 | B2 ingest; B1 and B3 regression | S1-only B2 9.97 s in a concurrent three-clip check | B2 now has three shots and keeps frame 558 onward, 209 keyframes. B1 stays at one shot and 177 keyframes; B3 stays at one shot and 173 keyframes | Keep if B2 geometry removes the 112.3 camera-step ratio | Pending |

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
