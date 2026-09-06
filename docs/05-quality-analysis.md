# Why the reconstruction is unusable close up, and what actually fixes it

Status: measured 2026-09-05, on three real runs. Every number here is reproducible from
`out/*_raw` with the scripts named at the end.

## 1. The finding

The pipeline samples the ground at **2.2 cm** and carries geometric information at
**30-50 cm**. That 15-25x gap is the entire complaint: at a distance you see the sampling,
up close you see the information.

Detrended relief per window, one raw view, sky masked, median |residual| (robust - the
RMS version of this table is meaningless because ~1% of pixels are depth discontinuities
that dominate the square):

| window | ground size | Short dense window | growth | Kolu survey pass | growth |
|---:|---:|---:|---:|---:|---:|
| 3 px | 6.5 cm | 0.09 cm | | 0.19 cm | |
| 5 px | 10.8 cm | 0.19 cm | x2.13 | 0.42 cm | x2.26 |
| 9 px | 19.4 cm | 0.39 cm | x2.09 | 1.05 cm | x2.51 |
| 17 px | 36.6 cm | 1.09 cm | **x2.76** | 2.93 cm | **x2.79** |
| 33 px | 71.1 cm | 3.24 cm | x2.98 | 8.19 cm | x2.79 |
| 65 px | 140.1 cm | 9.51 cm | x2.94 | 17.95 cm | x2.19 |

Read the growth column, not the residual column. Growth is x2.0 from 3 px to about 14 px,
then steepens to x2.8-3.0.

A 6.5 cm patch of ground reads as flat to **0.9 mm**. Real gravel, asphalt, kerbs and
steps are centimetres of relief at that scale. They are not in the output.

### 1a. What the x2.0 regime actually is

Two hypotheses predict a smooth sub-patch region, and they are distinguishable. Both were
tested against the same view (`src/analysis/spectrum3.py`):

| window | ground | **measured** | growth | 14 px grid + bicubic | growth | pure quadratic | growth |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 px | 6.5 cm | **0.089 cm** | - | **0.081 cm** | - | 0.0056 cm | - |
| 5 px | 10.8 cm | 0.188 cm | x2.13 | 0.257 cm | x3.19 | 0.0262 cm | x4.66 |
| 9 px | 19.4 cm | 0.393 cm | x2.09 | 0.739 cm | x2.87 | 0.0749 cm | x2.86 |
| 17 px | 36.6 cm | 1.086 cm | x2.76 | 1.911 cm | x2.59 | 0.2680 cm | x3.58 |
| 33 px | 71.1 cm | 3.240 cm | x2.98 | 3.941 cm | x2.06 | 0.9927 cm | x3.70 |
| 65 px | 140.1 cm | 9.512 cm | x2.94 | 10.132 cm | x2.57 | 3.8077 cm | x3.84 |

**A plane fitted to a smoothly curved surface is not the explanation.** That hypothesis
predicts residual growing as the square of the window - x4 per doubling - and the control
confirms it at x3.6-3.8, with absolute values ~16x smaller than measured. Rejected.

**The interpolation hypothesis holds.** Take the real depth field, destroy everything below
one 14 px patch by downsampling to the patch grid, then put it back with a smooth
interpolant. At 3 px that control reproduces the measured roughness to **within 10%**
(0.081 vs 0.089 cm). At 9-33 px the control comes out *higher* than the real field, meaning
the actual output is smoother still than a bicubic reinterpolation of its own patch grid.

So the sub-patch regime carries no information that a smooth interpolant from the 14 px grid
does not already supply. That is the claim this whole document rests on, and it is measured,
not inferred.

## 2. The mechanism

MapAnything encodes with DINOv2, **ViT patch size 14**, and decodes with a DPT head.
The geometry is predicted per patch and the head interpolates smoothly inside it.

Every output grid we have produced is exactly patch-aligned, which confirms it:

    518 / 14 = 37     392 / 14 = 28     294 / 14 = 21

One patch is the real resolution unit:

| run | GSD | 1 patch = 14 px | measured break |
|---|---:|---:|---|
| Short dense window | 2.16 cm/px | **30.2 cm** | between 17 and 33 px |
| Kolu survey pass | 3.66 cm/px | **51.2 cm** | between 9 and 17 px |

So the ceiling is not the 518 px input cap that the literature emphasises. Even at
infinite input resolution the geometry would still be quantised to one patch. Feeding
sharper images moves the GSD down and moves the patch with it - the *ratio* stays at 14.

This matters for the requirement: the PS asks for <=1 m. We are at 30-50 cm effective
resolution with no margin, and that is *relative* resolution. Absolute accuracy is not
measurable at all on these clips, because neither has GNSS.

**Caveat on every centimetre figure in this document.** The metre labels come from the
model's own `metric_scaling_factor`; nothing here has been validated against a measured
length. The only check performed is a plausibility band - implied camera speeds of
1.6-3.0 m/s and altitudes of 6.4-11.4 m, which are reasonable for low-altitude drone video.
A 30% scale error sits comfortably inside that band. So the *ratio* of 14 (sampling to
information) is solid because it is scale-free; the absolute "30-50 cm" is only as good as
the model's asserted scale, and that stays unvalidated until a clip with GNSS or a known
control length is processed.

## 3. What the model already knows and we are discarding

The container prints its own prediction keys. All of these are produced on every run:

    pts3d, pts3d_cam, ray_directions, depth_along_ray, cam_trans, cam_quats,
    metric_scaling_factor, conf, non_ambiguous_mask, non_ambiguous_mask_logits,
    img_no_norm, depth_z, intrinsics, camera_poses, mask

We save five. **`intrinsics` and `depth_z` are the two that unlock everything in section 5**,
and saving them is a one-line change plus a container rebuild - not a re-derivation.

## 4. Lever already measured: coverage density

Same clip, same model, same 518 px cap, same fusion code. The only change is how much
ground the views are spread over.

| | Short, full 57 s | Short, dense 16 s |
|---|---:|---:|
| views | 45 | 42 |
| footprint | 115 x 58 m | 40 x 11 m |
| **model confidence, median** | **1.03** | **50.56** |
| confidence at the floor | 27.1% | 0.0% |
| fused density | 281 pts/m^2 | 1251 pts/m^2 |

The confidence channel collapsed to its floor on the wide pass: a third of those points sat
at exactly 1.000, meaning the 30th-percentile gate did nothing at all on the bottom third of
the cloud. The model was reporting that it had no idea, and the pipeline filtered on a
threshold of 1.000 and passed it through anyway.

Density scaled 4.5x, exactly the footprint ratio. Coverage density is a real lever and it is
free - it is a keyframe-selection policy, not new compute.

**But it does not fix section 1.** The dense window still resolves 30 cm, and its buildings
are still painted onto a sheet: relief p99.9 is 1.02 m under the PCA vertical and 1.72 m
under the camera-derived vertical, where the structures are visibly 3-4 m. Coverage buys
confidence and density. It does not buy detail.

## 5. What actually fixes it: use the model as an initialiser, not as the answer

The literature we surveyed reaches the same place from the other direction. From
arXiv 2507.14798, on aerial photogrammetric blocks: transformer-based methods beat COLMAP
by up to 50% only in the very-sparse, low-resolution regime, and "all three show limitations
on high-resolution imagery and large image sets". Its conclusion is that they "cannot
replace traditional SfM and MVS methods entirely" but "hold potential as complementary
approaches."

Complementary, concretely, means: MapAnything is very good at the thing classical MVS is bad
at - getting a globally consistent pose graph and metric scale out of a short single-pass
video with no GNSS, in one shot, with no matching failures. It is bad at the thing classical
MVS is good at - per-pixel depth. So:

    S2  MapAnything            poses + intrinsics + metric scale     (already have all three)
    S2b bundle adjustment      refine those poses on real features   NEW
    S3  MVS at full resolution per-pixel depth, photometric          REPLACES the point maps
    S4  edge-preserving mesh   Delaunay + refine                     REPLACES global Poisson

Ranked by expected gain per unit of work:

**1. Save `intrinsics` + `depth_z`.** One line. Blocks everything below. Without intrinsics
there is no COLMAP export and no MVS.

**2. Full-resolution MVS on MapAnything's poses.** PatchMatch estimates depth per pixel by
photometric matching rather than by interpolating a patch grid, so the 14 px floor goes away
entirely. *Projected, not measured:* a ~3 px correlation window suggests roughly 5x sharper,
but PatchMatch's real resolution is set by texture and baseline, not by its window size, so
treat 5x as a hypothesis to be measured once the stage exists - everything else in this
document is measured. COLMAP's dense
stereo is CUDA-only and this account has `GPUS_ALL_REGIONS = 0`, so that path is closed;
OpenMVS `DensifyPointCloud` runs on CPU and takes `--cuda-device -2` to force it. Budget it
as two Cloud Run executions (densify, then mesh) against the 1-hour task cap, with
intermediates on GCS.

**3. Bundle-adjust before MVS, not after.** Feed-forward poses carry error that MVS will
faithfully reproject into a blurred surface - the failure mode where the result looks
sharper but is wrong. `colmap point_triangulator` then `bundle_adjuster` are CPU-only and
cheap. Skipping this is the most likely way the rebuild produces a confident wrong answer.

**4. Drop voxel averaging.** Averaging positions across views blurs edges *by construction*;
it is the wrong operator no matter what feeds it. It exists today to stop overlapping views
triple-printing the surface. MVS geometric-consistency depth filtering solves the same
problem without the blur. Do not stack both.

**5. Replace global screened Poisson with OpenMVS `ReconstructMesh` + `RefineMesh`.**
Poisson closes over unobserved space by construction and smooths across depth
discontinuities - it is a second blur applied after the first.

**6. Tiled inference, if the model stays in the geometry path at all.** The 518 px cap is
per image, not per scene, so a tile covers less ground at the same 518 px: the GSD falls and
the *absolute* size of a 14 px patch falls with it. That is not in tension with section 2 -
the 14 px ratio is fixed, and tiling helps precisely because it shrinks what those 14 px
span on the ground. It costs global consistency across tile seams, so it is a fallback
rather than the plan.

**7. Sharper-detail models as an alternative branch.** MoGe-2 explicitly targets "metric
scale and sharp details"; 2DGS and ULSR-GS reach geometry comparable to COLMAP+OpenMVS on
aerial data. Worth a bake-off once 1-3 are in place, not before.

## 6. A defect this analysis turned up

**CORRECTED 2026-09-06 — this section originally claimed "no reliable gravity vector" and
that claim was wrong.**

The original evidence was that the cloud's thin principal axis and the scene-centroid-to-
camera direction disagree by 40.7, 55.7 and 56.5 degrees. That comparison was meaningless:
those are not two estimates of the same quantity. The centroid direction is not a vertical
at all for an oblique pass, where the drone sits *beside* the scene rather than above it,
and `render_views.upright_frame` only ever used it to disambiguate a **sign**. The direction
it ships - the thin principal axis - was never in question by that evidence.

What was genuinely missing was a way to *check* it. There is one, independent of the point
cloud: a gimballed drone camera holds roll near zero, so every camera's image-right axis is
horizontal in world space. Measured across the three runs, residual roll about the recovered
vertical is **0.21, 0.68 and 0.23 degrees median** - a real constraint, not an assumption.

Roll alone is not enough. It pins gravity only to one degree of freedom, and a pass flown on
a near-constant heading leaves that family undetermined: the camera-X singular spectrum is
`[1, 0.0086, 0.0044]` on Kolu, so those axes span one direction rather than a plane. Taking
the smallest singular vector there returns an arbitrary member of the family - which is how
the first pass at this manufactured a 40 degree "disagreement" out of nothing.

Using the ground plane for the direction and the roll constraint to check it,
**the two agree to 1.66, 2.14 and 2.47 degrees** on the three runs, and all three put the
camera plausibly above the ground (11.1 m, 11.0 m, 6.4 m). The new estimator lands
1.7-2.4 degrees from what was already shipping.

So the vertical is good to about two degrees and is now independently validated, rather than
merely assumed. `src/pipeline/gravity.py` returns that evidence alongside the vector -
`ground_correction_deg`, `residual_roll_deg`, `heading_degenerate` - and warns rather than
silently proceeding when the two constraints disagree by more than 15 degrees, which is what
a sloped or non-ground-dominated scene would look like.

## 7. Honest summary

The current output is a **2.2 cm sampling of a 30-50 cm surface**. Nothing in the fusion,
meshing or rendering stages can add information that the patch grid never carried, so no
amount of tuning downstream will change it. Two things change it: put more views over less
ground (measured, free, buys confidence and density but not detail), and move the geometry
stage off the feed-forward model onto full-resolution MVS driven by its poses (buys the
detail, costs a container rebuild and two Cloud Run stages).

Reproduce: `src/analysis/spectrum2.py` (section 1), `src/analysis/spectrum3.py` (section 1a),
`src/analysis/qual.py` (section 4),
`src/analysis/scale2.py` (section 6).

---

## 8. The rebuild, measured (2026-09-05)

Sections 1-7 were the diagnosis. This is what happened when the MVS stage was built
and run on the same 42 keyframes. Same poses, same clip, same renderer - the only
change is where the geometry comes from.

Job `sih26158-mvs-g5fjx`, asia-south1, 8 vCPU, **18 min 03 s wall clock**, CPU only:

| stage | seconds |
|---|---:|
| feature_extractor | 14.9 |
| exhaustive_matcher (861 pairs) | 104.1 |
| point_triangulator | 8.5 |
| bundle_adjuster | 27.0 |
| image_undistorter | 1.7 |
| InterfaceCOLMAP | 0.3 |
| **DensifyPointCloud** (full 1080x1250) | **876.6** |
| ReconstructMesh | 38.7 |
| TextureMesh | failed, rc=1 |

### The seed was sound, and bundle adjustment mattered

All **42 of 42 images registered**, 40,111 points, 244,549 observations, mean track
length 6.10. Mean reprojection error **1.525 px after triangulation, 0.414 px after
bundle adjustment** - a 3.7x improvement.

Both halves of that matter. 1.5 px on the first pass says the intrinsics fitted from
the point maps and the recovered crop geometry were right; had either been wrong the
error would have been tens of pixels, or frames would have dropped. And the 3.7x
improvement is the direct measurement of section 5 lever 3: the feed-forward poses
really did carry error, and densifying before correcting it would have reprojected
that error into a sharper-looking wrong surface.

### The patch floor is gone

Plane fitted in a ball of radius r, median |residual|:

| radius | MapAnything | OpenMVS | ratio |
|---:|---:|---:|---:|
| 3 cm | *too sparse* | **0.187 cm** | - |
| 6 cm | 1.288 cm | **0.353 cm** | 3.6x |
| 12 cm | 1.944 cm | **0.624 cm** | 3.1x |
| 25 cm | 2.344 cm | **1.121 cm** | 2.1x |
| 50 cm | 2.634 cm | 2.031 cm | 1.3x |
| 100 cm | 3.340 cm | 3.217 cm | 1.04x |

Read the shape, not the rows. **At 1 m the two agree to 4%** - they should, MVS
inherited MapAnything's poses, so the metre-scale shape is the same reconstruction.
The whole difference is at small scale, which is exactly where the diagnosis said the
information was missing.

MapAnything's residual grows only 2.6x while the radius grows 16x: it flattens into a
floor at ~1.3 cm, the signature of a surface with no structure below that scale, and
the 3 cm ball cannot even be populated because the fused cloud is voxelised at 3.4 cm.
OpenMVS grows a consistent **~1.8x per doubling** across the whole range and keeps
resolving down to 1.9 mm at 3 cm. That is a self-affine surface - real structure at
every scale - rather than an interpolant with a noise floor.

### Buildings have walls now

The test that noise cannot fake, since noise is isotropic and buildings are not:

| | MapAnything | OpenMVS |
|---|---:|---:|
| relief p99 | 0.89 m | **1.36 m** |
| relief p99.9 | 1.02 m | **2.51 m** |
| relief max | 1.32 m | **3.01 m** |
| above 1.0 m | 0.135% | **1.596%** |
| above 1.5 m | **0.000%** | **0.902%** |
| above 2.5 m | 0.000% | **0.103%** |

The feed-forward result had *zero* points more than 1.5 m above local ground against
structures visibly 3-4 m tall - buildings as paint on a sheet. MVS puts them at 3.01 m
with 0.9% of the cloud above 1.5 m. In the render the plan view now resolves interior
walls dividing rooms inside the large structure, and the 40% section shows a raised
roof profile standing off the ground.

### What it cost: completeness

MVS is honest about what it cannot see, where the feed-forward model interpolated
smoothly over it. Planimetric occupancy on a shared 20 cm grid:

| | cells | area |
|---|---:|---:|
| MapAnything | 6,528 | 261.1 m^2 |
| OpenMVS | 5,429 | 217.2 m^2 |

MVS covers **69.6%** of the cells MapAnything filled and adds 887 cells of its own,
for 83% of the occupied area. The visible black holes in the render are shadow and
textureless dirt where photometric matching found no geometric consistency across
three views. That is a real regression against the PS's completeness weighting (20
marks) and it is the honest trade for the accuracy weighting (30 marks): the surface
that remains is measured rather than interpolated. `--number-views-fuse 2` and
`RefineMesh` are the levers to claw coverage back, neither tried yet.

### Still open

- `TextureMesh` fails in 0.2 s (rc=1). Non-fatal - the finish stage colours mesh
  vertices from the nearest dense point - but the textured export is not produced.
- Absolute accuracy remains unmeasurable on this clip: no GNSS, so the <=1 m target
  cannot be scored, and the metre labels still rest on the model's own
  `metric_scaling_factor` (section 2 caveat stands).
- The gravity vector defect in section 6 is untouched.

## 9. Second clip: Kolu (2026-09-05)

Run on the Kolu survey pass to check that section 8 was a property of the method and
not of one clip. Job `sih26158-mvs-5cl9k`, 45 views at 1920x1080, **32 min 43 s**.

Three assumptions in the bridge held only for the first clip and were fixed before
this run (see `src/pipeline/colmap_export.py`):

- the crop geometry assumed height was the limiting dimension - true for 9:16, and
  true for this 16:9 by only 0.9% (294/1080 = 0.2722 vs 518/1920 = 0.2698), so it
  would have passed by luck. Now cover-crop on either axis, with a principal-point
  check that refuses a fit landing more than 8% off the frame centre.
- the fit ignored the non-ambiguous mask and used plain least squares. Kolu has sky:
  unmasked it returned **fy = 258 +/- 102** against a true ~394, residual 18.9 px.
- aggregating per-view intrinsics with the MEAN. Three of 45 views still reach
  |Y/Z| ~ 2.8 (~55 deg, outside the real 41 deg vertical FOV) and one collapsed to
  fy = 39.8, dragging the mean to 378 +/- 71. The **median held at 394.84 against a
  median fx of 394.91 - 0.02% apart**, which is the square pixels a real camera has.

Sparse stages: **45/45 registered**, 76,918 points, reprojection error
**1.730 -> 0.366 px** through bundle adjustment (4.7x, against 3.7x on the Short).
Mean track length 4.34 vs the Short's 6.10 - a wider-baseline pass over more ground.

### Same accuracy result

| radius | MapAnything | OpenMVS | ratio |
|---:|---:|---:|---:|
| 3 cm | *too sparse* | **0.349 cm** | - |
| 6 cm | 1.382 cm | **0.756 cm** | 1.8x |
| 12 cm | 2.762 cm | **1.487 cm** | 1.9x |
| 25 cm | 4.756 cm | **2.787 cm** | 1.7x |
| 50 cm | 5.852 cm | 4.707 cm | 1.2x |
| 100 cm | 7.219 cm | 7.359 cm | 0.98x |

The same signature: identical at 1 m (2% apart - same poses, same large-scale shape),
separating steadily as the scale shrinks. MapAnything's residual grows 5.2x over a
16x radius range and flattens; OpenMVS grows a consistent ~1.6-2.2x per doubling and
keeps resolving to 3.5 mm. The gain is smaller than the Short's 3.6x because Kolu's
baseline was already the better reconstruction - it is a real survey pass, not a
57 s cinematic sweep.

Relief: max **2.33 -> 3.58 m**, above 2.5 m **0.000% -> 0.315%**. The feed-forward
result had a hard ceiling at 2.33 m; MVS breaks through it. This clip's baseline
already had genuine vertical structure (8.0% above 1 m, since a wildlife overpass
really does have relief), so the change is less dramatic than the Short's
paint-on-a-sheet - but the ceiling was real and it is gone.

### The completeness cost was clip-specific, not inherent

Section 8 reported MVS covering 69.6% of the baseline's cells and framed that as the
trade. **On Kolu the opposite happens.** Planimetric occupancy, 20 cm cells:

| | cells | area | |
|---|---:|---:|---|
| MapAnything | 6,033 | 241.3 m^2 | |
| OpenMVS | 8,166 | 326.6 m^2 | **135% of baseline** |

MVS covers **94.3%** of the baseline cells, adds **2,476** new ones, and leaves only
343 baseline-only. So it wins on accuracy AND completeness here.

The difference is the footage, not the method. The Short's dense window was a tight
strip over shadowed, textureless dirt where photometric matching has nothing to lock
onto; Kolu is a well-textured survey pass with wide overlap. **The correct statement
is that MVS declines to invent surface where it cannot match, and how much that costs
depends entirely on how matchable the scene is** - which is a property worth having,
because the feed-forward alternative fills that ground with interpolation that was
never measured.
