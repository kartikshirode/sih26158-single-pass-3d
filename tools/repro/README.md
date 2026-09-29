# Reproducing the paper's numbers

This folder rebuilds every run behind the paper's result tables and the live site, from the committed code, on one machine with a CUDA GPU. `queue.ps1` runs them all in order. The rest of this page says what each job is, what it produced last time, and which settings it depends on.

The recorded outputs are committed, so you can check a rerun against them without the old folders:

- `audit/runs/<run>/` holds each kept run's `run_manifest.json`, `qa_report.md`, `local_gpu_result.json` (every option the geometry stage used), `view_check.json` and, for the synthetic flights, `truth.json`.
- `audit/overnight-2026-09-29/results/<job>/` holds the baseline and ablation JSON.
- `audit/runs/superseded/` keeps the manifests of older runs whose folders were deleted on 2026-09-29.

## Setup

The machine behind every number: Intel i7-13650HX, 24 GB RAM, RTX 4060 Laptop GPU (8 GB), Windows 11, Python 3.12, COLMAP 4.2.0 (CUDA), OpenMVS 2.4.0 (CUDA), assimp for FBX, and the `facebook/map-anything-apache` checkpoint in the Hugging Face cache.

```powershell
$env:SIH_COLMAP  = "C:\...\colmap\bin\colmap.exe"
$env:SIH_OPENMVS = "C:\...\openmvs_cuda"
$env:SIH_ASSIMP  = "C:\...\assimp\Release"
$env:HF_HUB_OFFLINE = "1"          # once the MapAnything weights are cached
powershell -File tools/repro/queue.ps1        # or: queue.ps1 7  to start at job 7
```

Inputs: `SIH DEMO.mp4` at the repo root (not committed, sha256 `a98a6346...d326a`), `data/test_flight.mp4` with its SRT, `data/nicosia_1080p.mp4`, and `out/codex/b5v.mp4` with `b5v.SRT`. The queue renders the B5v clip again if it's missing (`python src/ingest/make_test_video.py out/codex/b5v.mp4 --seconds 600 --fps 1`, seed 7, 110 m, 60 degrees down, sha256 `89037b3b...ca80` last time).

The whole queue takes about 3 hours and needs roughly 12 GB free. It stops before any job that would start with C: under 101.5 GB.

## The runs

Every pipeline run uses the defaults in `src/pipeline/local_gpu.py` (`DEFAULTS`); the table lists only what differs. The commit is the one the manifest recorded.

| Run | Command options | Commit | Recorded result |
|---|---|---|---|
| `night-b1-final` | `--geometry local --horizon crop` | a9eb905 | 293.4 s, 214,550 faces, held out 24.64 dB / 0.709 / 98.7% |
| `demo-prior2` | same, plus `--config tools/repro/prior.json` | 1e6df4c | 752.7 s, 458,297 faces, verify PASS, six formats |
| `night-b1-six` | same as night-b1-final, with SIH_ASSIMP set | 1e6df4c | 291.8 s, 214,506 faces, six formats |
| `night-b3-final` | `--telemetry data/test_flight.SRT --geometry local` | ce9d13d | 349.0 s; cameras 0.116 m RMS, cloud 0.392 m median, 95.36% within 1 m |
| `night-b5v-2` | `--telemetry out/codex/b5v.SRT --geometry local` | 782118f | 548.2 s; cameras 0.138 m RMS (1.15 GSD), cloud 0.344 m median, 0.506 m RMSE, 98.53% within 1 m |
| `b2-rep1..3` | `--geometry local --horizon crop` on Nicosia | 782118f, 8ac175a | 27.48 / 27.46 / 27.49 dB, coverage 70.35 / 70.89 / 69.31% |

`demo-prior2` is the site's b1 model (`python tools/pack_site.py out/runs/demo-prior2 --id b1`), and `night-b3-final` is its b3 model. The paper's figures read `night-b1-final`, `demo-prior2` and `out/evidence/`, so keep those three when clearing disk.

The truth numbers come from `python tools/b5v_truth.py out/runs/<run> [--frames 600]`. It rebuilds the synthetic scene and writes `truth.json` into the run. GSD there is the slant range at the image centre over the focal length, 0.119 m for both flights.

## Baselines and ablation (paper Tables 7 and 8)

These use the keyframes and poses of `night-b1-final`, so run that first. Every tenth keyframe (`names[9::10]`, 17 views) is kept out of densification and texture and scored at full resolution by `tools/view_check.py`. `common.py` copies the run's keyframes to `out/exp/kf` on first use.

| Job | Command | Recorded PSNR / SSIM / coverage |
|---|---|---|
| COLMAP sparse | `classical.py sparse` | mapper 1,062 s, 177 of 177 placed, self-calibrated f = 592 px |
| COLMAP, OpenMVS defaults | `classical.py dense cl-def defaults` | 8.97 dB / 0.013 / 73.2% |
| same, seam levelling off | `classical.py dense cl-defns defaults_ns` | 18.68 dB / 0.329 / 73.2% |
| COLMAP poses, our dense stage | `classical.py dense cl-ours ours` | 18.65 dB / 0.327 / 88.1% |
| MapAnything alone | `ma_alone.py ma` | 20.86 dB / 0.354 / 87.1%, 166 s |
| control | `ablate.py control` | 24.62 dB / 0.708 / 98.87% |
| depth prior on | `ablate.py prior geometry_prior=1` | 24.35 dB / 0.683 / 98.62% |
| fusion filter 2 | `ablate.py fusion2 dense_fusion_filter=2` | 22.33 dB / 0.613 / 36.4%, 7 views empty |
| sharpening 0.5 | `ablate.py sharp05 texture_sharpness=0.5` | 23.13 dB / 0.657 / 98.70% |
| smoothness 0.1 | `ablate.py smooth01 texture_smoothness=0.1` | 24.44 dB / 0.699 / 98.83% |
| no fill | `ablate.py nofill texture_fill=0` | 24.61 dB / 0.709 / 98.47% |
| no levelling | `ablate.py nolevel texture_level=0` | 24.48 dB / 0.704 / 98.33% |
| old pose path | `ablate.py mapanything --solve pose_method=mapanything` | 22.85 dB / 0.546 / 99.25% |
| no bridging | `ablate.py keyframes-nobridge`, then `ablate.py nobridge --solve --kf out/exp/kf-nobridge` | 24.95 dB / 0.720 / 98.93% on 139 keyframes |

## How close a rerun gets

The next morning, 2026-09-29, the control ran again at commit 2fb0b7e and scored 24.626 dB, SSIM 0.7087 and 98.85% coverage, against 24.620, 0.7082 and 98.87% the night before. Poses are reused, so what varies is OpenMVS's densification: 6,474,834 dense points against 6,474,570.

The depth-prior row is the one to watch. The paper's Table 6 figure, 24.43 dB / 0.687 / 98.53%, came from a scratch chain that fixed the median depth at 3.876 and textured through a separate script. Through the pipeline with one command the same settings give 24.35 dB / 0.683 / 98.62% in 589 s, and that's the number a rerun should match.

The B5v and B3 truth checks sample the true surface at random, so the third decimal of the cloud figures can move by one.
