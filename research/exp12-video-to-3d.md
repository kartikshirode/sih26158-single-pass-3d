# EXP-12 — Real video in, 3D out. The last gap closed.

The PS's mandatory input is a **video**. Until this run, every result had come from synthetic
poses or still JPEGs, so stage S1 was specified but never exercised. This closes that.

**Source video:** 40 s of drone footage over Nicosia, Cyprus. Wikimedia Commons, **CC BY 3.0**
(The Track Record - BTS). 4K, downscaled to 1080p as the PS specifies. Chosen over a beach clip
because it is dense urban - buildings and infrastructure, which is what the PS asks for.

## S1 ingest, run locally on real H.264 (`src/ingest/video_ingest.py`)

| | |
|---|---|
| Frames decoded | **1,199** (PyAV, real H.264) |
| Rejected as slate / title card | **293** = 9.8 s of credits, found automatically |
| Rejected as blurry | 300 (25th percentile **of this clip**, never a hardcoded value) |
| Keyframes selected | **20**, by optical-flow baseline budget (34.97 px) |
| Reduction | 1199 : 20 |
| GPS sidecar | none — correctly detected and reported |

**The slate gate had to be added after the first run.** A title card *passes* a sharpness test:
black-on-white text gives a strong Laplacian response, so blur scoring alone let 5 s of credits
straight through. It takes a content check (mostly-flat-and-dark) to catch it. Worth having,
because at the finale nobody will warn us that a stranger's video opens with credits.

**The blur gate, honestly, did nothing here.** Selected keyframes average 365 sharpness against
361 for naive uniform sampling. This is professionally gimbal-stabilised cinematography with no
bad frames to reject. That gate will earn its place on amateur or fast mapping footage; on this
clip it is inert, and claiming credit for it would be wrong.

## S3 geometry, MapAnything on a free Kaggle T4

| | |
|---|---|
| Inference | **8.4 s for 20 views = 0.42 s/view** |
| Peak VRAM | **11.0 GB** (fits any 16 GB card) |
| Autocast | fp16 — selected from compute capability; T4 is Turing, no native bf16 |
| Points | **1,696,707** |
| Extent | 391 × 79 × 382 (model units — no metric scale without GPS) |

**600 keyframes extrapolates to 251 s against a 405 s geometry budget — WITHIN, 1.61× headroom.**

Faster per view than the aukerman still-image run (0.42 s vs 0.55 s), because these frames are
1080p rather than 18 MP.

## What this establishes

A real drone **video file** goes in and a 3D point cloud comes out. Decode, slate rejection, blur
rejection, baseline-aware keyframing and learned reconstruction all ran on genuine H.264 footage,
and the GPU cost fits the budget. That is the PS's stated input-to-output path, demonstrated.

## What it does not

**Georeferencing and accuracy.** This clip carries **no GPS**, so there is no absolute frame to
place the model in and no ground truth to score against. The PS lists GPS as mandatory precisely
because without it the problem is unsolvable as stated.

The plots also show the honest failure mode of *cinematic* footage: the cloud is a thin sheet
with the city on it, degrading with distance. A high-oblique shot puts most pixels in the
far field, where a monocular model has almost no parallax. A nadir or low-oblique mapping pass
would behave very differently — and that is the flight the PS actually describes.

## Still needed for a complete answer
A **single-pass mapping video with per-frame GPS** (ideally RTK), plus a LiDAR or multi-pass
reference to score against.
