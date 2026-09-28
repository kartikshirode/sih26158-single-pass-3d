# Night run log, 2026-09-28

Branch `night-7of10`. All scores are B1 (`SIH DEMO.mp4`) held-out views: every tenth
keyframe (18 views) kept out of densify and texture, the textured mesh rendered into each
at full size, PSNR and SSIM over covered pixels, coverage over the whole frame
(`tools/view_check.py --scale 1`). Two identical runs have differed by 0.02-0.05 dB.

## Machine

| Change | Where | Size | Undone |
|---|---|---:|---|
| `npm install` of esbuild 0.25.10, three 0.180.0, three-mesh-bvh 0.9.1 | `web/node_modules` (gitignored) | 44 MB | No, the web build needs it. Delete the folder to undo |
| Archivo and Newsreader italic, latin woff2 (OFL 1.1) | `web/fonts/` | 0.24 MB | No, committed |
| Deleted tonight's own scratch depth maps and rejected texture trials | `out/codex/next7/` | about 1.5 GB freed | Regenerable |

The deletion of the eight superseded runs Codex listed was refused by the permission
check; they are still there. Free space on C: stayed between 100 and 104 GB all night.

## Baseline

| Run | PSNR | SSIM | Coverage | Note |
|---|---:|---:|---:|---|
| Master (f95481a), fresh held-out build `b1-base-ho` | 22.866 | 0.6490 | 98.39% | 22.822 on b360949 last night: same within noise |

## Texture experiments

One change at a time on a held-out build that kept its intermediates (`b1-keep`), so
only TextureMesh reran (45-50 s each). Seam step is Codex's metric (FINDINGS.md): mean
RGB step across patch borders, and its ratio to the step inside patches.

| ID | Change | PSNR | SSIM | Seam step (ratio) | Kept |
|---|---|---:|---:|---|---|
| X0 | none (same flags as the pipeline) | 22.820 | 0.6474 | 25.6 (4.45) | reference |
| X1 | `--cost-smoothness-ratio 0.5` | 22.966 | 0.6544 | 25.5 (4.30) | with X4 |
| X2 | `--cost-smoothness-ratio 1` | 22.686 | 0.6281 | (4.02) | No |
| X3 | `--outlier-threshold 0` | 22.375 | 0.6277 | (5.45) | No, and 107 s |
| X4 | `--sharpness-weight 0` | 24.212 | 0.6957 | 22.6 (5.80) | Yes |
| X5 | X4 + X1 | **24.415** | **0.7055** | (5.17) | **Yes** |
| X6 | X4 + ratio 0.3 | 24.311 | 0.7011 | (5.60) | No |
| X7 | sharpness 0.25 | 23.567 | 0.6747 | (5.04) | No |
| X8 | X5 at decimation 0.35 (368k faces) | 24.197 | 0.6858 | (4.76) | No, and 72 s |
| X9 | X5 at decimation 0.1 (105k faces) | 24.278 | 0.6972 | (5.17) | No |
| X10 | X5 with a 2.5 px mesh (405k faces) | 24.297 | 0.6866 | coverage 97.82% | No, and 98 s texture |

X4 is not the check being flattered by softness (research/11 T4 rejected a half-resolution
texture for that): the atlas keeps full resolution, and what goes is OpenMVS's unsharp
mask, which put contrast into the texture that the photos never had. Side by side
(`out/codex/next7/cmp_sharp.jpg`) the unsharpened texture is the closer match to the real
frame. The seam ratio rises only because the inside-patch step falls faster than the
border step (25.6 to 22.6 levels at borders, 5.7 to 3.9 inside).

## Unseen faces

TextureMesh sends every face no photo saw to one texel of its empty colour: 6,815 faces
(3.24%) on the held-out mesh, all on a single UV point. `texture_fill` gives each its own
cell under the atlas, painted from the nearest dense points.

| ID | Change | PSNR | SSIM | Orange faces | Kept |
|---|---|---:|---:|---:|---|
| F1 | X5 + fill, atlas re-encoded at JPEG 93 | 24.340 | 0.6956 | 0 | No, the re-encode cost 0.07 dB |
| F2 | X5 + fill, JPEG 97 | 24.406 | 0.7029 | 0 | Yes |

Unseen faces are rarely in any photo, so the held-out views barely see this change; it is
for the model seen from above, where the orange blotches were the first thing anyone
noticed.

## End to end on the kept code (0a01cf8)

| Run | Wall | PSNR | SSIM | Coverage | Verify |
|---|---:|---:|---:|---:|---|
| `night-b1`, clean, no resume | 287.6 s (S3 276.3 s) | | | | PASS |
| `night-b1` held-out build (`view_check --build`) | | **24.443** | **0.7037** | **98.47%** | |

Against tonight's baseline: +1.58 dB, +0.055 SSIM, coverage +0.08 points, 23 s slower
(the fill 8 s, TextureMesh a little slower with larger patches). The 7/10 bars for held
out views (23.3 dB, 0.66, 98%) and B1 time (300 s) are met.

## OpenMVS seam levelling, one pass at a time

| ID | Change | PSNR | SSIM | Kept |
|---|---|---:|---:|---|
| X11 | X5 + `--global-seam-leveling 1` | 9.167 | 0.0084 | No: the atlas is black |
| X12 | X5 + `--local-seam-leveling 1` | 9.245 | 0.0278 | No: the atlas is black |

Either pass alone still blackens the atlas with tonight's flags, as both together did in
RUNLOG Q1 and TX2. Levelling has to happen outside OpenMVS.

## B2 on the new texture settings

Same poses (`night-b2-ho`, current code), held-out build twice, only the texture flags
different.

| Texture | PSNR | SSIM | Coverage |
|---|---:|---:|---:|
| Old flags (sharpness 0.5, ratio 0.1, no fill) | 25.317 | 0.8199 | 61.09% |
| New defaults | **27.098** | **0.8616** | 61.09% |

The texture change helps B2 as much as B1 (+1.8 dB). Coverage is the same both ways, so
the fall from the 72.40% that Codex quoted (FINDINGS.md, from the final suite) is not
tonight's doing: it comes with the current geometry. Per view it runs from 28% at the ends
of the pan to 90% in the middle. Not investigated further tonight: the demo clip is the
target, and B2's 80% bar stays open.

## MapAnything's scale as a metre estimate for clips without GPS

B1 has no GPS, so every length is in model units. MapAnything is trained to predict
metric depth, so its camera centres might give an approximate metre scale. Test
(`out/codex/next7/ma_scale.py`): MapAnything on the same 60 spread views S3 uses, a
similarity from the COLMAP centres to MapAnything's, and on the georeferenced runs the
same fit to the GNSS-fitted centres as the reference.

| Run | MapAnything, m per unit | GNSS, m per unit | Error |
|---|---:|---:|---:|
| codex-b3-v2 | 1.49 | 63.58 | -97.7% |
| codex-b5v-v3 | 1.59 | 64.05 | -97.5% |
| night-b1 | 3.69 | none | unknown |

Rejected: on the synthetic flights (110 m up) MapAnything's scale is 40 times too small,
so nothing on a real clip could be trusted from it. B1 keeps model units, and the
workspace's one-length calibration is the only way to metres without GPS.

## B3 on the new code, end to end

`night-b3`: `data/test_flight.mp4` with its SRT, clean, no resume. 342.4 s (318.1 s on
codex-b3-v2; the fill took 13.6 s for 3,457 unseen faces), verify PASS, cloud against the
synthetic truth 0.393 m median and 95.2% within 1 m (0.394 m and 95.3% before). The
texture change leaves geometry and georeferencing alone, as it should.

## Seam levelling outside OpenMVS

`src/pipeline/texture_level.py`, Waechter et al.'s global adjustment on the finished OBJ
and atlas (method in the codemap and the module). Tuned on B2 and B3 only (lambda 0.1,
pull toward zero 0.03), then measured on B1. Seam step is the mean RGB step across patch
borders (Codex's metric), before and after; scratch in `out/codex/seams/`.

| Mesh | Seam step before (ratio) | After | Clipped texels |
|---|---|---|---:|
| night-b1 | 9.665 (2.290) | 7.968 (1.876) | 0.03% |
| codex-b1-v2 (old texture) | 24.503 (4.397) | 21.966 (3.871) | 0.19% |
| codex-b2-v2 | 11.510 (1.869) | 10.061 (1.616) | 0.64% |
| codex-b3-v2 | 4.920 (3.096) | 4.495 (2.721) | 0.02% |
| codex-b5v-v3 | 5.825 (2.027) | 5.782 (1.908) | 0.03% |
| night-b1-ho | 9.577 (2.264) | 7.848 (1.844) | 0.02% |

Held out on `night-b1-ho`: 24.443 to **24.650 dB**, SSIM 0.7037 to **0.7096**, coverage
98.466% both. Side by side (`out/codex/seams/view08.jpg`), the bright blotches across the
sand field in view 8 are gone, with no banding. Two findings from the tuning: sampling
two texels inside a seam measured texture detail rather than colour (interior pairs
differed as much as seams), so samples sit a quarter texel in; and without the pull
toward zero brightness drifted across the model and cost 1.9 dB. B5v's step barely moves:
its seams are misregistration, not colour. Kept, in S3 after the fill (9c972c9).

## Final B1 run on the kept code (9c972c9)

| Run | Wall | PSNR | SSIM | Coverage | Verify |
|---|---:|---:|---:|---:|---|
| Master baseline (`b1-base-ho`) | 264.5 s | 22.866 | 0.6490 | 98.39% | PASS |
| `night-b1-final`, clean, no resume | 293.4 s | | | | PASS |
| `night-b1-final` held-out build | | **24.634** | **0.7089** | **98.77%** | |

+1.77 dB, +0.060 SSIM and +0.38 coverage points over master for 29 s more (texture 61 s,
fill 8.2 s, levelling 5.7 s). The fill coloured 7,134 unseen faces. All four 7/10 bars that
concern B1 alone are met: 23.3 dB, SSIM 0.66, 98% coverage, 300 s. The superseded
`night-b1` run and its held-out build were deleted for disk; their numbers are above.

## B2 coverage: variance, not a regression

The same held-out build of B2 on the same code, run a second time (`b2-rep`):

| Build | PSNR | SSIM | Coverage |
|---|---:|---:|---:|
| night-b2-ho | 27.098 | 0.8616 | 61.09% |
| b2-rep, identical command | 27.510 | 0.8707 | 70.96% |

Ten points of coverage between two identical runs. The 72.40% of the final suite and the
61% here are the same distribution; nothing on master or tonight lost coverage. B2 is a
long-lens pan with little parallax, where the mapper's and densify's run-to-run spread is
large; B1 differed by 0.02-0.05 dB between identical runs. Any B2 comparison needs
several runs each. The 80% bar stays open.

## Final B3 run (9c972c9)

`night-b3-final`: 349.0 s (318.1 s on codex-b3-v2; fill and levelling about 29 s of the
difference, levelling 15.0 s on its 8192 px atlas), verify PASS, cloud 0.391 m median and
95.35% within 1 m of the synthetic truth. Packed as the workspace's second model
(`web/data/b3`). This run and `night-b1-final` are the ones to keep.

## Final B5v run (b8eaf6c, morning)

The owner cleared the eight superseded runs (C: from 100.7 to 113.1 GB), so the
ten-minute clip could run. `night-b5v-final`: `out/codex/b5v.mp4` with its SRT, clean, no
resume. 547.1 s, R 0.91 (502.2 s and R 0.84 on codex-b5v-v3), S3 514.3 s: Densify 135.0 s,
ReconstructMesh 76.7 s, TextureMesh 123.7 s, fill 17.7 s for 4,412 unseen faces,
levelling 16.5 s. Focal held at 1091 px, scale gnss x64.412, verify PASS. Against the
synthetic truth: cameras 0.140 m RMS, cloud 0.344 m median and 98.56% within 1 m (0.346 m
and 98.54% before). The prediction was about 530 s; the real cost is 45 s, most of it the
slower TextureMesh with larger patches plus the two new steps. Still inside the budget.

The first attempt ran from a shell without `SIH_COLMAP` and `SIH_OPENMVS` set, fell down
the ladder to L5 in 43 s, and was deleted.
