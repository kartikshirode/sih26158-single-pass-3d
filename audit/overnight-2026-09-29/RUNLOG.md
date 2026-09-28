# Overnight runs, 2026-09-29

Every run here is clean with no resume, on the RTX 4060 laptop, with `SIH_COLMAP`,
`SIH_OPENMVS`, `SIH_ASSIMP` and `HF_HUB_OFFLINE=1` set. The queue that ran them is
`out/exp/scripts/night_queue.ps1` (local only, like the rest of `out/`), and each job's
log is `out/exp/q-<job>.log`.

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
