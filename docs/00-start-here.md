# Start here

The narrative introduction to SIH26158. It exists because the suite has nineteen documents
and a newcomer needs the argument before the reference: what the problem is, why the obvious
solutions fail, what has actually been measured, and what is still open. Read this once, then
use [`README.md`](README.md) as the index it is.

Every figure below names the document it comes from. Where this file and a numbered document
disagree, the numbered document wins, and the disagreement is a bug to report.

---

## 1. The product in one page

One drone video. One flight pass. No second flight, no ground control points, no survey grid.
Out comes a 3D model of the scene that is georeferenced (it knows where on Earth it is) and
metrically accurate (a metre in the model is a metre on the ground), in under fifteen minutes.

The customer is the National Technical Research Organisation, India's technical intelligence
agency. The problem statement names border and strategic area mapping, military reconnaissance
and mission planning, and rapid damage assessment as the applications (`01` §2).

The name of the thing is **Tesseract**. The pipeline is `src/tesseract/`; the console is at
[tesseract-demo.vercel.app/console/](https://tesseract-demo.vercel.app/console/).

Why this is still an open problem: every photogrammetry product on the market is built
around *planned* capture. Pix4D asks for 75% frontal and 60% side overlap, and
85% frontal for a single corridor (`11` §1). Skydio's 3D Scan plans extra views around a
structure. This problem statement is the opposite case: one pass, flown when it could be
flown, over a target that may not permit a second visit. Nobody ships a product whose design
centre is the unplanned single pass with consumer telemetry, run on sovereign infrastructure,
under licences a defence customer can accept.

---

## 2. The problem statement, as given

### 2.1 A warning about the source

The sih.gov.in listing for this problem statement contains the literal editorial placeholder
*"Add 'Desired Output' and 'Evaluation Criteria' table here"*. The portal text is incomplete.
The binding numbers exist only in the linked Drive PDF, three pages, no text layer, a
print-to-PDF of a Google Doc that has to be read as images. It is kept here as
`docs/SIH26158.pdf`.

Any team working from the portal alone does not know the accuracy, time or format targets
(`01` §1.1). Every requirement in `01` is traced to that PDF, and anything not traceable is
marked as an assumption in `01` §8.

### 2.2 The six hard targets

From PDF p.38, "Desired Output". These are pass or fail (`01` §4.1).

| ID | Parameter | Target |
|---|---|---|
| R-O1 | Reconstruction type | 3D mesh or point cloud |
| R-O2 | Processing time | under 15 min for a 10-min video |
| R-O3 | Spatial accuracy | 1 m or better |
| R-O4 | Coverage | the entire visible scene |
| R-O5 | Output formats | OBJ, PLY, LAS, GeoTIFF, glTF/GLB, FBX |
| R-O6 | Visualisation | a web or desktop viewer |

Derived from the Description paragraph and non-negotiable: the model must be georeferenced
and metrically accurate. R-O3 is an absolute world-frame requirement, not a self-consistent
shape. `01` §7.2 calls this the single most common way to fail this problem statement while
appearing to pass it.

### 2.3 The scoring function

From PDF p.38, "Evaluation Criteria" (`01` §5).

| Criterion | Weight |
|---|---|
| Reconstruction accuracy | 30% |
| Model completeness | 20% |
| Processing speed | 20% |
| Innovation | 15% |
| Scalability | 10% |
| User interface | 5% |

Accuracy, completeness and speed are 70% of the score, and all three can be measured
objectively. The remaining 30% is subjective. The strategy that follows is to instrument the
measurable 70% and spend proportionate effort on the rest. The user interface is 5%: it has to
exist and it must not become the project.

### 2.4 The nine key challenges

PDF pp.37-38 lists eight; `01` §6 restates them as testable requirements R-C1 to R-C8 and adds
R-C9, which the team found rather than inherited.

R-C1 limited viewing angles. R-C2 motion blur and compression. R-C3 variable illumination.
R-C4 dynamic objects. R-C5 GPS noise. R-C6 near-real-time. R-C7 occluded surfaces. R-C8 metric
accuracy without ground control points. R-C9 input admissibility: measure whether a clip can be
reconstructed *before* spending inference on it, and say why when it cannot.

R-C7 carries a deliberate scope bound. Generative completion of unseen 3D surface is an open
research problem and does not fit the time budget. This system closes occluded surfaces by
geometric inference, footprint extrusion and planar continuation, and tags every such face as
inferred. A bounded labelled answer is worth more than an oversold one when innovation is 15%
and accuracy is 30%.

### 2.5 Out of scope, explicitly

Multi-pass capture, flight planning, re-flight. On-board processing. Reconstruction of scene
content that was never observed and cannot be inferred from context (`01` §1.2).

---

## 3. Who this is for, and what changes for them

Four stakeholders, from `01` §2.

NTRO gets border and strategic area mapping, reconnaissance and rapid damage assessment from
footage that already exists, without commissioning a survey flight. The operational value is
in the cases where a second pass is not available: contested airspace, a fast-moving situation,
a target that would notice the aircraft coming back.

The UAV operator flies once with minimal effort and no ground control point survey. Everything
a survey pipeline normally demands, overlap planning, marked targets, a return flight, is
removed from their job.

The analyst gets a model they can measure distances, areas and heights in, inspect, and export
to GIS in the six formats the problem statement lists.

SIH evaluators get a system that scores against the six weighted criteria, and a per-run report
that states which targets were met, which were not, and which could not be measured on the clip
supplied.

The gap in the market is the same for all four (`11` §1): incumbent photogrammetry assumes that
a bad result means reflowing the mission. Here there is no second flight, so the product has to
say *why* a clip is weak before it spends compute on it, which is what stage S0 does.

---

## 4. Seven findings that shape the design

Each of these was measured or read from a primary source, and each changed a decision. They
are the fastest route to understanding why the architecture looks the way it does.

### 4.1 The obvious model is licensed out of this job

VGGT (Meta) is the strongest known feed-forward model for this exact task. Its Acceptable Use
Policy prohibits *"Military, warfare, nuclear industries or applications, espionage, use for
materials or activities that are subject to the International Traffic Arms Regulations"*, and
this applies to both checkpoints; the July 2025 relicensing is explicitly "commercial use, with
the exception of military applications" (`01` §7.1).

The customer is an intelligence agency and the problem statement names military reconnaissance.
VGGT is therefore disqualified. MapAnything replaces it and wins on technical merit as well: it
is Apache-2.0 throughout, it is metric by design where VGGT is scale-ambiguous, and it accepts
`intrinsics`, `camera_poses`, `depth_z` and `is_metric_scale` as first-class priors (`02` §2).
The full verified register is `11` §5. See ADR-002.

### 4.2 Classical photogrammetry cannot be the spine

A 10-minute 4K video is roughly 18,000 frames and about 600 keyframes. EXP-01 measured the
classical front end's dominant costs on real image data (`02` §1.1):

| | 1080p | 4K |
|---|---|---|
| Feature extraction, 600 frames | 186 s | 1,073 s |
| Exhaustive matching, 179,700 pairs | 10.3 h | 13.7 h |
| Sequential matching, 12 neighbours | 1,485 s | 1,980 s |
| Front end alone | 186% of budget | 339% of budget |

Two conclusions survive the "a GPU would be faster" objection, because they are about shape
rather than constant factors. 600 keyframes is 179,700 pairs, which is hours on any hardware.
And even sequential matching consumes more than the whole budget before structure-from-motion
starts. ADR-001.

### 4.3 A single straight pass is geometrically degenerate

This is the most consequential result in the project. Near-collinear camera centres cannot
constrain rotation about the flight axis, so an unrestricted 7-DOF similarity fit nails the
trajectory and throws the scene hundreds of metres (EXP-09, root `README.md`):

| | trajectory error | scene error |
|---|---|---|
| Straight pass, full 7-DOF | 3.9 m | 311 m |
| Straight pass, yaw-only | 3.5 m | 3.7 m |
| RTK, full 7-DOF | 0.042 m | 267 m |
| RTK, yaw-only | 0.038 m | 0.041 m |

Centimetre GPS buys nothing against this, because the error lives in a direction the data does
not constrain. Error grows with distance from the flight line, 216 m to 725 m across the tested
range. The consequence is that "IMU: optional" in the problem statement is misleading: for a
single straight pass a vertical reference is required, or the problem is under-determined.
ADR-008 fixes the fit at 5 degrees of freedom, yaw plus translation plus scale, in local ENU.

### 4.4 One metre absolute is unreachable from consumer GPS

EXP-05 measured about 4.1 m absolute error from consumer GNSS, and that error is *flat* from 50
to 2400 keyframes where 1/sqrt(N) would predict 3.9 m falling to 0.6 m. The correlated GNSS bias
does not average away. RTK reaches 0.097 m (root `README.md`, `11` §6).

So R-O3 at 1 m is achievable with RTK or PPK and is not achievable without. The project reports
that rather than hiding it. Whether the finale dataset carries RTK is open question 1 to the
organisers.

### 4.5 Facades cap completeness, and the lever is capture, not code

EXP-08 measured what a single pass can physically see. Within the overflown corridor, a nadir
pass sees 14.3% of along-track facade and a 60 degree tilt sees 52.0%. A 60 degree and a 45
degree tilt are identical, because forward tilt saturates. A sideways tilt or a wider lens buys
more than any model choice (root `README.md`).

This is why completeness is reported against two denominators, the observable surface and the
whole scene (ADR-022). Reporting only the whole scene penalises physics; reporting only the
observable hides a real limit.

### 4.6 Indian law decides where this can run

The DST Guidelines for acquiring and producing Geospatial Data and Geospatial Data Services
(15 February 2021) set a threshold of 1 m horizontal and 3 m vertical. Data finer than that may
be created and owned only by Indian entities, and must be stored and processed in India (`01`
§7.3).

This problem statement targets 1 m or finer, so the rule is assumed to bind. Compute is pinned
to GCP `asia-south1` or `asia-south2`, or the Baramati cluster. That excludes
`asia-southeast1`, which was the only region where Cloud Run L4 GPUs were reachable for this
project. ADR-010.

### 4.7 Two silent ways to lose the vertical budget

GNSS altitude is ellipsoidal; maps and DSMs are orthometric. Geoid separation across India runs
from -24.3 m at Leh to -98.2 m at Kanyakumari, and choosing EGM96 instead of EGM2008 shifts the
answer by 1.68 m at Amritsar, which exceeds the whole requirement on its own. PROJ returns the
height unchanged and raises nothing when the grid is missing, so the failure is silent
(root `README.md`, ADR-008).

Separately, UTM is not a metric frame. It carries about 0.6 m/km of scale error across India, so
the georeferencing fit is done in local ENU and projected to UTM last.

---

## 5. How it works

### 5.1 The decision that determines everything

R-O2 gives 900 seconds of wall clock for a 10-minute video (`02` §1). That number eliminates
full classical photogrammetry (measured in hours, §4.2) and per-scene neural training such as
NeRF or Gaussian splatting (per-scene optimisation plus mesh extraction spends the budget
twice).

What is left, and what was selected: a learned feed-forward multi-view model on the spine, with
classical photogrammetry demoted to the refinement and export tail where it is fast and
unmatched.

### 5.2 The amendment that matters

ADR-001 put a feed-forward model on the spine. ADR-004 amended it: the model keeps the poses and
the metric prior, and its *geometry* is discarded.

The reason is in `05`. MapAnything encodes with DINOv2 at ViT patch size 14 and decodes with a
DPT head, so geometry is predicted per patch and interpolated smoothly inside it. The pipeline
samples the ground at 2.2 cm and carries geometric information at 14 pixels, a gap of about 14x
that no downstream tuning can close. The test that proves it: take the real depth field, destroy
everything below one 14-pixel patch by downsampling, put it back with a smooth interpolant, and
the control reproduces the measured roughness to within 10%. A competing hypothesis, a plane
fitted to a curved surface, predicts growth as the square of the window and was rejected against
a control (`05` §1a).

So the geometry comes from full-resolution per-pixel photometric MVS, driven by the model's
poses. Measured on two clips: 1.8 to 3.6x finer surface at matched radius, and the vertical
ceiling broken, from 0.000% of points above 1.5 m to 0.902% where buildings are visibly 3 to 4 m
tall (`05` §8-9).

### 5.3 The stages

```
S0  screen        admissibility: horizon, sky, shot continuity, burned-in overlay
S1  ingest        decode, crop, shot detection, telemetry, keyframes
S2  plan          pose set (~600 views) and dense set (~150-300), separately
S3  geometry      MapAnything Apache: cameras, intrinsics, metric prior
S3b bundle adjust COLMAP triangulate + bundle_adjuster, CPU
S4  dense         OpenMVS DensifyPointCloud, then Delaunay mesh
    scale         GNSS, else known object, else witness, else unvalidated
S5  georeference  5-DOF fit in local ENU, EGM2008, project to UTM last
S5b level         F4 to F5: gravity rotation and calibration, applied once
S6  export        seven files, one frame
S7  score         the evaluation harness
S8  verdict       the six targets, three-valued
```

Full I/O contracts per stage are `09` §3. The v1 design is `02`; `13` is where it goes next.

### 5.4 Frames

Every array in the system is in exactly one of eight frames, and the frame is named in every
variable, file and manifest field that carries coordinates (`09` §1).

| ID | Name | Units | Notes |
|---|---|---|---|
| F0 | Source pixel | px | the full decoded frame |
| F1 | Model pixel | px | the model's cropped, resized grid |
| F2 | Camera | model units | OpenCV convention |
| F3 | Model world | model units | not gravity-aligned |
| F4 | Refined world | model units | same gauge as F3; BA refines, does not re-frame |
| F5 | Local level frame | model units x scale | up is gravity, heading is arbitrary |
| F6 | Local ENU | metres | GNSS only |
| F7 | Projected | metres | UTM plus EGM2008, GNSS only |

F5 is not ENU. Its horizontal axes are an arbitrary orthonormal pair, and calling it ENU would
invite a GIS user to trust a heading that does not exist (`09` §1.1).

### 5.5 The scale contract, and the mistake behind it

This is the part a newcomer should read twice, because it is the project's most expensive
lesson.

Until September 2026, every metre the system printed came from MapAnything's own
`metric_scaling_factor`. The only check was a plausibility band: implied camera speeds of 1.6 to
3.0 m/s and altitudes of 6.4 to 11.4 m. `05` §2 even warned that a 30% error would pass it.

The band passed a 450% error. EXP-14 (`08`) measured the Kolu reconstruction against two
published lengths and found it 5.3 to 5.8x too small:

| Ruler | In the model | Published | Factor |
|---|---|---|---|
| Lane width, edge line to dashed centre line | 0.650 model m | 3.50 to 3.75 m | 5.38 to 5.77 |
| Ecoduct waist, barrier crest to barrier crest | 3.95 model m | 21 to 22 m | 5.32 to 5.57 |

A third check sets a floor. Estonian road norms (MKM regulation 106 §9) require 5.0 m of
clearance under any overpass opening carrying vehicles, and the arch crown reads 1.30 model m,
so the factor is at least 3.85 (`08` §3.6). It excludes a x2 correction on its own.

The band failed for a structural reason. A camera 10.6 m up with a 67 degree horizontal field of
view sees about 14 m of ground, and the keyframes show a four-lane highway with a median, a
parallel road, the ecoduct and its verges. The band compared the model with itself and never with
the picture.

Three rules came out of it, and they now bind the whole system:

1. A metric claim is validated only by a length whose value comes from outside the model: GNSS, a
   surveyed check point, or an object of published size. A self-consistency check is a smoke test
   and must never be called validation (`08` §2).
2. Scale is a per-run, evidenced value. There is no global correction constant, because the factor
   is a per-run model output and cannot transfer between clips (ADR-014).
3. A run whose scale status is `unvalidated` may not print its lengths as metres. It prints model
   units, and the page says so (`09` §2).

Kolu now carries `research/calibration/kolu.json`, factor 5.54, bracket 5.32 to 5.77, applied once
at export. The Village clips have no ruler yet and stay unvalidated.

A separate defect surfaced in the same investigation. A measurement pick aimed into an unobserved
region silently lands on whatever surface the drone did see: the underpass interior holds one
point in the whole volume, so a click aimed at the ceiling returns the arch face or the deck. That
is backlog item B-30.

### 5.6 The degradation ladder

The orchestrator predicts each stage's cost and picks the highest level that fits the budget.
After a failure it drops one level and continues. The level is written into the manifest and shown
on every output (`13` §5).

| Level | What runs | Label |
|---|---|---|
| L0 | Dense set at full resolution, mesh, texture | measured |
| L1 | Densify at half resolution | measured, reduced resolution |
| L2 | Dense set halved | measured, sparse coverage |
| L3 | No MVS: fused feed-forward point maps | coarse, patch-limited |
| L4 | Sparse points and a DSM | sparse |
| L5 | The screen report and its codes | not reconstructable |

Absolute placement degrades on its own axis: RTK gives F7 at 0.15 m, consumer GNSS gives F7 at
about 4 m and says so, no telemetry gives F5 with no CRS.

The principle is that a run always returns something labelled. A budget overrun or a stage failure
moves down the ladder; it never ends in nothing (`13` §2).

### 5.7 The code

`src/tesseract/` is the pipeline built to these documents: `contracts.py` (frames, units, codes,
artefacts, run manifest, validator), `scale.py` (the scale service and the footprint check),
`pipeline.py` (stage DAG, content-addressed resume, cost budget, ladder), `stages.py`,
`report.py` and `cli.py`.

Every run writes `run_manifest.json` and a QA report stating the ladder level, the frame, the
units, the scale status and a three-valued verdict on each of the six targets. `tesseract verify`
checks a finished run against the contracts: schema, units against scale status, frame against the
georeferencing claim, and every artefact re-hashed.

`13` §10 is the table of what is built and what is not. The honest short version: the executors
for Slurm and Cloud Run are not built, so a real clip's geometry is adopted from an earlier run or
computed by the containers by hand; L1 half-resolution densify is a flag on a stage this host
cannot run; texture does not work.

---

## 6. Feasibility: what the numbers say

### 6.1 What has been run

Two real clips have gone end to end through MapAnything, bundle adjustment, OpenMVS and all seven
export files (`05` §8-9).

| | Short dense window | Kolu survey pass |
|---|---|---|
| Views registered | 42 / 42 | 45 / 45 |
| Reprojection error, after triangulation to after BA | 1.525 to 0.414 px | 1.730 to 0.366 px |
| Wall clock, 8 vCPU | 18 min 03 s | 32 min 43 s |
| Planimetric coverage vs feed-forward baseline | 83% | 135% |

Bundle adjustment improved reprojection error 3.7x and 4.7x. Both halves of that matter: 1.5 px on
the first pass says the intrinsics fitted from the point maps were right, and the improvement is
the direct measurement of why densifying before correcting the poses would have reprojected pose
error into a sharper-looking wrong surface (`05` §8, ADR-006).

The completeness difference between the two clips is a property of the footage, not the method.
MVS declines to invent surface where it cannot match. On the Short's shadowed textureless dirt
that costs coverage; on Kolu's well-textured survey pass it gains it.

### 6.2 Speed: the gap, stated

R-O2 is 900 s for a 10-minute video. Kolu took 2,078.7 s for 45 views on 8 vCPU, and dense
densification is 77% of that (`06` §5, ADR-011).

Per-view densify cost is 35 to 43 s at 8 vCPU regardless of window size. A 600-view clip on the
full five-project fan-out, 12 tasks of 8 vCPU, projects to about 36 minutes. Reaching 15 minutes
would need 27 tasks, 216 vCPU, more than double what the account has (`06` §7b).

Sharding was measured rather than assumed. Five tasks of 4 vCPU with overlap 4 was 7% *slower*
than one task and 21% less precise. Two tasks of 8 with overlap 2 was 13% faster end to end,
1.42x on densify, at quality parity (ADR-012). Horizontal CPU is worth about 1.4x and cannot reach
the speed criterion.

So: R-O2 is not met on CPU, and this is recorded as an open target rather than hidden. The
route to meeting it is a GPU. MapAnything measures 0.42 to 0.55 s per view on a free T4 against
6.4 to 11.4 s on 8 vCPU, a 14x gain (`13` §7). The dense stage on a GPU is unmeasured, and EXP-16
is the experiment that decides it. The v2 budget (`13` §6) allocates 900 s across the stages from
measured rates where they exist, with a target of 600 s to leave 1.5x headroom.

### 6.3 Compute, and why it is what it is

GPU quota on the project's GCP account is zero, and this was established empirically (`01` §9,
`06`). Every request auto-denies within seconds with
`quotaIncreaseEligibility.ineligibilityReason = "NOT_ENOUGH_USAGE_HISTORY"`, across Compute
Engine, Cloud Run and Vertex AI. Two traps are documented so they are not re-encountered:
`gcloud compute regions describe` reports K80/P100/V100/P4 = 1 in asia-south1, which are vestigial
rows for retired SKUs rather than usable access; and the quota API lists asia-south1 under Cloud
Run L4 while the deploy rejects it. Trust the deploy error, not the quota API.

Three deployment topologies are in the design (`13` §4). Cloud Run Jobs in asia-south1 at 8 vCPU
is the reproducible reference and produced every measured result. The Baramati cluster at VPKBIET
is the speed path: it has real GPUs and it is inside India, so it satisfies the residency rule. A
single air-gapped workstation is the field kit for the finale. All three run the same containers,
with weights, the EGM2008 grid and the sensor database baked in so no stage reaches the network.

### 6.4 Accuracy: what can and cannot be claimed

End to end on the synthetic path, where ground truth exists by construction:

| GNSS | absolute | shape | completeness | runtime |
|---|---|---|---|---|
| Consumer | 2.260 m | 1.058 m | 8.8% | 7.3 s |
| RTK/PPK | 0.098 m | 0.085 m | 100% | 2.9 s |

On real data, absolute accuracy is not measurable at all, because neither processed clip carries
GNSS (`14` §5). That is the single largest gap in the project and it is tracked as EXP-21.

The harness that produces these numbers was built and unit-tested before the pipeline it judges
(ADR-003), and it always reports absolute and aligned error separately. The reason: ICP alignment
reported 0.21 m on a model with a real 2.68 m offset, 12.8x flattering, and a
Tanks-and-Temples-style 7-DOF alignment scores a 5%-too-small model at 0.000 m. Reporting only the
aligned number is the common shortcut and it hides georeferencing failure completely.

### 6.5 The world-class bar

`11` §6 states where the product is against where it intends to be. Abridged:

| Axis | Today | Target |
|---|---|---|
| Speed | 2,078.7 s for 45 views on 8 vCPU | 600 s for a 10-min 4K clip on one 24 GB GPU |
| Relative accuracy | shape consistent; scale was 5.5x off on Kolu | scale error 1% against an external length |
| Absolute accuracy | not measurable, no GNSS clip | 0.15 m with RTK; 1 m is not achievable on consumer GNSS |
| Detail | about 2 cm corrected on Kolu MVS | 2x GSD against a LiDAR reference |
| Completeness | 135% of the feed-forward baseline on Kolu | 90% of observable surface |
| Provenance | figures re-grepped against sources | every metric carries a scale status |

---

## 7. What is proven, and what is not

The project treats this distinction as a first-class artefact, for a reason `08` demonstrates:
a figure can exist correctly in its source file while the source is wrong.

### 7.1 Maturity gates

`12` §1.1. A result may be *presented* at G2 and *claimed as a capability* only at G3.

| Gate | Meaning |
|---|---|
| G0 | A written hypothesis and a falsifying test |
| G1 | Measured on one real clip |
| G2 | Measured on two unrelated real clips |
| G3 | Measured on a held-out clip nobody tuned on |
| G4 | Timed end to end on unseen data inside the finale runbook |

### 7.2 The claims ledger

`14` §4 lists every figure the project states in public, its source file, its gate and its status:
Valid, Relabel, Invalid, or Unvalidated. After `08`, every item was corrected, relabelled or
removed across the viewers, the exported files, the Q&A page, the deck and the portal text, except
two that stay unvalidated until their data exists: the Village clip's finest-detail figure, and
the 1 m spatial accuracy claim.

The rule that keeps it honest: any change touching a public number updates the ledger in the same
change (`14` §2.2), and no external artefact ships without a ledger review (`18` §5).

### 7.3 The three largest gaps

No clip with per-frame GNSS has been processed, so stage S5 and the whole of absolute accuracy are
exercised only on synthetic data (EXP-21, `12` R3). Acquiring one clip closes half of two research
tracks.

R-O2 is not met on CPU and no GPU has been timed, so the speed criterion, 20 marks, rests on a
projection (EXP-16, EXP-25).

`TextureMesh` fails in 0.2 s with return code 1, so the textured export is not produced and mesh
vertices are coloured from the nearest dense point instead (ADR-016, EXP-20).

---

## 8. The research programme

`12` turns the open questions into experiments with pass and kill criteria written *before* they
run. Four rules govern it: pre-register the criterion, ship negative results, never tune on the
test set, and label the unit of every length.

Seven tracks, ordered by the score they move:

| Track | Question | Score | Gate today |
|---|---|---|---|
| R1 Metric truth | Can every metre be trusted, and how do we know? | Accuracy 30 | G1 |
| R2 Speed | Can a 10-min video finish in 600 s on one GPU? | Speed 20 | G0 |
| R3 Real georeferencing | Does S5 work on a real clip with GNSS? | Accuracy 30 | G0 |
| R4 Surface quality | Texture, while keeping MVS detail and coverage? | Completeness 20 | G2 / G0 |
| R5 Completeness | How much observable surface, and how is inference labelled? | Completeness 20 | G0 |
| R6 Robustness | Does an unknown clip ever crash us? | All | G1 |
| R7 Model | Is there a better licence-clean geometry or scale model? | Accuracy 30 | G1 |

The current sprint, in order, each unblocked today (`12` §5): EXP-23 telemetry fuzzing, which needs
no data and closes the largest robustness risk; persisting `metric_scaling_factor` per view and
plumbing priors into S3; EXP-17, priors on Kolu, the cheapest possible fix for the scale error;
EXP-14b, a ruler for the Village clip; EXP-15, an independent scale witness; EXP-20, diagnosing
`TextureMesh`; and acquiring a held-out clip with GNSS.

### 8.1 The data plan

Kolu is a CC0 Wikimedia clip of Estonia's first wildlife overpass, a 52 second oblique pass with
no GNSS and two published rulers. It is a development clip and no longer held out. The Village
clips are a third-party YouTube Short, usable for pipeline testing only because the rights are not
clear (`16` L-8). Synthetic scenes have ground truth by construction and are valid for geometry,
CRS, coverage and timing, but not for evaluating a learned model, because the domain gap to real
imagery is too wide. Two held-out sets are to be acquired, and the finale dataset arrives on the
day (`12` §4).

---

## 9. Compliance, licences and security

The customer is an intelligence agency and the data is regulated, so `16` treats security as a
design input.

On licences: the only copyleft in the runtime is OpenMVS at AGPL-3.0, invoked unmodified as a
separate process, which keeps the project's code outside its copyleft. Modifying it and offering
it over a network would require offering that source (L-1, ADR-005). ADR-023 proposes a BSD path
via COLMAP PatchMatch on GPU that avoids the question. VGGT, MASt3R, UniDepth, Inria 3DGS and 2DGS,
Pi3 weights and the CC-BY-NC MapAnything checkpoint are barred from any product build. The project
has not declared its own licence yet, which is a decision that has to be made before anything is
published beyond the demo (L-9).

Four findings from a repository check are open or recently closed. `PROJ_NETWORK=ON` in the
pipeline image means PROJ fetches geoid grid chunks for the region being transformed, which tells
a CDN where you are working; the fix is to bake the whole 80 MB grid and set `PROJ_NETWORK=OFF`
(F-1). Model load fetched DINOv2 from the hub at runtime, which breaks the offline requirement
(F-2). `demo/` was untracked, so the deployed site could not be rebuilt from version control,
since fixed (F-3). The public gallery serves third-party footage whose rights are not clear (F-4,
backlog B-05, still open).

The field kit baseline for the finale: full-disk encryption, network disabled during processing,
images loaded from a checksummed archive, no cached cloud credentials, input media mounted
read-only and checksummed at intake, and a recorded wipe afterwards (`16` §5).

---

## 10. Run it

```bash
pip install -r requirements.txt

python tesseract.py run synthetic --gnss rtk        # the whole pipeline, CPU, seconds
python tesseract.py screen data/cand/*.webm         # admissibility, before any compute
python tesseract.py run data/cand/kolu.webm --adopt out/kolumvs3d --calibration-run kolumvs3d
python tesseract.py verify out/runs/kolu            # a run against its own contracts
python tesseract.py report out/runs/kolu            # the QA report

python src/tesseract/test_tesseract.py              # 46 checks
python src/eval3d/test_metrics.py                   # 21 checks
python src/ingest/test_srt.py                       # 65 checks, real DJI sidecars and fuzz
python tools/build_all.py                           # the console and three pages, plus audits
```

The four deployed surfaces are `/console/` (the run console), `/` (a one-clip walkthrough),
`/gallery/` (every reconstructed clip, video beside 3D) and `/qa/` (53 technical questions ordered
by how exposed the answer is).

Start by running the synthetic pipeline, then open `out/runs/<name>/qa_report.md`. That file is the
shortest complete statement of what the system does and what it refuses to claim.

The experiments behind §4 are reproducible:

```bash
python src/experiments/exp01_classical_cost.py            # why classical SfM cannot be the spine
python src/experiments/exp05_gps_noise.py                 # accuracy vs GNSS class
python src/experiments/exp08_coverage_ceiling.py          # what one pass can physically see
python src/experiments/exp09_straight_line_degeneracy.py  # the degeneracy and its fix
python src/experiments/exp14_scale_audit.py               # the scale audit
```

---

## 11. Repo layout

```
docs/            the engineering suite, 00-18; index in docs/README.md
src/tesseract/   the pipeline: contracts, scale service, orchestrator, stages, CLI
src/ingest/      S0 screening, S1 video ingest (PyAV), SRT fixtures
src/pipeline/    COLMAP bridge, gravity, fusion, windowing, renders, exports
src/eval3d/      the evaluation harness and GNSS model, unit-tested
src/simscene/    synthetic scene, flight, visibility, CPU rasteriser
src/analysis/    MVS-vs-baseline measurement and the patch-floor analysis
src/experiments/ EXP-01, 05, 08, 09, 13, 14
mapanything_job/ the S3 container
mvs_job/         bundle adjustment, MVS and export container
tools/           builders for the console, demo, gallery, Q&A and deck, plus the audits
demo/            the deployed site
research/        verified findings and recorded experiment output
```

---

## 12. Glossary

**Admissibility** The S0 verdict on whether a clip can be reconstructed, with codes saying why
not. `ADM-HORIZON`, `ADM-SKY`, `ADM-SHOTS`, `ADM-OVERLAY`.

**Feed-forward model** A network that regresses cameras and geometry in a bounded number of
forward passes, rather than optimising per scene. MapAnything here.

**GSD** Ground sample distance: how much ground one pixel covers.

**LLF** Local level frame, F5. Gravity is up, heading is arbitrary. Not ENU.

**Model units** Lengths in the reconstruction's own scale, which is not metres until an external
ruler says so.

**Patch floor** The resolution limit imposed by a vision transformer's patch grid. 14 pixels for
DINOv2, and the reason the geometry moved to MVS.

**Scale status** One of `unvalidated`, `calibrated`, `gnss`, `gnss+rtk`. Decides whether a length
may be printed as metres.

**The ladder** L0 to L5. The quality level a run achieved, written into the manifest and shown on
every output.

**Three-valued verdict** A target is `met`, `not met`, or `not measurable`. The third is not a
softer version of the second.

---

## 13. References

Everything the project cites, grouped. A source with a link is one the suite already records
that way; a source without one is named exactly as the suite names it, because an invented URL
is worse than none. `tools/check_onboarding.py` refuses any link in this file that appears
nowhere else in the repository.

### 13.1 The problem statement

`docs/SIH26158.pdf`. Three pages, PS #17, pp. 37-39 of the NTRO problem-statement document, a
print-to-PDF of a Google Doc with no text layer. The sih.gov.in listing for the same problem
statement carries the editorial placeholder *"Add 'Desired Output' and 'Evaluation Criteria'
table here"* and is not a usable source (§2.1, `01` §1.1).

Four questions for the organisers that change what may legitimately be claimed, from the root
`README.md`: does the dataset include RTK or PPK corrections; is the 1 m target absolute or
relative; is evaluation against a LiDAR or multi-pass reference; is the single pass nadir or
oblique.

### 13.2 Papers and preprints

| Work | Where | Why it is cited |
|---|---|---|
| MapAnything | [arXiv 2509.13414](https://arxiv.org/abs/2509.13414) | The geometry spine. Metric by design, accepts intrinsics, poses, depth and metric flags as priors. Apache-2.0 code and an Apache-2.0 checkpoint. 1 B parameters, latest release 2026-01-20 |
| Wu, Landgraf, Ulrich and Qin, *An Evaluation of DUSt3R, MASt3R and VGGT on Photogrammetric Aerial Blocks* | [arXiv 2507.14798](https://arxiv.org/abs/2507.14798) | Independent arrival at ADR-004. Completeness gains up to 50% over COLMAP from very sparse low-resolution sets, but pose reliability falls with more images; these models *"cannot fully replace traditional SfM and MVS, but offer promise as complementary approaches"* |
| Song, Chen, Zhang et al., *AerialMetric* | [arXiv 2606.29716](https://arxiv.org/abs/2606.29716), [project page](https://kuieless.github.io/AerialMetric-ECCV2026-page/) | The closest external evidence for `08`. Zero-shot metric depth collapses at UAV altitude: MoGe-2 at 5.1% delta-1 on its oblique-city split without true intrinsics, 89.3% after rank-96 LoRA adaptation. Accuracy drops precipitously from 80 m to 120 m. Data, code and weights CC BY 4.0 per the paper |
| GLOMAP, *Global Structure-from-Motion Revisited* | [arXiv 2407.20219](https://arxiv.org/abs/2407.20219) | Global SfM, accuracy on par with or better than COLMAP at 1 to 2 orders of magnitude less time per its authors (ECCV 2024). The revisit condition on ADR-001 |
| H3D, the Hessigheim benchmark | [arXiv 2102.05346](https://arxiv.org/abs/2102.05346) | UAV LiDAR at about 800 pts/m2 with oblique imagery at 2 to 3 cm GSD, multiple epochs. Candidate held-out set B |
| UseGeo | [ResearchGate 381534229](https://www.researchgate.net/publication/381534229_UseGeo_-_A_UAV-based_multi-sensor_dataset_for_geospatial_research) | UAV multi-sensor dataset with LiDAR. The other candidate held-out set |
| VGG-T3 | [arXiv 2602.23361](https://arxiv.org/pdf/2602.23361) | Surveyed in `11`; not usable here for the same licence reason as VGGT |
| LONG3R | [arXiv 2507.18255](https://arxiv.org/pdf/2507.18255) | Long-sequence feed-forward reconstruction, surveyed in `11` |
| Pertuz, Puig and Garcia, *Analysis of focus measure operators for shape-from-focus*, Pattern Recognition 46(5):1415-1432, 2013 | named in `research/02` §6 | The blur-metric survey behind keyframe sharpness scoring. Also the correction: Tenengrad is attributed to Krotkov 1986, not Tenenbaum 1970 |
| James and Robson, 2014, DOI 10.1002/esp.3609 | named in `research/02` §4 | Why intrinsics are fixed rather than self-calibrated: on a near-planar nadir pass `k1` and focal length are nearly linearly dependent and the surface domes |

### 13.3 Law, standards and geodesy

**Indian geospatial regulation.** Guidelines for acquiring and producing Geospatial Data and
Geospatial Data Services, Department of Science and Technology, 15 February 2021. Threshold
1 m horizontal and 3 m vertical; data finer than that may be created and owned only by Indian
entities and must be stored and processed in India, on a domestic cloud or on servers
physically located in India. Compliance is by self-certification, so it has to be stated in the
submission (`01` §7.3, `research/02` §1, ADR-010).

**Flight.** The Drone Rules 2021 and the Digital Sky airspace map govern any flight the team
makes to collect held-out data. Registration, pilot and airspace requirements change, so they
are checked before a flight rather than restated here (`12` R3, `16` §6).

**Coordinate reference systems.** EPSG:4979 (WGS 84 3-D) as the source; EPSG:9518 (WGS 84 plus
EGM2008 height) as the vertical target, with EPSG:9707 (EGM96) as the model that must not be
chosen by accident; EPSG:32642 to 32647 for UTM zones 42N to 47N over India, selected at runtime
from mean longitude. A correction recorded in `research/02` §2.2: EPSG:7755-7787 is not a UTM
block but the per-state ISRO set under NNRMS TR 122:2005, 7755-7776 Lambert Conformal Conic and
7777-7787 Transverse Mercator.

**Geoid.** EGM2008, shipped as `us_nga_egm08_25.tif`, 80.6 MB, inside the image so no stage
reaches the network. Separation measured with PROJ 9.5.1 across India runs -24.32 m at Leh to
-98.24 m at Kanyakumari, and EGM96 against EGM2008 differs by 1.68 m at Amritsar. No public
Indian national geoid model is downloadable; Survey of India publishes a partial-coverage status
map, so EGM2008 is the defensible choice (`research/02` §2.1).

**Estonian road design norms.** MKM regulation 106 §9: *"Tuleb tagada kõrgusgabariit 5,0 m …
viadukti ja estakaadi all avades, kus on lubatud sõidukiliiklus"*, 5.0 m of clearance under any
overpass opening carrying vehicles. The 1999 norms, under which the 2013 structure was designed,
carry the same paragraph at §8, and Table 2.4 sets 3.75 m lanes for this road class. Used as the
clearance floor in `08` §3.6.

### 13.4 The Kolu clip and its rulers

The development clip is a CC0 Wikimedia Commons video of the Kolu ecoduct, Estonia's first
wildlife overpass (2013), over national road 2, Tallinn to Tartu. Two published dimensions make
it the only clip in the project that can be scale-audited (`08` §3.2):

- Lane width. The four-lane sections were designed on 3.5 m lanes, the Swedish-style
  cross-section, reported by ERR article 650086 and ERR news 1608116446 for the Kärevere to
  Kardla section. The ministry's stated minimum for a 2+2 section is 3.75 m. The bracket uses
  both.
- Ecoduct waist. Estonian Wikipedia, *Ökodukt*: *"ehitati Kolu sild selle kitsaimas kohas 22
  meetri laiuseks"*. 21 m is also reported. The bracket uses both.

Rights for the other footage, from `16` L-8: Nicosia and the Bahá'í temple CC BY 3.0 with
attribution, Toolse CC BY-SA 4.0, and the Village clip a third-party YouTube Short with no clear
rights, which is why it is for pipeline testing only and why its presence on the public gallery
is open finding F-4.

### 13.5 Models and weights

The register in `11` §5 was read from repositories and model cards on 2026-09-16. Verdicts are
for this deployment, where the customer is an intelligence agency.

| Model | Code | Weights | Usable here |
|---|---|---|---|
| MapAnything | Apache-2.0 | `facebook/map-anything-apache` Apache-2.0; `facebook/map-anything` CC-BY-NC-4.0 | Yes, the Apache checkpoint |
| DINOv2 giant, the MapAnything backbone | Apache-2.0 | Apache-2.0 | Yes |
| VGGT | VGGT licence plus AUP | same | **No.** The AUP prohibits *"Military, warfare, nuclear industries or applications, espionage, use for materials or activities that are subject to the International Traffic Arms Regulations (ITAR)"*, on both checkpoints. The July 2025 relicensing is explicitly commercial use except military |
| Depth Anything 3 | Apache-2.0 | BASE, SMALL, METRIC-LARGE, MONO-LARGE Apache-2.0; GIANT-1.1, LARGE-1.1, NESTED CC-BY-NC-4.0 | The Apache checkpoints only |
| MoGe and MoGe-2 | MIT | MIT (`Ruicheng/moge-2-vitl`) | Yes. The base of AerialMetric's adapted model |
| Pi3 | BSD-3 | non-commercial research and education | Code yes, weights no |
| MASt3R and MASt3R-SfM | CC BY-NC-SA 4.0 | same | No |
| UniDepth | CC BY-NC 4.0 | not separately listed | No |
| Metric3D | BSD-2 code | unverified | Code yes |
| Inria 3DGS and 2DGS | research-only licence | not separately listed | No |
| gsplat | Apache-2.0 | not applicable | Yes, as a viewer branch only |

### 13.6 Toolchain

| Component | Licence | Role |
|---|---|---|
| COLMAP | BSD | Triangulation and bundle adjustment on CPU. Its dense stereo is CUDA-only, which is why it is not the CPU densifier |
| GLOMAP | BSD-3 | Untested here; the candidate global SfM |
| OpenMVS | **AGPL-3.0** | `DensifyPointCloud` with `--cuda-device -2` for CPU, then Delaunay mesh. Run unmodified as a separate process from the upstream v2.4.0 prebuilt binaries, which keeps this project's code outside its copyleft (ADR-005, `16` L-1) |
| assimp | BSD-3 | Writes OBJ, PLY, glTF/GLB and FBX. `Exporter.cpp` registers `"fbx"` and `"fbxa"` at FBX 2016+, driven from Python through `pyassimp` (ISC). Two decoys avoided: FBX2glTF wraps the account-gated Autodesk SDK and converts the wrong direction, and ufbx is import-only (`research/02` §5) |
| PyAV | BSD-3 | Decode. Chosen over decord, whose HEAD is 2022-07-19 with 221 open issues (ADR-019) |
| FFmpeg | LGPL-2.1+ | The native H.264 and HEVC decoders are LGPL; libx264 and libx265 are encoders only, so a decode-only pipeline never needs GPL (`research/02` §6) |
| telemetry-parser | MIT or Apache-2.0 | Decodes the `djmd` protobuf track embedded in DJI MP4s, and yields focal length and distortion coefficients |
| laspy, rasterio, trimesh, pyproj, open3d | BSD-3-style, BSD-3, MIT, MIT, MIT | LAS 1.4 with `add_crs`, GeoTIFF with the COG driver, mesh IO, CRS transforms, geometry |
| PDAL, Potree 1.8.2, PoseLib | BSD, BSD-2, BSD-3 | Point-cloud pipeline, the COPC web viewer, minimal solvers for the 5-DOF fit |
| 3d-tiles-tools | Apache-2.0 | Candidate delivery format |
| IBM Plex Sans and Mono | SIL OFL 1.1 | The console's self-hosted type (`11` §5.2) |
| Blender `bpy` | GPL if published | The FBX fallback on a developer machine only. Shelling out is fine under GPL mere aggregation, but a published `bpy` glue script is itself GPL, so it never goes into a product build (`16` L-3) |

Pinned Python dependency versions and their licences: `11` §5.1, read from the installed
distributions' own metadata. CI refuses a new pin that is not listed there.

### 13.7 Incumbent products

| Product | Source | What it establishes |
|---|---|---|
| Pix4D | [overlap verification](https://support.pix4d.com/hc/en-us/articles/203756125), [image acquisition](https://support.pix4d.com/hc/en-us/articles/115002471546) | The reference for survey-grade output, and the overlap assumption this problem statement breaks: 75% frontal and 60% side in general, 85% frontal for a corridor |
| RealityScan 2.x, formerly RealityCapture | [2.0 release notes](https://www.realityscan.com/news/realityscan-20-new-release-brings-powerful-new-features-to-a-rebranded-realitycapture), [CG Channel on 2.1](https://www.cgchannel.com/2025/11/epic-games-releases-realityscan-2-1/) | Fast desktop photogrammetry; free below USD 1 M annual revenue |
| Skydio 3D Scan | [introduction](https://www.skydio.com/blog/introducing-skydio-3d-scan) | Solves capture by planning more views, which is the opposite of this problem |
| OpenDroneMap and WebODM | [options and flags](https://docs.opendronemap.org/arguments/) | The open incumbent, AGPL-3.0, reference only. Its `--video-limit` default of 500 is the anchor for the 600-keyframe figure. Two findings taken from it: it stamps extracted frames `Model: "Unknown"` so every video reconstruction falls back to a generic focal prior, and it applies no geoid correction at all |

DroneDeploy, Agisoft Metashape, Bentley iTwin Capture and Esri Site Scan share the same
planned-capture design centre and are not evaluated here beyond category (`11` §2).

### 13.8 Benchmarks, and what each can prove

From `11` §4. None is a single-pass video benchmark, which is why `14` §3.2 specifies
sub-sampling one flight strip from a survey block, with the caveat that survey stills are
sharper, better exposed and more overlapped than video frames, so the result is an upper bound.

| Benchmark | Ground truth | Alignment | Proves |
|---|---|---|---|
| ETH3D | laser scan | none | Absolute accuracy, the analogue of `evaluate(align=False)` |
| Tanks and Temples | laser scan | 7-DoF including scale | Shape only. A 5%-too-small model scores 0.000 m, which is why the harness never fits scale |
| H3D Hessigheim | UAV LiDAR, oblique imagery, multiple epochs | not specified | Aerial geometry and semantics on a real site |
| UseGeo | UAV multi-sensor with LiDAR | not specified | Real UAV depth and geometry |
| UrbanScene3D | LiDAR | not specified | Urban aerial reconstruction |
| AerialMetric | LiDAR and metric depth at known altitude | not specified | Metric scale at altitude, the exact failure `08` found |

### 13.9 Infrastructure evidence

GPU quota was surveyed through the Service Usage and Cloud Quotas APIs rather than the console,
so the numbers are the limits the scheduler enforces. Two traps recorded in `01` §9 and `06`:
`gcloud compute regions describe asia-south1` reports K80, P100, V100 and P4 at 1, which are
vestigial rows for retired SKUs rather than usable access; and the quota API lists asia-south1
under Cloud Run L4 `applicableLocations` while the deploy refuses it. Trust the deploy error.

The Baramati cluster at VPKBIET has its own `CONTEXT.md`: campus network only, `srun` broken so
jobs go through `sbatch`, and only the `torch-gpu` conda environment runs on its cards.

### 13.10 Inside this repository

| Where | What it holds |
|---|---|
| `docs/01` to `docs/18` | The suite. Index and reading paths in `docs/README.md` |
| `docs/10` | 25 architecture decision records, each with the evidence that made it and the evidence that would unmake it |
| `docs/14` §4 | The claims ledger: every public figure, its source, its gate and its status |
| `research/01-licensing-findings.md` | The licence verdicts, read from primary sources |
| `research/02-ingestion-export-findings.md` | Telemetry, intrinsics, geoid, UTM, export and decode findings, with an explicit "do not rely on these" list at §7 |
| `research/exp*-results.txt` | Recorded output from EXP-01, 05, 08, 09 and 14 |
| `research/exp1*.md` | Write-ups for the MapAnything CPU, GPU and video-to-3D runs |
| `research/calibration/*.json` | Per-run scale calibration: factor, bracket, method and references |
| `research/run-evidence/` | Screenshots of real runs |
| `out/runs/*/run_manifest.json` | What each run claims, and `qa_report.md` beside it |

### 13.11 Where to go next

| Read | When |
|---|---|
| This file | First |
| `08` | Before trusting any length |
| `01` | Before arguing about a requirement |
| `13` and `09` | Before changing a stage |
| `15` | Before a first commit |
| `12` and `14` | Before running an experiment or making a claim |
| `10` | Before reversing a decision, and write a new ADR rather than editing an old one |
| `16` | Before publishing anything or handling supplied data |
| `17` | Before the finale |
