# Licensing findings — SIH26158 (NTRO)

**Why this matters more than usual:** NTRO is India's technical intelligence agency. The PS lists
"Military reconnaissance and mission planning" and "Border and strategic area mapping" as
applications. Any model whose licence carries a *military / espionage* field-of-use restriction is
disqualified for the real deployment, regardless of technical merit.

## VERDICT TABLE (verified against primary sources)

| Component | Code licence | Weights licence | Usable for NTRO? | Source |
|---|---|---|---|---|
| **VGGT** (Meta) | custom "VGGT AUP licence" | VGGT-1B non-commercial; VGGT-1B-Commercial = commercial **except military** | **NO — AUP bans military/espionage** | github.com/facebookresearch/vggt LICENSE.txt |
| **MapAnything** (Meta) | **Apache-2.0** | `facebook/map-anything-apache` = **Apache-2.0**; `facebook/map-anything` = CC-BY-NC-4.0 | **YES — use the -apache checkpoint** | raw LICENSE + HF card |
| **Pi3 / π³** | (code TBC) | **non-commercial research/education only** | NO for weights | github.com/yyfz/Pi3 |
| **Depth Anything 3** | Apache-2.0 | DA3-BASE (0.12B), DA3-SMALL (0.08B), **DA3METRIC-LARGE (0.35B)**, DA3MONO-LARGE = Apache-2.0. DA3-GIANT-1.1 / LARGE-1.1 / NESTED = CC-BY-NC-4.0 | **YES — Apache checkpoints only** | github.com/ByteDance-Seed/Depth-Anything-3 |

### VGGT — exact disqualifying clause
Acceptable Use Policy prohibits:
> "Military, warfare, nuclear industries or applications, espionage, use for materials or
> activities that are subject to the International Traffic Arms Regulations (ITAR)"

Applies to BOTH checkpoints. The July 2025 "commercial" relicensing is explicitly
"commercial use, with the exception of military applications." **Do not build the core on VGGT.**

## MapAnything — why it is the strategic pick
- Apache-2.0 code AND an Apache-2.0 weights variant. No field-of-use restriction at all.
- Regresses **metric** 3D geometry directly (factored: depth maps + ray maps + camera poses +
  a metric scale factor) — directly serves the <=1 m requirement.
- **Accepts optional geometric priors as input**: `intrinsics` OR `ray_directions`, `depth_z`,
  `camera_poses` (OpenCV cam2world), and `is_metric_scale` flags. This is exactly how we inject
  GPS/flight-metadata priors. (Cannot pass intrinsics and ray_directions together — redundant.)
- Memory-efficient inference: "up to 2000 views on 140 GB" with
  `memory_efficient_inference=True, minibatch_size=1`; `use_amp=True, amp_dtype="bf16"`.
- 1B params. Supports >12 reconstruction tasks incl. uncalibrated SfM, calibrated MVS,
  depth completion, registration.
- Latest release 2026-01-20. arXiv 2509.13414.

## Depth Anything 3 — supporting role
- DA3METRIC-LARGE (0.35B, Apache-2.0) gives metric depth: `metric_depth = focal * net_output / 300`.
- Streaming sliding-window inference for ultra-long video in **<12 GB VRAM** — good for 10-min video.
- Also does camera pose estimation and 3D Gaussian estimation, but the strong (GIANT/NESTED)
  checkpoints are CC-BY-NC — stay on the Apache ones.

## TO VERIFY NEXT
- DUSt3R / MASt3R licences (believed CC-BY-NC — confirm)
- ODM / OpenMVS AGPL implications for a hosted government service
- COLMAP / GLOMAP (BSD) — expected clean
