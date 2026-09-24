# Operations runbook

Version 1.0 — 2026-09-16. How to run the system, how to recover when it breaks, and exactly
what to do in the 36 hours of the finale. Closes `docs/03` C1 (runbook), C2 (offline bundle)
and C3 (degradation ladder), and it is written to be followed under pressure: short steps,
explicit decision points.

---

## 1. Service objectives

For the product, not the demo. They are what the finale runbook defends.

| Objective | Target | Measured by |
|---|---|---|
| Time to **first labelled result** (any ladder level) | ≤ 20 min from intake | run manifest timestamps |
| Time to **L0 result**, 10-min video, one GPU | ≤ 15 min (PS); ≤ 10 min (`docs/11` §6) | T-PERF-01 |
| Admissible clips producing a labelled result | 100% | QA reports |
| Crashes on unknown telemetry schemas | 0 | EXP-23 fuzz suite |
| Metric figures without a scale status | 0 | QA report lint |

---

## 2. Observability

- **One run manifest per run** (`docs/09` §4): inputs and checksums, container digests, stage
  timings and return codes, frame, scale status, ladder level, verdicts. The first thing to
  open when anything looks wrong.
- **Stage logs** carry the stage ID and run ID on every line.
- **GCP.** Job status shows scheduling states only. For anything stuck, read Cloud Logging for
  `compute.instances.insert` and quota errors first (`docs/03` §3.1).

---

## 3. Incident playbooks

| Symptom | Likely cause | Do this |
|---|---|---|
| Cloud job sits `QUEUED` / `SCHEDULED_PENDING` | Global `CPUS-ALL-REGIONS` quota, not the regional one | Cloud Logging → `QUOTA_EXCEEDED`; free vCPUs or use Cloud Run Jobs (separate quota) |
| OpenMVS binary "fails" in the image build | Loader error (GLIBC) | The build greps for loader errors on purpose; confirm the base is `ubuntu:24.04` |
| MapAnything OOM | Too many views in one window | Window at 24 views, overlap 8 (EXP-13); `memory_efficient_inference=True`; on MIG slices stay ≤ 24 GB |
| `torch.cuda.is_available()` True but kernels fail (Baramati) | Wrong conda env for sm_120 cards | Use `torch-gpu`; smoke-test with a real matmul |
| `srun` fails with "Job credential expired" (Baramati) | Clock skew on the login node | Use `sbatch` |
| Registered < N views | Weak overlap or bad frames | Drop unregistered views; below 80% → ladder L3 (`GEO-UNREG`) |
| Reprojection > 1 px after BA | Bad intrinsics or poses | Check the intrinsics fit residual and principal point (refuses > 8% off both the keyframe centre and, when S1 cropped, the crop-shifted source centre); stop (`GEO-REPROJ`) |
| `TextureMesh` rc = 1 in 0.2 s | Known (EXP-20) | Non-fatal; per-vertex colour ships (ADR-016) |
| Transform raises instead of returning heights | Geoid grid missing — **this is the defence working** | Load the grid; never set `allow_ballpark=True` (`REF-BALLPARK`) |
| Measured distances look wrong | Scale status `unvalidated` (`docs/08`) | Calibrate from a known length (§4.5); never apply a global factor |
| 45 keyframes became 90 | Stale files from a previous run | Clear the output directory and re-run S1 |
| Screen says REJECT on a clip you need | Horizon, sky, shots, overlay | Read the codes; `--horizon crop`, take the longest shot, re-screen |
| Cloud Run job dies mid-densify | Memory: Cloud Run's writable filesystem is in-memory, so scratch counts against RAM (verify for the configured execution environment) | Stream intermediates to GCS; use 2-shard densify; or move to Baramati |

---

## 4. Finale runbook — 36 hours

### 4.1 Before the event (T − 14 days to T − 1)

| When | Task | Done when |
|---|---|---|
| T − 14 | Build the **offline bundle**: all images with weights, EGM2008 grid, sensor DB baked in; image digests and weight SHA-256s recorded | Archive checksummed |
| T − 10 | **T-NF-03**: full run with networking disabled | Passes; the manifest shows no network access |
| T − 10 | Pre-measure every ladder level on the kit (**T-PERF-04**) | Table of seconds per view per level |
| T − 7 | **Dry runs on ≥ 3 unseen clips**, end to end, timed (`docs/03` C4) | Three QA reports |
| T − 7 | Print this runbook, the failure codes (`docs/09` §6) and the claims ledger (`docs/14` §4) | On paper |
| T − 3 | Field kit: disk encryption, no cached credentials, GPU matmul smoke test | Checklist signed |
| T − 1 | Rehearse the 36-hour plan below with a stopwatch | Timings noted |

### 4.2 The first hour

```
T+0:00  Receive data. Mount read-only. SHA-256 every file into the manifest.
T+0:05  tesseract screen <video>            → verdict + codes            (≤ 1 min/clip)
T+0:10  Telemetry probe: which parser matched? (SRT / djmd / mov_text / CSV / none)
        ├─ RTK/PPK present  → absolute target ≤ 0.15 m is in play
        ├─ consumer GNSS    → expect ~4 m absolute; say so from the start
        └─ none             → LLF output; scale must be calibrated (§4.5)
T+0:15  Start an L3 run (feed-forward only) as INSURANCE.   → a labelled result in minutes
T+0:20  Start the L0 run in parallel if the GPU allows; else L1.
T+0:60  Check the insurance result exists. From here there is always something to show.
```

### 4.3 Decision points

| At | Question | If yes | If no |
|---|---|---|---|
| Screen | Is the clip admissible? | Continue | Try `--horizon crop` / longest shot; if still rejected, present the verdict and its codes — that *is* an answer (R-C9) |
| Telemetry | Did a parser match? | Continue with S5 | Proceed without; record `ING-NOGNSS` |
| S3b | Registered ≥ 80% and reprojection ≤ 1 px? | Continue to S4 | Ladder L3 |
| S4 | Predicted densify time fits the remaining budget? | L0 | L1 → L2 |
| S5 | Georeferencing fit residual (6-DOF, ADR-026) consistent with the GNSS class? | Write F7 | Ship LLF; report the fit failure |
| Scale | Status `gnss` or `calibrated`? | Print metres | Print model units, and calibrate (§4.5) |

### 4.4 The 36 hours

| Hours | Work |
|---|---|
| 0–1 | Intake, screen, telemetry probe, insurance L3 run (§4.2) |
| 1–6 | L0/L1 run; watch the per-stage timings against the budget |
| 3–6 | In parallel: scale calibration from objects in the scene (§4.5) |
| 6–10 | Exports: open every file in QGIS and CloudCompare (T-EXPORT-03); fix any frame or CRS issue |
| 10–12 | QA report: six PS rows, scale and georef status, ladder level, provenance |
| 12–24 | Improve: coverage (`--number-views-fuse 2`), texture if EXP-20 landed, further clips |
| 24–30 | Freeze. Re-run nothing that changes a presented number without re-checking the ledger |
| 30–34 | Presentation: lead with the measured result and the two honest gaps |
| 34–36 | Buffer. Sleep is a valid use |

### 4.5 Calibrating scale on the day

When there is no GNSS, the scene itself usually carries a ruler. In order of preference:

1. **A dimension the organisers give** (ask for one).
2. **Road markings.** Lane width on Indian national highways is typically 3.5 m — **confirm
   for the site**; dashed-line pitch where the standard is known.
3. **Standard objects**: vehicle length and width, shipping containers, sports-court
   markings.
4. Measure two independent rulers. If they agree within 10%, write `scale_calibration.json`
   with both references and a bracket. If they disagree, report both and leave the status
   `unvalidated`.

EXP-14 (`src/experiments/exp14_scale_audit.py`) is the worked method: lane profile plus a
structural width, both in the export frame.

### 4.6 Things to say, and not say

| Say | Do not say |
|---|---|
| "Metric scale is calibrated from <ruler>, bracket x–y" | "Metric with zero ground control" when the status is `unvalidated` |
| "Absolute ≤ 1 m needs RTK; with consumer GNSS we measure ~4 m and report it" | Any aligned (ICP) number as if it were absolute |
| "This is feed-forward geometry, patch-limited" at L3 | "Full resolution" at any level below L0 |
| "The facades the pass could not see are labelled inferred" | A completeness figure without its denominator |

---

## 5. Capture guidance (if the team can influence the flight)

From EXP-08 and `research/02-ingestion-export-findings.md`:

- **Turn on DJI "Video Subtitles"** so an `.SRT` is written; keep the flight log too.
- **RTK/PPK** if available — the only route to ≤ 1 m absolute.
- A **gently curved** track beats a ruler-straight one for georeferencing (EXP-09: 7-DOF
  scene error 367 m straight vs 7.9 m curved).
- **Forward tilt saturates** at about 45–60°; a **sideways tilt or wider lens** buys
  cross-track facades.
- Keep the horizon **out of frame**; oblique enough to see facades, not so oblique that sky
  enters.
- Steady speed, one continuous shot, no cuts.

---

## 6. Demo operations

| Task | Procedure |
|---|---|
| Rebuild | `python tools/build_all.py` — must end "All three pages built and both audits pass" |
| Deploy | `cd demo && vercel deploy --prod --yes` |
| Verify | Open `https://tesseract-demo.vercel.app`, `/gallery/`, `/qa/` in a **signed-out** browser; a `200` from curl is not proof |
| Roll back | Promote the previous production deployment in the Vercel dashboard or CLI |
| Never | Point a custom `*.vercel.app` alias at it (login wall); reconnect git integration; run `vercel blob` without backing up `.env.local` |
| Local check | Double-click `demo/index.html` and `demo/gallery/index.html`; confirm the video plays and the layout holds at phone width. The automation browser cannot test this (its tab is hidden) |
