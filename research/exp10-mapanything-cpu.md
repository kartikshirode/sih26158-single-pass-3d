# EXP-10 — MapAnything on GCP CPU: what it costs, and what synthetic renders can't test

Run on **Cloud Run, asia-south1 (Mumbai)**, 8 vCPU / 32 GiB, no GPU.
Checkpoint: `facebook/map-anything-apache` (Apache-2.0 — the deployable one).

## Result 1 — the timing number, which is solid and is the point

| | |
|---|---|
| Model | 1.228 B parameters |
| Load (incl. DINOv2-giant from hub) | 32–40 s |
| **Inference** | **6.4 – 8.1 s per view** (3 runs) on 8 vCPU / 5 torch threads |
| Output | pts3d, pts3d_cam, ray_directions, depth_along_ray, cam_trans, cam_quats, **metric_scaling_factor**, conf, non_ambiguous_mask |
| Points returned | ~1.62 M for 8 views |

**Extrapolation to the real workload.** 600 keyframes at ~7.5 s/view is **~4,500 s ≈ 75 minutes**
on 8 vCPU, against a **900 s** budget. So the CPU path is **5× too slow** — and that is the
deployment-sizing answer we wanted:

- A single L4/A100 typically gives 20–50× over CPU for a transformer of this class, so **one
  GPU clears the budget with room to spare**, which is what the architecture assumed.
- Equally: **there is no CPU-only fallback for the full-length job.** A CPU deployment could
  handle a ~2-minute clip inside 900 s, not a 10-minute one. Worth stating rather than
  discovering at the finale.

This is a real measurement of the actual Apache checkpoint, not an estimate.

## Result 2 — synthetic renders are NOT adequate to test a learned model

The reconstruction quality was poor across three renderer generations. Camera baselines should
have been a uniform 24.6 m:

| Renderer | Local texture | Baseline CV (want <0.2) | Verdict |
|---|---|---|---|
| Point splatting | n/a — 19% pixel coverage, black speckle | 1.46 | model fed noise |
| Triangle raster, flat facets | ~2 | — | no local detail |
| + periodic (sine) texture | 6.9 | 1.46 | **periodic ⇒ ambiguous correspondence** |
| + aperiodic value noise | 3.6 | 1.07 | better, still unusable |

Final state: trajectory shape RMSE **36 m over a 172 m run** after Sim(3) alignment. Not usable.

**Three renderer bugs found by looking at the frames, each invisible in the model's output:**
1. **Point splatting cannot fill an image.** Only samples landing in a pixel contribute — 19%
   coverage, frames were black speckle. Fixed by rasterising triangles.
2. **Flat-shaded facets have no matchable detail.** Fixed with per-pixel texture interpolated
   from world position, so it is view-consistent.
3. **Sinusoidal "noise" is exactly periodic**, so the ground repeated every few metres and
   correspondence was ambiguous. Fixed with hash-based value noise.

### The honest conclusion

Even with all three fixed, the renders remain too simple: an 11k-face scene of flat terrain and
boxes, with procedural noise standing in for real texture. MapAnything is trained on real imagery
and the domain gap is too wide. **Chasing it further would be tuning a renderer to flatter a
model, which proves nothing.**

So the scope of the synthetic harness is now explicit:

- **Valid for** — georeferencing maths, CRS/geoid handling, export writers, scoring, timing, the
  straight-line degeneracy (EXP-09), and coverage geometry (EXP-08). All of these depend on
  geometry and metadata, not on photometric realism.
- **NOT valid for** — evaluating a learned reconstruction model's accuracy. That needs real
  imagery: a public UAV dataset, or footage flown for the purpose.

That boundary is worth stating in the submission. A team that reports learned-model accuracy on
synthetic renders is reporting a number about their renderer.

## Reproduce

```
gcloud run jobs execute sih26158-mapanything --region=asia-south1 --project=agentbillboard --wait
```
Inputs `gs://sih26158-mumbai/mapanything/ma_input/`, outputs `.../out/`.
