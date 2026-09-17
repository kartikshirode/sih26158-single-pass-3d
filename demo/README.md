# SIH26158 demo

An interactive walkthrough of the pipeline, from picking a clip to measuring the
finished 3D model. It is a **replay**, and it says so in its own chrome, on every
screen: the compute was done ahead of time, and every counter, duration, thumbnail
and byte size on the page is read out of the artefacts of a real run.

## Running it

Double-click `index.html`. That is the whole procedure. No server, no network, no
install.

    demo/
      index.html        6.5 MB   the whole demo, mesh and keyframes inlined
      assets/clip.mp4  15.5 MB   the source video

**Keep `assets/` next to `index.html`.** It is the only external file. If it goes
missing the page still works and falls back to the keyframe strip, but you lose the
video.

Needs Chrome, Edge or Firefox with WebGL2, which is anything from the last decade.
Check it on the machine you will actually present from, before the day.

## The three acts

**1 Input.** Pick the prepared clip. Ingest reads the container, resolution, frame
rate and frame count off the file, and reports that there is **no GNSS sidecar and
no SRT telemetry**. That is the honest starting condition for this clip, and it is
what forces the "metric but not georeferenced" result at the end.

**2 Run.** Seven phases. Durations are the real recorded wall-clock times on 8 vCPU
with no GPU; the replay advances on a fixed beat so it fits a presentation, but the
numbers it prints are not rescaled. Two phases are marked *not separately timed*
because they genuinely were not, and inventing a number for them would be the one
dishonest thing on the page.

The timeline at the bottom right is the argument: **dense MVS is 77.5% of the run**,
and it is the single stage a GPU changes.

It ends on the problem statement's own six Desired Output rows, scored honestly:
four met, two not. Do not skip past the two red ones. They are the strongest thing
in the demo, because a panel that finds an overclaim stops believing the rest.

**3 Result.** The real mesh, orbiting in the browser. Drag to orbit, shift-drag to
pan, wheel to zoom, and the four view presets. `points` swaps the mesh for the dense
cloud.

`measure` is the one to show. Click two surface points and it gives a straight-line
distance **in metres**. It picks against the dense point cloud, so a measurement is
anchored to real measured surface points rather than to interpolated geometry, and
it tracks the model as you orbit because the distance is a property of the model and
not of the view.

**The distances it prints are too small, by about 5.5×.** The model reads the
scene as ~24.5 m across; measured against the lane markings and the ecoduct's
published 21–22 m waist, it is roughly 106 × 133 m (`docs/08`, EXP-14). An
earlier version of this page said the DSM "corroborated" 24.5 m. That was
circular: the DSM's 0.1 m cell is a chosen parameter in the same model units, so
it could only ever agree. Until the calibration lands in the build
(`docs/18` B-02/B-03), treat every printed metre as model units.

**Pick your two points before the day and know what they span.** Use the `plan`
preset, where the deck edges are unambiguous from above. Measuring blind in front of
a panel and then having to explain what you just measured is the one way this feature
works against you.

The scale comes from the feed-forward prior, not from ground control, and on this
clip it is wrong by ~5.5×. If someone asks whether a measurement is true on the
ground, the answer is "no — the shape is right, the ruler is not, and here is the
audit that measured by how much" (`docs/08`).

## The gallery

`gallery/index.html` (live at `/gallery/`) is the other half: every clip that reached a
3D model, source video beside the interactive geometry, with the feed-forward baseline
and the MVS rebuild on one toggle in a shared metric frame. It is where the "the AI's
geometry is flat" claim stops being a sentence and becomes something a judge can rotate.
See `gallery/README.md`.

This demo walks one clip end to end. The gallery shows all three and what separates them.

## The Q&A

`qa/index.html` (live at `/qa/`) is the technical Q&A, built by
`tools/build_qa.py`. They are ordered by **how exposed we are when asked**, not by how
technical the topic is — so "do you meet the processing-time target?" (no, by 2.3×) sits
in the last tier where it gets rehearsed, rather than in the middle where it gets skipped.

Every answer is tagged `measured` / `designed` / `open` and cites the file it came from.
The build re-greps all 54 headline figures against their source files and **fails the
build** if one does not appear, which is what stops a confident-sounding wrong number
getting onto the page. Press `/` to search; it prints with every answer expanded.

## Driving it from a lectern

Keyboard, so you are not hunting for an 11px button on a projector:

| key | does |
|---|---|
| `1` `2` `3` | jump to input / run / result |
| `space` | start the replay (on the run step) |
| `m` | measure on/off |
| `c` | clear the measurement |
| `p` | dense point cloud on/off |
| `v` | mesh on/off |

Mouse still does everything: drag to orbit, shift-drag to pan, wheel to zoom.

## If a judge asks whether it is live

Say no, plainly, and say why: the pipeline needs COLMAP, OpenMVS and a MapAnything
checkpoint, and this run took 34 minutes on 8 vCPU. It cannot happen in a browser
while someone watches. What they are looking at is the real output of a real run on
a real clip, wired to the interface it will have once the compute is fast enough to
sit behind it.

The page is built so that answer costs you nothing, because it never claimed
otherwise.

## The design system

All three pages are built on one stylesheet, `tools/design_system.css`, which is
**inlined into each page at build time** — they have to open from `file://` with
no server, so none of them can `<link>` anything. It ships in two layers: a base
(tokens, type, controls, surfaces, tables) that all three take, and a viewer layer
(canvas chrome, dock, HUD, measurement) that only the two 3D pages take.

It replaced a measured mess. Before it existed, across the three templates:

| literal values left in the CSS | before | after |
|---|---|---|
| font sizes | 18 | 0 |
| spacings | 28 | 0 |
| corner radii | 4 | 0 |
| colours outside the tokens | 6 | 0 |

Read that table precisely, because it is narrower than it looks: the audit counts
**hard-coded values**, and everything is now written as `var(--sp-5)`, which it
skips. So what it proves is that **no un-tokenised value can ship** — not that
every token is the right one for its slot. A rule could still say
`padding:var(--sp-7)` where `var(--sp-4)` was meant and the audit would pass.
That is worth having (it is what stopped the drift) but it is a spelling check,
not a taste check.

and two things were shipping below WCAG AA: `--faint` at **2.91:1**, which was
the colour of every source citation on the Q&A page, and `--muted` at 4.47:1.
The surface steps were 1.06, so "elevated" panels were not visibly elevated.
The ramp now has three text levels that all clear 4.5:1 on the lightest surface
and three surfaces each ≥1.15 apart.

`python tools/check_design.py` re-audits the **built** pages and fails on any
off-scale value, any colour outside the tokens, or any contrast regression.
`python tools/check_wiring.py` catches the other way a refactor breaks a page:
a renamed class orphaning the script that queries it. Both run automatically as
part of `build_all.py`, so neither is something anyone has to remember.

## Rebuilding

    python tools/build_all.py

builds all three pages and runs both audits, failing the run if anything drifted.
The individual builders still work on their own:

    python tools/build_demo.py

Reads `out/kf_kolu/ingest.json`, `out/kolu_mvs/mvs_result.json`,
`out/kolumvs3d/export/export_manifest.json` and `out/kolumvs3d/viewer_stats.json`,
and lifts the packed geometry straight out of `out/kolumvs3d/viewer.html`, so it
does not need open3d. Every number on the page comes from those files. Nothing is
typed in by hand, which is the point: rerun the pipeline and the demo re-reports
whatever actually happened.

`assets/clip.mp4` is cut once, to exactly the span the keyframes came from
(frames 781 to 1517, 24.6 s), and is not regenerated by the build:

    ffmpeg -y -ss 26.059 -i data/cand/kolu.webm -t 24.558 -vf "scale=1280:-2" \
      -c:v h264_mf -b:v 5M -pix_fmt yuv420p -an -movflags +faststart \
      demo/assets/clip.mp4

Showing any other part of the video would be showing footage the model was not
built from.

## What this demo does not do

- It does not process a dropped file. Drop one and it says so rather than pretending.
- It does not run the pipeline, on this clip or any other.
- It does not claim a CRS. The DSM ships with a real geotransform in metres and no
  CRS at all, because the clip carries no GNSS and a plausible-looking wrong one
  would silently reproject in downstream GIS.
