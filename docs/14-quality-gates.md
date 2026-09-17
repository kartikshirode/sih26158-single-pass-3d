# Quality gates, benchmarks and the claims ledger

Version 1.0 — 2026-09-16. How a change is allowed in, how a result becomes a claim, and the
current status of every claim the project makes in public. It extends `docs/04` (the test
register) and does not repeat it.

---

## 1. Metric definitions

One definition per metric, so two documents cannot mean different things by the same word.

| Metric | Definition | Unit | Scale-free? | Implemented |
|---|---|---|---|---|
| **Absolute error** | RMSE of reconstruction→reference nearest-neighbour distance, **no alignment** | m | No | `eval3d.evaluate(align=False)` |
| **Shape error** | Same after a rigid (6-DoF, **no scale**) ICP alignment | m | No | `evaluate(align=True, align_with_scale=False)` |
| **Scale error** | \|s − 1\| from a 7-DoF fit, reported separately and never absorbed | ppm | — | harness scale diagnostic (T-ACC-05) |
| **Scale factor** | Real length ÷ model length from an external ruler, with a bracket | × | — | `exp14_scale_audit.py` |
| **Precision / recall / F @ τ** | Fraction of reconstruction within τ of reference / the reverse / harmonic mean | % | No | `eval3d.prf_at_tau` |
| **Completeness (observable)** | Recall @ τ over the surface the flight could see (EXP-08 visibility) | % | Yes | `simscene.visibility` + harness |
| **Completeness (scene)** | Recall @ τ over the whole reference | % | Yes | harness |
| **Surface residual @ r** | Median \|residual\| from a plane fitted in a ball of radius r | length | Ratio only | `compare_mvs.roughness` |
| **Relief** | Height above a per-cell local ground (5th percentile per 1-unit cell) | length | Ratio only | `compare_mvs.relief` |
| **Planimetric occupancy** | Occupied cells on a shared grid; overlap and IoU between two runs | cells, % | Yes | `compare_mvs.occupancy` |
| **Reprojection error** | COLMAP mean, after triangulation and after BA | px | Yes | `run_mvs.reproj_error` |
| **Registration** | Registered views ÷ input views | % | Yes | COLMAP model_analyzer |
| **Wall clock** | Per stage and total, from the run's own record | s | Yes | `mvs_result.json` |

**Rule.** A length metric is reported with its unit status: `model units`, or metres with a
scale status (`docs/09` §2). "cm" on a model-unit measurement is a defect.

---

## 2. Gates

### 2.1 Commit gate — every commit, under five minutes, CPU only

| Check | Command | Today |
|---|---|---|
| Harness unit tests | `python src/eval3d/test_metrics.py` | **21 PASS / 0 FAIL** (2026-09-16) |
| Window-fusion test | `python src/pipeline/test_window_fuse.py` | **T-SCALE-01 PASS** |
| Syntax | `python -m compileall -q src tools mvs_job mapanything_job` | not wired |
| Demo build + audits + figure re-grep | `python tools/build_all.py` | passing at last deploy |
| Manifest schemas | validate any changed `*_manifest.json` / `scale_calibration.json` against `docs/09` | **not built** |
| Licence register | a new import or image package must appear in `docs/11` §5 | manual |
| Telemetry fuzz | EXP-23 suite | **not built** |

**Not in place: CI.** Nothing runs automatically on push. Proposed workflow (Ubuntu runner,
Python 3.12), to be added as `.github/workflows/ci.yml`:

```yaml
name: ci
on: [push, pull_request]
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r requirements.txt opencv-python-headless av matplotlib
      - run: python -m compileall -q src tools
      - run: python src/eval3d/test_metrics.py
      - run: python src/pipeline/test_window_fuse.py
```

`build_all.py` needs the `out/` artefacts, which are gitignored. It stays a local pre-deploy
gate until a small fixture run is committed.

### 2.2 Merge gate — before anything reaches `main`

- The commit gate passes.
- If the change touches a stage: that stage re-run on **Kolu**, and the regression thresholds
  (§2.4) hold.
- If the change touches a public number: the claims ledger (§4) is updated in the same change.
- A reviewer who did not write the change has read the diff (`docs/15` §4).

### 2.3 Milestone gate — before a claim is made in public

- The held-out set is run **once**, and its result recorded whatever it is.
- Every claim in the deliverable is in the ledger at **G2 or higher**, and capability claims
  are at **G3** (`docs/12` §1.1).
- Timings are taken on the declared hardware, cold start.
- Scale status is `calibrated` or `gnss` for any metric figure.

### 2.4 Regression thresholds (Kolu baseline, 8 vCPU)

| Quantity | Baseline | Fails if |
|---|---|---|
| Registered views | 45 / 45 | any view lost |
| Reprojection after BA | 0.366 px | > 0.40 px |
| Surface residual @ 6 / 12 / 25 model-cm | 0.756 / 1.487 / 2.787 | > 10% worse at any radius |
| Planimetric occupancy | 8,166 cells | < 95% of baseline |
| Relief max | 3.58 model units | outside ±10% |
| Densify wall clock | 1,593.9 s | > 15% slower on the same executor |
| Scale factor (after S1 lands) | 5.3–5.8 | outside the bracket |

---

## 3. Benchmark protocol

### 3.1 Splits

`docs/12` §4. Development clips may be looked at freely; held-out sets are opened once per
milestone.

### 3.2 Simulating a single pass from a survey block

Public LiDAR-referenced aerial sets (H3D, UseGeo) are survey blocks, not single-pass video.
To use them:

1. Take the images of **one flight strip**, ordered by capture time.
2. Treat the sequence as keyframes. Do not upsample to a frame rate; there is no blur to
   reject and that must be stated.
3. Run S3 → S6 unchanged.
4. Score with the harness **both ways** (absolute with the dataset's georeferencing; shape
   with rigid alignment), plus scale error, plus completeness against the strip's observable
   surface.
5. Report range bands from the flight line (EXP-12 found a 6.6× density fall-off).

**Caveat, stated in every report:** survey stills are sharper, better exposed and more
overlapped than video frames. The result is an *upper bound* on video performance.

### 3.3 Per-run QA report

Every run produces one page with:

- the six PS desired-output rows, each `met / not met / not measurable` with its evidence;
- the scale status and method, and the georef status;
- the ladder level (`docs/13` §5);
- the admissibility verdict and codes;
- every figure's provenance (file and field).

The demo's Q&A page (`/qa/`) is the prototype of this report; it already re-greps 54 figures.

---

## 4. Claims ledger

Every figure the project states in public, its source, its gate, and its status **after
`docs/08`**. Status: **Valid** · **Relabel** (number stands, unit or label is wrong) ·
**Invalid** (must change) · **Unvalidated** (cannot be claimed yet).

| # | Claim (where) | Source | Gate | Status |
|---|---|---|---|---|
| 1 | Reprojection 1.73 → 0.37 px (deck, Q&A) | `kolu_mvs/mvs_result.json` | G2 | **Valid** |
| 2 | 45 / 45 views registered | same | G2 | **Valid** |
| 3 | 1.8–3.6× finer surface than feed-forward (deck, Q&A) | `measure_*.json` | G2 | **Valid** as a ratio |
| 4 | "…at 6 cm" | same | — | **Relabel**: 6 model-cm. Kolu ≈ 33 cm corrected; Village unvalidated |
| 5 | Finest detail 3.5 mm (Kolu) | `docs/05` §9 | G1 | **Invalid**: ~1.8–2.0 cm corrected |
| 6 | Finest detail 1.9 mm (Village) | `docs/05` §8 | G1 | **Unvalidated** — no ruler yet (EXP-14b) |
| 7 | Vertical ceiling 2.33 → 3.58 m (deck, Q&A) | `measure_kolu.json` | G1 | **Invalid** as metres: ~12–14 → ~19–21 m corrected; the 1.54× ratio is valid |
| 8 | Coverage 136% of baseline (deck) | `measure_kolu.json` | G1 | **Valid**, but show Village's 83% beside it |
| 9 | 6 of 6 formats written and read back | `export_manifest.json` | G1 | **Valid** |
| 10 | 34 min 38 s, 77% in dense MVS | `mvs_result.json` | G1 | **Valid** |
| 11 | CPU fan-out 1.42× on densify | `docs/06` §7a | G1 | **Valid** |
| 12 | MapAnything 0.42–0.55 s/view on T4; 600 views fits the geometry budget | EXP-11, EXP-12 | G2 | **Valid** — extrapolation labelled |
| 13 | Consumer GNSS gives ~4.1 m absolute; RTK 0.097 m | EXP-05 | Simulation | **Valid as simulation**; not field-validated |
| 14 | Effective resolution 30–50 cm | `docs/05` §2 | G2 | **Relabel/Invalid**: model units; Kolu 2.7–3.0 m corrected. The **14× ratio is Valid** |
| 15 | "Metric scale with zero GCPs" (Q&A, deck) | `docs/02` §2 | — | **Invalid** as a model capability: scale 5.5× off on Kolu. Q&A rewritten 2026-09-17 (scale from GNSS, then known objects, else unvalidated); **deck still to fix** |
| 16 | "Measurement in metres" (demo, gallery) | `research/calibration/kolu.json` | G1 | **Valid on Kolu** since 2026-09-17 (calibrated ×5.54); Village measures in model units, labelled |
| 17 | Scene ~24.5 m across; the DSM "corroborates independently" (`demo/README.md`, now corrected) | — | — | **Invalid** and circular: the DSM cell size is a chosen parameter in the same units |
| 17a | Demo "scene extent" readout (`demo_template.html`) | `D.scale` | — | **Fixed 2026-09-17**: now `2·D.scale·factor` = 132 m; was 24.5 m, wrong by the factor and by a +2.4% arithmetic slip |
| 17b | Gallery Kolu table and note | `measure_kolu.json` × factor | G1 | **Valid** since 2026-09-17: footprint, relief, thresholds and residual radii in calibrated metres; Village rows marked `*` as model units |
| 18 | Camera 10.59 m above ground (Q&A) | `export_manifest.json` | — | **Relabelled** in the Q&A 2026-09-17: 10.59 model units, about 58 m calibrated |
| 19 | Intrinsics fit residual 0.22 px | `mvs_result.json` | G1 | **Valid** |
| 20 | ≤ 1 m spatial accuracy | — | — | **Unvalidated**: no GNSS clip (EXP-21) |
| 21 | Village relief/footprint 0.037, 1.34% above ground | `yt3d/viewer_stats.json` | G1 | **Valid** as ratios; any metre label unvalidated |

**Remediation.** Items 4–7, 14–18 and 17a are fixed by `docs/08` S7 in a single change: correct or
relabel the source files, then let `build_qa.py`'s re-grep fail on every stale figure and fix
each one. That is the re-grep working as designed — it checks that a figure *appears in*
its source, so the source has to be corrected first.

---

## 5. Test register gaps

From `docs/04`, never executed on real data:

| Test | Blocker |
|---|---|
| T-ACC-01/02/04 on a real clip | GNSS data (EXP-21) |
| T-ACC-05 scale | now partly executed by EXP-14 (Kolu); needs automation |
| T-COMP-01/02, T-CONT-01…05 | LiDAR-referenced set; labelled geometry (EXP-22, EXP-27) |
| T-PERF-01/03/04 | GPU and a 10-minute clip |
| T-ROB-02/04/05/06/07 | amateur footage; fuzz suite (EXP-23) |
| T-EXPORT-03 in QGIS / CloudCompare | manual session, not recorded |
| T-UI-02 measurement vs GT | depends on the scale fix |
| T-NF-01 determinism, T-NF-03 offline | not run |
