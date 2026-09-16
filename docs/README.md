# SIH26158 engineering suite

The complete engineering record for **Tesseract** — single-pass drone video to a
georeferenced, metrically accurate 3D model — from the problem statement to the finale
runbook. Every figure in these documents traces to a file, a run or a cited source.

---

## Read this first

**`08-measurement-validation.md`.** On 2026-09-16 the metric scale was audited against
objects of published size, and the Kolu reconstruction came out **5.3–5.8× too small**. That
finding changes a set of public figures (`14` §4) and one design rule: a metre is valid only
with an external ruler or GNSS behind it (ADR-014).

---

## The suite

| # | Document | Answers | Status |
|---|---|---|---|
| **Requirements and design** ||||
| 01 | [SRS](01-SRS-requirements.md) | What the PS actually requires, traced to its PDF | Baselined 2026-09-04 |
| 02 | [Architecture v1](02-architecture.md) | The 900 s budget, model choice, stages | v1; extended by 13 |
| 09 | [Interface contracts](09-interface-contracts.md) | Frames, units, stage I/O, manifests, failure codes | **New** |
| 10 | [Decision log](10-decision-log.md) | 24 ADRs with evidence and revisit conditions | **New** |
| 13 | [Target architecture v2](13-target-architecture.md) | Scale service, orchestrator, ladder, GPU delta | **New** |
| **Research** ||||
| 05 | [Quality analysis](05-quality-analysis.md) | Why feed-forward geometry is patch-limited; the MVS rebuild, measured | Absolute lengths corrected by 08 |
| 08 | [Measurement validation](08-measurement-validation.md) | Is the metre a metre? EXP-14 | **New — read first** |
| 11 | [State of the art](11-state-of-the-art.md) | Incumbents, methods, benchmarks, licences, the world-class bar | **New** |
| 12 | [Research program](12-research-program.md) | Tracks R1–R7, pre-registered experiments, gates G0–G4 | **New** |
| `../research/` | Findings and recorded output | Licensing, ingestion/export, EXP-01…14 | Living |
| **Planning and delivery** ||||
| 03 | [Plan and SDLC](03-plan-sdlc.md) | Phases, compute ladder, trap list | v1; superseded where it differs by 18 |
| 07 | [Idea submission](07-idea-submission.md) | Portal fields, deck rules, deck design | Figures to correct (18, B-01) |
| 18 | [Roadmap](18-roadmap.md) | Milestones M0–M4, roles, RACI, backlog, risks | **New** |
| **Verification** ||||
| 04 | [Test plan](04-test-plan.md) | Test register, defect log | v1 |
| 14 | [Quality gates](14-quality-gates.md) | Metric definitions, gates, benchmark protocol, **claims ledger** | **New** |
| **Engineering and operations** ||||
| 06 | [GCP deployment](06-gcp-deployment.md) | Quota survey, CPU deployment, sharding | Measured |
| 15 | [Engineering handbook](15-engineering-handbook.md) | Setup, commands, conventions, review, trap register | **New — read before a first commit** |
| 16 | [Security and compliance](16-security-and-compliance.md) | Threat model, data residency, licences, field kit | **New** |
| 17 | [Operations runbook](17-operations-runbook.md) | Incidents, the 36-hour finale plan, calibration on the day | **New** |
| — | [Architecture prompt](architecture-prompt.md) | A self-contained prompt for regenerating the architecture | Reference |

---

## Reading paths

| You are | Read |
|---|---|
| **New to the project** | 01 → 08 → 13 → 15 |
| **Reviewing a claim** | 14 §4 → the cited source → 08 |
| **Running an experiment** | 12 → 14 §1 → 09 |
| **Changing a stage** | 09 → 10 → 15 §4–5 → 14 §2 |
| **Preparing the finale** | 17 → 16 §5 → 13 §5 → 18 |
| **Judging the project** | 01 §5 → 05 → 08 → 11 §6 |

---

## Keeping it true

- A document that states a number names the file the number came from.
- A correction is marked **CORRECTED** with its date, and the old reasoning stays visible.
- A decision changes by a new ADR, never by editing an old one.
- A contract changes in the same commit as the code that implements it.
- The claims ledger (`14` §4) is updated before any external artefact ships.
- Owners: 01, 02, 09, 10, 13, 14 — tech lead; 05, 08, 12 — geometry/ML; 11 — tech lead;
  15, 16 — platform; 17, 18 — tech lead with all roles (`18` §3).
