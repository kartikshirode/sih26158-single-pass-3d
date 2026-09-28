# 13 · A depth prior for the houses and the tree

On master, 2026-09-28. The owner watched the demo model fly by and named what was wrong:
the houses, the tree in the first couple of seconds, the far end and the terrain. This
note covers what those faults turned out to be, the fix (`src/pipeline/prior_depth.py`,
wired into `local_gpu.py` as the `geometry_prior` option) and what it costs. The option is
off by default. The demo run that uses it is `out/runs/demo-prior2` (section 9); the
first one, `out/runs/demo-prior`, is section 6.

The short version. OpenMVS can't shape the houses on this clip, because it sees them from
far away with almost no change of angle. MapAnything can, once it's given the solved
poses. Its depth, pulled onto the MVS surface and fused in a TSDF, then refined by
OpenMVS, gives the houses flat roofs and upright walls and makes the tree stand. The
held-out score drops by 0.2 dB and 0.02 SSIM, still over the 23.3 dB and 0.66 bars, and
coverage stays over the 98% bar (98.53%) since the Poisson remesh and the gap fill went
in. The demo runs end to end in 752.7 s of the 900 s budget with it on.

## 1. What was actually wrong

I rendered the base model (`night-b1-final`) from above, from the side and along the
pass, with its texture and without. Four faults, in order of how bad they looked:

- **Blob houses.** Roofs and walls melt into one rounded lump. The MVS depth maps are
  noise on the houses, since every photo of them is taken from far off at about the same
  angle.
- **The crumpled tree.** The tree in the first seconds is a thin folded sheet instead of
  a crown.
- **Sails.** Long thin triangles bridge from roofs down to the ground behind them. Those
  gaps are ground no view saw, and ReconstructMesh closes them with whatever spans them.
- **Far-field stripes.** At the top of the crop the ground is seen at a grazing angle
  and the mesh turns into stripes along the view direction.

The terrain itself was a smaller problem than it looked. The ground is domed by about
5% of the flying height across the track, and research/12 already traces that to the
single pass. A radial distortion term moved the sag from 6.7% to 4.5% (the
`refine_distortion` option in 640bd74). It stays an experiment, off by default, and the
prior needs a pinhole camera anyway (section 8).

## 2. The method

`prior_depth.py` has the steps in its docstring. In short:

1. Every keyframe (1920 x 595) is cut into 3 overlapping tiles of the network's grid
   shape, 710 px wide at x = 0, 605 and 1210, resized to 518 x 434. A whole keyframe
   would be squeezed to 518 x 161 and lose the houses.
2. MapAnything runs on windows of 8 consecutive views of each tile, 2 shared between
   windows, with the scaled intrinsics and the COLMAP poses given as inputs. With poses
   in, the depth comes out in the model's frame up to a scale.
3. A ratio field corrects each depth map to the MVS mesh: per 48 px cell, the median of
   MVS depth over network depth, filled and blurred. The metric shape comes from the
   photos and the detail from the network. A small MVS spike doesn't move the field.
4. All tiles are fused in Open3D's voxel block grid TSDF. Voxel is the median MVS depth
   over 240, truncation 8 voxels, depth upsampled 2x first. Grazing rays (cos under 0.05)
   are dropped, and so are the lowest 15% of confidence and an 8 px border. MVS depth
   stands in where the network has nothing it trusts. A voxel needs 3 observations.
   Components under 0.2% of the faces are dropped and the mesh is decimated to 900k
   faces.
5. Holes the fused mesh surrounds in plan view (ground behind a house) are closed with
   the MVS mesh's faces (`close_holes`). Open ground past the edge stays open.
6. OpenMVS RefineMesh pulls the result back onto the photos: decimate 0.35, resolution
   level 1, 2 scales, max face area 16. Then TextureMesh at `--decimate 1`, and
   texture_fill and texture_level as before.

The network's depth is used out to 1.55 times the median depth (`prior_depth`). Past
that, out to 2.8 times (`prior_fill_depth`), only the MVS surface goes into the TSDF.
That's the far field, kept at the photos' own coarse surface instead of the network's
guess about it.

## 3. What was tried on the way

- **Without upsampling** the TSDF left combs on every roof edge. Upsampling depth 2x and
  a truncation of 8 to 10 voxels fixed it.
- **Unseen faces** started at 27% of the fused mesh. A cleaner fusion (the confidence
  and border cuts) got that to 13%, and refinement to about 10-14%. On the final
  stride 2 model it's 29,783 of 277,580 faces, 10.7%. texture_fill colours them from the
  dense cloud.
- **RefineMesh's own decimation** (it picks one when not told) softened the houses
  back toward the lumps. It's set to 0.35 explicitly.
- **A separate far-field pass** came first: `add_far_field` adds MVS faces outside the
  fused footprint within reach of a camera, after refinement. Letting the MVS surface
  into the TSDF out to 2.8 replaced it, so one mesh goes through refinement. The function
  stays in the module with its test; local_gpu doesn't call it.
- **No far field at all** (d6ref) had the crispest houses and the worst coverage.

## 4. Held-out numbers

Every tenth keyframe (`names[9::10]`) is held out of densify and texturing, and the model
is scored by rendering it from those views (`tools/view_check.py`, scale 1). Same poses
for every row.

| Model | PSNR (dB) | SSIM | Coverage | Faces |
|---|---:|---:|---:|---:|
| Base, OpenMVS mesh (ho-base) | 24.643 | 0.709 | 98.72% | |
| Prior, no far field, refined (d6ref) | 24.441 | 0.677 | 90.73% | |
| Prior, fill 2.8, refined 0.35, every view (m3) | 24.402 | 0.680 | 97.68% | 285,817 |
| Same, tiles on every second view (m5) | 24.342 | 0.678 | 97.27% | 277,580 |

Held-out PSNR can't see what the prior is for. A lumpy roof with the right texture on
it renders almost the same as a flat one from a view next to the photos. What the
numbers do show is that the prior costs little in photo agreement, and that coverage is
where it loses: the TSDF drops grazing and low-weight surfaces that ReconstructMesh keeps.

The renders show the gain. Close views of the houses in the first half of the pass,
shaded without texture, show roofs and walls where the base model had lumps, and a tree
with a crown. Stride 2 against stride 1: the houses look the same, the tree is a little
rougher.

## 5. Time

Tile inference ran 352 s for 531 tile views at stride 1 (177 keyframes, 3 tiles each).
Fusion took 50-60 s and RefineMesh about 250 s. That's about 660 s on top of the base
run's roughly 293 s, over the 900 s budget. Stride 2 tiles every second keyframe, halves
the network time and fuses 267 tiles, for 0.06 dB. It's the default.

The end-to-end run with the prior on is section 6.

## 6. The demo run

`out/runs/demo-prior`: `SIH DEMO.mp4` end to end with `{"local_gpu": {"geometry_prior": true,
"prior_stride": 2}}`, clean, no resume. 892.8 s of the 900 s budget, level L0, verify PASS,
all six formats (FBX too, with `SIH_ASSIMP` set). S3 took 867.4 s, and the prior's share was
572.5 s:

| Step | Seconds |
|---|---:|
| MapAnything on 267 tile views (load 22.4 s) | 208.2 |
| Fusion, 267 tiles, 2,338,098 faces kept to 899,999 | 51.1 |
| RefineMesh | 305.4 |
| TextureMesh | 48.0 |

RefineMesh ran 55 s longer than in the held-out test, and that's what used up the margin.
The model has 274,735 faces, 28,791 of them (10.5%) coloured from the cloud.

Rendered next to the base model from off the flight line, the houses are blocks with roofs
where the base has lumps, and the tree stands. But the model is full of black holes and
comb-like stripes the base doesn't have, which would show in any fly-through. So it wasn't
packed for the site.

## 6a. The stripes, and what closes them

The stripes are in the fused TSDF mesh itself, before refinement: at grazing range the
surface breaks into thin parallel ribbons. None of these changed them (held-out setup,
stride 2, fused mesh rendered from the same off-path views):

- a coarser voxel, median depth / 180;
- depth upsampled 3x instead of 2x;
- a weight threshold of 2 instead of 3;
- Open3D's `fill_holes` on loops up to 0.1 units.

What worked was remeshing the fused surface with screened Poisson (depth 11, vertices
more than 3 voxels from the fused mesh trimmed, then decimated to 900k faces) before
RefineMesh, and after refinement adding the MVS mesh's faces wherever a plan-view cell of
median depth / 120 has no face of the prior. The stripes are gone and the houses keep
their shape; a few holes remain behind the tree.

| Model (held out, stride 2) | PSNR (dB) | SSIM | Coverage |
|---|---:|---:|---:|
| Prior as in section 4 (m5) | 24.342 | 0.678 | 97.27% |
| m5 plus the gap fill only | 24.357 | 0.679 | 97.86% |
| Poisson, RefineMesh 2 scales, gap fill | 24.400 | 0.687 | 98.68% |
| Poisson, RefineMesh 1 scale, gap fill | 24.382 | 0.686 | 98.69% |

The Poisson version meets the 98% coverage bar the prior used to miss. Poisson and the
decimation took 40 s and the gap fill 1 s; RefineMesh at 1 scale ran slower here (393 s
against 257 s), so it doesn't buy the time back. Section 9 has how both went into the
pipeline and fit the budget.

## 7. What changed on the laptop

Open3D 0.19.0 was installed with pip for the TSDF (186 MB in site-packages). It brought
dash, ConfigArgParse, retrying and janus, which nothing else here uses. numba was already
there. To undo:

```
pip uninstall -y open3d dash ConfigArgParse retrying janus
```

## 8. What is still open

- The back of every house is still a guess. The prior makes it a plausible wall instead
  of a sail, but no photo shows it.
- The far edge is still smeared. That's the photos, not the mesh (research/12, section
  1).
- The prior needs a pinhole camera. A run with refine_distortion on falls back to the
  OpenMVS mesh and records `prior_error`.
- A few small gaps are left at the far edge of the crop, much as in the base model, and
  a few shard triangles at the tree's left flank.
- 18.8% of the demo model's faces are coloured from the cloud, not a photo. Most of them
  are the ring of MVS faces under the prior (section 9), hidden by it from any view.

## 9. Into the pipeline, and a demo run inside the budget

On master, 2026-09-29. Both steps from section 6a are now in `prior_depth.py`
(`poisson_remesh`, `gap_fill`) with tests, and `prior_mesh` runs them: fuse, close holes,
Poisson, RefineMesh, gap fill, then TextureMesh. New options: `prior_upsample` (2),
`prior_poisson` (octree depth, 10), `prior_gap_cell` (120), `prior_gap_below` (120) and
`prior_gap_ring` (1).

### What the held-out runs said

Same setup as section 4 (`out/exp/scripts/hochain.py`, through the module's own
functions). Times are for the held-out scene, 159 views.

| Setup | Fusion | Poisson | RefineMesh | PSNR (dB) | SSIM | Coverage |
|---|---:|---:|---:|---:|---:|---:|
| Stride 2, upsample 2, Poisson 11 | 50.1 s | 31.4 s | 224.2 s | 24.390 | 0.686 | 98.62% |
| Stride 2, no upsampling, Poisson 11 | 42.3 s | 30.4 s | 220.5 s | 24.370 | 0.684 | 98.72% |
| Stride 2, upsample 2, Poisson 10 | 44.3 s | 15.3 s | 217.1 s | 24.409 | 0.687 | 98.63% |
| Stride 2, no upsampling, Poisson 10 | 42.4 s | 16.8 s | 245.6 s | 24.405 | 0.685 | 98.72% |
| Stride 3, upsample 2, Poisson 11 | 37.0 s | 32.2 s | 259.2 s | 24.392 | 0.685 | 98.43% |
| Stride 2, Poisson 11, RefineMesh decimate 0.25 | 44.7 s | 31.8 s | 206.4 s | 24.396 | 0.687 | 98.62% |
| **Stride 3, Poisson 10, height test and ring (the defaults)** | 38.0 s | 16.0 s | 220.1 s | **24.429** | **0.687** | **98.53%** |

Two RefineMesh times ran beside other GPU work and read high. The handoff's two ideas for
finding time did less than hoped: dropping the upsampling saved 8 s of fusion, because
the TSDF's cost is in the tiles, not the rays. Poisson depth 10 halved the remesh with no
change in score or in the close renders, and tiling every third keyframe scored like
every second while skipping a third of the network's views, about 60 s on the demo.
RefineMesh at decimate 0.25 saved 15 s but keeps fewer faces for the houses, and it
wasn't needed.

### Ground under the trees

Rendered from off the flight line, the first chain still showed black holes on the ground
beside the trees. The prior kept the crown and lost the floor under its edge, so the
plan-view test saw a covered cell and added nothing. `gap_fill` now also takes an MVS
face lower than every prior face in its cell by more than the median depth / 120. That
filled the holes but left slivers along each patch's border, so every patch grows by one
ring of MVS faces sharing a vertex with it. The first ring also took in ReconstructMesh's
long sails, which poked up through the roofs; faces with an edge over 4 times the median
aren't grown into. Held out: the height test alone scored 24.407 dB, 0.687, 98.66%, the
ring 24.430, 0.688, 98.66%.

### The demo run

`out/runs/demo-prior2`: `SIH DEMO.mp4` end to end with `{"local_gpu": {"geometry_prior":
true}}` and the defaults above, clean, no resume, `SIH_ASSIMP` set. **752.7 s** of the 900 s
budget (892.8 s for the run in section 6), level L0, verify PASS, all six formats.

| Step | Seconds |
|---|---:|
| MapAnything on 177 tile views (load 15.7 s) | 123.6 |
| Fusion, 177 tiles, 2,183,793 faces kept to 900,000 | 38.1 |
| Poisson, depth 10 | 15.2 |
| RefineMesh | 237.8 |
| TextureMesh, 458,297 faces | 62.6 |
| Texture fill (86,204 faces), seam levelling | 16.0, 15.6 |

The gap fill added 186,929 MVS faces. Rendered from the same off-path views as section 6
beside `night-b1-final` and `demo-prior`, the houses keep their roof steps and walls, the
tree is one crown, and the stripes and black holes of the section 6 run are gone. This is
the model the site shows now.
