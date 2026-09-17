"""
Build the viva Q&A page: demo/qa/index.html

Ordering is by HOW EXPOSED WE ARE, not by how technical the topic is. Those two
axes diverge badly here. "What is your processing time?" is topically trivial and
answer-wise brutal - we miss the target by 2.3x. "Why patch-14 rather than the 518 px
cap?" is topically deep and answer-wise easy, because it was measured three ways with
the competing hypothesis tested and rejected. Sorting by topic depth would bury the two
questions that can actually sink the presentation in the middle of tier 2.

Numbers here are written as PROSE with a citation, not injected from JSON. The other
builders inject because they report a handful of counters and a mis-wire shows up as a
visibly broken widget. This page carries ~40 figures embedded in arguments, where a
mis-wire would instead produce a confidently wrong sentence. `check_numbers()` greps the
headline figures back against their source files after rendering, which is the guarantee
that actually matters.

Every entry carries a provenance tag using the project's own vocabulary from
docs/architecture-prompt.md §4: measured / designed / open.

    python tools/build_qa.py
"""
from __future__ import annotations
import html as _html
import io, json, os, re, sys

from design_system import css as ds_css

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "demo", "qa")
SITE = "https://tesseract-demo.vercel.app"

TIERS = [
    ("settled", "Settled",
     "Measured, favourable, nothing to defend. Answer briefly and move on."),
    ("mechanism", "Mechanism",
     "Needs a real explanation. We have these cold, with the measurement behind each."),
    ("challenged", "Challenged",
     "Decisions a sharp examiner will push on. Defensible, but the reasoning has to be "
     "the real one rather than a rationalisation."),
    ("exposed", "Exposed",
     "Where we miss the target, cannot make the claim, or genuinely do not know. "
     "These are the ones to rehearse. Conceding them precisely is what makes the rest "
     "believable."),
]

T_MEAS = ("measured", "measured")
T_DES = ("designed", "designed, unbuilt")
T_OPEN = ("open", "open")


def Q(tier, q, a, tag, src, detail=None):
    return {"tier": tier, "q": q, "a": a, "tag": tag[0], "tagl": tag[1],
            "src": src, "detail": detail}


QA = [
    # ------------------------------------------------------------ SETTLED
    Q("settled", "What does the system do, in one sentence?",
      "It turns a <b>single pass</b> of drone video into a textured, metrically scaled 3D "
      "mesh and point cloud, exported in the six formats the problem statement asks for, "
      "viewable and measurable in a browser. One flight line, no ground control points, "
      "no GPU required.",
      T_MEAS, "docs/01 §1"),

    Q("settled", "What are the inputs, and what happens if the metadata is missing?",
      "Mandatory per the PS: 1080p/4K video, GPS, flight metadata. Optional: IMU, "
      "barometric altitude, camera intrinsics, RTK/PPK. Ingest auto-detects SRT, CSV, "
      "EXIF and flight logs, because the PS says the dataset is handed over at the event, "
      "so the drone, codec and metadata schema are unknown in advance. <b>Both of our test "
      "clips carry no GNSS sidecar and zero SRT records</b>, and the pipeline still "
      "completes - it self-calibrates intrinsics and reports the result as metric-relative "
      "rather than georeferenced.",
      T_MEAS, "out/kf_kolu/ingest.json, docs/01 §3"),

    Q("settled", "What comes out, and in what formats?",
      "A textured mesh and a dense point cloud, written to <b>6 of 6</b> required formats: "
      "OBJ, PLY, LAS 1.4, GeoTIFF DSM, glB/glTF and FBX, all in one shared local frame. "
      "The files are still in the model's units: the scale calibration is applied in the "
      "viewer and has not yet been written into them. Each is written and read back as a "
      "check. FBX comes via assimp (BSD-3), "
      "so every format has a permissive route.",
      T_MEAS, "out/kolumvs3d/export/export_manifest.json"),

    Q("settled", "You throw away 97% of the frames. Why?",
      "1,562 decoded frames become <b>45 keyframes</b> on the Kolu clip. The rejections are "
      "recorded by reason: <b>787 for motion blur</b>, <b>529 for sky fraction</b>, "
      "<b>356 for horizon geometry</b>. Redundant frames add matching cost and no "
      "parallax; degraded frames actively poison the pose solve. Dropping them before pose "
      "is solved is cheaper and safer than filtering afterwards.",
      T_MEAS, "out/kf_kolu/ingest.json"),

    Q("settled", "How do you detect motion blur?",
      "Variance of the Laplacian, with the threshold set per clip rather than fixed. On "
      "Kolu the threshold landed at <b>3837.5</b> and rejected 787 frames. Compression "
      "artefacts are handled by the same gate, because a heavily re-encoded frame loses "
      "high-frequency energy in the same way a blurred one does.",
      T_MEAS, "out/kf_kolu/ingest.json"),

    Q("settled", "How do you deal with moving cars, people and animals?",
      "No detector, and deliberately so. Dense matching requires photometric consistency "
      "across <b>three or more views</b>; a car that moved between keyframes cannot be "
      "consistent in three, so it fails the geometric-consistency filter and never reaches "
      "the surface. Answering PS challenge (iv) by construction is more robust than a "
      "class-list detector that fails on the object class nobody trained for.",
      T_MEAS, "docs/02 §8"),

    Q("settled", "Why per-vertex colour instead of a texture atlas?",
      "A single drone pass crosses large exposure changes. An atlas bakes those changes "
      "into seams at chart boundaries, which look like geometry defects and are hard to "
      "undo. Per-vertex colour spreads the variation smoothly across the surface. The cost "
      "is that colour resolution is tied to mesh density, which is acceptable at "
      "1.95 M triangles.",
      T_MEAS, "docs/02 §7"),

    Q("settled", "How many keyframes registered?",
      "<b>45 of 45</b> on Kolu and 42 of 42 on the second clip. No dropped views, which is "
      "the first thing to check on a single-pass sequence because there are no loop "
      "closures to recover a lost frame.",
      T_MEAS, "out/kolu_mvs/mvs_result.json"),

    Q("settled", "What did bundle adjustment actually buy you?",
      "Mean reprojection error <b>1.730 px to 0.366 px</b>, a factor of 4.7, over 76,918 "
      "points and 334,057 observations with mean track length 4.34. On the second clip, "
      "1.525 px to 0.414 px.",
      T_MEAS, "out/kolu_mvs/mvs_result.json"),

    Q("settled", "How large is the delivered model?",
      "<b>3,445,735 dense points</b> and <b>1,952,962 triangles</b> from 45 keyframes. "
      "The browser viewer ships a decimated 160k-triangle / 220k-point version so it loads "
      "without a server; the full-resolution model is in the exports.",
      T_MEAS, "out/kolumvs3d/viewer_stats.json"),

    Q("settled", "Can you measure on the model, and in what units?",
      "Yes - two clicks in the viewer give a straight-line distance, picked against the "
      "dense cloud so it is anchored to real measured surface points. On the Kolu clip it "
      "is in <b>calibrated metres</b>: the model's own units were <b>5.3–5.8x too small</b>, "
      "measured against the lane width and the ecoduct's published 21–22 m waist, and the "
      "viewer applies that factor. The Village clips have no ruler yet, so they measure in "
      "model units and say so. Picks only land on surfaces the drone saw - the underpass "
      "interior is empty, so a click aimed at the ceiling lands on the arch face or the deck.",
      T_MEAS, "docs/08-measurement-validation.md"),

    Q("settled", "What hardware produced these results?",
      "<b>8 vCPU, no GPU</b>, on Cloud Run in asia-south1. Every component is permissive "
      "and CPU-capable by design: a GPU is a speed upgrade, never a dependency for getting "
      "a result. Measured CPU fan-out is 1.42x.",
      T_MEAS, "docs/06"),

    # ---------------------------------------------------------- MECHANISM
    Q("mechanism", "You use an AI model but throw its geometry away. Why?",
      "Because its geometry has a hard resolution ceiling and its poses do not. Modern "
      "feed-forward models (DUSt3R / VGGT / MapAnything) are what make a single pass "
      "tractable at all - they recover pose and metric scale from one flight line where "
      "classical SfM lacks the overlap. But we measured the pipeline <b>sampling the ground "
      "at 2.2 cm while carrying information only at 30-50 cm</b>, a 15-25x gap. So the "
      "model is used strictly as a pose and metric-scale prior, and <b>every delivered "
      "surface point</b> comes from full-resolution photometric multi-view stereo.",
      T_MEAS, "docs/05 §1"),

    Q("mechanism", "What exactly is the resolution ceiling, mechanically?",
      "MapAnything encodes with DINOv2 at <b>ViT patch size 14</b> and decodes with a DPT "
      "head. Geometry is predicted per patch and the head interpolates smoothly inside it. "
      "Every output grid we produced is exactly patch-aligned - 518/14 = 37, 392/14 = 28, "
      "294/14 = 21 - which confirms the patch is the real resolution unit. At 2.16 cm/px "
      "that is a 30.2 cm patch; at 3.66 cm/px, 51.2 cm.",
      T_MEAS, "docs/05 §2"),

    Q("mechanism", "How do you know that is interpolation rather than a genuinely smooth surface?",
      "Two hypotheses predict a smooth sub-patch region and they are distinguishable, so "
      "both were tested against the same view. <b>Curvature is rejected</b>: a plane fitted "
      "to a curved surface predicts residual growing as the square of the window, x4 per "
      "doubling; the control confirms x3.6-3.8 with absolute values ~16x smaller than "
      "measured. <b>Interpolation holds</b>: destroy everything below one 14 px patch by "
      "downsampling to the patch grid, then reinterpolate, and at 3 px the control "
      "reproduces the measured roughness to within 10% (0.081 vs 0.089 cm). At larger "
      "windows the control comes out <i>higher</i> than the real field - the output is "
      "smoother than a bicubic reinterpolation of its own patch grid.",
      T_MEAS, "docs/05 §1a, src/analysis/spectrum3.py"),

    Q("mechanism", "Does feeding sharper images fix it?",
      "No, and this is the part people get wrong. The ceiling is not the 518 px input cap "
      "the literature emphasises. Higher input resolution lowers the ground sample distance "
      "and moves the patch down with it - <b>the ratio stays at 14</b>. Even at infinite "
      "input resolution the geometry would still be quantised to one patch. No downstream "
      "tuning recovers detail the patch grid never carried.",
      T_MEAS, "docs/05 §2"),

    Q("mechanism", "So what is the AI model still doing?",
      "Three things nothing else supplies cheaply: camera <b>pose</b> across a low-overlap "
      "single pass, an explicit <b>metric scale factor</b> (it is natively metric, not "
      "scale-ambiguous), and <b>intrinsics</b> when the clip carries none. The intrinsics "
      "fit residual is <b>0.2214 px</b>. Pose and scale are then refined by COLMAP "
      "triangulation and global bundle adjustment before any surface is computed.",
      T_MEAS, "out/kolu_mvs/mvs_result.json"),

    Q("mechanism", "Why exhaustive matching rather than sequential?",
      "A single pass gives no loop closures, so a sequential matcher has nothing to fall "
      "back on when a link is weak. Exhaustive matching costs 323.1 s of the run - 15.7% - "
      "and buys 45/45 registration. It is also the stage that stops scaling first: at the "
      "~600 keyframes a 10-minute video implies, exhaustive matching is 179,700 pairs, "
      "which is why classical SfM cannot be the spine here.",
      T_MEAS, "out/kolu_mvs/mvs_result.json, docs/02 §1"),

    Q("mechanism", "Why OpenMVS for densification rather than COLMAP?",
      "COLMAP's dense stereo is <b>CUDA-only</b>, so on a no-GPU floor it is simply "
      "unavailable. OpenMVS <code>DensifyPointCloud</code> runs on CPU with "
      "<code>--cuda-device -2</code>. That single constraint decides the stage.",
      T_MEAS, "docs/02, docs/06"),

    Q("mechanism", "How do you get metric scale with zero ground control points?",
      "Not from the model alone - we tested that and it failed. MapAnything's "
      "<code>metric_scaling_factor</code> put the Kolu clip <b>5.3–5.8x too small</b>. So "
      "scale now comes, in order, from GNSS when the clip has it, from objects of known "
      "size in the scene (lane markings, published structure dimensions), and otherwise "
      "the result is labelled unvalidated. No ground control points are needed; a ruler "
      "the scene already contains is. That is our answer to PS challenge (viii).",
      T_MEAS, "docs/08-measurement-validation.md"),

    Q("mechanism", "Where does the vertical direction come from?",
      "A ground plane fitted to the cloud, cross-checked against the gimbal roll-zero "
      "constraint. The export manifest records the residual roll as 0.24 deg and the camera "
      "height above ground as 10.59 model units - about 58 m once the scale calibration is "
      "applied. Note the manifest also records "
      "<code>heading_degenerate: true</code> - a single straight pass does not constrain "
      "heading. See the Exposed tier for how far to trust the vertical.",
      T_MEAS, "out/kolumvs3d/export/export_manifest.json"),

    Q("mechanism", "Why Delaunay plus graph cut for the surface?",
      "It produces a watertight, topologically sound surface from a noisy oriented point "
      "cloud without the blobbing that screened Poisson shows at pass edges, and the "
      "graph-cut labelling gives a principled inside/outside decision rather than a "
      "density threshold. Cost on Kolu: 80.4 s, under 4% of the run.",
      T_MEAS, "out/kolu_mvs/mvs_result.json"),

    Q("mechanism", "What is 'relief above local ground' and why measure that?",
      "Height above a per-cell locally fitted ground plane, taking the 5th percentile "
      "within each 1-unit cell as ground (about 5.5 m on the calibrated Kolu clip). It is the metric that <b>cannot be faked by noise</b>: "
      "buildings either have vertical extent or they are paint on a sheet. Point counts and "
      "small-scale roughness can both be gamed - a noisier cloud scores higher on roughness "
      "and a smoother one wins on point count - so relief is the discriminator.",
      T_MEAS, "src/analysis/compare_mvs.py"),

    Q("mechanism", "What is the '6 cm surface residual' figure?",
      "Fit a plane in a 6 cm ball around a query point and take the median absolute "
      "residual. Lower means a tighter, better-resolved surface. Baseline 1.38 cm against "
      "the rebuild's 0.76 cm on Kolu (<b>1.8x</b>), and 1.29 cm against 0.35 cm on the "
      "second clip (<b>3.6x</b>) - that pair is where the deck's '1.8-3.6x finer' comes "
      "from. Finest resolved residual at a 3 cm ball is 1.9 mm. These lengths are in the "
      "model's units; on Kolu, calibrated, the 6 cm ball is about 33 cm. The ratios do not "
      "depend on scale.",
      T_MEAS, "out/ppt/measure_kolu.json, measure_short.json"),

    Q("mechanism", "How are occluded surfaces handled?",
      "Bounded geometric closure only, and <b>every inferred face is tagged inferred</b>. "
      "A single pass cannot see behind a building; the honest options are to leave a hole "
      "or to close it and say so. We close it and say so. There is no generative "
      "hallucination of unseen geometry.",
      T_DES, "docs/02 §7"),

    Q("mechanism", "What about variable illumination and shadows across the pass?",
      "Two places. Keyframe scoring survives exposure ramps rather than rejecting a whole "
      "stretch of the pass as 'degraded', and per-vertex colour avoids atlas seams where "
      "exposure changes meet. Shadowed regions still lose photometric matching quality; "
      "that shows up as lower point density, not as invented surface.",
      T_MEAS, "docs/02 §4"),

    Q("mechanism", "What does the failure case look like?",
      "The same source video as our second clip, ingested over its whole 57 s instead of "
      "the single moving pass. Keyframing detected <b>2 shots</b> against 1, spread 45 "
      "keyframes over a 115 x 58 m footprint, and produced a flat sheet: relief-to-footprint "
      "ratio <b>0.037</b>, with 1.34% of points above local ground. It is on the gallery "
      "page. The fix was choosing the span, not changing the model, which is exactly why "
      "adaptive keyframing is a first-class stage.",
      T_MEAS, "out/yt3d/viewer_stats.json"),

    # --------------------------------------------------------- CHALLENGED
    Q("challenged", "Why MapAnything and not VGGT, which is better known?",
      "Technical merit first, licence second - the ordering matters. <b>Technically</b>: "
      "MapAnything outputs metric geometry natively (VGGT and Pi3 are scale-ambiguous, so "
      "metric scale has to be bolted on from GPS alone), and it accepts "
      "<code>intrinsics</code>, <code>camera_poses</code>, <code>depth_z</code> and "
      "<code>is_metric_scale</code> as first-class priors, which is precisely the injection "
      "point for GPS, IMU and barometric altitude. <b>Legally</b>: VGGT's acceptable-use "
      "policy bans \"Military, warfare, nuclear industries or applications, espionage\", "
      "which is disqualifying for an NTRO deliverable. If an examiner reads the licence "
      "differently, the architecture does not collapse - MapAnything still wins on merit.",
      T_MEAS, "docs/02 §2"),

    Q("challenged", "Is the Apache checkpoint weaker than the non-commercial one?",
      "Probably, and we say so rather than hiding it. The Apache checkpoint trains on six "
      "datasets against the CC-BY-NC checkpoint's thirteen. The plan is to benchmark both, "
      "use the NC weights only for internal ablation, and report the <b>Apache</b> "
      "configuration as the deployable system. Choosing the weaker-but-usable weights is "
      "the correct engineering call when the stronger ones cannot legally ship to this "
      "customer.",
      T_DES, "docs/02 §2"),

    Q("challenged", "OpenMVS is AGPL-3.0. How is that acceptable in a deliverable?",
      "It is invoked as a <b>separate, unmodified process</b> rather than linked, so the "
      "copyleft boundary is the process boundary. That is a defensible position, not a "
      "clever one, and we treat it as a debt: a BSD-licensed GPU replacement for that one "
      "stage is the clean long-term answer, and it happens to be the same stage a GPU would "
      "accelerate.",
      T_DES, "docs/02"),

    Q("challenged", "Why not just use a GPU and meet the time budget?",
      "We would, and the architecture adds one without becoming dependent on it. We could "
      "not: <b>every GPU path on the available GCP account auto-denies</b> with "
      "<code>NOT_ENOUGH_USAGE_HISTORY</code>, on both Compute Engine and Cloud Run, and "
      "asking for less does not help. So the CPU pipeline is not a preference, it is the "
      "only reproducible deployment we had - and it is what produced every number quoted "
      "anywhere in this project.",
      T_MEAS, "docs/06 §2-4"),

    Q("challenged", "You tried to parallelise across tasks. What happened?",
      "It came out <b>7% slower</b> than the single task it was meant to beat - 2,098 s "
      "against 1,963 s - and we publish that because the diagnosis is worth more than the "
      "idea was. Three compounding causes: overlapping windows turned 45 views into <b>77 "
      "view-slots, 1.71x the work</b>; 5 x 4 vCPU is slower per view than 1 x 8 vCPU "
      "because OpenMVS scales well inside a task; and the shards ran 719 s to 1,454 s, a 2x "
      "spread, while a parallel stage costs what its slowest shard costs. The geometry did "
      "concatenate correctly, which validated the underlying design.",
      T_MEAS, "docs/06 §7"),

    Q("challenged", "Why is processing pinned to an Indian region?",
      "India's Geospatial Data Guidelines (DST, 2021) require data at or finer than 1 m "
      "horizontal to be stored and processed within India. This PS targets ≤ 1 m, so the "
      "requirement binds. Everything runs in asia-south1. This also removed the only region "
      "that had the GPU we wanted, which is a real cost of the constraint rather than a "
      "convenient story.",
      T_MEAS, "docs/01, docs/06"),

    Q("challenged", "Your DEM ships with no CRS. Isn't that an incomplete deliverable?",
      "It is a deliberate refusal. The clip carries no GNSS, so any CRS we attached would be "
      "a guess, and a GeoTIFF with a plausible-looking wrong CRS is <b>worse than one with "
      "none</b> - downstream GIS will silently reproject it and the error becomes invisible. "
      "So the DSM ships with a real geotransform (in model units until the scale "
      "calibration reaches the files), "
      "<code>crs: null</code>, and <code>reason_no_crs: \"source clip has no GNSS\"</code> "
      "recorded in the manifest. Give us a GNSS-tagged clip and the CRS is populated.",
      T_MEAS, "out/kolumvs3d/export/export_manifest.json"),

    Q("challenged", "Neither test clip has GNSS. Wasn't that a poor choice of test data?",
      "It was the data we could get, and it constrains what we may claim - which we state "
      "rather than paper over. It is also not purely a loss: the PS says the dataset arrives "
      "at the event, so a pipeline that degrades cleanly to metric-relative when GNSS is "
      "absent is exercising a path it will genuinely need. What it costs us is the ability "
      "to demonstrate the ≤ 1 m absolute target at all.",
      T_OPEN, "docs/04 §5"),

    Q("challenged", "On one clip your rebuild covers less ground than the baseline. Explain.",
      "Correct, and it is on the gallery page rather than hidden. Kolu coverage is "
      "<b>136%</b> of the feed-forward baseline; the second clip is <b>83%</b>. Photometric "
      "MVS refuses surface it cannot match across three views, while the feed-forward model "
      "will happily invent it. Those are the same trade seen from two sides. The deck quotes "
      "the 136% figure, so the gallery carries the other half.",
      T_MEAS, "out/ppt/measure_short.json"),

    Q("challenged", "Why not align your model to the reference and report that error?",
      "Because alignment flatters, measurably. On a model with a real <b>2.68 m</b> offset, "
      "ICP alignment reports <b>0.21 m</b> - flattering by <b>12.8x</b>. Worse, "
      "Tanks-and-Temples aligns with scale enabled (7-DoF), so a model 5% too small can "
      "score 0.000 m there. Our harness prints the absolute and the aligned numbers side by "
      "side specifically so the aligned one can never be quoted as absolute by accident. "
      "ETH3D does no alignment and is the right analogue.",
      T_MEAS, "docs/04 §5"),

    Q("challenged", "Why Python 3.12 rather than 3.13?",
      "open3d has no 3.13 wheels and MapAnything specifies 3.12. A trivial-sounding pin that "
      "costs a day if discovered late.",
      T_MEAS, "docs/01 §9"),

    Q("challenged", "Would capturing differently have helped more than better code?",
      "Yes, and this is the uncomfortable one. Within the overflown corridor, a nadir camera "
      "sees <b>14.3%</b> of along-track facade against <b>52.0%</b> at 60 deg tilt - and 60 "
      "deg and 45 deg are <i>identical</i>, because forward tilt saturates. Cross-track "
      "facades need a wide field of view or a sideways tilt. Completeness is capped by "
      "capture geometry, not by the reconstruction code, and no amount of algorithm work "
      "recovers a surface the camera never saw.",
      T_MEAS, "docs/02"),

    # ------------------------------------------------------------ EXPOSED
    Q("exposed", "Do you meet the processing-time target?",
      "<b>No.</b> The target is 15 minutes for a 10-minute video. We take <b>34 min 39 s "
      "for 45 keyframes</b> on 8 vCPU with no GPU - already 2.3x over budget on a 25-second "
      "span. And it gets worse with length, not better: a 10-minute pass yields roughly 600 "
      "keyframes, about 13x our view count, and densification scales close to linearly, so a "
      "full-length clip is hours rather than minutes. Cloud Run caps at 8 vCPU, so scaling "
      "up inside Cloud Run is not available either. This is 20 of 100 marks and we do not "
      "have it.",
      T_OPEN, "out/kolu_mvs/mvs_result.json, docs/06 §5"),

    Q("exposed", "What is the route to meeting it, concretely?",
      "<b>77.3% of the run is one stage</b>, <code>DensifyPointCloud</code> at 1,593.9 s of "
      "2,061.8 s. That is the stage a GPU changes, and it is the same stage whose AGPL "
      "licence we want to replace, so one substitution addresses both. Beyond that: keyframe "
      "budgeting to cap view count independently of clip length, and a resolution ladder "
      "that returns a coarse result inside the budget and refines afterwards. None of that "
      "is built. Quoting a projected GPU speed-up would be inventing a number.",
      T_DES, "out/kolu_mvs/mvs_result.json"),

    Q("exposed", "Do you meet the ≤ 1 m spatial accuracy target?",
      "<b>Unvalidated - we cannot say.</b> Neither test clip carries GNSS, so absolute "
      "accuracy has not been demonstrated at all. Demonstrating it needs an RTK/PPK-tagged "
      "dataset with surveyed check points. This is 30 of 100 marks, the heaviest single "
      "criterion, and the honest position is that we have strong relative accuracy evidence "
      "and no absolute evidence.",
      T_OPEN, "docs/04 §5"),

    Q("exposed", "Then what accuracy claim are you actually permitted to make?",
      "This is written down in advance precisely so it cannot drift under deadline pressure. "
      "<b>If the supplied dataset carries RTK/PPK</b>: claim ≤ 1 m absolute, evidenced. "
      "<b>If it does not</b>: claim ≤ 1 m <i>relative/shape</i> accuracy and state the "
      "absolute georeferencing error separately and plainly. That is what \"metric accuracy "
      "without GCPs\" conventionally means and it is defensible. <b>Never</b> quote the "
      "ICP-aligned number as if it were absolute.",
      T_MEAS, "docs/04 §5"),

    Q("exposed", "What is the absolute error with ordinary consumer GPS?",
      "About <b>4.1 m</b>, against <b>0.097 m</b> with RTK. The part that hurts: the error "
      "is <b>flat from 50 to 2,400 keyframes</b>. The bias is correlated, so it does not "
      "average away with more data - you cannot fly longer to fix it. Without RTK/PPK, "
      "≤ 1 m absolute is not reachable, and that is a property of the sensor rather than of "
      "our pipeline.",
      T_MEAS, "docs/04 §5 (EXP-05)"),

    Q("exposed", "How much do you trust the '30-50 cm' effective-resolution figure?",
      "The <b>ratio of 14 is solid</b> - it is scale-free, confirmed three ways, with the "
      "competing hypothesis tested and rejected. <b>The centimetres were wrong.</b> They came "
      "from <code>metric_scaling_factor</code>, checked only against a plausibility band "
      "(implied camera speeds of 1.6-3.0 m/s, altitudes of 6.4-11.4 m), and that band passed "
      "a 5.5x error. Calibrated, Kolu's 51.2 cm patch is about 2.7-3.0 m on the ground - "
      "so the feed-forward geometry alone misses the 1 m target even in relative terms, "
      "which is the case for the MVS stage. The Village figures have no ruler yet.",
      T_MEAS, "docs/05 §2, docs/08"),

    Q("exposed", "Your measurements were wrong. By how much, and how do you know now?",
      "By <b>5.3–5.8x</b> on Kolu - distances read far too short. A teammate measured the "
      "road-to-bridge distance and knew it could not be that low; they were right. We then "
      "measured the model against things of published size: <b>lane width</b> (0.650 model "
      "units against 3.5–3.75 m) and the <b>ecoduct's waist</b> (3.95 against 21–22 m). "
      "Both give the same factor. A third check is a floor: Estonian road norms require "
      "<b>5.0 m</b> of clearance under an overpass, the arch crown reads 1.30 model units, "
      "so the factor is at least 3.85 - a simple 2x fix would leave a 2.6 m underpass. The "
      "viewer now applies x5.54 on Kolu. The factor is a property of one run, so it is "
      "never applied to another clip.",
      T_MEAS, "docs/08-measurement-validation.md, research/calibration/kolu.json"),

    Q("exposed", "Is the vertical direction trustworthy?",
      "To about two degrees, and that is now checked rather than assumed. We once reported "
      "a 40-57 deg disagreement; that compared two quantities that are not both verticals, "
      "and it was withdrawn. The check that holds: a gimballed camera keeps roll near zero, "
      "so the ground-plane vertical must leave every camera's right axis horizontal. It "
      "does, to 0.21-0.68 deg median, and the two estimates agree to 1.7-2.5 deg. What "
      "stays weak is heading: the manifest records <code>heading_degenerate: true</code>, "
      "because a single straight pass does not constrain it. Telemetry - DJI SRT gimbal "
      "pitch - would close that.",
      T_MEAS, "docs/05 §6, src/pipeline/gravity.py"),

    Q("exposed", "Your own documents quote 1,963 s and 2,078.7 s for the same clip. Which is it?",
      "Both are real and they are on different bases; they have not been reconciled, and "
      "that is recorded rather than quietly resolved. The deck and the demo use "
      "<b>2,078.7 s</b> (34 min 39 s), which is <code>total_seconds</code> from the run's "
      "own <code>mvs_result.json</code> - the same run that produced every other number we "
      "quote, and the <i>slower</i> of the two, so it errs conservatively. The 1,963 s figure "
      "in docs/05 §9 and docs/06 comes from a different job. No conclusion moves either way: "
      "both are far outside a 15-minute budget.",
      T_OPEN, "docs/07 §7"),

    Q("exposed", "Would more keyframes improve accuracy?",
      "Density and accuracy are separate levers, which we measured. On the same clip and "
      "model, a dense 16 s window against the full 57 s pass lifted median model confidence "
      "from 1.03 to 50.56 and density by 4.5x, and changed <b>effective resolution not at "
      "all</b>. More coverage buys completeness and confidence; it does not buy detail, "
      "because the patch grid is unchanged. Separately, GNSS bias is flat from 50 to 2,400 "
      "keyframes, so more frames do not buy absolute accuracy either.",
      T_MEAS, "docs/05 §4"),

    Q("exposed", "What happens if the event dataset is 4K, or a drone you have not seen?",
      "Ingest is built for exactly that - auto-detection of container, resolution, frame "
      "rate, and any SRT/CSV/EXIF/flight-log sidecar, with intrinsics self-calibration when "
      "absent. What we have <b>actually run</b> is two clips, 1920x1080 and 1080x1920, both "
      "without GNSS. 4K, RTK-tagged input and DJI SRT telemetry are handled by design and "
      "have <b>not been exercised end to end</b>. Higher resolution also raises "
      "densification cost, which is already the failing stage.",
      T_DES, "docs/01 §3"),

    Q("exposed", "What is the single biggest risk to this project?",
      "That the event dataset is a full-length 10-minute clip with RTK. That is the good "
      "case for accuracy - it is the only way we could demonstrate ≤ 1 m - and "
      "simultaneously the worst case for speed, because 600 keyframes on CPU is hours. We "
      "would produce a defensible accuracy number and miss the time budget by an order of "
      "magnitude. The mitigation is the degradation ladder: return a coarse, labelled, "
      "partial result inside the budget rather than nothing.",
      T_DES, "docs/02 §11"),

    Q("exposed", "What have you designed but not built?",
      "Named plainly: GPU densification; keyframe budgeting to decouple cost from clip "
      "length; the resolution ladder and degradation behaviour under a hard deadline; "
      "georeferencing validated against surveyed check points; RTK/PPK ingestion exercised "
      "end to end; inferred-face tagging carried through every export format; and the "
      "BSD-licensed replacement for the AGPL densification stage. The pipeline runs end to "
      "end on two real clips today - that is the extent of what is measured.",
      T_DES, "docs/02, docs/03"),

    Q("exposed", "If we gave you two more weeks, what would you do first?",
      "Acquire one RTK/PPK-tagged clip with surveyed check points and run the accuracy "
      "validation. It converts the heaviest criterion (30 marks) from unvalidated to "
      "evidenced, and it is the only item on the list we cannot substitute effort for - "
      "everything else is engineering we know how to do, while this one needs data we do "
      "not have. Speed work is second, because the route there is already identified and "
      "bounded by that single 77.3% stage.",
      T_DES, "docs/03 §7"),
]


# ------------------------------------------------------------------ render
CSS = """__DS_CSS__
/* ---------------------------------------------------------------------------
   Q&A-SPECIFIC LAYOUT. Everything above is tools/design_system.css (BASE layer
   only - this page has no WebGL canvas, so it ships none of the viewer chrome).
   --------------------------------------------------------------------------- */

body{line-height:var(--lh-body)}

/* Sticky header: the site bar, plus a second row of search and filters. The
   filters have to stay reachable while scrolling 52 answers. */
.top{position:sticky; top:0; z-index:var(--z-nav); background:var(--bg);
     border-bottom:1px solid var(--line)}
.top .topbar{position:static; border-bottom:0; padding-bottom:0}
.tools{display:flex; gap:var(--sp-2); padding:var(--sp-3) var(--sp-5) var(--sp-4);
       flex-wrap:wrap; align-items:center}
.tools .input{flex:1; min-width:180px; max-width:340px}
.count{font-size:var(--t-xs); color:var(--fg-3); margin-left:auto; font-family:var(--mono)}

.wrap{max-width:860px; padding:var(--sp-6) var(--sp-5) var(--sp-8)}
.lede{margin:0 0 var(--sp-6)}
.lede b{color:var(--fg); font-weight:600}

/* Tier heading. The dots encode exposure, 1 to 4 - this page is sorted by how
   exposed we are when asked, not by how technical the topic is. */
.tier{margin:var(--sp-7) 0 var(--sp-4); border-top:1px solid var(--line-2); padding-top:var(--sp-5)}
.tier:first-of-type{margin-top:var(--sp-3); border-top:0; padding-top:0}
.tier h2{font-size:var(--t-lg); margin:0; display:flex; align-items:center; gap:var(--sp-3)}
.tier .dots{display:inline-flex; gap:2px}
.tier .dots i{width:6px; height:6px; border-radius:var(--r-sm); background:var(--line-2)}
.tier .dots i.on{background:var(--accent)}
.tier p{font-size:var(--t-sm); color:var(--fg-3); margin:var(--sp-2) 0 0}

/* One question. The whole header is the button, so it is a large target on a
   projector and reachable by keyboard in one tab stop. */
.qa{border:1px solid var(--line); border-radius:var(--r-md); margin:var(--sp-2) 0;
    background:var(--s1); overflow:hidden}
.qa.hide{display:none}
.qa.on{border-color:var(--line-2)}
.q{display:flex; gap:var(--sp-4); align-items:flex-start;
   padding:var(--sp-4); cursor:pointer; width:100%; text-align:left;
   background:none; border:0; color:inherit; font:inherit;
   transition:background var(--dur-1) var(--ease)}
.q:hover{background:var(--s2)}
.q .n{font-family:var(--mono); font-size:var(--t-xs); color:var(--fg-3);
      flex:none; padding-top:2px; min-width:20px}
.q .t{flex:1; font-size:var(--t-md); font-weight:600}
.q .chip{flex:none; margin-top:2px}

.a{display:none; padding:0 var(--sp-4) var(--sp-4) var(--sp-8);
   font-size:var(--t-md); color:var(--fg-2)}
.qa.on .a{display:block}
.a b{color:var(--fg); font-weight:600}
.a code{font-family:var(--mono); font-size:var(--t-sm); color:var(--accent);
        background:color-mix(in srgb,var(--accent) 9%,transparent);
        padding:1px var(--sp-1); border-radius:var(--r-sm)}

/* Provenance tags. The names are semantic, not decorative - they are the
   vocabulary from docs/architecture-prompt.md and the filter buttons key off
   them - so they keep their own names and borrow the chip's shape. */
.chip.measured{color:var(--ok);     border-color:color-mix(in srgb,var(--ok) 45%,transparent)}
.chip.designed{color:var(--accent); border-color:color-mix(in srgb,var(--accent) 45%,transparent)}
.chip.open{color:var(--bad);        border-color:color-mix(in srgb,var(--bad) 45%,transparent)}

/* Source citation was --faint at 2.91:1, i.e. below AA and effectively
   invisible on a projector - on the one line that carries the page's whole
   traceability claim. It is --fg-3 (5.26:1) now. */
.src{display:block; margin-top:var(--sp-3)}
.src::before{content:"source  "; color:var(--line-2)}

.none{display:none; color:var(--fg-3); font-size:var(--t-md); padding:var(--sp-6) 0}
.none.on{display:block}
footer{max-width:860px; margin:0 auto; padding:0 var(--sp-5) var(--sp-8);
       font-size:var(--t-sm); color:var(--fg-3); line-height:1.7}
footer a{color:var(--fg-2)}

@media (max-width:620px){
  .wrap{padding:var(--sp-5) var(--sp-4) var(--sp-7)}
  .tools{padding:var(--sp-3) var(--sp-4) var(--sp-4)}
  .a{padding-left:var(--sp-4)}
  .q .chip{display:none}
}

/* Print. Deliberately NOT on the dark palette: this prints to white paper, so
   it is the one place the screen tokens are the wrong answer. The design audit
   exempts this block for exactly that reason. */
@media print{
  .top,.tools,footer{display:none}
  body{background:#fff; color:#000; font-size:10.5pt}
  .wrap{max-width:none; padding:0}
  .qa{border:0; border-bottom:1px solid #bbb; border-radius:0; background:none;
      break-inside:avoid; page-break-inside:avoid; margin:0}
  .qa .a{display:block !important; color:#222; padding:0 0 9pt 26pt}
  .q{padding:9pt 0 4pt}
  .q .t{font-weight:700}
  .a b{color:#000}
  .a code{color:#000; background:#eee}
  .src{color:#666}
  .chip{color:#000 !important; border-color:#999 !important}
  .tier h2{font-size:12pt}
  .tier p{color:#444}
  .lede{color:#222}
  h1{font-size:14pt}
}
"""

JS = """
var qas=[].slice.call(document.querySelectorAll('.qa'));
qas.forEach(function(el){
  el.querySelector('.q').onclick=function(){el.classList.toggle('on');};
});
function setAll(on){qas.forEach(function(e){e.classList.toggle('on',on);});}
document.getElementById('xall').onclick=function(){setAll(true);};
document.getElementById('call').onclick=function(){setAll(false);};
var filt='', tagf='';
function apply(){
  var n=0;
  qas.forEach(function(e){
    var okT=!tagf||e.dataset.tag===tagf;
    var okQ=!filt||e.textContent.toLowerCase().indexOf(filt)>=0;
    var show=okT&&okQ;
    e.classList.toggle('hide',!show);
    if(show)n++;
  });
  document.querySelectorAll('.tier').forEach(function(t){
    var any=false,s=t.nextElementSibling;
    while(s&&s.classList.contains('qa')){if(!s.classList.contains('hide'))any=true;
      s=s.nextElementSibling;}
    t.style.display=any?'':'none';
  });
  document.getElementById('cnt').textContent=n+' of '+qas.length;
  document.getElementById('none').classList.toggle('on',n===0);
}
document.getElementById('s').addEventListener('input',function(e){
  filt=e.target.value.toLowerCase().trim();
  if(filt)setAll(true);
  apply();
});
document.querySelectorAll('[data-tagf]').forEach(function(b){
  b.onclick=function(){
    tagf = tagf===b.dataset.tagf ? '' : b.dataset.tagf;
    document.querySelectorAll('[data-tagf]').forEach(function(x){
      x.setAttribute('aria-pressed', String(x.dataset.tagf===tagf));});
    apply();
  };
});
document.addEventListener('keydown',function(e){
  if(e.key==='/'&&document.activeElement.id!=='s'){e.preventDefault();
    document.getElementById('s').focus();}
  if(e.key==='Escape'){document.getElementById('s').value='';filt='';apply();
    document.getElementById('s').blur();}
});
apply();
"""

PAGE = """<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<meta name="description" content="__DESC__">
<meta name="robots" content="noindex, nofollow">
<meta property="og:type" content="website">
<meta property="og:title" content="__TITLE__">
<meta property="og:description" content="__DESC__">
<meta property="og:image" content="__OG__">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' fill='%2306080a'/><path d='M16 4 28 26 4 26Z' fill='none' stroke='%23e8a84a' stroke-width='2.5' stroke-linejoin='round'/><path d='M16 4V26M9 15h14' stroke='%23e8a84a' stroke-width='1.2' opacity='.7'/></svg>">
<style>__CSS__</style>

<div class="top">
  <div class="topbar">
    <div class="brand">
      <span class="nm">Questions, ordered by how exposed we are</span>
      <span class="tag">SIH26158 &middot; NTRO</span>
    </div>
    <nav class="sitenav" aria-label="Pages">
      <a href="../index.html">Walkthrough</a>
      <a href="../gallery/index.html">Gallery</a>
      <a href="index.html" aria-current="page">Q&amp;A</a>
    </nav>
  </div>
  <div class="tools">
    <input class="input" type="search" id="s"
           aria-label="Search questions and answers"
           placeholder="search questions and answers   ( / )">
    <button class="btn btn--sm" id="xall">expand all</button>
    <button class="btn btn--sm" id="call">collapse all</button>
    <button class="btn btn--sm" data-tagf="measured" aria-pressed="false">measured</button>
    <button class="btn btn--sm" data-tagf="designed" aria-pressed="false">designed</button>
    <button class="btn btn--sm" data-tagf="open" aria-pressed="false">open</button>
    <span class="count" id="cnt"></span>
  </div>
</div>

<div class="wrap">
  <p class="lede">__COUNT__ questions, sorted by <b>how exposed we are when asked</b>,
  not by how technical the topic is. Those two axes come apart here: "what is your
  processing time?" is a trivial question with a brutal answer, and "why patch-14 rather
  than the 518 px cap?" is a deep question with an easy one. Sorting by topic would bury
  the two questions that can actually sink a viva.
  Every answer is tagged <b class="chip measured">measured</b>,
  <b class="chip designed">designed</b> (built on paper, not in
  code) or <b class="chip open">open</b> (we do not know), and
  cites the file it comes from. Where the honest answer is "unmeasured", it says so
  instead of a paragraph that reads like an answer.</p>
__BODY__
  <p class="none" id="none">No question matches that.</p>
</div>
<footer>
  __FOOTER__
</footer>
<script>__JS__</script>
"""


def render():
    body, n = [], 0
    for i, (key, name, blurb) in enumerate(TIERS):
        dots = "".join(f'<i class="{"on" if j <= i else ""}"></i>' for j in range(4))
        body.append(f'  <div class="tier"><h2><span class="dots">{dots}</span>'
                    f'{_html.escape(name)}</h2><p>{_html.escape(blurb)}</p></div>')
        for item in [x for x in QA if x["tier"] == key]:
            n += 1
            body.append(
                f'  <div class="qa" data-tag="{item["tag"]}">'
                f'<button class="q"><span class="n">{n:02d}</span>'
                f'<span class="t">{_html.escape(item["q"])}</span>'
                f'<span class="chip {item["tag"]}">{item["tagl"]}</span></button>'
                f'<div class="a">{item["a"]}'
                f'<span class="src">{_html.escape(item["src"])}</span></div></div>')

    foot = ('Companion pages: <a href="../">the pipeline demo</a> and '
            '<a href="../gallery/">the reconstruction gallery</a>. '
            'Every figure on this page is traceable to a file in the repository; the '
            'build script re-checks the headline numbers against their sources on each '
            'run. Press <b>/</b> to search, <b>Esc</b> to clear. This page prints with '
            'every answer expanded.')
    title = "SIH26158 - technical Q&A"
    desc = (f"{n} questions on the single-pass drone-video-to-3D pipeline, ordered by how "
            f"exposed the answer is, each tagged measured / designed / open and cited to "
            f"the file it comes from.")
    return (PAGE.replace("__CSS__", CSS.replace("__DS_CSS__", ds_css("base")))
                .replace("__JS__", JS)
                .replace("__BODY__", "\n".join(body))
                .replace("__COUNT__", str(n))
                .replace("__FOOTER__", foot)
                .replace("__TITLE__", title)
                .replace("__DESC__", desc)
                .replace("__OG__", f"{SITE}/assets/og.jpg")), n


# ------------------------------------------------------- verify the figures
CHECKS = [
    # (needle to find, file to find it in)
    ("3837.5", "out/kf_kolu/ingest.json"),
    ("1562", "out/kf_kolu/ingest.json"),
    ("787", "out/kf_kolu/ingest.json"),
    ("529", "out/kf_kolu/ingest.json"),
    ("356", "out/kf_kolu/ingest.json"),
    ("1.730119", "out/kolu_mvs/mvs_result.json"),
    ("0.365727", "out/kolu_mvs/mvs_result.json"),
    ("1.525251", "out/ytd_mvs/mvs_result.json"),
    ("0.414378", "out/ytd_mvs/mvs_result.json"),
    ("0.2214", "out/kolu_mvs/mvs_result.json"),
    ("2078.7", "out/kolu_mvs/mvs_result.json"),
    ("1593.9", "out/kolu_mvs/mvs_result.json"),
    ("323.1", "out/kolu_mvs/mvs_result.json"),
    ("80.4", "out/kolu_mvs/mvs_result.json"),
    ("76918", "out/kolu_mvs/mvs_result.json"),
    ("334057", "out/kolu_mvs/mvs_result.json"),
    ("3,445,735", "out/kolumvs3d/viewer_stats.json"),
    ("1,952,962", "out/kolumvs3d/viewer_stats.json"),
    ("0.24", "out/kolumvs3d/export/export_manifest.json"),
    ("10.59", "out/kolumvs3d/export/export_manifest.json"),
    ("heading_degenerate", "out/kolumvs3d/export/export_manifest.json"),
    ("source clip has no GNSS", "out/kolumvs3d/export/export_manifest.json"),
    ("2.3297", "out/ppt/measure_kolu.json"),
    ("3.5818", "out/ppt/measure_kolu.json"),
    ("1.3817", "out/ppt/measure_kolu.json"),
    ("1.3582", "out/ppt/measure_kolu.json"),
    ("1.2877", "out/ppt/measure_short.json"),
    ("0.3533", "out/ppt/measure_short.json"),
    ("0.8268", "out/ppt/measure_short.json"),
    ("0.1875", "out/ppt/measure_short.json"),
    ("0.037", "out/yt3d/viewer_stats.json"),
    ("1.34%", "out/yt3d/viewer_stats.json"),
    # prose sources
    ("4.1 m", "docs/04-test-plan.md"),
    ("0.097", "docs/04-test-plan.md"),
    ("2400 keyframes", "docs/04-test-plan.md"),
    ("2.68 m", "docs/04-test-plan.md"),
    ("12.8", "docs/04-test-plan.md"),
    ("30-50 cm", "docs/05-quality-analysis.md"),
    ("2.2 cm", "docs/05-quality-analysis.md"),
    ("patch size 14", "docs/05-quality-analysis.md"),
    ("518 / 14 = 37", "docs/05-quality-analysis.md"),
    ("30.2 cm", "docs/05-quality-analysis.md"),
    ("51.2 cm", "docs/05-quality-analysis.md"),
    ("1.6-3.0 m/s", "docs/05-quality-analysis.md"),
    ("6.4-11.4 m", "docs/05-quality-analysis.md"),
    ("5.3–5.8", "docs/08-measurement-validation.md"),
    ("0.650", "docs/08-measurement-validation.md"),
    ("21–22 m", "docs/08-measurement-validation.md"),
    ('"factor": 5.54', "research/calibration/kolu.json"),
    ('"implies_factor_at_least": 3.85', "research/calibration/kolu.json"),
    ("kõrgusgabariit 5,0 m", "docs/08-measurement-validation.md"),
    ("0.21, 0.68 and 0.23 degrees", "docs/05-quality-analysis.md"),
    ("1.66, 2.14 and 2.47 degrees", "docs/05-quality-analysis.md"),
    ("50.56", "docs/05-quality-analysis.md"),
    ("2098", "docs/06-gcp-deployment.md"),
    ("1963", "docs/06-gcp-deployment.md"),
    ("77 view-slots", "docs/06-gcp-deployment.md"),
    ("1454", "docs/06-gcp-deployment.md"),
    ("719", "docs/06-gcp-deployment.md"),
    ("NOT_ENOUGH_USAGE_HISTORY", "docs/06-gcp-deployment.md"),
    ("Apache-2.0", "docs/02-architecture.md"),
    ("espionage", "docs/02-architecture.md"),
]


def check_numbers():
    cache, bad = {}, []
    for needle, rel in CHECKS:
        p = os.path.join(ROOT, rel)
        if p not in cache:
            if not os.path.exists(p):
                bad.append((needle, rel, "FILE MISSING"))
                cache[p] = ""
                continue
            with io.open(p, encoding="utf-8", errors="replace") as f:
                cache[p] = f.read()
        if needle not in cache[p]:
            bad.append((needle, rel, "not found"))
    return bad


def main():
    html, n = render()
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, "index.html")
    with io.open(out, "w", encoding="utf-8") as f:
        f.write(html)

    by_tier = {k: sum(1 for x in QA if x["tier"] == k) for k, _, _ in TIERS}
    by_tag = {}
    for x in QA:
        by_tag[x["tag"]] = by_tag.get(x["tag"], 0) + 1
    print(f"  questions  {n}   " + "  ".join(f"{k}:{v}" for k, v in by_tier.items()))
    print(f"  provenance " + "  ".join(f"{k}:{v}" for k, v in sorted(by_tag.items())))

    bad = check_numbers()
    if bad:
        print(f"\n  !! {len(bad)} headline figure(s) NOT found in their cited source:")
        for needle, rel, why in bad:
            print(f"       {needle!r:28} {rel}  ({why})")
        sys.exit(1)
    print(f"  figures    all {len(CHECKS)} headline values verified against their sources")
    print(f"  -> {out}  {os.path.getsize(out)/1e3:.0f} KB")


if __name__ == "__main__":
    main()
