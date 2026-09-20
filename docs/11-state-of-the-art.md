# State of the art, and what "world class" means here

Version 1.0 — 2026-09-16. Research landscape for single-pass aerial video to metric 3D:
incumbent products, open toolchains, learned models, benchmarks, and the licence status of
each. Licences were read from the repositories and model cards on 2026-09-16, not from
summaries. Anything not verified that way is marked *unverified*.

---

## 1. The gap this product sits in

Incumbent drone photogrammetry is built for **planned capture**. Pix4D's own guidance asks
for **75% frontal and 60% side overlap** in general, and **85% frontal** for a single-track
corridor. Skydio's 3D Scan goes further the same way: an autonomous, adaptive flight
that plans *more* views around a structure.

The problem statement is the opposite case: **one pass, taken when it could be, over a
target that may not allow a second**. That is the gap. Nobody ships a product whose design
centre is an unplanned single video pass with consumer telemetry, run on sovereign
infrastructure, under licences a defence customer can accept.

Three results from this project say why the gap is real rather than a matter of tuning:

1. A straight single pass is **geometrically degenerate** for a full similarity fit (EXP-09);
   planned grids never meet that failure.
2. Feed-forward models make the single pass tractable, but their **geometry is capped by
   their patch grid** (`docs/05`) and their **metric scale fails at altitude** (`docs/08`,
   and independently AerialMetric, §3.3).
3. Classical SfM on 600 keyframes **cannot fit the time budget** with exhaustive matching
   (EXP-01).

---

## 2. Incumbents

| Product | Model | Relevance | Notes |
|---|---|---|---|
| **Pix4D** (mapper / matic / cloud) | Commercial | Reference for survey-grade output | Designed around overlap grids (75/60; 85 frontal for corridors) |
| **RealityScan 2.x** (was RealityCapture, Epic) | Proprietary; free below USD 1 M annual revenue | Fast desktop photogrammetry | 2.0 (June 2025) added AI masking, alignment changes and airborne LiDAR import (LAS/LAZ/E57); 2.1 (Nov 2025) added SLAM scanner data |
| **Skydio 3D Scan** | Commercial, tied to Skydio aircraft | Solves capture, not single-pass | Adaptive multi-view scan; partners with Bentley for processing |
| **OpenDroneMap / WebODM** | **AGPL-3.0** | The open incumbent | Video input since 3.0.4; `--video-limit` default 500; SRT GPS supported. Stamps extracted frames `Model: "Unknown"`, so video always falls back to a generic focal prior (`research/02-ingestion-export-findings.md` §4). Applies no geoid correction. |
| DroneDeploy, Agisoft Metashape, Bentley iTwin Capture, Esri Site Scan | Commercial | Same planned-capture design centre | Not evaluated here; *unverified* beyond category |

**What to take from them.** Survey-grade outputs, QA reports that state GSD and check-point
residuals, COPC/3D Tiles delivery, and the discipline of reporting the capture conditions
alongside the result.

**What not to copy.** The assumption that a bad result means "reflow the mission". Here there
is no second flight, so the product has to say *why* a clip is weak before spending compute
on it — which is what S0 already does.

---

## 3. Methods

### 3.1 Classical

| Component | Licence | State |
|---|---|---|
| **COLMAP** | BSD (new BSD) | Incremental SfM + CUDA PatchMatch stereo. Used here for triangulation and BA on CPU |
| **GLOMAP** | **BSD-3** | Global SfM; its authors report accuracy on par with or better than COLMAP at **1–2 orders of magnitude** less time (ECCV 2024). Untested here |
| **OpenMVS** | **AGPL-3.0** | PatchMatch densify, Delaunay + graph-cut mesh, refine, texture. Runs on CPU with `--cuda-device -2`. Used here |
| **PoseLib** | BSD-3 | Minimal solvers and robust estimation; a candidate for the S5 5-DOF fit |
| **PDAL**, **Potree** | BSD, BSD-2 | Point-cloud pipeline and web viewer (COPC) |

### 3.2 Learned multi-view geometry

| Model | Code | Weights | Usable for NTRO? | Why it matters |
|---|---|---|---|---|
| **MapAnything** (arXiv 2509.13414) | Apache-2.0 | `-apache`: Apache-2.0; default: CC-BY-NC-4.0 | **Yes, Apache checkpoint** | Metric by design; accepts intrinsics, poses, depth and metric flags as priors. Its scale is what `docs/08` found 5.5× off at altitude |
| **VGGT** | VGGT License + AUP | Same | **No** — AUP bars military and espionage use | Strongest-known feed-forward baseline; VGGT-Long (chunk, loop, align) targets kilometre-scale sequences |
| **Pi3 / π³** | BSD-3 | Non-commercial (`research/01-licensing-findings.md`) | Code yes, weights no | Permutation-equivariant; would need retraining |
| **MASt3R / MASt3R-SfM** | CC BY-NC-SA 4.0 | Same | **No** | Strong on sparse, low-overlap sets |
| **Depth Anything 3** | Apache-2.0 | BASE / SMALL / METRIC-LARGE / MONO-LARGE Apache; larger ones CC-BY-NC | **Yes, those checkpoints** | Streaming inference for long video in < 12 GB |
| **MoGe-2** | MIT | MIT (`Ruicheng/moge-2-vitl`) | **Yes** | Monocular metric geometry with sharp detail; base of AerialMetric's adapted model |
| **UniDepth** | CC BY-NC 4.0 | — | **No** | Metric depth |
| **Metric3D** | BSD-2 (code) | *unverified* | Code yes | Metric depth |

**The independent evaluation to read first.** Wu, Landgraf, Ulrich and Qin (arXiv 2507.14798)
tested DUSt3R, MASt3R and VGGT on aerial photogrammetric blocks. They found completeness
gains of up to +50% over COLMAP from very sparse, low-resolution sets, but pose reliability
falls with more images and more complex geometry. Their conclusion: these models *"cannot
fully replace traditional SfM and MVS, but offer promise as complementary approaches."* That
is ADR-004, reached independently.

### 3.3 Metric scale from the air

**AerialMetric** (Song, Chen, Zhang et al., arXiv 2606.29716, June 2026) is the closest
external evidence for `docs/08`:

- It benchmarks monocular metric depth on real UAV imagery: an oblique set with RGB+LiDAR,
  a set decoupled by altitude (80 m and 120 m), a 70–300 m synthetic set, and a varied
  in-the-wild set.
- **Zero-shot models fail.** Without true intrinsics, on its oblique-city split: MoGe-2
  δ₁ = 5.1%, UniDepthV2 34.1%, ZoeDepth 0.0%. Metric accuracy drops "precipitously" from
  80 m to 120 m.
- **LoRA adaptation (rank 96) on MoGe-2** lifts δ₁ from 5.1% to 89.3% (AbsRel 48.4 → 10.3),
  and from 9.5% to 53.7% on the 0–400 m wild set.
- Dataset, code and weights are released under **CC BY 4.0** (per the paper). Verify at
  download before use.
- It does **not** evaluate MapAnything or VGGT.

Two consequences for this project: an altitude-adapted metric-depth model is a candidate
**independent scale witness** (ADR-024), and **true intrinsics matter for scale** — the
pipeline has never passed them (`docs/09` GAP C-5).

### 3.4 Radiance fields and splats

| Method | Licence | Use here |
|---|---|---|
| 3D Gaussian Splatting (Inria) | Research-only licence | **Excluded** from the deliverable |
| 2D Gaussian Splatting | Inria research licence | **Excluded** |
| **gsplat** | Apache-2.0 | Candidate visualisation branch only |

Per-scene optimisation spends the time budget twice over (`docs/02` §1). Splats may earn a
place as a **viewer** for inspection, never as the measured geometry.

---

## 4. Benchmarks and what each can prove

| Benchmark | Ground truth | Alignment | Proves |
|---|---|---|---|
| **ETH3D** | laser scan | **none** | Absolute accuracy — the analogue of `evaluate(align=False)` |
| Tanks and Temples | laser scan | 7-DoF, scale included | Shape only; forgives scale (a 5%-small model scores 0.000 m) |
| **H3D, Hessigheim** | UAV LiDAR (~800 pts/m²), oblique imagery at 2–3 cm GSD, multiple epochs | — | Aerial geometry and semantics on a real site; multi-epoch change |
| **UseGeo** | UAV multi-sensor with LiDAR | — | Real UAV depth and geometry |
| **UrbanScene3D** | LiDAR | — | Urban aerial reconstruction |
| **AerialMetric** | LiDAR / metric depth, known altitude | — | **Metric scale at altitude** — the exact failure `docs/08` found |

None of these is a *single-pass video* benchmark. Frames can be sub-sampled from a single
strip of a survey block to simulate one (`docs/14` §3), with the caveat that survey
cameras are not video cameras.

---

## 5. Licence register, verified 2026-09-16

| Component | Licence | Verdict | Source |
|---|---|---|---|
| MapAnything code | Apache-2.0 | Use | GitHub API |
| `facebook/map-anything-apache` | Apache-2.0 | Use | HF model card |
| `facebook/map-anything` | CC-BY-NC-4.0 | Internal ablation only | HF model card |
| DINOv2 giant (MapAnything backbone) | Apache-2.0 | Use | HF model card |
| COLMAP | BSD | Use | LICENSE |
| GLOMAP | BSD-3 | Use | GitHub API |
| OpenMVS | **AGPL-3.0** | Use unmodified, as a separate process | GitHub API |
| OpenDroneMap | **AGPL-3.0** | Reference only | GitHub API |
| VGGT | VGGT License + AUP | **Do not use** | LICENSE.txt |
| MASt3R | CC BY-NC-SA 4.0 | **Do not use** | LICENSE |
| Pi3 | BSD-3 code; NC weights | Weights: **do not use** | GitHub API; `research/01-licensing-findings.md` |
| Depth Anything 3 | Apache-2.0 (selected checkpoints) | Use those only | GitHub API; HF |
| MoGe / MoGe-2 | MIT / MIT | Use | LICENSE; HF |
| UniDepth | CC BY-NC 4.0 | **Do not use** | LICENSE |
| Metric3D | BSD-2 (code) | Weights unverified | GitHub API |
| Inria 3DGS / 2DGS | Research-only | **Do not use** | LICENSE.md |
| gsplat | Apache-2.0 | Use | GitHub API |
| PDAL / Potree / PoseLib | BSD / BSD-2 / BSD-3 | Use | LICENSE; API |
| 3d-tiles-tools | Apache-2.0 | Use | GitHub API |
| telemetry-parser | Apache-2.0 (API) — `research/02-ingestion-export-findings.md` reads MIT OR Apache | Use | GitHub API |
| assimp | BSD-3 | Use | `research/02-ingestion-export-findings.md` |

### 5.1 Pinned Python dependencies

Read from the installed distributions' own metadata on 2026-09-18, not from memory. The
CI gate refuses a new pin that is not listed here (`.github/workflows/ci.yml`).

| Package | Version | Licence |
|---|---|---|
| numpy | 2.2.6 | BSD |
| scipy | 1.15.2 | BSD |
| trimesh | 4.7.4 | MIT |
| pyproj | 3.7.2 | MIT |
| laspy | 2.7.0 | BSD-2-Clause |
| rasterio | 1.5.1 | BSD-3-Clause |
| google-cloud-storage | 2.19.0 | Apache-2.0 |
| av (PyAV) | 15.0.0 | BSD-3-Clause |
| opencv-python(-headless) | 4.11.0 | Apache-2.0 |
| matplotlib | 3.10.3 | PSF |
| python-pptx | 1.0.2 | MIT |
| pillow | 11.1.0 | MIT-CMU |
| open3d | 0.19.0 (Python 3.11 only here) | MIT |

All permissive. The only copyleft in the runtime is OpenMVS (AGPL-3.0), invoked as a
separate unmodified process (ADR-005, `docs/16` L-1).

### 5.2 Fonts shipped with the console

The console (`demo/console/`) self-hosts its webfonts rather than linking a font CDN,
so the page has no third-party runtime dependency and works offline. Redistribution is
what the licence is for, and the files are the latin subsets only.

| Family | Weights | Licence | Where |
|---|---|---|---|
| IBM Plex Sans | 400, 500, 600 | SIL OFL 1.1 | `demo/console/fonts/` |
| IBM Plex Mono | 400, 500 | SIL OFL 1.1 | `demo/console/fonts/` |

OFL 1.1 permits redistribution with the software; it forbids selling the fonts on their
own and requires that a modified version be renamed. Neither applies here: the files are
shipped unmodified, under their own names, as part of a page.

---

## 6. What "world class" means, in numbers

Targets the product commits to. Each has a test in `docs/14`, and none is claimed until that
test passes on data the team did not tune on.

| Axis | Today (measured) | World-class target | Why this number |
|---|---|---|---|
| **Speed** (R-O2) | 2,078.7 s for 45 views on 8 vCPU; ~600 views not run | **≤ 600 s** for a 10-min 4K clip on **one** 24 GB GPU | 1.5× headroom inside the PS's 900 s |
| **Relative accuracy** | Shape consistent; absolute scale 5.5× off on Kolu | **Scale error ≤ 1%** against an external length; shape RMSE ≤ 0.25 m | T-ACC-05's 1000 ppm is 0.1%; 1% is the first honest milestone |
| **Absolute accuracy** (R-O3) | Not measurable (no GNSS clip) | **≤ 1 m** consumer GNSS is *not* achievable (EXP-05); **≤ 0.15 m** with RTK/PPK | EXP-05: RTK 0.097 m RMSE, p95 0.157 m |
| **Detail** | ~2 cm corrected on Kolu MVS | ≤ 2 × GSD, measured on a LiDAR reference | Photogrammetric norm |
| **Completeness** (R-O4) | 135% of the feed-forward baseline (Kolu) | **≥ 90% of observable surface**, against the EXP-08 denominator | T-COMP-01 |
| **Robustness** (R-NF4) | 4 real clips screened; schema tests absent | **100%** of admissible clips give a labelled result; **0** crashes on unknown schemas | The dataset is unknown until the event |
| **Provenance** | Figures re-grepped against sources | **Every** metric carries a status (`measured` / `calibrated` / `gnss` / `unvalidated`) | `docs/08`: a number existing in its source is not the same as the source being right |
| **Sovereignty** | India-resident compute; licence register | Air-gapped bundle with SBOM; zero non-permissive runtime deps except OpenMVS (isolated) | NTRO |

### 6.1 Where this project can lead, not follow

1. **Single-pass-native design.** Admissibility verdicts, degeneracy-aware georeferencing and
   observable-surface completeness are built for the unplanned pass.
2. **Measured provenance.** Every number traces to a run, and every metre says what kind of
   metre it is.
3. **Defence-grade licence hygiene** from the first dependency.
4. **Sovereign by construction**, with an offline bundle rather than a cloud dependency.

### 6.2 Where it will not lead, and should not pretend to

Survey-grade absolute accuracy without RTK; facade completeness from a nadir pass;
photorealistic texture while `TextureMesh` fails. Each is a physical or current-state limit,
already stated in `docs/02` and `docs/04`.

---

## Sources

- Pix4D — [How to verify that there is enough overlap](https://support.pix4d.com/hc/en-us/articles/203756125); [Image acquisition](https://support.pix4d.com/hc/en-us/articles/115002471546)
- [RealityScan 2.0 release notes](https://www.realityscan.com/news/realityscan-20-new-release-brings-powerful-new-features-to-a-rebranded-realitycapture); [CG Channel on 2.1](https://www.cgchannel.com/2025/11/epic-games-releases-realityscan-2-1/)
- [Skydio 3D Scan](https://www.skydio.com/blog/introducing-skydio-3d-scan)
- [OpenDroneMap options and flags](https://docs.opendronemap.org/arguments/)
- [GLOMAP — Global Structure-from-Motion Revisited, arXiv 2407.20219](https://arxiv.org/abs/2407.20219)
- [MapAnything, arXiv 2509.13414](https://arxiv.org/abs/2509.13414)
- [An Evaluation of DUSt3R/MASt3R/VGGT on Photogrammetric Aerial Blocks, arXiv 2507.14798](https://arxiv.org/abs/2507.14798)
- [AerialMetric, arXiv 2606.29716](https://arxiv.org/abs/2606.29716); [project page](https://kuieless.github.io/AerialMetric-ECCV2026-page/)
- [H3D Hessigheim benchmark, arXiv 2102.05346](https://arxiv.org/abs/2102.05346)
- [UseGeo](https://www.researchgate.net/publication/381534229_UseGeo_-_A_UAV-based_multi-sensor_dataset_for_geospatial_research)
- [VGG-T³, arXiv 2602.23361](https://arxiv.org/pdf/2602.23361); [LONG3R, arXiv 2507.18255](https://arxiv.org/pdf/2507.18255)
- Licences: GitHub repository metadata and LICENSE files for every repo in §5; Hugging Face model cards for `facebook/map-anything(-apache)`, `facebook/dinov2-giant`, `depth-anything/DA3METRIC-LARGE`, `Ruicheng/moge-2-vitl`
- Kolu dimensions and lane widths: see `docs/08` §3.2
