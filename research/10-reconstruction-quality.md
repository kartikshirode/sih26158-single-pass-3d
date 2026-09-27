# 10 · Why the demo model looked wrong, and the fix

Started 2026-09-25, after the laptop GPU work in `research/09`. The demo run
(`out/runs/demo_gpu`) passed every gate: 134 of 134 views registered, 0.44 px after
bundle adjustment, verify PASS. The model still did not look like the video. Seen from
the side, the ground was three or four tilted sheets stacked on top of each other. This
file records how that was traced, what was tried, what changed in the code and what is
still wrong. Time was not optimised here; that comes next (section 7).

No software was installed or removed for this work. Section 8 lists what was deleted.

## 1. How it was measured

No ground truth exists for the demo clip, so every check uses a fact that holds for any
drone flight over a construction site: the ground is close to one plane, and the camera
moves smoothly. `tools/geometry_check.py` computes three numbers from a geometry folder:

| Check | What it is | Failure it catches |
|---|---|---|
| sparse on plane | share of sparse points within 3% of the flight height of one RANSAC ground plane | drifting poses stack the ground in sheets |
| layered cells | share of ground cells, 5% of the flight height across, whose dense heights spread over 10% of it | the same, in the dense cloud |
| step ratio | largest camera step over the median step | a hole in the keyframe chain |

I also rendered the dense cloud from the keyframe cameras next to the real frames, and
from new viewpoints. The pictures named below are frames and renders of the demo clip,
which is gitignored, so they stay out of git too: they are in
`out/evidence/quality-2026-09-25/` on the laptop, and `tools/geometry_check.py --out`
redraws the side and top views from any run.

## 2. Cause 1: the keyframe selector left two holes in the flight

The camera path had two jumps: 25 and 14 times the median step. Both sat exactly where
the selector had skipped a long stretch of frames.

- **Frames 82 to 144 (2 s)** failed the sky gate. After the 37% horizon crop, pale sand
  and haze scored 0.15 to 0.19 as "sky" against a 0.15 limit. The frames are sharp,
  normal ground (`keyframe_hole_f80_f146.jpg`).
- **Frames 240 to 306 (2 s)** failed the blur gate. That gate always drops the least
  sharp 25% of the clip. This stretch was only less textured, not blurred: its sharpness
  was 1900 to 2150 against 2800 elsewhere, and the drone was barely moving.

With no keyframes in a stretch, the views on either side share few or no features, and
their poses come out as separate pieces.

**Fix** (`src/ingest/video_ingest.py`, `select_keyframes`). The gates now express a
preference. A frame that passes them is taken once the optical flow since the last
keyframe reaches the budget, as before. If none arrives before 1.5 budgets, the sharpest
frame past one budget is taken anyway, provided it is not a slate and is under 50% sky.
The demo now gives 177 keyframes (was 134), 42 of them bridged, and the largest gap is 6
frames (was 66). The flow budget also counts all motion now, including frames the gates
rejected; before, the motion during a rejected stretch was ignored.

Removing the gates alone did not fix the model. The path became continuous (step ratio
1.8), but the ground was still layered: 34% of cells, about the same as before.

## 3. Cause 2: MapAnything's poses drift, and the refinement never saw it

The old pose step took MapAnything's poses, window by window, stitched with a Sim(3) on
shared views. COLMAP then triangulated points against those fixed poses, and a short
bundle adjustment refined them. The stitch scales between windows were 0.69, 0.61, 0.49
and 0.50: each window saw the scene at a different scale.

Every attempt to repair those poses left the model as it was:

| Run | Change | Layered cells | Note |
|---|---|---|---|
| E2 | gap-free keyframes, old pose path | 0.34 | path continuous, ground still layered |
| E2b | bundle adjustment to convergence (108 iterations, was cut at 10) | 0.31 | final cost 0.347 px against 0.344 px; the same shape |
| E2c | matching window 40 instead of 6 | 0.32 | 526,333 observations against 526,217: not one extra track; 0.45 of the sparse ground on one plane |

The last row explains the rest. An exhaustive match of the 200 keyframes showed frames
still sharing 150 verified matches 30 keyframes apart and about 50 at 40 apart. Yet the
mean track length stayed at 5. The long-range matches were there, and triangulation
against the drifted poses rejected them as outliers (reprojection over 4 px). So the
bundle adjustment only ever saw neighbours agreeing with neighbours. That cannot remove
drift across windows.

**Pose methods compared on the same 200 gap-free keyframes:**

| Run | Method | Sparse on plane | Outcome |
|---|---|---|---|
| E1 | COLMAP incremental mapper, focal length free | broken | focal went to 576 px (MapAnything fits 1100 px); the ground curled into a bowl |
| E3 | incremental mapper, focal fixed at 1100 px | broken | still curled; 564 s |
| E4 | global mapper, all pairs matched, focal fixed | **0.82** | one flat ground, track length 11.6, 0.51 px |
| E5 | global mapper, 30 neighbours matched, focal fixed | **0.78** | nearly as good; matching 14 s instead of about 100 s |

A forward flight over flat ground barely constrains focal length, which is why
self-calibration failed. MapAnything's focal length is good (its fit residual is 0.14
px); its poses across windows are the weak part.

**Fix** (`src/pipeline/local_gpu.py`, `global_sparse`). MapAnything now runs on a spread
subset of 60 views, only to fit the shared camera. COLMAP extracts features with that
camera fixed as PINHOLE. It matches each keyframe with its 30 neighbours plus the
quadratic far pairs. Then `global_mapper` solves every pose at once with focal length,
principal point and distortion held fixed. The old path is still there as `pose_method
mapanything`, for comparison.

## 4. Cause 3: OpenMVS kept almost none of the depth maps

On the global mapper's poses, DensifyPointCloud returned 141k points: a fan in front of
the first cameras, and nothing at all in view of camera 120 or 180. The depth maps were
fine. I read OpenMVS's `.dmap` files directly. They were 90 to 96% valid, and projected
into the world they tiled the ground in sequence along the flight. So the loss happened
in fusion.

- **ROI trimming.** OpenMVS estimates a region of interest assuming a Z-up scene, and
  trims the cloud to it. Here it cut the far field (141k points; 216k with it off). Off
  now: `--estimate-roi 0 --crop-to-roi 0`, plus `--tower-mode 0`, since tower mode is
  for orbits around a vertical structure.
- **Fusion filter.** The default, `dense-fuse` (2), kept 160k points from 52M depths.
  `fuse` (1) kept 7.9M from the same depth maps, covering 90 to 96% of every camera's
  view. The default is now 1 (`dense_fusion_filter`).
- **Model scale is not the cause.** The same poses scaled 3.7 times gave the same
  result. The first attempt at this test was invalid: COLMAP 4 takes camera poses from
  `frames.txt`, not `images.txt`, so only the points had been scaled.

## 5. Texture

A coloured cloud is not a model you can show. The page used to colour a thinned mesh
from the nearest dense point, which smeared everything. `local_gpu` now runs OpenMVS
TextureMesh after ReconstructMesh. It first decimates the mesh to 10% (demo: 2.1M faces
to 208k), then writes `geometry/scene_tex.obj` with an MTL file and a JPEG atlas, in
about 60 s.

With seam levelling on, 73% of the demo's faces sampled black from the atlas. The
global pass alone gave 95% black and the local one alone 66%, so both are off; with both
off, 0.2% of faces sample black. The cost is visible seams where two photos meet. A
further 3.8% of faces, mostly in the far field, are seen by no photo. They carry
TextureMesh's orange "empty" colour, and `tools/build_run_page.py` leaves them out of
the page.

## 6. Before and after, on the demo clip

Same clip, same horizon crop, same laptop. `demo_gpu` is the old pipeline and
`demo_gpu2` the new one.

| | demo_gpu | demo_gpu2 |
|---|---|---|
| keyframes | 134 | 177 |
| largest keyframe gap | 66 frames | 6 frames |
| step ratio | 25.1 | 2.2 |
| sparse on plane | 0.47 | 0.77 |
| layered cells | 0.35 | 0.06 |
| median cell spread / flight height | 0.042 | 0.008 |
| mean track length | 4.5 | 10.8 |
| reprojection error | 0.44 px | 0.49 px |
| dense points | 931k | 7.0M |
| textured mesh | none | 208k faces, 4096 px atlas |
| S3 time | 134 s | 259 s |
| whole run | 140 s | 269 s |

Rendered from the keyframe cameras, the new cloud covers 63 to 96% of each frame and
matches it: houses, trees, roads, the pond (`demo_gpu2_from_cameras.jpg`). The old one
did too from those cameras, but only because the sheets line up from where they were
built. The side and top views (`demo_gpu*_side.jpg`, `demo_gpu*_top.jpg`) show the
difference.

## 7. Still wrong, and the time cost

- **The far field is smeared.** The houses at the end of the site are only ever seen
  at a grazing angle from a distance, and the 37% horizon crop removes most of the frame
  that would see them better. The mesh there is long, thin strips.
- **Seams.** With seam levelling off, patch borders show where two photos differ in
  exposure.
- **No metres, no map.** The demo has no GPS track. The model is in model units and not
  georeferenced. Nothing here changes that.
- **Exports.** The textured OBJ lives in `geometry/`. The S6 exports (PLY, LAS, GeoTIFF)
  are in the levelled frame, and the OBJ is not yet carried into `export/` in that frame,
  so R-O5 still reads 3 of 6 formats.
- **Time.** S3 roughly doubled on the demo: the global mapper takes 85 s, texturing
  about 60 s, and meshing the larger cloud 60 s. The 8 to 12 minute prediction for a
  10-minute clip in `research/09` section 8 was measured on the old pose path and no
  longer holds. The global mapper's cost on 600 views has not been measured; bundle
  adjustment there is CPU only on this COLMAP build. Measuring and cutting that is the
  next piece of work. `Geometry.S_PER_VIEW_LOCAL_*` in `src/tesseract/stages.py` still
  carry the old rates.

## 8. Files and machine

- **Code.** `src/ingest/video_ingest.py` (`select_keyframes`, S1 version 3),
  `src/pipeline/local_gpu.py` (`global_sparse`, `mapanything_sparse`, the densify flags,
  texturing), `src/tesseract/stages.py` (S3 version 5, new facts),
  `tools/build_run_page.py` and `tools/run_page_template.html` (the textured mesh).
- **Tools and tests.** `tools/geometry_check.py` (the checks in section 1).
  `src/ingest/test_frames.py` T3b covers the bridging.
- **Machine.** Nothing installed or uninstalled. TextureMesh was already part of the
  OpenMVS build from `research/09` item 7. Deleted: my own experiment folder `out/exp`
  (7.7 GB) and an intermediate `out/runs/demo_gpu2/geometry/dense` folder I had
  recreated for texturing. Both are regenerable and gitignored.

**Reproduce:**

```powershell
$env:SIH_COLMAP = "C:\Users\Kartik\gpu-tools\colmap\bin\colmap.exe"
$env:SIH_OPENMVS = "C:\Users\Kartik\gpu-tools\openmvs_cuda"
python tesseract.py run "SIH DEMO.mp4" --geometry local --horizon crop --name demo_gpu2
python tools/geometry_check.py out/runs/demo_gpu2/geometry --out demo_gpu2
python tools/build_run_page.py out/runs/demo_gpu2
```
