# Night of 2026-09-28: report

Branch `night-7of10`, not merged and not pushed. Master is untouched and was checked
green before the night started. Details: `research/12-demo-model-and-workspace.md`;
every number: `RUNLOG.md` beside this file.

## The demo model against the 7/10 bars

| Bar (audit/codex-7of10) | Master | Now | |
|---|---|---|---|
| Held-out PSNR at least 23.3 dB | 22.87 dB | **24.63 dB** | met |
| Held-out SSIM at least 0.66 | 0.649 | **0.709** | met |
| Held-out coverage at least 98% | 98.39% | **98.77%** | met |
| B1 wall time at most 300 s | 264.5 s | **293.4 s** | met |
| No orange holes at the default view | 3.3% of faces orange | **none** | met |
| No patchwork on roads and roofs | colour step across patch borders 25.6 levels | **7.8**, the bright blotches gone | much better, not zero |
| Far-field houses read as blocks | smeared | still smeared at a grazing angle | physics; now shown on the map sheet and the Detail layer |
| B3 accuracy with a gimbal pitch at most 0.5 m | 0.394 m | **0.393 m** | held |
| B2 held-out coverage at least 80% | 72% quoted earlier | 61% and 71% in two identical builds | open; B2 varies run to run |
| B5v R at most 1.0 | 0.84 | not rerun (disk) | predicted about 0.88 |

## What changed

1. **TextureMesh without its unsharp mask, in larger patches.** The default sharpening
   added contrast the photos never had: turning it off was worth 1.4 dB on its own.
2. **Unseen faces coloured from the dense cloud** instead of flat orange.
3. **Seams levelled outside OpenMVS**, whose own levelling still blackens the atlas.
4. **A workspace** (`web/workspace.html`) that travels the whole pass (grab-pan, turn and
   zoom about the cursor, a plan map, a flight strip with a chase camera), and measures on
   the surface: distance, height, area, volume, profile, line of sight, coordinates, notes,
   with export, one-length scale calibration, contours and a detail layer. The GPS test
   flight opens beside the demo clip in metres and latitude and longitude.
5. **A presentation site** (`web/index.html`) with its own look: the drone's photo wiped
   against the model from the same camera, the site as a hatched map sheet, measured
   timings, evidence and the application matrix.

Tried and rejected tonight: other TextureMesh ratios, decimations and a finer mesh;
OpenMVS global or local levelling alone (black atlas); MapAnything's scale as a stand-in
for GPS (40 times off on the synthetic flights).

## What stops a perfect model

One straight pass sees the far field only at a grazing angle and never sees the back of
anything; the horizon crop keeps sky out but cannot add houses; every texture patch is a
different photo; and the demo clip has no GPS, so its metres need one known length. These
are the capture, not the code. The workspace's Detail layer and the site's hatched sheet
show exactly where they bite.

## To see it

```
python tools/pack_site.py out/runs/night-b1-final --id b1 --title "SIH demo clip"
python tools/pack_site.py out/runs/codex-b3-v2 --id b3 --title "Synthetic test flight" --out web/data/b3
```

Both are already packed on this laptop. Open `web/index.html` or `web/workspace.html` by
double-clicking.

## Decisions for you

- **Disk.** C: sits at 102 GB. Deleting the eight superseded runs Codex listed was refused
  by the permission check; they are still in `out/runs/`. Deleting them frees about
  12.8 GB and lets the ten-minute clip be rerun.
- **Merge.** The branch passes every CI test locally. Merge it into master when you've
  looked at the pages.
- **The Codex seam job** (`audit/codex-seams/PROMPT.md`) is done, by a subagent instead;
  don't launch it.

## Machine changes

`web/node_modules` (44 MB, esbuild, three, three-mesh-bvh; delete the folder to undo);
two OFL font files committed under `web/fonts`; tonight's own scratch deleted as it was
used. Nothing outside the repository changed.
