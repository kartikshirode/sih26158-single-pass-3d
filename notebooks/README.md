# Free GPU compute — options and the ready-to-run notebook

The whole project runs on CPU except one stage: the learned reconstructor. There is **no GPU quota
on our GCP account** — verified by submitting real jobs to Compute Engine, Cloud Run *and* Vertex
AI, all refused. So the GPU stage needs free compute elsewhere.

## Options, ranked for this workload

| Platform | Free GPU | Quota | Card needed | Verdict for us |
|---|---|---|---|---|
| **Kaggle** | T4 x2 (16 GB each) or P100 16 GB | **~30 h/week, guaranteed** | No | **Best.** Predictable, 12 h sessions, internet on |
| Google Colab | T4 16 GB | 15–30 h/week, elastic | No | Fine, but throttled first under load; sessions can vanish |
| Lightning AI | T4 / L4 / A10G / L40S | ~15 credits/mo ≈ 22 h on T4 | Phone verify | Good GPU choice; studios restart every 4 h |
| GCP free trial | — | $300 / 90 days | Yes | **GPUs historically excluded from trial** — do not rely on it |
| Local Intel Arc | integrated, shared RAM | — | — | torch here is `+cpu`; an XPU build is possible but the iGPU is far too small for a 1.23 B model |

**Kaggle wins**: guaranteed quota, 16 GB VRAM (enough for the 1.23 B Apache checkpoint), and no
payment details.

## The notebook

`kaggle_mapanything_real_drone.ipynb` — runs the **real** model on **real** drone imagery.

- **Data:** OpenDroneMap `odm_data_aukerman` — 77 drone photos, 18 MP, Sony DSC-WX220, GPS in
  EXIF, **CC0-1.0 (public domain)**. No focal length in EXIF, so it genuinely exercises the
  unknown-intrinsics path (R-I6).
- **Model:** `facebook/map-anything-apache` — the Apache checkpoint, because the default is
  CC-BY-NC and unusable for an intelligence customer.
- **Georeferencing:** the gravity-constrained 5-DOF fit from EXP-09.

### Run it

1. kaggle.com → Create → Notebook → File → Import Notebook → upload the `.ipynb`
2. Settings → **Accelerator: GPU T4 x2** and **Internet: On**
3. Run All (~10 min, mostly the download and model load)

### What it answers

**Measured GPU seconds per view**, and therefore whether 600 keyframes fits the 900 s budget.
The CPU reference is already measured at **7.5 s/view** on 8 vCPU (GCP Cloud Run), which
extrapolates to ~75 min — 5x over budget. The notebook prints the GPU speedup directly.

### What it does NOT answer

**Reconstruction accuracy.** This scene has no ground truth, and the GPS residual the notebook
prints is agreement with a noisy sensor, not accuracy. Quoting it as accuracy would be exactly
the error the evaluation harness exists to prevent. A real number needs a LiDAR or multi-pass
survey reference — worth asking the organisers for.

> **Data residency.** Aukerman is US imagery, so India's rule does not apply. Indian survey data
> finer than 1 m must be processed on infrastructure inside India (R-NF8), which rules out Kaggle
> for the real deliverable — it is fine for benchmarking the model.
