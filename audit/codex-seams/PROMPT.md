# Codex job: level the texture seams outside OpenMVS

The demo model (B1, `SIH DEMO.mp4`) looks like a patchwork: every texture patch comes
from a different photo, and the colour jumps at patch borders. OpenMVS's own seam
levelling blackens the atlas in this Windows build (audit/codex-7of10/FINDINGS.md, "Why
levelling fails"), so it stays off. Your job is to build the levelling as a separate CPU
step that runs on the finished textured mesh, prove it on the saved outputs, and hand it
over. Another agent is running GPU reconstructions and the website at the same time;
it integrates your tool into the pipeline when you're done.

## Setup

1. Read `audit/codex-7of10/FINDINGS.md` (the seam metric paragraph and the levelling
   paragraph), `audit/codex-7of10/NEXTRUN.md` experiment 1, and the `.claude/codemap.md`
   Overview plus the entries for `tools/view_check.py` and `tools/build_run_page.py`.
2. Work in your own git worktree so you never touch the other agent's working tree:
   `git worktree add ..\sih26158-seams -b codex-seams master`, then do everything there.
   Saved outputs are only in the main checkout, so read them by absolute path:
   `C:\Users\Kartik\Documents\Kartik\EDU\Local\Projects\sih26158-single-pass-3d\out\...`
   (called `MAIN\out` below). Put your scratch under `MAIN\out\codex\seams\`.
3. Set `NUMBA_NUM_THREADS=6` and `OMP_NUM_THREADS=6` in every shell. The GPU and the
   other cores are busy with timed runs.

## What to build

`tools/texture_level.py`:

```
python tools/texture_level.py <geometry_dir> --out <new_dir> [--lambda-smooth 0.1] [--report <json>]
```

- Reads `scene_tex.obj`, its MTL and every atlas it names (TextureMesh writes one atlas per
  material past 8192 px; keep all of them), writes a levelled copy to `<new_dir>` with the
  same OBJ structure, UVs and material names. Never writes into `<geometry_dir>`.
- Copies `sparse_txt/` alongside if present, so `tools/view_check.py --geometry <new_dir>`
  can score the result.
- Method: the global colour adjustment of Waechter, Moehrle and Goesele (2014, "Let There
  Be Color!"). Patches are connected face sets whose shared edges have identical UV
  coordinates (within one material). Every (patch, mesh vertex) pair gets an RGB offset.
  Minimise, per channel, the squared difference of the adjusted colours of the two patches
  at each seam vertex (colour sampled along the seam edges on each side, averaged, a few
  texels inside the patch), plus a smoothness term between neighbouring vertices inside a
  patch weighted by `--lambda-smooth`, plus a small pull toward zero so the solution is
  unique. Solve with scipy sparse least squares or conjugate gradient. Apply the offsets by
  interpolating them barycentrically across each triangle in texture space, and also over
  the atlas gutter texels around each patch so filtering doesn't bleed old colours. Clip
  to 0-255 and report how many texels clipped.
- Speed: under 60 s on B1 (about 200k faces, 11.5k patches) on 6 threads. numba is
  installed; no new packages.
- `--report` writes the seam metric before and after, the patch count, the solve
  residual, the clipped fraction and the time.

`tools/test_texture_level.py`: a synthetic mesh of two or more patches with known constant
and linear offsets between them; the tool removes them to within 1 level; a mesh with no
seam is unchanged; a multi-material OBJ keeps both atlases. Plain script style like
`tools/test_view_check.py`, exits non-zero on failure.

## How to prove it

Use the seam metric exactly as FINDINGS.md defines it (Codex's code is in
`MAIN\out\codex\7of10\audit_saved.py`); don't change its definition.

1. Saved whole-run meshes: `MAIN\out\runs\codex-b1-v2\geometry`, `codex-b2-v2`, `codex-b3-v2`,
   `codex-b5v-v3`. Report the seam ratio before and after for each (B1 before is 4.397).
2. Held-out mesh: `MAIN\out\codex\next7\b1-base-ho` (the other agent is building it; if
   its `scene_tex.obj` isn't there yet, do step 1 first). Score before and after with
   `python tools/view_check.py MAIN\out\runs\codex-b1-v2 --geometry <dir> --scale 1 --out <json>`
   (no `--build`). Levelling mustn't cost more than 0.05 dB of held-out PSNR or any coverage.
3. Pictures, kept under `MAIN\out\codex\seams\` and never committed (they come from the demo
   clip): the same held-out view rendered before and after, and one close crop of a road
   or roof seam. view_check's `rasterize` can render them.

Tune `--lambda-smooth` on B3 and B2 only (not on B1's held-out views), then report B1 at
the chosen value. Target: B1 seam ratio 2.5 or lower with no visible banding or
clipped blotches.

## Rules

- No GPU work, no reconstruction, no `--build`, no `tesseract.py run`, no COLMAP or
  OpenMVS, no installs or downloads, no deleting anything outside `MAIN\out\codex\seams\`.
- Don't edit `src/` or `local_gpu.py`; the other agent wires the tool in. Only
  `tools/texture_level.py`, `tools/test_texture_level.py`, `audit/codex-seams/` and their
  `.claude/codemap.md` entries.
- Never read `.env`. Never commit anything under `out/`, the demo clip or any render of it,
  `.gitignore`, or the two GC-1 files.
- Commit on `codex-seams` only, in plain sentence-case imperative subjects without a
  prefix, no `Co-Authored-By`, no tool or model names. Stage explicit paths. No push, no
  merge, no rebase, no force.
- No em or en dashes in any prose you write.

## Hand-over

`audit/codex-seams/REPORT.md`: the method in five lines, the before and after table (seam
ratio on all four meshes, B1 held-out PSNR, SSIM and coverage, clipped fraction, time),
the chosen `--lambda-smooth` and why, the picture paths, and anything that still looks
wrong. Commit it, then print the report and `git log --oneline master..codex-seams`.
