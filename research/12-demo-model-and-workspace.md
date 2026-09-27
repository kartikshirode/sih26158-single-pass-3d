# 12 · The demo model at 7/10, and a workspace to use it

Branch `night-7of10`, the night of 2026-09-27 to 28, from master at f95481a. The owner
asked for the demo clip's model at 7/10 by morning, a viewer that can travel a long pass
instead of orbiting one point, measuring tools that serve the problem statement's
applications, and a presentation site with its own character. Every number here is in
`audit/night-7of10/RUNLOG.md` with the folder it came from.

The short version. The demo's held-out views went from 22.87 dB and SSIM 0.649 to
24.63 dB and 0.709, over the 23.3 dB and 0.66 bars Codex set (`audit/codex-7of10`), and
the orange holes are gone. Two TextureMesh flags did most of it. The model now opens in
`web/workspace.html`, which moves along the pass like a map and measures on the surface,
and `web/index.html` presents it. OpenMVS's own seam levelling is still broken, so the
seams are levelled outside it (section 3).

## 1. What stops a perfect model from one pass

None of these is a bug to fix tonight. They set the ceiling.

- **One angle.** The drone flies one straight line with the camera about 23 degrees
  down. Everything to the side and far ahead is seen at a grazing angle. The detail map
  (section 5) puts a number on it: one photo pixel covers 0.003 model units on the ground
  under the flight and 0.1 on the far houses, 30 times coarser. The far edge smears
  because the photos there are smeared, not because the software drops them.
- **The back of anything.** A single pass never sees behind a building or a tree. The
  mesh bridges those gaps with long thin triangles, which is where most of the 3.3% of
  faces with no photo come from.
- **The sky crop.** Every B1 frame has a horizon, so S1 keeps the part below it: frames
  of 1920 x 595 from 1920 x 1080. Cropping less adds sky, not houses; the houses already
  sit at the top of the kept frame.
- **Seams.** Each texture patch comes from one photo. Neighbouring patches come from
  different photos with different exposure and view angle, so colour steps show at
  borders. OpenMVS's global and local levelling passes both blacken the atlas in this
  build (RUNLOG X11, X12, and Q1, TX1, TX2 before them).
- **No GPS on the demo clip.** Without GPS or a gimbal angle the model has no metres.
  MapAnything's own scale was tested as a stand-in and came out 40 times too small on the
  synthetic flights (RUNLOG), so the only honest route is one known length.
- **Video.** 1080p H.264 with motion blur and compression. S1 already drops the blurriest
  62 of 284 analysed frames.

## 2. The texture: what the unsharp mask was costing

TextureMesh sharpens every patch by default (`--sharpness-weight 0.5`). On B1 that put
contrast into the texture the photos never had, and the held-out renders paid for it:

| Setting | PSNR | SSIM |
|---|---:|---:|
| Before (sharpness 0.5, smoothness ratio 0.1) | 22.82 | 0.647 |
| Sharpness 0 | 24.21 | 0.696 |
| Sharpness 0, smoothness ratio 0.5 | 24.42 | 0.706 |

This isn't the check being flattered by blur, the trap research/11 found with a
half-resolution texture: the atlas keeps full resolution, and side by side the
unsharpened render is the closer match to the held-out photo. A higher smoothness ratio
makes fewer, larger patches, so fewer seams. Decimation 0.1 or 0.35, a finer mesh and
ratios 0.3 or 1.0 were all worse. B2 gains as much (25.32 to 27.10 dB).

## 3. Unseen faces and seams

TextureMesh points every face no photo saw at one texel of its empty colour, which drew
the demo's orange blotches. `src/pipeline/texture_fill.py` now gives each such face its
own cell under the atlas, painted from the nearest dense points, inside S3. Held out it
changes nothing (24.41 against 24.42 dB, since those faces are rarely in any photo), but
the orange is gone from every view of the model.

Seams are levelled after that by `src/pipeline/texture_level.py`, the global colour
adjustment of Waechter, Moehrle and Goesele (2014) that OpenMVS fails at here: one RGB
offset per patch corner, solved so both sides of every border agree, spread smoothly over
each patch. On the held-out mesh the colour step across borders falls from 9.6 to 7.8
levels and the score rises to 24.65 dB, SSIM 0.710. The bright blotches on the sand field
are gone. B5v's seams don't move, which says its seams come from misregistration rather
than colour.

## 4. End to end

| Run | Wall | Held out | Truth | Verify |
|---|---:|---|---|---|
| B1 `night-b1-final` | 293.4 s (264.5 s before) | 24.63 dB, 0.709, 98.77% | none (no GPS) | PASS |
| B3 `night-b3` | 342.4 s (318.1 s before) | | 0.393 m median, 95.2% within 1 m | PASS |
| B2 held-out build | | 27.10 dB, 0.862, 61.09% | | |

The ten-minute clip was not rerun: its 2.9 GB would have taken C: under the owner's 100 GB
floor, and the permission check refused the clean-up that would have made room. From the
measured increases on B1 and B3 (texture and fill about 10-25 s per run), B5v should land
near 530 s, R 0.88, against 502 s before. That is a prediction.

B2's held-out coverage came out 61% and then 71% from two identical builds, against the
72% Codex quoted. The texture change doesn't move it (the same poses with the old flags
give 61.09% too); B2, a long-lens pan with little parallax, simply varies by ten points
from run to run. Its 80% bar is still open, and any B2 comparison needs several runs.

## 5. The workspace

`web/workspace.html` opens from disk; `python tools/pack_site.py out/runs/<run>` puts a
run into `web/data/` first. The design is a map sheet: a double neatline round the view,
graduated in plan view, chart magenta for anything the user measures, contour brown for
what the model's own heights draw.

- **Moving along the pass.** Drag grabs the ground and slides it; right-drag turns about
  the point under the cursor; the wheel zooms toward the cursor; double-click flies
  there; W A S D move. A plan map shows where the view is and moves it on a click. The
  flight strip under the view scrubs the pass with the camera just behind the drone, and
  "Fly the pass" plays it. The page opens a third of the way along, from behind the
  drone, where the model looks most like the video.
- **Measuring.** Every point is a BVH raycast on the real mesh. Distance (3D, plan,
  slope), height, area (plan and surface), volume (cut and fill against a base),
  elevation profile with a chart, line of sight from a 1.7 m eye, coordinates, notes.
  Export as GeoJSON and CSV. Without GPS, lengths are in model units until "Set scale"
  takes one known length; the label always says which.
- **Detail layer.** Colours the surface by how much ground one photo pixel covers there,
  so nobody measures the far field as if it were the near field.
- **Contours**, drawn in the shader from the model's heights.
- **More than one model.** The synthetic test flight with its SRT packs beside the demo
  clip (`?model=b3`), and there the same tools read metres, east and north, latitude and
  longitude, with heights labelled as above take-off.

| Application in the problem statement | Tools |
|---|---|
| Border and strategic area mapping | profile, line of sight, coordinates, distance |
| Disaster damage assessment | area, volume, height, notes |
| Urban planning | height, area, distance, profile |
| Infrastructure inspection | distance, height, profile, notes, detail |
| Construction progress | volume, area, height, profile |
| Archaeology | profile, contours, area, notes |
| Digital twin | the six exports, coordinates |
| Mission planning | line of sight, profile, distance, coordinates |

## 6. The site

`web/index.html`. Its one bold element is the hero: each keyframe photo wiped against
the model rendered from that keyframe's own camera, playing through the pass. Then the
site as a map sheet with contours and the flight path, the stage log with measured
timings, the evidence table, the application matrix and the limits. The sheet hatches
the 18% of the site that the photos saw only coarsely (a pixel footprint over four times
the median), the way a map marks ground that wasn't surveyed. Offline, two
vendored fonts (Archivo and Newsreader italic, OFL), one bundled script.

## 7. Still wrong

- Seams are reduced, not gone (section 3).
- The far field is smeared by physics; the detail layer shows where.
- Hole bridges behind trees and houses are coloured from the dense cloud: plausible, not
  photographed.
- B2 coverage 61-71% run to run, below the 80% bar.
- The no-pitch accuracy bar (1 m on synthetic clips without a gimbal angle) was not
  worked on tonight; the demo clip was the target.
- B5v not rerun (section 4).
