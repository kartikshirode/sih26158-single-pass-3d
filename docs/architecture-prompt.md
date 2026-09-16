# Architecture-generation prompt — SIH26158

A self-contained prompt for generating the full technical architecture. Every fact in it
is traced: PS constraints come from `docs/SIH26158.pdf` (read as images, pp. 37–39),
measured numbers from `out/*/mvs_result.json` and `out/ppt/measure_*.json`, licence
claims from the projects' own terms.

Paste everything between the rules below into a fresh model. It assumes no access to
this repository.

---

You are a systems architect. Design the complete technical architecture for the system
described below, then output it in the deliverables listed at the end.

## 1. The problem statement (binding, quoted from the source)

Smart India Hackathon 2026, problem statement **SIH26158**, posted by the **National
Technical Research Organisation (NTRO)**. Category Software, theme Robotics and Drones.

**Title:** Single-Pass Drone Video to Accurate 3D Model Generation System.

**Background.** Accurate 3D models of buildings, infrastructure, terrain and objects
normally require multiple drone passes, extensive image overlap, specialised flight
planning and significant post-processing. In disaster response, surveillance,
infrastructure inspection, military reconnaissance and rapid mapping there is often only
a single opportunity to capture data over the target. A system that produces an accurate,
textured 3D model from one pass would reduce mission time, operator effort, data
acquisition requirements and processing complexity, and enable near real-time situational
awareness.

**Description.** Design an AI-enabled system that generates a **georeferenced and
metrically accurate** 3D model of a scene from **only a single-pass drone video stream
captured from a moving UAV**. Process the frames of one flight path and reconstruct:
(i) 3D terrain and structures, (ii) building facades and rooftops, (iii) roads and
infrastructure, (iv) vegetation and obstacles, (v) textured 3D meshes or point clouds.

**Expected deliverable.** The generated model must be suitable for **visualization,
measurement and analysis**.

**Input data.**
- Mandatory: (i) drone video 1080p/4K, (ii) GPS coordinates, (iii) flight metadata.
- Optional: (i) IMU, (ii) barometric altitude, (iii) camera intrinsic parameters,
  (iv) RTK/PPK corrections.
- **The dataset link is provided in real time at the event.** Drone model, camera, codec
  and metadata schema are therefore unknown in advance. Auto-detecting ingest is a
  first-class requirement, not polish.

**Desired output (pass/fail).**

| Parameter | Target |
|---|---|
| Reconstruction Type | 3D Mesh / Point Cloud |
| Processing Time | **< 15 minutes for a 10-minute video** |
| Spatial Accuracy | **≤ 1 m** |
| Coverage | Entire visible scene |
| Output Formats | OBJ, PLY, LAS, GeoTIFF, .glb/.gltf, .fbx |
| Visualization | Web-based or Desktop Viewer |

**Evaluation criteria (weighted — optimise explicitly against these).**

| Criterion | Weight |
|---|---|
| Reconstruction Accuracy | **30%** |
| Model Completeness | **20%** |
| Processing Speed | **20%** |
| Innovation | 15% |
| Scalability | 10% |
| User Interface | 5% |

Accuracy + Completeness + Speed = 70% and all three are objectively measurable. The other
30% is subjective. Architect accordingly: instrument the measurable 70%, and do not let
the 5% user interface drive design.

**Key challenges (the architecture must answer each by name).**
(i) Limited viewing angles due to single flight path. (ii) Motion blur and video
compression artifacts. (iii) Variable illumination and shadows. (iv) Dynamic objects
(vehicles, humans, animals). (v) GPS inaccuracies and sensor noise. (vi) Real-time or
near-real-time processing requirements. (vii) Reconstruction of occluded surfaces.
(viii) Maintaining metric accuracy without extensive Ground Control Points (GCPs).

## 2. What already exists, is implemented, and is measured

Treat this as ground truth. Do not contradict it; build the architecture around it.

**The core finding, which determines the whole design.** Modern feed-forward 3D models
(DUSt3R / VGGT / MapAnything) are what make a single pass tractable at all: they recover
camera pose and metric scale from one flight line, where classical structure-from-motion
lacks the overlap to. But their *geometry* has a hard ceiling. Measured: the model samples
depth at **2.2 cm** while carrying information only at **30–50 cm**, set by its patch-14
vision backbone and an interpolating depth head. Confirmed three ways, with the competing
explanation tested and rejected. No downstream tuning recovers detail the patch grid never
carried. This is why single-pass AI reconstructions look convincing from altitude and fall
apart on inspection.

**Consequence: a two-model split.** Use the feed-forward model *strictly* as a pose and
metric-scale prior. Refine with global bundle adjustment. Take **every delivered surface
point** from full-resolution per-pixel photometric multi-view stereo.

**Implemented pipeline (running end to end on two unrelated real clips):**
1. **Ingest** — 1080p/4K video + GPS + flight metadata; auto-detects SRT / CSV / EXIF /
   flight log; adaptive keyframing rejects motion blur, compression artefacts and
   redundant frames; self-calibrates intrinsics when absent.
2. **Pose + metric scale** — MapAnything point maps; intrinsics by robust masked fit
   (measured residual **0.22 px**); COLMAP triangulation then global bundle adjustment.
3. **Dense geometry** — OpenMVS PatchMatch at full keyframe resolution;
   geometric-consistency filtering across ≥ 3 views (this also rejects moving vehicles,
   people and animals by construction).
4. **Surface + frame** — Delaunay + graph-cut mesh, per-vertex colour (no texture atlas,
   therefore no seams across exposure changes); vertical from the ground plane,
   cross-checked against the gimbal roll-zero constraint.
5. **Export + view** — OBJ, PLY, LAS 1.4, GeoTIFF DSM, glB/glTF, FBX in one shared ENU
   frame, plus a browser viewer built for measurement.

**Measured results (survey clip, 45 keyframes, 8 vCPU, unless noted):**
- Keyframes registered: 45 / 45.
- Mean reprojection error: **1.73 px → 0.37 px** after bundle adjustment (4.7×).
- Dense points **3.45 M**; mesh **1.95 M** triangles.
- Finest detail resolved **1.9 mm** (second clip) / 3.5 mm (survey clip).
- **1.8–3.6× finer** than the feed-forward baseline at 6 cm scale, on two unrelated clips.
- Vertical structure ceiling **2.33 m → 3.58 m** (buildings stop being flat paint).
- Ground coverage **136%** of the AI-only baseline.
- Export formats: **6 of 6** written and read back.
- Wall clock **34 min 38 s**, of which **77% is the dense-geometry stage** — the one stage
  a GPU changes. CPU fan-out measured at 1.42×.

**Stack.** PyTorch, MapAnything, COLMAP, OpenMVS, Open3D, OpenCV; trimesh, laspy,
rasterio, pygltflib, assimp; Python 3.11, Docker, Cloud Run (asia-south1), GCS, three.js.

**Non-negotiable constraints.**
- **Licence over leaderboard.** VGGT is the better-known model, but its acceptable-use
  policy bars military and espionage use — which this PS explicitly names. MapAnything's
  Apache-2.0 checkpoint does not. OpenMVS is AGPL-3.0, so it is invoked as a separate
  unmodified process rather than linked, and a BSD GPU replacement for that one stage is
  the clean long-term answer.
- **Sovereign by construction.** All processing pinned to an Indian region: India's
  Geospatial Data Guidelines (DST, 2021) require data at or finer than 1 m to be stored
  and processed within India, and this PS targets ≤ 1 m.
- **No GPU floor.** Every component is permissive and runs on CPU. GPU is a speed upgrade,
  never a dependency for getting a result.
- **Zero GCPs.** Scale comes from the feed-forward prior and flight metadata.
- **Honest georeferencing.** With no GNSS in a clip, the DSM ships with a real geotransform
  in metres and **no CRS at all**, rather than a plausible-looking wrong one that
  downstream GIS would silently reproject.

**Open gaps — do not paper over these; architect the route that closes them.**
- **Processing speed is not met.** 34 min 38 s against a < 15 min budget on CPU.
- **Absolute accuracy is unvalidated.** Neither test clip carries GNSS, so ≤ 1 m has not
  been demonstrated. Validation needs an RTK/PPK-tagged dataset with surveyed check points.

## 3. What to produce

1. **Component architecture** as a Mermaid diagram: every module, the boundaries between
   them, and what crosses each boundary.
2. **Data-flow / sequence view** from video ingest to exported artefacts, showing what is
   parallelisable and what is strictly serial.
3. **Stage table**: stage, function, inputs, outputs, time budget within 900 s, CPU vs GPU
   behaviour, and what degrades if it is cut short.
4. **Interface contracts** between stages — concrete formats and coordinate frames, not
   prose. Name the frame at every hop (camera → local metric → ENU → projected CRS).
5. **Deployment topology**: containers, orchestration, storage, region pinning, and how a
   GPU node is added without becoming a dependency.
6. **Challenge traceability matrix**: all eight key challenges (i)–(viii), the specific
   mechanism that answers each, and the test that would verify it. Mark honestly where
   the answer is partial.
7. **Evaluation-criteria map**: each of the six weighted criteria, the architectural
   decisions that move it, and how it is measured.
8. **Risk register** with the failure mode, the blast radius, and the mitigation.
9. **Degradation ladder**: what the system returns when the budget is exceeded, GPS is
   absent, the clip is unreconstructable, or a stage fails outright. Partial, labelled
   output beats no output.
10. **The GPU delta**: what changes when a GPU is available, quantified against the 77%
    figure above.

## 4. Rules

- Ground every architectural choice in a constraint, a measurement or a licence term from
  §1–2. If a choice rests on an assumption, mark it **ASSUMPTION** and state what would
  falsify it.
- **Invent no numbers.** Use the measured values given; where a value is unknown, write
  "unmeasured" rather than an estimate that will read as fact.
- Use the problem statement's own vocabulary — *single-pass, georeferenced, metrically
  accurate, textured 3D mesh or point cloud, facades and rooftops, vegetation and
  obstacles, near real-time situational awareness*.
- Prefer permissive licences; flag any component that is not, and say what replaces it.
- Distinguish throughout between what is **implemented and measured**, what is
  **designed but unbuilt**, and what is **open**.
- Optimise for the 70% that is objectively measured. Do not gold-plate the 5% UI.

---

## Adapting this prompt

**For a diagram tool rather than a written architecture** (an image generator, draw.io,
Excalidraw): keep §1 §2 and replace §3 with deliverable 1 only, then add — *"Output a
single left-to-right block diagram, six stages, with a labelled branch at the pose stage
showing that the AI's pose and scale are kept and its geometry is discarded. Grey for
data stores, one accent for the compute path. No icons, no gradients, no 3D."* That
branch is the whole idea; a diagram that omits it misses the argument.

**If you want the architecture to fit slide 3 of the deck**, add: *"Constrain the
methodology view to five stages that read left to right in a single row, each summarisable
in under 30 words."*
