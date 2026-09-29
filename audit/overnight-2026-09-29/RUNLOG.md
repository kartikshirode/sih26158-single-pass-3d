# Overnight runs, 2026-09-29

Every run here is clean with no resume, on the RTX 4060 laptop, with `SIH_COLMAP`,
`SIH_OPENMVS`, `SIH_ASSIMP` and `HF_HUB_OFFLINE=1` set. The queue that ran them is
`out/exp/scripts/night_queue.ps1` (local only, like the rest of `out/`), and each job's
log is `out/exp/q-<job>.log`.

Update, 2026-09-29: `out/exp` was cleared. The queue and the scripts it called are now
committed as `tools/repro/` (`queue.ps1`, `classical.py`, `ma_alone.py`, `ablate.py`), the
truth check as `tools/b5v_truth.py`, and every job's JSON is in `results/` here. The
paths below are where things were on the night.

## The demo with the depth prior (`demo-prior2`)

`SIH DEMO.mp4` with `{"local_gpu": {"geometry_prior": true}}` and the prior's new
defaults (stride 3, Poisson depth 10, gap fill with the height test and one ring).
752.7 s of 900, level L0, verify PASS, all six formats. The prior took 420.9 s:
MapAnything on 177 tile views 123.6 s, fusion 38.1 s, Poisson 15.2 s, RefineMesh 237.8 s.
458,297 textured faces. research/13 section 9 has the detail and the held-out scores
(24.429 dB, SSIM 0.687, coverage 98.53% on the same setup). This is the model the site
shows as `b1` now.

## B1 again, with assimp (`night-b1-six`)

The final B1 run (`night-b1-final`, 293.4 s) was started without `SIH_ASSIMP` and wrote
five formats. Run again with it: 291.8 s, verify PASS, all six formats including FBX,
214,506 textured faces against 214,550, 7,059,655 dense points against 7,042,576.

## B5v again (`night-b5v-2`)

`out/codex/b5v.mp4` with its SRT. The earlier final run's folder was deleted, so the
paper's stage chart and reprojection came from an older run; this one gives all of them.
548.2 s (547.1 s before), verify PASS, scale gnss x64.415, focal held at 1091 px, 353 of
353 views at 0.80 px. Stages: Densify 140.0 s, ReconstructMesh 78.9 s, TextureMesh
116.4 s, fill 18.0 s for 4,494 unseen faces, levelling 18.3 s. Against the synthetic
truth (`out/codex/7of10/recheck_truth.py`): cameras 0.138 m RMS, cloud 0.344 m median
and 98.54% within 1 m (0.140 m and 98.56% before).

## Nicosia three times (`b2-rep1` to `b2-rep3`)

`data/nicosia_1080p.mp4 --horizon crop`, then `tools/view_check.py --build --scale 1`
on each (poses solved again for the held-out build). The wall times ran beside other
work and aren't clean timings.

| Build | PSNR (dB) | SSIM | Coverage |
|---|---:|---:|---:|
| b2-rep1 | 27.480 | 0.8700 | 70.35% |
| b2-rep2 | 27.458 | 0.8704 | 70.89% |
| b2-rep3 | 27.489 | 0.8701 | 69.31% |
| Mean | 27.476 | 0.8702 | 70.19% |

Three builds in a row spread 1.6 points of coverage. With the three earlier builds on the
same settings (night-7of10: 61.09%, 70.96%, 72.40%) the six run from 61.1% to 72.4%,
mean 69.2% and standard deviation 4.1 points; the 61.09% build is the outlier. The 80%
bar stays open.

## Baselines on the demo clip

The same 177 keyframes and the same held-out views (every tenth, `names[9::10]`, kept out
of densification and texturing and scored at full size by `view_check.score`). Scripts:
`out/exp/scripts/classical.py` and `ma_alone.py`.

| Method | PSNR (dB) | SSIM | Coverage | Time |
|---|---:|---:|---:|---:|
| Tesseract, default (`night-b1-final` held-out build) | 24.643 | 0.709 | 98.72% | 293 s end to end |
| Tesseract with the depth prior (research/13 section 9) | 24.429 | 0.687 | 98.53% | 753 s end to end |
| MapAnything alone | 20.857 | 0.354 | 87.07% | 166 s |
| COLMAP incremental, then Tesseract's dense and texture stage | 18.650 | 0.327 | 88.12% | 1,120 s sparse + 92 s |
| COLMAP incremental, OpenMVS defaults, seam levelling off | 18.675 | 0.329 | 73.23% | 1,120 s sparse + 118 s |
| COLMAP incremental, OpenMVS defaults | 8.974 | 0.013 | 73.21% | 1,120 s sparse + 124 s |

- **COLMAP as it comes for video**: one shared SIMPLE_RADIAL camera, self-calibrated,
  sequential matching and the incremental mapper, all at their defaults. It placed all
  177 views, but the mapper alone took 1,062 s, and the focal length came out at 592 px
  against MapAnything's 1,098 (k1 -0.0069). That's the curled ground research/10 found.
  Held-out views are scored on the undistorted frames, since that camera has distortion.
- **OpenMVS defaults** keep the ROI crop, fusion filter 2 (743 thousand points), 8
  neighbours, sharpening and no decimation. With seam levelling on, the atlas samples
  black, the Windows build's bug research/10 recorded, hence 8.97 dB. The row with only
  that switched off is the fair out-of-the-box figure.
- **MapAnything alone**: its own stitched poses over four windows of 54 views (the most an
  8 GB card holds at 518 x 168), per-view pinhole intrinsics fitted to its point maps
  (median focal 1,151 px), its points fused in the same TSDF as the depth prior and
  textured by the same TextureMesh settings, fill and levelling. The windows' stitch
  scales ran 0.64, 0.54 and 0.45, the drift research/10 describes. Nothing from COLMAP or
  OpenMVS geometry is used.
- **COLMAP's poses with Tesseract's dense stage** isolate the poses: same dense and texture
  settings as the default row, 5.99 dB lower. The poses are most of the difference.

## Ablation on the demo clip

`out/exp/scripts/ablate.py`: the local pipeline with one option changed, the same held-out
views, scored one view at a time (a view the model covers under 100 pixels counts as
empty and stays out of PSNR and SSIM). Rows reuse `night-b1-final`'s poses unless marked
solved. The control is the unchanged pipeline through the same script.

| Change | PSNR (dB) | SSIM | Coverage | Dense points | Shape |
|---|---:|---:|---:|---:|---|
| None (control) | 24.620 | 0.708 | 98.87% | 6,474,570 | as `night-b1-final`: 0.745 on plane, 0.058 layered, step 2.2 |
| OpenMVS's fusion filter 2 | 22.332 | 0.613 | 36.41% | 163,566 | 7 of 17 views empty |
| Sharpening 0.5 (OpenMVS default) | 23.131 | 0.657 | 98.70% | 6,473,290 | |
| Smoothness ratio 0.1 (OpenMVS default) | 24.442 | 0.699 | 98.83% | 6,476,383 | |
| No unseen-face fill | 24.610 | 0.709 | 98.47% | 6,475,113 | |
| No seam levelling | 24.479 | 0.704 | 98.33% | 6,476,105 | |
| Old pose path: MapAnything windows, triangulate, adjust (solved) | 22.854 | 0.546 | 99.25% | 5,470,381 | 0.641 on plane, 0.201 layered, step 2.1 |
| No keyframe bridging: 139 keyframes (solved) | 24.950 | 0.720 | 98.93% | 4,397,881 | 0.768 on plane, 0.060 layered, step 19.1 |

- The old pose path keeps a SIMPLE_RADIAL camera (k1 -0.011); its row is scored through
  a pinhole copy with k1 dropped, which costs it a little at the frame edges.
- Without bridging the selector keeps 139 keyframes, so its held-out set is 13 other
  frames, all from the stretches the sharpness and sky gates accepted, so none of the hazy
  or low-texture frames bridging adds is tested. Its score isn't comparable with the others. What it shows: with the global mapper the
  ground stays one layer without bridging (research/10's layering came with the old pose
  path), and bridging's job is the continuous camera chain, a largest step of 2.2 times
  the median instead of 19.1, with 38 more views where the gates had left gaps.
- No fill moves nothing, as research/10 found: the faces it colours are ones no held-out
  photo sees either.
