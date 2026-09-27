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
