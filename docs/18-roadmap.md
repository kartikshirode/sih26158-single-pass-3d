# Roadmap and delivery plan

Version 1.0 — 2026-09-16. Milestones, roles, the prioritised backlog, and the consolidated
risk register. It supersedes the phase tables in `docs/03` §2 where they differ, and it
inherits `docs/03`'s warning: **the dates below come from the portal and secondary reporting —
confirm them with the SPOC.**

---

## 1. Calendar

| Date | Event | Source |
|---|---|---|
| **2026-09-30** | Idea-submission deadline shown on the PS listing | Portal, checked 2026-09-07. The SPOC guidelines PDF gives two *other* dates on the same page (`docs/07` §1) |
| October 2026 | National screening | Secondary reporting |
| November 2026 | Shortlist announced | Secondary reporting |
| December 2026 | Grand finale, 36 hours, dataset supplied on the day | Secondary reporting |

**Two weeks to submission.** The deck's metric figures were corrected on 2026-09-17
(`docs/14` §4). What remains for M0 is B-05 (footage rights) and B-07 (team fields,
deadline confirmation, submission).

---

## 2. Milestones

| Milestone | By | Exit criteria |
|---|---|---|
| **M0 · Truthful submission** | **2026-09-23** (a week before the deadline) | Every claim in the deck, Field 9, the Q&A page and the demo is Valid or relabelled in the ledger; Kolu scale calibration applied; the Village footage question resolved; `demo/` committed; idea submitted |
| **M1 · Metric truth and contracts** | 2026-10-15 | Contract gaps C-1…C-9 closed; EXP-17, EXP-14b, EXP-23 run; offline run passes (T-NF-03); CI live; security actions 1–5 done |
| **M2 · Speed** *(if shortlisted)* | 2026-11-20 | GPU densifier chosen (EXP-16); orchestrator with ladder and keyframe planner; a 10-minute clip timed end to end on one GPU (EXP-25); S5 run on real GNSS data (EXP-21) |
| **M3 · Finale ready** | 2026-12-01, or 10 days before the finale | Field kit built and rehearsed; three unseen-clip dry runs; every ladder level timed; QA report generator; viewer calibration tool |
| **M4 · Product** *(after the finale)* | — | Completeness and inferred-geometry labelling (EXP-22, EXP-27); model track (EXP-02, EXP-18); COPC / 3D Tiles delivery; web job UI |

---

## 3. Roles

Six roles, which fit a six-person team. One person may hold two; every workstream has exactly
one accountable owner.

| Role | Owns | Research tracks |
|---|---|---|
| **Tech lead** | Architecture, ADRs, contracts, the claims ledger, review | — |
| **Geometry / ML** | S3, scale service, model evaluation | R1, R7 |
| **Photogrammetry** | S3b, S4, surface and texture, speed | R2, R4 |
| **Geospatial** | S1 telemetry, S5, exports, CRS and geoid, data acquisition | R3, R5 |
| **Platform** | Containers, orchestrator, Baramati, CI, security, field kit | R6 |
| **Product / UX** | Viewer, QA report, demo, deck, presentation | — |

### 3.1 RACI

R = does it, A = accountable, C = consulted, I = informed.

| Workstream | Lead | Geo/ML | Photogr. | Geospatial | Platform | Product |
|---|---|---|---|---|---|---|
| Claims ledger and deck truth (M0) | **A** | C | C | C | I | **R** |
| Scale calibration and service | C | **A/R** | C | C | I | C |
| Contracts and run manifest | **A** | R | R | R | R | I |
| GPU speed path | C | C | **A/R** | I | R | I |
| Real georeferencing | C | I | C | **A/R** | I | I |
| Security and offline bundle | C | I | I | I | **A/R** | I |
| Viewer and QA report | C | C | I | C | I | **A/R** |
| Finale runbook and rehearsal | **A** | R | R | R | R | R |

---

## 4. Backlog

Priorities: **P0** blocks the submission · **P1** before M1 · **P2** M2–M3 · **P3** after.

| ID | P | Item | Source | Owner | Size |
|---|---|---|---|---|---|
| ~~B-01~~ | P0 | Correct or relabel every invalidated figure in the deck, Field 9 (`docs/07` §4), the Q&A page and `docs/05` — **done 2026-09-17**; the deck also lost a wrong "Apache-2.0 / BSD" licence claim | `docs/14` §4 | Product | M |
| ~~B-02~~ | P0 | Kolu calibration applied to viewer measurement, labels, gallery tables, the Q&A and all seven exported files — **done 2026-09-17** | `docs/08` S1–S3, ledger 16–22 | Geo/ML | M |
| ~~B-03~~ | P0 | Decide the correction to ship — **decided 2026-09-17**: the measured ×5.54, not ×2. The ×2 came from a road-to-bridge reading that the 5.0 m clearance norm shows ×2 cannot fix | `docs/08` §3.6, §7 | Lead + requester | decision |
| ~~B-04~~ | P0 | `demo/README.md`: remove the circular DSM "corroboration" and the 24.5 m figure — **done 2026-09-16** | `docs/14` item 17 | Product | S |
| **B-05** | P0 | Village footage on the public gallery: obtain permission or remove | `docs/16` F-4 | Product | S |
| **B-06** | P0 | Commit `demo/` and the design-system tools | `docs/16` F-3 | Platform | S |
| **B-07** | P0 | Confirm the deadline with the SPOC; set `TEAM_NAME` / `TEAM_ID`; submit | `docs/07` §5 | Lead | S |
| B-08 | P1 | Persist `metric_scaling_factor` per view (C-4); pass priors (C-5); run EXP-17 | `docs/09`, `docs/12` | Geo/ML | M |
| B-09 | P1 | EXP-14b: a ruler for the Village clip | `docs/12` | Geo/ML | S |
| B-10 | P1 | EXP-23 telemetry fuzz suite; align SRT records to keyframes (C-3) | `docs/12`, `docs/09` | Geospatial | M |
| B-11 | P1 | Whole EGM2008 grid in the image, `PROJ_NETWORK=OFF`; bake DINOv2; `HF_HUB_OFFLINE=1`; T-NF-03 | `docs/16` F-1, F-2 | Platform | M |
| ~~B-12~~ | P1 | CI workflow (commit gate) — **done 2026-09-18**, plus a licence-register check | `docs/14` §2.1 | Platform | S |
| B-13 | P1 | Python 3.12 environment with open3d; `finish_mvs.py` uses `sys.executable` | `docs/15` §1.1 | Platform | S |
| B-14 | P1 | Run manifest (C-8). *C-1, C-2, C-7 and C-9 closed 2026-09-17* | `docs/09` | Lead | M |
| B-15 | P1 | EXP-15 independent scale witness, after its licence check | `docs/12`, ADR-024 | Geo/ML | M |
| B-16 | P1 | Decide the project's own licence | `docs/16` L-9 | Lead | decision |
| B-17 | P1 | `THIRD_PARTY_NOTICES`; image digests; SBOM | `docs/16` | Platform | S |
| B-18 | P2 | Baramati GPU path; EXP-16; ADR-023 decision | `docs/12` R2 | Photogr. | L |
| B-19 | P2 | Orchestrator: stage DAG, resume, ladder, keyframe planner — **built 2026-09-18** (`src/tesseract/`). **Open:** Slurm and Cloud Run executors | `docs/13` §10 | Platform | L |
| B-20 | P2 | EXP-19 (SfM at 600 views), EXP-03 (dense-set size), T-PERF-04 | `docs/12` R2 | Photogr. | M |
| B-21 | P2 | Acquire Held-out A (single pass + SRT + check points); EXP-21; EXP-07 | `docs/12` R3 | Geospatial | L |
| B-22 | P2 | EXP-20 `TextureMesh`; EXP-26 coverage recovery | `docs/12` R4 | Photogr. | M |
| B-23 | P2 | Viewer "calibrate from a known length" tool. *The CLI half exists: `tesseract calibrate`* | `docs/08` S8 | Product | M |
| ~~B-24~~ | P2 | Per-run QA report generator — **done 2026-09-18**, written on every run | `docs/14` §3.3 | Product | M |
| ~~B-25~~ | P2 | Footprint check (automatic scale sanity) — **done 2026-09-18**; a test asserts it rejects the pre-EXP-14 Kolu scale | `docs/08` S5 | Geo/ML | M |
| B-26 | P2 | Field kit build, rehearsal, wipe procedure | `docs/16` §5, `docs/17` §4.1 | Platform | M |
| B-27 | P3 | EXP-22, EXP-27: observable completeness and inferred-geometry labels | `docs/12` R5 | Geospatial | L |
| B-28 | P3 | EXP-02, EXP-18: model track | `docs/12` R7 | Geo/ML | M |
| B-29 | P3 | COPC via Potree; 3D Tiles | `docs/11` | Product | M |
| **B-30** | P1 | **Warn on picks near unobserved regions.** A click aimed at a surface the drone never saw (the underpass ceiling) silently lands on a different one. Flag picks whose nearest point is far from the cursor ray, or that sit on the rim of a hole | `docs/08` §3.6 | Product | M |

### 4.1 Definition of done

An item is done when:

1. the code is merged after review (`docs/15` §5);
2. the commit gate passes, and the regression thresholds hold if a stage changed;
3. any contract change is in `docs/09`, and any decision in `docs/10`;
4. any public number it changes is updated in the claims ledger;
5. any experiment it ran has its output in `research/`, whatever the result.

---

## 5. Cadence

| Ritual | When | Output |
|---|---|---|
| Planning | Weekly | Backlog order; owners |
| Stand-up | Daily, 15 min, async allowed | Blockers |
| Experiment review | Before any experiment runs | Pre-registered criteria in `docs/12` |
| Results review | After any experiment | `research/` entry; ADR if a decision moved |
| Claims review | Before any external artefact ships | Ledger status for every figure |
| Freeze | 24 h before any submission or presentation | No number changes without a ledger check |

---

## 6. Risk register

Consolidates `docs/03` §6 with what has been learned since. P = probability, I = impact.

| # | Risk | P | I | Response | Owner |
|---|---|---|---|---|---|
| R1 | No GPU for the timed benchmark | High | High | Baramati (B-18); CPU ladder levels measured | Photogr. |
| R2 | Dataset has no RTK → ≤ 1 m absolute not claimable | High | High | Dual reporting; ask the organisers | Geospatial |
| R3 | Pure-nadir flight → facades unobservable | Med | High | Labelled inference; capture guidance | Geospatial |
| R4 | Unknown telemetry schema on the day | Med | High | Fuzz suite (B-10); proceed without GNSS | Geospatial |
| R5 | 900 s exceeded | High | High | Ladder; dense-set knob; GPU path | Photogr. |
| R6 | Apache weights materially weaker | Med | Med | EXP-02; report the gap | Geo/ML |
| R7 | Team bandwidth during the semester | Med | Med | P0/P1 first; M4 is optional | Lead |
| R8 | No internet at the venue | Med | High | Offline bundle; T-NF-03 | Platform |
| **R9** | **Scale wrong on the finale clip, with no GNSS** | **High** | **High** | Scale service; calibration on the day (`docs/17` §4.5); `unvalidated` label otherwise | Geo/ML |
| **R10** | **Invalidated metric claims reach the screening panel** | **High** if unfixed | **High** | B-01 before M0 | Product |
| **R11** | **Third-party footage on the public demo** | Med | Med | B-05 | Product |
| R12 | Deadline ambiguity (three dates) | Med | High | B-07; submit a week early | Lead |
| R13 | AGPL exposure if OpenMVS is ever modified | Low | Med | Keep unmodified; ADR-023 BSD path | Platform |
| R14 | Environment drift (3.13 default, open3d on 3.11) | High | Low | B-13 | Platform |
| R15 | Runtime network egress reveals the area of interest | Med | High | B-11 | Platform |
| R16 | The PS freezes at 500 ideas before submission | Low | High | Submit early (`docs/07` §1) | Lead |

---

## 7. What "done" looks like for this product

Measured against `docs/11` §6, the world-class bar:

- a 10-minute 4K video in **≤ 10 minutes** on one GPU, with the ladder guaranteeing a labelled
  result in ≤ 20 minutes whatever happens;
- **every metre with a status**, and calibrated scale within 1%;
- **≤ 0.15 m absolute with RTK**, and the consumer-GNSS figure stated rather than hidden;
- **≥ 90% of the observable surface**, with inferred geometry labelled;
- **zero crashes** on unknown inputs, and a reason for every rejection;
- an **air-gapped, licence-clean, India-resident** deployment with an SBOM.

The foundation for all of it — the harness, the measured diagnosis, the MVS rebuild, the
contracts and now the scale audit — is in place. The remaining work is listed above, in order.
