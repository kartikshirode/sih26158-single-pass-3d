# Night plan: the demo model to 7/10, and a site worth presenting

Written 2026-09-28 at the start of the night, on branch `night-7of10`. Master stays as it
is until the morning, when this branch is checked and merged.

## The aim

By morning the owner opens one page and sees three things:

1. **The demo model (B1, `SIH DEMO.mp4`) at 7/10.** At the default view: no orange holes,
   no patchwork of colours across roads and roofs, a far edge that ends cleanly instead of
   in shreds. Held-out views no worse than tonight's baseline (22.866 dB, SSIM 0.649,
   coverage 98.4%) and ideally at the 23.3 dB bar.
2. **A workspace where you can travel the whole pass.** The old viewers orbit one point
   in the middle of the model, which is useless on a long strip. The new one moves like a
   map: drag to pan across the ground, orbit around whatever is under the cursor, zoom to
   the cursor, jump to any moment of the flight from a timeline, and see where you are on
   a small plan map.
3. **Measurements that serve the problem statement's applications**, done against the
   real mesh surface with honest units: distance, height, area, volume, elevation
   profile, line of sight, coordinates and notes, with export. B1 has no GPS, so it gets
   a scale calibration from one known length, stated as such.

Plus a presentation site with its own identity, built around the real model, and a plain
account of what stops a perfect model from a single pass.

## What stops a perfect model (short form)

- **One pass, one angle.** The far field is seen only at grazing angles (median 78 degrees
  from the surface normal at 8-16 model units, FINDINGS.md), and the back of anything is
  never seen.
- **The horizon crop.** S1 drops the top 37% of every frame to keep the sky out, and that's
  most of what sees the far houses. The keyframes are 1920 x 595.
- **Texture seams.** Every patch comes from a different photo with different exposure,
  angle and blur. OpenMVS's seam levelling blackens the atlas in this build.
- **Unseen faces.** 3.35% of faces get no photo and show the empty colour.
- **No GPS on the demo clip**, so no metres without an outside length.

## Tracks, run side by side

| Track | Who | Work |
|---|---|---|
| Model | me, GPU | baseline held out; TextureMesh settings that make fewer, larger patches; fill unseen faces from the dense cloud's colours; trim far-field shreds; wire in the seam tool; a clean final B1 run |
| Seams | Codex, CPU, own worktree | `tools/texture_level.py` (audit/codex-seams/PROMPT.md) |
| Web | me plus one subagent | the workspace (navigation and measurement modules by the subagent, design, data packing and pages by me), then the site |

GPU jobs run one at a time, and each gets a `nvidia-smi` check first because another
session shares the laptop.

## Design direction for the web

The subject is survey and mapping for an intelligence agency, so the vocabulary is the
topographic sheet and the aeronautical chart, not a SaaS dashboard.

- **Colour.** Drafting film `#E8EDEB` as the ground; graphite `#1F2629` for ink; contour
  brown `#7A4E26` used only for contours drawn from the model's heights; chart magenta
  `#B0246E` (the overprint colour of aeronautical charts) for everything the user
  measures; slate `#5C6A66` for secondary text.
- **Type.** Archivo, a variable grotesk with a width axis: wide and light for titles, as
  map titles are lettered, normal width for text, tabular figures for numbers. Newsreader
  italic for annotations, the way hydrography is lettered on maps. Both vendored for
  offline use.
- **Structure.** The 3D view sits in a map neatline whose border ticks are real graduations
  in the model's units, so the frame itself carries information. No card grid, no
  all-caps labels, no monospace labels.
- **The one bold thing.** The model drawn with live contour lines computed from its own
  heights, flying along the recorded camera path when the page opens.
- **Offline.** Static files that open from disk: one bundled script, fonts and model data
  beside the page. No server, no network at presentation time.

## Order of work

1. B1 held-out baseline (done: 22.866 dB, 0.649, 98.4%) and a build that keeps its
   intermediates for texture sweeps.
2. Texture sweeps on the GPU while the web scaffold and workspace spec get written.
3. Workspace modules (subagent) while I pack the B1 data and build the page shell.
4. Fill unseen faces, trim shreds, seam tool from Codex; a clean B1 run with everything
   kept.
5. The site. Screenshots, critique, fix.
6. Morning: tests, codemap, merge plan, report.
