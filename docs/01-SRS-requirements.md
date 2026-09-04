# Software Requirements Specification
## SIH26158 — Single-Pass Drone Video to Accurate 3D Model Generation System

| | |
|---|---|
| **Problem statement** | SIH26158 (PS #17, pp. 37–39 of the NTRO problem-statement document) |
| **Organisation** | National Technical Research Organisation (NTRO) |
| **Category / Theme** | Software / Drone–Robotics |
| **Document version** | 1.0 — 2026-09-04 |
| **Status** | Baselined against the official PDF. No requirement here is inferred. |

---

## 1. Purpose and scope

Convert **one** monocular drone video captured in a **single flight pass**, together with its GPS
track and flight metadata, into a **georeferenced, metrically accurate, textured 3D model** of the
scene, within a bounded processing time.

### 1.1 Source of truth — and a warning

The sih.gov.in listing for this PS contains the literal editorial placeholder
*"Add 'Desired Output' and 'Evaluation Criteria' table here"*. **The portal text is incomplete.**
The binding numbers exist only in the linked Drive PDF (`SIH26158.pdf`, 3 pages, no text layer —
it is a print-to-PDF of a Google Doc and must be read as rendered images).

Any competing team working only from the portal will not know the accuracy, time, or format
targets. Every requirement below is traced to that PDF.

### 1.2 Out of scope (explicitly)

- Multi-pass / multi-flight capture, flight planning, or re-flight.
- Live on-board processing on the UAV itself. Processing is ground/cloud-side, post-landing or
  post-stream.
- Reconstruction of scene content never observed *and* not inferable from context (see R-C7,
  which is deliberately bounded).

---

## 2. Stakeholders

| Stakeholder | Interest |
|---|---|
| NTRO | Operational: border/strategic mapping, reconnaissance, rapid damage assessment |
| SIH evaluators | Score against the six weighted criteria in §5 |
| UAV operator (end user) | One pass, minimal effort, no GCP survey, fast usable output |
| Analyst (end user) | Measure distances/areas, inspect, visualise, export to GIS |

---

## 3. Input requirements

Traced to PDF p.38 "Input Data".

| ID | Requirement | Priority | Notes / risk |
|---|---|---|---|
| **R-I1** | Accept drone video at 1080p and 4K | Mandatory | Codec/container unknown in advance |
| **R-I2** | Accept GPS coordinates | Mandatory | Format unknown — SRT sidecar, CSV, EXIF, or flight log |
| **R-I3** | Accept flight metadata | Mandatory | Vendor-specific schema |
| **R-I4** | Optionally use IMU data | Optional | Improves rotation priors |
| **R-I5** | Optionally use barometric altitude | Optional | Often better relative height than GNSS |
| **R-I6** | Optionally use camera intrinsic parameters | Optional | **Must self-calibrate when absent** |
| **R-I7** | Optionally use RTK/PPK corrections | Optional | When present, absolute accuracy improves ~10× |

> **Critical planning fact.** The PS states *"Dataset Link: Will be provided real time."* The drone
> model, camera, codec, and metadata schema are therefore **unknown until the event**. Robust,
> auto-detecting ingestion is a first-class requirement, not polish. This drives R-NF4.

---

## 4. Functional requirements

### 4.1 Desired output — hard targets
Traced to the PDF p.38 "Desired Output" table. These are pass/fail.

| ID | Parameter | Target | Verification |
|---|---|---|---|
| **R-O1** | Reconstruction type | 3D mesh **or** point cloud | T-EXPORT-01 |
| **R-O2** | Processing time | **< 15 min for a 10-min video** | T-PERF-01 |
| **R-O3** | Spatial accuracy | **≤ 1 m** | T-ACC-01/02 |
| **R-O4** | Coverage | Entire visible scene | T-COMP-01 |
| **R-O5** | Output formats | OBJ, PLY, LAS, GeoTIFF, .glb/.gltf, .fbx | T-EXPORT-02 |
| **R-O6** | Visualisation | Web-based **or** desktop viewer | T-UI-01 |

> **R-O5 carries one unresolved item: `.fbx`.** FBX is a proprietary Autodesk format with no known
> permissively-licensed writer. OBJ, PLY, LAS, GeoTIFF and glTF all have clean routes; FBX does
> not. Candidate resolutions are a Blender CLI export (GPL, invoked as a separate process, which
> avoids linking) or the Autodesk FBX SDK (proprietary terms). **Status: open**, pending the
> export-tooling verification still outstanding. If no acceptable route exists this must be raised
> with the organisers, not quietly dropped.

**Derived, non-negotiable, from the Description paragraph:** the model must be *georeferenced* and
*metrically accurate* — R-O3 is an absolute-world-frame requirement, not merely a self-consistent
shape. This distinction is the single most common way to fail this PS while appearing to pass it;
see §7.2.

### 4.2 Scene content to reconstruct
Traced to PDF p.37 Description (i)–(v).

| ID | Requirement | Verification |
|---|---|---|
| **R-F1** | 3D terrain and structures | T-CONT-01 |
| **R-F2** | Building facades **and** rooftops | T-CONT-02 |
| **R-F3** | Roads and infrastructure | T-CONT-03 |
| **R-F4** | Vegetation and obstacles | T-CONT-04 |
| **R-F5** | Textured 3D meshes or point clouds | T-CONT-05 |

> R-F2 is the sharpest technical constraint in the whole PS. A nadir (straight-down) single pass
> **physically cannot observe vertical facades**. Satisfying R-F2 therefore depends either on the
> flight being oblique, or on the bounded inference described in R-C7. This must be stated openly
> in the design, not glossed.

### 4.3 Usability
| ID | Requirement | Verification |
|---|---|---|
| **R-F6** | Model suitable for **visualisation** | T-UI-01 |
| **R-F7** | Model suitable for **measurement** (distance, area, height) | T-UI-02 |
| **R-F8** | Model suitable for **analysis** | T-UI-03 |

---

## 5. Evaluation criteria (the scoring function)

Traced to PDF p.38 "Evaluation Criteria".

| Criterion | Weight | Owned by |
|---|---|---|
| Reconstruction Accuracy | **30%** | R-O3, R-C5, R-C8 |
| Model Completeness | **20%** | R-O4, R-F1–F5, R-C1, R-C7 |
| Processing Speed | **20%** | R-O2, R-C6 |
| Innovation | 15% | R-C7, architecture novelty |
| Scalability | 10% | R-NF2 |
| User Interface | 5% | R-O6, R-F6–F8 |

**Engineering consequence.** Accuracy + Completeness + Speed = **70%**, and all three are
*objectively measurable*. Innovation + Scalability + UI = 30% and are subjective. The rational
strategy is to make the measurable 70% verifiable and instrumented, and to spend only proportionate
effort on the remaining 30%. Concretely: **UI is 5% — it must exist and must not be the focus.**

---

## 6. Key challenges as engineering requirements

Traced to PDF pp. 37–38 Key Challenges (i)–(viii). Each is restated as a testable requirement.

| ID | Challenge | Requirement | Verification |
|---|---|---|---|
| **R-C1** | Limited viewing angles (single path) | Reconstruct from a single trajectory with low/no cross-strip overlap; degrade gracefully, never fail hard | T-ROB-01 |
| **R-C2** | Motion blur, compression artifacts | Detect and down-weight or reject degraded frames | T-ROB-02 |
| **R-C3** | Variable illumination and shadows | Texture without visible seams across exposure changes | T-ROB-03 |
| **R-C4** | Dynamic objects (vehicles, humans, animals) | Detect and exclude moving objects from geometry | T-ROB-04 |
| **R-C5** | GPS inaccuracies and sensor noise | Robust to consumer-GNSS noise and outliers; must not let a single bad fix warp the model | T-ACC-03 |
| **R-C6** | Real-time / near-real-time | Satisfy R-O2; report progress | T-PERF-01/02 |
| **R-C7** | Reconstruction of occluded surfaces | Close unobserved surfaces by bounded inference, **explicitly labelled as inferred** | T-COMP-02 |
| **R-C8** | Metric accuracy without extensive GCPs | Achieve R-O3 using GPS/flight metadata only, **zero GCPs** | T-ACC-01 |

> **R-C7 scope bound (deliberate, and stated up front).** Generative completion of unseen 3D
> surfaces is an open research problem and cannot be done reliably inside the R-O2 time budget.
> This system will close occluded surfaces by *geometric* inference (footprint extrusion to the
> terrain, planar continuation) and will **tag every such face with a confidence attribute**
> distinguishing observed from inferred geometry. A bounded, honest, labelled solution is worth
> more than an oversold one — Innovation is only 15%, and Accuracy is 30%.

---

## 7. Non-functional requirements

| ID | Requirement | Rationale |
|---|---|---|
| **R-NF1** | Deterministic and reproducible: same input → same output, fixed seeds, pinned versions | Evaluator must be able to re-run |
| **R-NF2** | Scalable: degrade by configuration, not code change, from 1-min to 30-min video | Scalability = 10% |
| **R-NF3** | Observable: per-stage timing, and a machine-readable run manifest | Proves R-O2; enables tuning |
| **R-NF4** | Robust ingestion: auto-detect metadata format; never hard-fail on an unknown drone | Dataset is unknown until the event |
| **R-NF5** | **Deployment-legal**: no component whose licence forbids the stated end use | See §7.1 — this is a real disqualifier |
| **R-NF6** | Runs offline on a single machine, no internet dependency at inference | Finale may be offline; the customer is an intelligence agency |
| **R-NF7** | Every accuracy claim traceable to a reproducible measurement, never an estimate | Accuracy is 30% |

### 7.1 R-NF5 — the licensing constraint that changes the architecture

NTRO is India's technical intelligence agency, and the PS lists *"Military reconnaissance and
mission planning"* and *"Border and strategic area mapping"* among its applications.

**VGGT (Meta) — the highest-profile model for exactly this task — is therefore disqualified.**
Its Acceptable Use Policy prohibits:

> "Military, warfare, nuclear industries or applications, espionage, use for materials or
> activities that are subject to the International Traffic Arms Regulations (ITAR)"

This applies to **both** checkpoints; the July 2025 relicensing is explicitly *"commercial use,
with the exception of military applications."*

Every third-party component must be licence-cleared before adoption. See
`research/01-licensing-findings.md` for the verified register.

### 7.2 Absolute vs. relative accuracy — how teams fail R-O3 invisibly

A reconstruction can be internally beautiful and still be tens of metres out of place. Two
distinct errors must be measured and reported **separately**:

1. **Shape error** — model vs. ground truth *after* best-fit alignment (ICP/Sim(3)). Measures
   geometric fidelity.
2. **Georeferencing error** — model vs. ground truth *without* any alignment. Measures whether
   the thing is actually where it claims to be on Earth.

R-O3's "≤ 1 m" is only meaningful as the second. Reporting only the aligned number, which is the
common shortcut, silently hides georeferencing failure. **This system reports both** (T-ACC-01 vs
T-ACC-02).

A specific trap inside georeferencing error: GNSS altitude is **ellipsoidal**, while most maps and
DSMs are **orthometric** (geoid-referenced). Over India that difference is large — tens of metres —
and applying it wrongly blows the ≤1 m vertical budget by an order of magnitude on its own.

---

## 8. Assumptions and open questions

Recorded rather than assumed silently, per the "don't assume things" constraint.

| # | Assumption / question | Status | Impact if wrong |
|---|---|---|---|
| A1 | Evaluation compares against a reference model (LiDAR or multi-pass survey) | **Unconfirmed** — PS does not say | Changes how accuracy is scored |
| A2 | "Spatial accuracy ≤ 1 m" is absolute georeferenced RMSE | **Unconfirmed** — could be relative | If relative, target is much easier |
| A3 | The 15-min budget is wall-clock on our own hardware | **Unconfirmed** — hardware unspecified | Hardware class changes the design |
| A4 | Video will carry usable per-frame GPS (e.g. DJI SRT) | **Unconfirmed** | Sparse GPS weakens georeferencing |
| A5 | The single pass is oblique, not pure nadir | **Unconfirmed** | Pure nadir makes R-F2 (facades) near-impossible |
| A6 | GCP compute available for the demo | **FALSE — verified 2026-09-04** | See §9 |

**Action:** A1–A5 to be raised with the organisers / SPOC. None blocks design, because the system
is built to satisfy the strictest reading of each.

---

## 9. Verified environment constraint (as of 2026-09-04)

**GPU compute on the team's GCP account is unavailable, and this was established empirically, not
assumed.**

Every request auto-denied within seconds, root cause
`quotaIncreaseEligibility.ineligibilityReason = "NOT_ENOUGH_USAGE_HISTORY"`:

- Compute Engine `GPUS-ALL-REGIONS`, `NVIDIA-L4-GPUS` and `PREEMPTIBLE-NVIDIA-L4-GPUS`
  (asia-south1) — denied at both 4 and 1 GPU.
- Cloud Run `NvidiaL4GpuAllocPerProjectRegion` **and** the no-zonal-redundancy variant — denied;
  a live deploy fails admission on both redundancy settings.

Two traps documented so they are not re-encountered:
- `gcloud compute regions describe asia-south1` reports `K80/P100/V100/P4 = 1`. These are
  vestigial rows for retired SKUs, **not** usable GPU access. T4/L4/A100 are all 0.
- The quota API lists `asia-south1` under Cloud Run L4 `applicableLocations`, but deploying there
  fails: *"GPU configuration for nvidia-l4 is only supported in regions: asia-southeast1,
  europe-west4, europe-west1, us-central1, us-east4."* Trust the deploy error, not the quota API.

This is a **hard constraint on the plan**, not a footnote; the compute strategy in
`03-plan-sdlc.md` §Compute is built around it.

---

## 10. Traceability summary

14 numbered PS-derived requirements (6 output + 8 challenge), plus 5 content, 7 input, 3 usability
and 7 non-functional. Every one carries a verification ID. The test IDs are specified in
`04-test-plan.md`; the design elements that satisfy them are in `02-architecture.md`.

**No requirement in this document is invented.** Anything not traceable to the PDF is marked as an
assumption in §8 and flagged for confirmation.
