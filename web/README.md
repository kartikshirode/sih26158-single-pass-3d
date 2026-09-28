# Tesseract web

Two pages that open straight from disk, no server and no network:

- `index.html`, the presentation: the drone's video wiped against the model from the same
  camera, the site as a map sheet, the method, the evidence, the uses and the limits.
- `workspace.html`, the model itself: travel along the pass and measure on the surface.
- `run.html`, the way into the workspace from the presentation: pick a processed flight or
  drop a new video, watch the run's recorded stages play back in real time (4x and 16x to
  hurry it; `?replay=b1&speed=16` starts one straight away), then the workspace opens. A
  dropped video is only a preview of the upload flow: the page plays the demo clip's run.

## Before opening them

The model isn't in git (a model of the demo clip counts as a render of it), so pack a
finished run first:

```
python tools/pack_site.py out/runs/night-b1-final --id b1 --title "SIH demo clip"
python tools/pack_site.py out/runs/night-b3-final --id b3 --title "Synthetic test flight" --out web/data/b3
```

The first writes `web/data/model.js` and its images; the second adds a model in its own
folder. Both are listed in `web/data/models.js`, and `workspace.html?model=b3` opens the
second. Then double-click either page. Chrome or Edge.

## In the workspace

| Do this | To |
|---|---|
| Drag | slide the ground under the cursor |
| Right-drag, or Ctrl and drag | turn around the point under the cursor |
| Scroll | zoom toward the cursor |
| Double-click | go to that point |
| W A S D, Q E, Shift | move, down and up, faster |
| The strip at the bottom | jump to a moment of the flight; "Fly the pass" plays it |
| The plan map, top right | move the view there |
| D, H, A, V, P, L, C, N | distance, height, area, volume, profile, line of sight, coordinates, note |
| Escape | back to moving |

Every measurement is taken on the reconstructed surface. On a clip without GPS the
lengths are in model units until "Set scale" takes one length you know. The Detail layer
shows how much ground one photo pixel covered, so you can see where not to trust a
measurement. Export writes GeoJSON and CSV.

## Changing the code

```
cd web
npm install        # esbuild, three, three-mesh-bvh; once
npm run build      # src/workspace.js -> dist/workspace.js
npm run build:site # src/site.js -> dist/site.js
npm test           # the measurement maths
```

`SPEC.md` is the behaviour and the data contract. The built bundles in `dist/` are
committed, so the pages work without npm.
