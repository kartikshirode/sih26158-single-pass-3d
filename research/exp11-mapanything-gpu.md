# EXP-11 — MapAnything on a free GPU, real drone imagery

**Kaggle, Tesla T4 (16 GB), free tier.** `facebook/map-anything-apache`, 1.23 B params.
Data: OpenDroneMap `odm_data_aukerman` — real drone photos, 18 MP, GPS in EXIF, CC0-1.0.
Notebook run: successful in 123.3 s end to end.

## The headline: the 900-second budget is reachable

| | CPU (GCP Cloud Run, 8 vCPU) | **GPU (free Kaggle T4)** |
|---|---|---|
| Per view | 7.5 s | **0.55 s** |
| 600 keyframes | ~4,500 s (75 min) | **330 s (5.5 min)** |
| vs 405 s geometry budget | 11× over | **WITHIN, 1.2× headroom** |

**A free T4 is 14× faster than 8 vCPU**, and turns a 5×-over-budget workload into one that
fits. Peak VRAM **11.5 GB**, so it runs on any 16 GB card — no A100 needed. That settles the
deployment question the architecture had left open: **one modest GPU is sufficient**.

Other measured facts:
- Model load 45.4 s (dominated by fetching DINOv2-giant). One-off, not per-run in production.
- Autocast fell back to **fp16**, correctly — T4 is Turing and has no native bf16. The notebook
  now picks the dtype from compute capability rather than assuming bf16.
- 3.25 M points from 16 views.

## What this does NOT establish

**Reconstruction accuracy.** The GPS residual was **mean 46.05 m** (median 38.9, max 96.2), and
the recovered scale was 8.21 model-units-per-metre. The side view shows the cloud sitting ~80 m
above the GPS track. So the geometry is plausible in shape but the georeferencing did **not**
converge on this dataset.

Two honest reasons, neither of which is a defect in the timing result:
1. **This is not a single-pass dataset.** Aukerman is a survey *grid*: baselines mean 64 m, max
   265 m, and the GPS track visibly criss-crosses. Our yaw-only fit is designed for a straight
   single pass (EXP-09) and a grid violates its assumptions.
2. **There is no ground truth here anyway.** With no GCPs and no reference model, the GPS
   residual measures agreement with a noisy sensor. It is not an accuracy number and must never
   be reported as one.

## What to do next

- Get a **single-pass** dataset, ideally with RTK, and re-run. The georeferencing stage is what
  needs testing, and this dataset cannot test it.
- Raise `N_IMAGES` — 11.5 GB peak on 16 views leaves room for ~24.
- For a real accuracy figure, obtain a LiDAR or multi-pass survey reference.

## Reproduce
`notebooks/kaggle_mapanything_real_drone.ipynb` → Kaggle → Accelerator **GPU T4 x2**,
Internet **On** → Save & Run All. Three failures preceded the working run, all install-related:
missing `hydra-core`, then missing `uniception==0.1.7`, both hidden by `pip --no-deps`.
