# Decision log

Version 1.0 — 2026-09-16. The architecture decisions that were scattered across seven
documents and forty commit messages, in one place, each with the evidence that made it and
the evidence that would unmake it.

**Format.** Context · Decision · Evidence · Consequences · Status · Revisit when.
**Status** is one of *Accepted*, *Amended* (still in force, changed by a later ADR),
*Superseded*, *Proposed*. A decision is changed by writing a new ADR that names the old one,
never by editing the old one's text.

---

## Index

| ADR | Decision | Status |
|---|---|---|
| 001 | Learned feed-forward spine, not classical SfM | Amended by 004 |
| 002 | MapAnything, Apache checkpoint | Amended by 014 |
| 003 | Build and test the evaluation harness before the pipeline | Accepted |
| 004 | Feed-forward model for poses and scale only; geometry from MVS | Accepted |
| 005 | OpenMVS on CPU for dense geometry, invoked as a separate process | Accepted |
| 006 | Bundle-adjust before densifying | Accepted |
| 007 | Vertical from the ground plane, checked by the roll-zero constraint | Accepted |
| 008 | Georeference with a 5-DOF fit in local ENU, project last, EGM2008 | Amended by 026 |
| 009 | No CRS without GNSS | Accepted |
| 010 | India-resident compute only | Accepted |
| 011 | CPU-first deployment; GPU is a speed upgrade, never a dependency | Accepted |
| 012 | Shard densification as 2 × 8 vCPU, overlap 2 | Accepted |
| 013 | Screen admissibility before spending inference | Accepted |
| 014 | Scale is a per-run, evidenced value; no global correction | Accepted |
| 015 | One frame for every exported file; assimp for FBX | Accepted |
| 016 | Per-vertex colour instead of a texture atlas | Retired as default; fallback only |
| 017 | The demo is a self-contained replay built from run artefacts | Accepted |
| 018 | Python 3.12 | Accepted |
| 019 | PyAV for decode | Accepted |
| 020 | Robust Sim(3) with a MAD-derived threshold | Accepted |
| 021 | Chain windows for shape, anchor once for position | Accepted |
| 022 | Report completeness against two denominators | Accepted |
| 023 | GPU dense path is COLMAP PatchMatch (BSD), not OpenMVS CUDA | Rejected by 027 |
| 024 | Adapt a permissive metric-depth prior for aerial altitude | Proposed |
| 025 | The product surface is a run console, built from run manifests | Accepted |
| 026 | Level before georeferencing; the track gives yaw and slope, gravity only the roll about it | Accepted |
| 027 | The GPU path runs on one machine: MapAnything, COLMAP sequential, OpenMVS CUDA | Accepted |

---

## ADR-001 · Learned feed-forward spine, not classical SfM

**Context.** R-O2 allows 900 s for a 10-minute video (~18,000 frames, ~600 keyframes).
**Decision.** Put a feed-forward multi-view model on the spine; demote classical tooling to
refinement and export.
**Evidence.** EXP-01: exhaustive matching of 600 keyframes is 179,700 pairs, 10.3–13.7 h;
even sequential matching plus extraction is 186–339% of the budget *before* SfM.
**Consequences.** Model licence and model accuracy become architecture concerns.
**Status.** Amended by 004 — the model keeps the poses and discards its geometry.
**Revisit when.** A global SfM (GLOMAP, BSD-3, "1–2 orders of magnitude faster" than
COLMAP per its authors) is timed on 600 keyframes with sequential matching.

## ADR-002 · MapAnything, Apache checkpoint

**Context.** NTRO is a technical intelligence agency; the PS names military reconnaissance.
**Decision.** `facebook/map-anything-apache`. Not VGGT (AUP bans "military, warfare … espionage",
both checkpoints), not Pi3 weights (non-commercial), not MASt3R (CC BY-NC-SA 4.0), not the
CC-BY-NC MapAnything checkpoint.
**Evidence.** `research/01-licensing-findings.md`; licences re-verified 2026-09-16 from the
repositories and model cards (`docs/11` §5).
**Consequences.** The Apache checkpoint trains on 6 datasets against the NC one's 13 and is
probably weaker. The model accepts intrinsics, poses and metric flags as priors — which the
pipeline has not yet used (`docs/09` GAP C-5).
**Status.** Amended by 014: its metric scale is not trustworthy without an external check.
**Revisit when.** EXP-02 measures the Apache/NC gap, or a permissive model with a validated
aerial scale appears.

## ADR-003 · Evaluation harness before the pipeline

**Decision.** `src/eval3d/` was built and unit-tested (21 checks) first. It always reports
absolute *and* aligned error, and its aligner fits no scale.
**Evidence.** ICP alignment reports 0.21 m on a model with a real 2.68 m offset (12.8×
flattering). Tanks-and-Temples-style 7-DoF alignment scores a 5%-too-small model at 0.000 m.
**Consequences.** No accuracy figure is quoted unless the harness produced it.
**Status.** Accepted. `docs/08` shows the same principle was missing for *scale*; ADR-014
closes it.

## ADR-004 · Feed-forward for poses and scale; geometry from MVS

**Context.** The model samples at 2.2 cm but carries information at 30–50 cm (model units;
2.7–3.0 m corrected on Kolu, `docs/08` §4.3): its DINOv2 patch-14 grid is the resolution
unit.
**Decision.** Keep MapAnything's cameras; take every delivered surface point from
full-resolution per-pixel photometric MVS.
**Evidence.** Two clips: reprojection error 1.73 → 0.37 px after BA; 1.8–3.6× finer at
matched radius; relief ceiling broken; 135% of baseline coverage on Kolu (83% on Village).
**Consequences.** Dense MVS is 77% of wall clock. Speed now depends on the densifier.
**Status.** Accepted.
**Revisit when.** A feed-forward model resolves below its patch at aerial GSD (EXP-18).

## ADR-005 · OpenMVS on CPU, as a separate process

**Context.** COLMAP dense stereo is CUDA-only; GPU quota is zero in every region on the
project account (`docs/06`).
**Decision.** OpenMVS `DensifyPointCloud --cuda-device -2`, from the upstream prebuilt
v2.4.0 binaries, invoked unmodified as a subprocess.
**Evidence.** Both clips densified on 8 vCPU; the MVS image fails its build if a binary
cannot load.
**Consequences.** OpenMVS is **AGPL-3.0** (verified). Running it unmodified as a separate
program keeps our code outside its copyleft, but a hosted service that *modifies* it would
owe source. See `docs/16` L-1.
**Status.** Accepted for the CPU path; ADR-023 proposes the GPU path.

## ADR-006 · Bundle-adjust before densifying

**Decision.** COLMAP `point_triangulator` then `bundle_adjuster` on the feed-forward poses,
before MVS.
**Evidence.** 3.7× (Short) and 4.7× (Kolu) reduction in reprojection error. Densifying on
unrefined poses would reproject that error into a sharper-looking wrong surface.
**Status.** Accepted.

## ADR-007 · Vertical from the ground plane, checked by roll

**Decision.** Gravity = ground-plane normal projected so camera roll is exactly zero; warn if
the two disagree by more than 15°.
**Evidence.** Residual roll 0.21–0.68° median across three runs; ground and roll agree to
1.7–2.5°. An earlier "no reliable gravity" claim compared two non-comparable quantities and
was withdrawn (`docs/05` §6).
**Consequences.** A pass on constant heading only weakly constrains the check
(`heading_degenerate: true` on Kolu). Telemetry gimbal pitch would close it.
**Status.** Accepted.

## ADR-008 · Georeference: 5-DOF in local ENU, project last, EGM2008

**Decision.** Yaw + translation + scale fit (never 7-DOF) against GNSS in local ENU, then
PROJ to UTM (zone chosen at runtime, EPSG:32642–32647) with EPSG:9518 and
`allow_ballpark=False`.
**Evidence.** EXP-09: a 7-DOF fit on a straight pass throws the scene 267–311 m even with
RTK; yaw-only gives 0.041 m with RTK. UTM carries ~0.6 m/km of scale error across India.
EGM96 vs EGM2008 differ by 1.68 m at Amritsar. PROJ silently skips the geoid if the grid is
missing.
**Consequences.** A vertical reference is mandatory, not optional as the PS implies.
**Status.** Amended by ADR-026. Implemented in the synthetic path (`run_demo.py`); **not yet
exercised on a real clip with GNSS**.

## ADR-009 · No CRS without GNSS

**Decision.** With no GNSS, the DSM ships with a real geotransform and `crs=None`, plus a tag
saying why.
**Rationale.** A plausible-looking wrong CRS reprojects silently in GIS.
**Amendment note.** `docs/08` found the geotransform's *metres* were also wrong on Kolu. The
same logic now extends to scale: an `unvalidated` scale must not print as metres
(ADR-014, `docs/09` §2).
**Status.** Accepted.

## ADR-010 · India-resident compute only

**Decision.** `asia-south1` (and `asia-south2`) on GCP, or the Baramati cluster. Never
`asia-southeast1`.
**Evidence.** DST Geospatial Data Guidelines (15 Feb 2021): data finer than 1 m horizontal
must be stored and processed in India; the PS targets ≤ 1 m.
**Consequences.** Removes the only region where Cloud Run L4 existed for this project.
Kaggle is allowed only for benchmarking on non-Indian public footage.
**Status.** Accepted.

## ADR-011 · CPU-first; GPU is an upgrade, never a dependency

**Decision.** Every stage runs on CPU. Cloud Run Jobs (8 vCPU / 32 GiB) is the deployment;
Baramati is the scale path.
**Evidence.** GPU quota auto-denied (`NOT_ENOUGH_USAGE_HISTORY`) on Compute Engine, Cloud Run
and Vertex. Kolu takes 2,078.7 s on 8 vCPU.
**Consequences.** **R-O2 is not met on CPU** (34 min 38 s for 45 views against 15 min for
~600). Recorded as an open target, not hidden.
**Status.** Accepted.

## ADR-012 · Shard densification as 2 × 8 vCPU, overlap 2

**Decision.** Fewer, fatter shards.
**Evidence.** 5 × 4 vCPU with overlap 4 was 7% *slower* than one task and 21% less precise;
2 × 8 with overlap 2 was 13% faster end to end (1.42× on densify) at quality parity.
**Consequences.** Horizontal CPU is worth ~1.4× and cannot reach R-O2 alone.
**Status.** Accepted.

## ADR-013 · Screen before inference

**Decision.** S0 rejects or crops clips with a horizon, sky above 15%, multiple shots, or a
static overlay, and says why.
**Evidence.** T-ROB-08: three of four candidate clips rejected in 40 s of CPU each; the
Nicosia reconstruction had been run, downloaded and presented before these properties were
measured.
**Status.** Accepted.

## ADR-014 · Scale is per-run and evidenced; no global correction

**Context.** A ×2 correction was requested for all measurements.
**Decision.** Reject a global constant. Each run carries a `scale_calibration.json`
(`docs/09` §2) with factor, bracket, method and references; without one, scale is
`unvalidated` and is not printed as metres. The factor is applied once, at export.
**Evidence.** EXP-14 (`docs/08`): Kolu is 5.3–5.8× too small by two independent rulers. The
factor is a per-run model output, so it cannot transfer between clips.
**Consequences.** Every absolute figure on the Village clips is unvalidated until EXP-14b
gives them a ruler. The plausibility band is retired as a validation method.
**Status.** Accepted. Implementation tracked as S1–S8 in `docs/08` §6.
**Implemented 2026-09-17** for the viewers: `research/calibration/kolu.json` (×5.54, bracket
5.32–5.77), read through `tools/scale_cal.py`. The ×2 request was resolved against the
reference behind it — a road-to-bridge reading — and the Estonian 5.0 m clearance norm,
which ×2 would still violate (`docs/08` §3.6, §7).
**Caveat shipped with it.** The factor is one scalar. Both rulers are horizontal and agree;
the vertical evidence is weak, and an anisotropic error (hypothesis H5) would need a
per-axis correction. EXP-17 decides.

## ADR-015 · One frame for every export; assimp for FBX

**Decision.** All seven files are written in the same frame from the same transform. FBX goes
through assimp (BSD-3) in the container; Blender is a developer-machine fallback only.
**Evidence.** The first version rotated only the point products, so OBJ and LAS did not
overlay. Six of six formats now read back; FBX carries the `Kaydara FBX Binary` header.
**Consequences.** The Blender fallback passes a `bpy` script. Keep it out of any distributed
build (`docs/16` L-3).
**Status.** Accepted.

## ADR-016 · Per-vertex colour instead of a texture atlas (interim)

**Context.** `TextureMesh` fails in 0.2 s with rc = 1.
**Decision.** Colour mesh vertices from the nearest dense point.
**Consequences.** No texture seams across exposure changes (helps R-C3), but no texture
detail finer than the vertex spacing (hurts R-F5).
**Status.** Retired as the default 2026-09-22: the failure was a wrong file name (`docs/12` EXP-20) and the Kolu re-run wrote a textured OBJ with an 8192 x 8192 atlas. Per-vertex colour stays the fallback for any run whose `TextureMesh` step fails.

## ADR-017 · The demo is a self-contained replay

**Decision.** Three pages, each one HTML file that opens from `file://`: classic scripts,
base64 assets, one inlined design system, and every number read from run artefacts at build.
Deployed to Vercel with git integration off.
**Evidence.** The build re-greps 54 figures and fails on a missing one; two audits
(`check_design`, `check_wiring`) run in the same command.
**Consequences.** The figure re-grep checks that a number *exists in its source*, not that
the source is *right* — `docs/08` is the case where it was not.
**Status.** Accepted.

## ADR-018 · Python 3.12

**Evidence.** Open3D has no 3.13 wheels; MapAnything specifies 3.12. (The MVS image uses the
conda-forge Python 3.11 that ships with COLMAP; that is a separate process.)
**Status.** Accepted.

## ADR-019 · PyAV for decode

**Evidence.** decord is abandoned (HEAD 2022, 221 open issues). FFmpeg's native H.264/HEVC
decoders are LGPL, so a decode-only pipeline needs no GPL.
**Status.** Accepted. torchcodec or DALI for GPU decode when a GPU exists.

## ADR-020 · Robust Sim(3) with a MAD-derived threshold

**Evidence.** RANSAC does not improve the typical case (a fraction of a percent worse at
0–2% outliers); it bounds the worst case (flat near 4.1 m to 35% outliers). A fixed 1 m
threshold scored 5.29 m against 4.08 m for plain least squares.
**Status.** Accepted.

## ADR-021 · Chain windows for shape, anchor once for position

**Evidence.** EXP-13: 36 hops cost 3% (1.03×) because a shared view gives exact
correspondences. Anchoring every window to GNSS is 1.48× worse than anchoring once, because
24 m of baseline cannot determine scale under 1.5 m of GNSS noise.
**Status.** Accepted.

## ADR-022 · Completeness against two denominators

**Evidence.** EXP-08: a nadir pass sees 14.3% of along-track facade; reporting the whole
scene alone penalises physics, reporting the observable alone hides a real limit.
**Status.** Accepted.

## ADR-023 · GPU dense path is COLMAP PatchMatch (Proposed)

**Context.** Dense MVS is 77% of wall clock. OpenMVS has a CUDA build, but it is AGPL-3.0.
COLMAP is BSD and its PatchMatch stereo is CUDA.
**Proposal.** On a GPU node, densify with `colmap patch_match_stereo` + `stereo_fusion`; keep
OpenMVS as the CPU path.
**Evidence needed.** EXP-16 (`docs/12` R2): wall clock and the `compare_mvs.py` metrics for
both densifiers on Kolu, same poses.
**Decide by.** The first Baramati GPU run.

## ADR-025 · The product surface is a run console, built from run manifests

**Context.** ADR-017 shipped three pages that walk a visitor through one prepared
reconstruction. That is a presentation. Meanwhile the rebuilt pipeline writes a
`run_manifest.json` and a QA report for every run, and `tesseract verify` checks a finished
run against the contracts, and none of it had a surface.
**Decision.** `demo/console/` is the product: a rail of every run in `out/runs/`, and per run
its claim block, stage timeline, geometry, artefacts and contract check. Every figure is read
from that run's own manifest, and **the verdict strings are the manifest's**, so a target that
reads `not measurable` reads that way on the page. Monotone greyscale with no accent hue, so
status is carried by the word and the mark only reinforces it. Built by
`tools/build_console.py` from `console_template.html` and `console_ds.css`.
**Evidence.** Seven runs render, including one refused at L5 that produced nothing and says
so. `tools/test_console.py` drives it in a real browser (21 checks) and asserts the two claims
no static audit can see: a measurement on the calibrated clip prints metres, and the same tool
on the unvalidated clip prints units.
**Consequences.** The console build needs `out/`, which is gitignored, so CI drives the
committed page instead. A fingerprint of the template and the stylesheet is stamped into the
page and the test refuses to run when they drift. Hand-built rather than Carbon or Primer: the
only packaged system that runs without a bundler is Primer CSS, whose value is GitHub's colour
system and whose bundle is about 1 MB, and a monotone brief discards colour. Fonts are IBM Plex
Sans and Mono, self-hosted, OFL-1.1 (`docs/11` §5.2).
**Status.** Accepted. ADR-017's three pages stay live and unchanged at `/`, `/gallery/` and
`/qa/`; the console is at `/console/`.
**Revisit when.** The console is worth making the root, or the executors land and a run can be
started from the page rather than the CLI.

## ADR-024 · Adapt a permissive metric-depth prior for aerial altitude (Proposed)

**Context.** Zero-shot metric depth collapses at UAV altitude. AerialMetric (arXiv
2606.29716) reports MoGe-2 at δ₁ = 5.1% on its oblique-city split without true intrinsics,
and 89.3% after LoRA adaptation, with data, code and weights released under CC BY 4.0.
MoGe code and MoGe-2 weights are MIT.
**Proposal.** Use an aerial-adapted metric-depth model as an **independent** scale witness
beside MapAnything, never as the geometry.
**Evidence needed.** EXP-15 (`docs/12` R1): factor error on Kolu against the EXP-14 bracket;
verify the weights' licence at download.
**Decide by.** Before any scale claim reaches a deliverable.

## ADR-026 · Level before georeferencing; the track gives yaw and slope, gravity only the roll about it

**Context.** ADR-008's yaw-only fit assumes its input is already level with Z up. S5 fitted
the raw F3/F4 cameras before S5b levelled anything, and the synthetic source hid it: its
"arbitrary frame" was a yaw and a translation at scale 1.0, already level and already metric.
The core-logic audit (F-07) gave that frame a 5 degree roll and a 0.18 scale and got a
perfect camera-track fit with the scene 21.4 m off.
**Decision.** S5 levels first, with the same vertical S5b uses (ground plane checked by
roll-zero, ADR-007). The fit then takes yaw and the track's slope from the GNSS, and only the
roll about the track from gravity: `eval3d.gnss.track_sim3`, with `robust_yaw_sim3` choosing
the GNSS inliers. Six degrees of freedom; 7-DOF stays refused. The synthetic source now hands
S5 a gauge with roll and pitch up to 25 degrees, a scale of 0.1-2x, and full cam2world poses.
**Evidence.** On that gauge the ground-plane vertical came out 0.70 deg off, all of it along
the track, which is the direction a straight track does constrain. Scene RMSE over seeds 7-9,
levelled then fitted yaw-only: RTK 2.4-3.1 m, SBAS 3.1-4.3 m, consumer 4.4-5.7 m. Levelled
then fitted with the track's slope: RTK 0.06-0.09 m, SBAS 1.2-2.6 m, consumer 2.6-4.8 m.
EXP-09's degeneracy is untouched: rotation about the track axis still comes only from gravity.
**Consequences.** The synthetic RTK figure now tests levelling and scale recovery, which it
did not before. `run_demo.py`, the legacy job behind the README's 0.098 m, still uses the
old level-by-construction frame; that figure is claims ledger item 26. The slope comes from
the GNSS altitude, so a consumer receiver's vertical noise now reaches the tilt; on the
seeds above that still beat the ground-plane vertical.
**Status.** Accepted. Synthetic path only, like ADR-008; gap C-3 still blocks a real clip.
**Revisit when.** A real clip with per-frame GNSS (EXP-21) shows the GNSS slope noisier than
the scene's vertical, or a curved track makes the principal direction a poor summary of it.

## ADR-027 · The GPU path runs on one machine: MapAnything, COLMAP sequential, OpenMVS CUDA

**Context.** Every recorded run used CPU only (no GPU quota on the GCP account), and a
10-minute clip had never been timed end to end. ADR-023 proposed COLMAP PatchMatch as the
GPU densifier because it is BSD where OpenMVS is AGPL. A laptop with an 8 GB RTX 4060 was
available, and both COLMAP 4.2 and OpenMVS 2.4 publish Windows CUDA builds.
**Decision.** `src/pipeline/local_gpu.py`, selected in tesseract by `--geometry local`:
MapAnything in bf16 over overlapping windows sized to the GPU, COLMAP GPU SIFT with
sequential matching (6 neighbours, quadratic overlap), triangulation against the known
poses, a 10-iteration BA, point filtering and the S3b gate, then OpenMVS DensifyPointCloud
on CUDA over the dense view set and ReconstructMesh. OpenMVS stays a separate, unmodified
process (ADR-005's licence position).
**Evidence.** `research/09-gpu-pipeline.md`. On 129 views at 967x297, OpenMVS CUDA
densified in 31 s; COLMAP PatchMatch took 488 s for its photometric pass alone. On 600
uncropped views S3 takes 511 s at 0.63 px after BA; with S0 and S1 measured on a 10-minute
file, the prediction for a 10-minute 1080p30 clip is 8 to 12 minutes on this laptop.
**Consequences.** ADR-023 is rejected on speed. A local run needs CUDA torch, MapAnything
and the two CUDA builds (`research/09` section 1), found through `SIH_COLMAP` and
`SIH_OPENMVS`. MapAnything at 392 or 448 px was faster but failed the intrinsics guard, so
the model's own 518 mapping stays. The cloud jobs (`mapanything_job/`, `mvs_job/`) are
unchanged and still CPU.
**Status.** Accepted for the local path. The 10-minute prediction is not a measurement
until the full run is done (claims ledger item 28).
**Revisit when.** The full 10-minute run disagrees with the prediction by more than 25%,
or the job runs on a GPU with more than 8 GB, where larger MapAnything windows and full
resolution densify become affordable.

## ADR-028 · Local poses from COLMAP's global mapper; OpenMVS fuse filter; textured mesh

**Context.** The demo run built on ADR-027 passed every gate, yet its ground came out as
three or four stacked, tilted sheets. Three causes were found (`research/10`): the
keyframe gates left two 2-second holes in the flight; MapAnything's window poses drift,
and triangulating against them rejected the long feature tracks that would have exposed
the drift, so the short bundle adjustment never saw it; and OpenMVS's default fusion
filter kept almost none of the depth maps on corrected poses.
**Decision.** S1 bridges any stretch the gates empty with its sharpest usable frame
(`select_keyframes`). In `local_gpu`, MapAnything fits only the shared camera, on 60
spread views; COLMAP matches 30 neighbours per keyframe and `global_mapper` solves every
pose with that camera fixed (`pose_method` "global"; the old path stays as
"mapanything"). DensifyPointCloud runs with `--fusion-filter 1` and no region of
interest. TextureMesh textures the mesh decimated to 10%, with seam levelling off.
**Evidence.** `research/10` section 6, on the demo clip: sparse ground within 3% of one
plane 0.47 to 0.77, layered dense cells 0.35 to 0.06, largest camera step 25 to 2.2 times
the median, dense points 0.93M to 7.0M. Self-calibrating SfM (incremental, or with the
focal length free) curled the ground into a bowl, so the camera stays fixed.
**Consequences.** S3 on the demo went from 134 s to 259 s. ADR-027's 10-minute prediction
was measured on the old pose path and no longer holds. Seams show where photos differ in
exposure, and the far field, seen only at grazing angles, is smeared.
**Status.** Accepted for the local path. Partly supersedes ADR-027 (its pose step).
**Revisit when.** The global mapper is timed on 600 views, or a clip with GPS gives a
metric check of the shape.

## ADR-029 · The local S3b gate needs half the views registered, not all of them

**Context.** On the cloud path poses come from MapAnything and every view is triangulated
against its own pose, so "registered = N" held by construction. ADR-028 moved the local
path to COLMAP's global mapper, which can fail to place a view. On a 600-view synthetic
flight it placed 554: the last 46 frames look past the end of the site and hold 0 to 36
features each. The gate refused the whole run for them, and a finale clip with a stretch
of water or a few blank frames would have been refused the same way. `docs/09` already
listed `GEO-UNREG` as "drop unregistered views; warn if < 80%", so the code and the
contract disagreed.
**Decision.** On the local path the gate passes when at least `min_registered` (50%) of
the views are placed and reprojection error is at most 1.0 px. Unplaced views are listed
in `local_gpu_result.json`, left out of the dense set and kept as NaN rows in
`cameras.npy`, so the file still lines up with the keyframes. S3 adds `GEO-UNREG` and
`registered_views`, with a note when under 80%.
**Evidence.** `audit/codex-opt/RUNLOG.md` rows L1 and F3: the 600-view set now runs to a
textured mesh. The demo, Nicosia and test_flight baselines placed every view, so the change leaves them as they were.
**Consequences.** A partial model is delivered where there used to be none, with the
missing share in the manifest. Levelling, the shape check and the run page skip NaN
cameras. The cloud path keeps its 100% gate.
**Status.** Accepted for the local path.
**Revisit when.** A real clip shows the mapper splitting into two large models; keeping
only the largest then drops a real part of the flight, and merging would be the fix.

## ADR-030 · A clip's SRT track georeferences it to F6, with heights above take-off

**Context.** GAP C-3: S1 parsed and aligned a DJI SRT sidecar to every keyframe, but S5
only read GNSS through the synthetic source, so a real clip with GPS still came out in
model units and a local frame. Judging weighs accuracy at 30%, and the problem statement
asks for a georeferenced, metric model. The SRT gives latitude, longitude and a height
above take-off. Its `abs_alt` is barometric (rel_alt plus a constant), so nothing in the
file gives the take-off point's own height, and an orthometric F7 height would be a guess.
**Decision.** On a video source S5 fits the keyframes' camera centres to their SRT fixes
with the same levelled 6-DOF fit as the synthetic path (ADR-026), keyframe i to camera i,
skipping keyframes with no pose or no fix. The result is F6: local ENU in metres about the
first fix, up being height above take-off. `georef.json` holds the whole transform, so
S6 carries the textured mesh into the same frame. The LAS and GeoTIFF carry an
orthographic CRS about the reference fix, which matches ENU horizontally to within 2 cm
per km per 100 m of height, and the vertical is named in the tags and the manifest.
Fewer than 8 usable fixes or a track under 20 m skips the stage with `ING-NOGNSS`.
**Evidence.** `src/tesseract/test_tesseract.py` T3g: a gauge rotated on all three axes and
scaled 0.04 comes back to 0.010 m RMS against the truth, with an unposed view and an
empty fix left out. `audit/codex-opt/RUNLOG.md` row R1 has the test_flight clip.
**Consequences.** A clip with an SRT is in metres, scale status "gnss", with a CRS a GIS
can place. Heights stay relative until a take-off elevation (a DEM lookup, or the
operator) is supplied; that is the step to F7.
**Status.** Accepted.
**Revisit when.** A take-off elevation source is available, or an SRT family writes an
RTK flag, which would let the scale status say "gnss+rtk".

## ADR-031 · The global mapper refines one focal length, starting from MapAnything's

**Context.** ADR-028 fixed the camera at MapAnything's fit because self-calibration from
scratch curled the demo's ground into a bowl. On the synthetic test_flight clip, whose
true focal length is known (1066 px), MapAnything fitted 1414 px. The same 60 frames as
sharp renders gave 1058 px, so the H.264 encoding alone moved it by a third. Held fixed,
that left the georeferenced cloud 12.6 m (median) from the true surface while the
cameras sat within 14 cm of their true path.
**Decision.** The camera is SIMPLE_PINHOLE, starting at MapAnything's focal length, and
the global mapper refines that one value (`refine_focal`); principal point and
distortion stay fixed. The value it settles on is recorded as `focal_after_mapper_px`.
**Evidence.** `audit/codex-opt/RUNLOG.md` F1 and F2: test_flight's focal came to 1135 px
and the cloud error to 3.2 m. On the demo the focal stayed at 1095 px against 1098, with
the ground as flat as before and the held-out views unchanged. PINHOLE with refinement
split fx and fy (1599 and 1146 px), so it is not used.
**Consequences.** The metric model depends less on one network's reading of the frames.
The refined focal is still 6% long on test_flight, so heights are not yet at 1 m. A
clip that gives the mapper little parallax could still pull the focal length far; the
recorded value is there to catch it.
**Status.** Accepted. Amends ADR-028's fixed camera.
**Revisit when.** A clip with ground truth other than the synthetic one is available, or
a refined focal length moves more than about 20% from MapAnything's.
