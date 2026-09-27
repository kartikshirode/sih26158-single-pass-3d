# Workspace spec

What `web/workspace.html` does, and the contract between the page, its script and the
packed model. The page and its CSS are written; this file is what the script has to do.

## Constraints

- Opens from disk (`file://`) in Chrome or Edge with no server and no network. That rules
  out ES module scripts and `fetch()` of local files. Everything reaches the page through
  classic `<script src>` tags: `data/model.js` (the model, see below) and
  `dist/workspace.js` (the bundle).
- Source is ES modules under `web/src/`, bundled by esbuild into one IIFE:
  `cd web && npm run build`. Dependencies are `three` 0.180 and `three-mesh-bvh` 0.9.1,
  already in `web/node_modules`. No other packages.
- Pure maths lives in `web/src/geom.js` with no three.js import, and is tested with
  `node --test` from `web/test/` (`npm test`).
- The design is fixed by `css/base.css` and `css/workspace.css`. Don't restyle; use the
  classes and ids in `workspace.html`. Colours for drawing come from the CSS custom
  properties (read them with `getComputedStyle(document.documentElement)`): measurements
  in `--magenta`, contours in `--contour`, the flight path and minimap ink in `--ink`.

## The packed model: `window.TESSERACT`

Written by `tools/pack_site.py`. Frame: the run's export frame turned Y-up, exactly as the
GLB is. Horizontal plane is XZ, height is +Y.

```js
window.TESSERACT = {
  id: "b1",                       // key for localStorage (calibration, notes)
  title: "SIH demo clip",
  subtitle: "18.9 s single pass, 177 keyframes, 264 s to reconstruct",
  units: "model units",           // or "metres"
  scale: { factor: 1.0, status: "unvalidated", label: "no GPS, lengths in model units" },
                                  // status "gnss" or "calibrated" when metres are real
  georef: null,                   // or { lat0, lon0, h0 } of the local ENU origin (x east, -z north, y up)
  glb: "<base64>",                // the textured mesh
  bounds: { min: [x, y, z], max: [x, y, z] },
  duration: 18.9,                 // seconds of the pass
  cameras: [                      // every keyframe in time order
    { t: 0.0, file: "data/frames/kf_000.jpg", p: [x, y, z], f: [x, y, z], u: [x, y, z],
      fovy: 30.6, aspect: 3.23 }  // position, unit forward, unit up, vertical fov in degrees
  ]
};
```

Two optional fields:

- `detail`: `{ b64, counts, lo, hi, median }`. One uint8 per GLB vertex in accessor order
  (mesh after mesh, `counts` each): v in 0..254 means one photo pixel covers
  `exp(log(lo) + v / 254 * (log(hi) - log(lo)))` model units of surface there, over every
  keyframe that sees the vertex inside its frame; 255 means none does. Drawn by the
  Detail layer.
- `sheet`: the presentation page's plan-view map; the workspace ignores it.

## Rendering

- `WebGLRenderer` with antialias, `outputColorSpace = SRGBColorSpace`, no tone mapping. The
  photo texture must show its own colours: an unlit material with the GLB's map, texture
  colour space sRGB, mipmaps and the renderer's max anisotropy.
- Background `--paper`. A perspective camera with a near plane scaled to the model.
- Build a `MeshBVH` on the mesh at load (three-mesh-bvh `computeBoundsTree`,
  `acceleratedRaycast`) so every pick is on the real surface and fast.
- Contours layer: lines drawn in the fragment shader from world height (`onBeforeCompile`),
  interval from `geom.niceInterval(heightRange / 25)`, every fifth line heavier, colour
  `--contour`, anti-aliased with `fwidth`. With the photo texture off, the surface is a
  light hillshade (flat normals from derivatives) so contours read on it.
- Flight path layer: the camera centres as a line in `--ink`, small ticks every second,
  and the current camera as a frustum outline in `--magenta`.
- Render on demand (when the view, a layer or a tool changes), not in a constant loop,
  except while flying.

## Navigation: travel the pass, never orbit one fixed point

The model is a long strip. The old viewers turn around the centre of the model; on a long
pass that makes most of it unreachable. Controls:

- **Left-drag: grab and pan.** The surface point under the cursor at mouse-down stays under
  the cursor while dragging (pan in the horizontal plane at that point's height).
- **Right-drag, or Ctrl + left-drag: turn around the point under the cursor** at mouse-down
  (raycast; fall back to the horizontal plane through the view centre). Pitch clamped so
  the camera never goes under the pivot's horizon.
- **Wheel: zoom toward the point under the cursor**, exponential, never passing through it.
- **Double-click: go there.** Animate (400 ms, ease out) so the clicked point is centred at a
  comfortable distance.
- **Keys:** W A S D move along the ground relative to the view, Q E down and up, Shift
  faster; F or "Whole model" fits the model; arrow keys pan.
- **Views** (buttons with `data-view`): `plan` looks straight down over the current
  centre; `oblique` 45 degrees; `pilot` puts the camera on the keyframe camera nearest the
  playhead with its field of view, so the view matches the photo; `fit` frames the whole
  model from above and to the side.
- **Minimap** (`#minimap`): an orthographic top render of the model made once at load,
  plus the flight path, the current camera's ground footprint as a wedge, and the
  playhead position. Click or drag on it to move the view centre there, keeping height and
  heading.
- **Flight strip** (`#strip`, `#frames`, `#playhead`, `#clock`, `#playBtn`): thumbnails of
  about 24 evenly spaced keyframes fill the strip. Dragging or clicking sets the time;
  arrow keys step one keyframe when it has focus. The camera follows the flight from a
  chase position (behind and above the interpolated camera, looking where it looks).
  "Fly the pass" plays it in real time (x2 speed), and any drag on the view stops it.
  Interpolate positions linearly and orientations with slerp between keyframes.

## Tools

`[data-tool]` buttons and their `data-key` shortcuts pick a tool; Escape returns to Move.
While a tool is active, `body` gets `is-picking`. Every pick is a BVH raycast on the mesh;
a click that hits nothing is ignored with a note in `#toolHelp`. Points can be dragged
after placing. Finished measurements go into `#measureList` (name, value, a delete
button), can be selected (highlighted in the view, readout shown) and survive a tool
change. Lengths are multiplied by `scale.factor` and shown with the unit label ("m" when
status is `gnss` or `calibrated`, otherwise "units").

- **distance**: click points of a polyline, double-click or Enter to finish. Readout: total
  3D length (lead), horizontal length, height difference, average slope in percent, and each
  segment.
- **height**: two clicks. Readout: vertical difference (lead), horizontal offset, a plumb
  line drawn from the higher point down to the lower point's height.
- **area**: polygon, double-click or Enter to close. Readout: plan area (lead), surface
  area over the mesh, perimeter. Fill in `--magenta-wash`.
- **volume**: polygon, then a base: "lowest edge point", "average edge height" (default) or
  a typed height. Sample the surface on a grid inside the polygon by casting rays straight
  down (spacing so there are about 40,000 samples), then cut above the base, fill below
  it, net. Show the base plane.
- **profile**: two clicks. Sample 200 points along the line by casting down; draw an SVG
  elevation chart in `#chart` (distance on x, height on y, magenta line, ink axes with 3 or
  4 ticks); hovering the chart moves a marker on the model. Readout: length, climb,
  descent, highest and lowest.
- **sight**: observer click, then target click. The observer stands 1.7 m above the surface
  (converted through the scale; "1.7 units" uncalibrated). Cast observer to target; draw
  the visible part solid magenta and the blocked part dashed. Readout: visible or blocked,
  distance to the first obstruction.
- **point**: click; readout of x, y (height), z in the display units; with `georef`,
  latitude, longitude and height too.
- **note**: click, then type a short note inline; a pin with the note's first words.

**Export** (`#exportBtn`): download a GeoJSON FeatureCollection of all measurements
(coordinates in the local frame, x east, y north as -z, height; lon/lat when `georef` is
set) and a CSV summary, through a Blob link.

**Set scale** (`#calibrateBtn`, `#calibrateDialog`): "Draw the line" closes the dialog
into a two-click pick, then reopens it showing the model length in `#calibrateModel`;
"Apply" sets `scale.factor = metres / model length`, status `calibrated`, label
"calibrated from one 4.50 m length", stores it in localStorage under the model id
(wrapped in try/catch), updates `#unitsValue` (class `is-calibrated`) and every readout.
Offer "Reset scale" in the dialog once calibrated. When the model already has GNSS metres,
the button reads "Check scale" and applying needs a confirm.

## Neatline ticks and scale bar

`#ticks` overlays the neatline. In plan view, draw graduations on all four sides between
the two neatline rules at a nice interval in display units, labelled every fifth tick in
small tabular figures. In other views, draw no graduations and show `#scalebar` instead: a
bar whose length is correct at the depth of the view centre, labelled "about 20 m at the
centre of the view".

## Loading

Hide `#loading` (add `is-done`) once the mesh and the minimap are ready. If
`window.TESSERACT` is missing, show in `#loadingNote`: "No model packed. Run python
tools/pack_site.py out/runs/<run> first."

## Tests (`web/test/geom.test.js`)

polyline length; plan area of a square and an L shape; surface area of a tilted square;
volume of a box heap on a grid; profile resampling of a straight ramp; line-of-sight
against a wall height field; `niceInterval` on 0.07, 3.2, 48, 750.
