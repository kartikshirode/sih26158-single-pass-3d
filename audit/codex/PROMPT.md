# Codex audit: core logic of the SIH26158 pipeline

You are auditing a Python and Node codebase that turns one drone video into a georeferenced,
metrically accurate 3D model. The project will be judged mostly on numbers: accuracy (30%),
completeness (20%) and speed (20%). Its central promise is that it never prints a metre, a
coordinate or a verdict it cannot back. Your job is to find every place where the code breaks
that promise, computes something wrong, crashes on input it should survive, or exposes the
public upload service to real abuse.

This is a correctness audit, not a style review. A finding that would not change a number, a
claim, a crash or a cost is not worth reporting.

## Before anything else

1. Read `audit/codex/CONTEXT.md` in full. It holds the problem statement, the architecture,
   the contracts (section 3), the known issues you must not re-report (section 4), leads to
   test first (section 5), the local environment (section 6) and a risk-ranked file list
   (section 7).
2. Read the Overview of `.claude/codemap.md`. Use the entries to route yourself, but read the
   actual files: an entry is a summary, the file is the authority.
3. Read `docs/09-interface-contracts.md` and skim `docs/10-decision-log.md`. Every invariant
   you test comes from these two documents plus CONTEXT.md section 3.

## Ground rules

Allowed:

- Read anything in the repository.
- Run the existing test scripts and `python tesseract.py run synthetic ...` /
  `python tesseract.py verify ...` (they write under `out/`, which is gitignored). Prefix
  run names with `audit-`.
- Write new files ONLY under `audit/codex/`: the report `audit/codex/FINDINGS.md` and
  throwaway reproduction scripts under `audit/codex/scratch/`. Scratch scripts may import
  repository modules; they must not modify them.

Forbidden, no exceptions:

- Editing, deleting, moving or reformatting any existing file. You report fixes; you do not
  apply them.
- Any git command that writes: commit, add, stash, checkout, reset, branch, push.
- Anything that touches the network or the cloud: `gcloud`, `gsutil`, `bq`, `vercel`,
  `kaggle`, `docker`, `curl`/`wget`/`Invoke-WebRequest` to any host, including
  `tesseract-demo.vercel.app` and `storage.googleapis.com`. Each real upload run costs about
  70 minutes of 8 vCPU on a billing account with no auth in front of it. Probing the live
  API is out of scope; audit it by reading the code.
- `pip install` or any package manager. If a module is missing, audit statically and record
  what could not run.
- Running `tools/build_*.py` (they overwrite committed pages under `demo/`) or
  `src/experiments/exp14_scale_audit.py` (it overwrites `research/calibration/kolu.json`).

If a check needs something forbidden, write down what you would have run and why, and move on.

## Method

Work in the phases below, in order. Keep notes as you go; the report in phase 6 is built
from them.

### Phase 1: baseline

Run the four test scripts listed in CONTEXT.md section 6 with `PYTHONIOENCODING=utf-8` and
record pass, fail or could-not-run for each, with the first error line. Then try
`python tesseract.py run synthetic --gnss rtk --name audit-rtk` and
`python tesseract.py verify out/runs/audit-rtk`. Environment failures are not findings;
record them in the report's environment section and carry on.

### Phase 2: write down the invariants

Before reading code for bugs, list the invariants you will test, each with its source (docs
section, ADR, or CONTEXT.md section). At minimum: every frame transition F0 to F7, units
following scale status, the scale factor applied exactly once and never to rendering,
absolute versus aligned reporting, yaw-only versus 7-DOF, EGM2008 guard, telemetry keyed not
positional, ladder and resume semantics, status.json lifecycle, the web limits, data
residency. This list goes in the report's coverage section.

### Phase 3: deep passes, by area

Read every Tier 1 file from CONTEXT.md section 7 in full, line by line. Do not skim a Tier 1
file. For each area, trace data from where it enters to where it leaves, and at every step
write down the frame, the units, the dtype and the array shape you believe it has. Most bugs
in this kind of code live at the seams between functions that disagree about one of those
four things.

Test the leads in CONTEXT.md section 5 first. Then work through these areas in order.

**A. Georeferencing and frames.** `src/eval3d/gnss.py`, `stages.Georeference`,
`stages.Level`, `stages.Export`, `src/pipeline/run_demo.py`, `src/pipeline/gravity.py`.
- Is the input to every yaw-only fit actually gravity-aligned with Z up? Who guarantees it?
- Geodetic/ECEF/ENU conversions: formulas, reference ellipsoid, inverse accuracy at the
  distances and altitudes involved, lat/lon order and `always_xy` at every pyproj call.
- UTM zone selection from mean longitude: a scene straddling a zone boundary, southern
  hemisphere handling, and whether the chosen EPSG is recorded where exported files use it.
- Orthometric height: which transformation pyproj actually picks, whether the guard catches
  a ballpark or missing-grid transform in every code path that produces heights (stages,
  run_demo, export_formats), and the sign convention of the reported geoid separation.
- RANSAC: the "auto" threshold under non-unit scale, degenerate samples, seeds, what happens
  when inliers collapse, whether the final model is refit on inliers.
- gravity.estimate: sign disambiguation, the degenerate-heading case, and what Level does
  when only camera centres exist.

**B. Scale and units.** `src/tesseract/scale.py`, `tools/scale_cal.py`, `contracts.units_for`,
`stages.Scale`, `stages.Level`, `stages.Export`, `src/pipeline/export_formats.py`,
`report.py`, `cli.cmd_verify`, `cli.cmd_calibrate`.
- Trace the factor from the calibration file to every output. Count how many times it is
  multiplied in along each path (tesseract pipeline, finish_mvs + export_formats, builders
  and templates). Exactly once is correct. Zero or twice is a finding.
- Can any path label a length "m" while the status is `unvalidated`? Check manifest fields,
  QA report text, export metadata (LAS header, GeoTIFF tags, export_manifest.json), console,
  gallery, demo and run pages.
- `from_gnss`: is a consumer-GNSS fit (about 4 m absolute) allowed to claim the same status
  and the same wording as RTK? What does R-O3's verdict do with it?
- `footprint_check` and `implied_factor`: check the maths with numbers, including the case
  that motivated it (Kolu at factor 1.0 must fail, at 5.54 must pass).
- `verify`: list what it checks, then try to build a run directory that is wrong but passes.

**C. Evaluation harness.** `src/eval3d/metrics.py`, `stages.Score`, `stages.Verdicts`.
- Precision/recall/F definitions and NN direction (reconstruction to GT versus GT to
  reconstruction), tau units, empty inputs, duplicate points.
- Umeyama reflection guard, trimmed ICP convergence and trimming fraction, whether scale can
  leak into "aligned" anywhere.
- Completeness denominators (ADR-022) and how S8 turns scores into met / not met / not
  measurable. Find any input for which a verdict says "met" when it should not.

**D. Ingest and screening.** `src/ingest/video_ingest.py`, `src/ingest/screen.py`.
- Frame indices through the whole of S1: decode order, `skip_start_s`, `end_s`, shot
  selection, crop, the second decode pass, keyframe filenames, telemetry lookup. The second
  pass must return exactly the analysed frames. Check seeking, B-frames, variable frame
  rate, rotation metadata, and odd resolutions.
- Keyframe selection edge cases: zero frames pass the blur gate, one shot, all sky, a clip
  shorter than the analysis window, `target_keyframes` larger than the frame count.
- SRT parsing: every family in `research/04-dji-srt-formats.md`, unit handling, sign of
  longitude, altitude fields, NaN and zero fixes, the "longtitude" spelling.
- Screening thresholds: can an admissible clip be rejected, or a hopeless one accepted,
  because of sampling (about 140 frames) or division by zero?

**E. Geometry bridge and MVS.** `src/pipeline/colmap_export.py`, `mvs_job/run_mvs.py`,
`mapanything_job/run_mapanything.py`, `src/pipeline/fuse_mesh.py`, `tools/finish_kolu.py`,
`tools/finish_mvs.py`, `tools/build_viewer.py`.
- Pose conventions end to end: MapAnything cam2world (which axis convention?) to COLMAP
  world2cam quaternion `(w, x, y, z)` and translation. Build a two-camera example in
  scratch and check the reprojection of a known point.
- Intrinsics from the model grid back to the full frame: resize factor, centre-crop offset,
  half-pixel convention, and the non-centred S1 crop case.
- Image and camera id mapping through `database.db`, image ordering, and what happens when
  MapAnything and COLMAP disagree on the image list.
- Gates: the confidence percentile, the 2.0 px intrinsics residual guard, the BA gate in
  docs/09. Are thresholds data-independent where the handbook says they must not be?
- Subprocess calls: argument construction, shell use, return-code handling, partial outputs
  treated as success, files over 900 MB skipped silently.
- fuse_mesh: confidence gating, outlier removal, voxel size, normal orientation and the
  inside-out Poisson risk.

**F. Orchestrator.** `src/tesseract/pipeline.py`, `contracts.py`, `stages.py`, `cli.py`,
`report.py`.
- Cache keys: which inputs are hashed? Change each of source file, config, calibration
  file, stage version, ladder level and an upstream artefact, and check that resume re-runs
  what it must. Prove any stale-reuse case with a scratch script.
- Ladder: budget accounting across restarts, a stage that fails at every level, fatal versus
  non-fatal classification, and whether the final manifest reflects the level that actually
  produced each artefact.
- Manifest validator versus manifest writer: fields written but not validated, validated but
  never written, and schema drift against docs/09.
- Artefact hashing: are hashes taken after the file is fully written, and does `verify`
  re-hash everything it claims to?

**G. Web upload path.** `run_job/run_upload.py`, `demo/api/_lib.js`, `runs.js`, `start.js`,
`status.js`, `file.js`, `tools/run_template.html`, `tools/build_run.py`.
- Model `status.json` as a state machine. For every failure point (screen refusal, ingest
  crash, child job failure, child job timeout, finish script failure, container OOM or
  SIGKILL, a retry), what does the browser see? Can a run hang in a non-terminal state
  forever?
- Child job handling: how completion and failure are detected, how the single retry is
  gated, what the 3 h job timeout does to the orchestrator, and per-execution env overrides.
- Limits: compare every limit across the three places it is defined. Check which limits are
  enforced server-side and which only in the browser.
- API security and cost: input validation of `runId`, `name`, `type`, `p`; signed URL
  scope, expiry, method and content constraints; path traversal; header injection through
  the filename in Content-Disposition; SSRF; information leakage in error bodies;
  concurrency races between check and act; pagination of `listExecutions`; what an
  anonymous caller can make the system spend. Rate each by realistic cost, not theory.
- Untrusted video: the uploaded file is decoded by PyAV and OpenCV in the job. Note decoder
  exposure and resource exhaustion (duration, resolution, frame count) before and after the
  checks in `run_upload.py`.

**H. Export formats.** `src/pipeline/export_formats.py`, `stages.Export`.
- LAS: scale and offset choice for large coordinates, header bounds, CRS writing, point
  format, colour depth.
- GeoTIFF: transform, row order, pixel-is-area, nodata, CRS present or deliberately absent.
- glTF/GLB axis swap handedness and winding; OBJ/PLY frame; FBX fallback behaviour when
  assimp is missing (is that reported as a missing format, or silently dropped from the
  "seven files" claim?).
- All seven files in one frame: check that no file is written in a different frame, scale or
  origin from the others, and that export_manifest.json says so truthfully.

**I. Claims surfaces.** Tier 2 builders and templates listed in CONTEXT.md section 7.
- Measurement code in each template: factor handling, units label, rounding, the
  `D.scale * 32767 / 32000` constant, and int16 quantisation error relative to the scene
  extent.
- `tools/build_qa.py` `check_numbers`: a figure can be present in its source and still
  wrong. Spot-check the five figures that matter most for R-O3 and R-O2 against the code
  that produced them.

### Phase 4: cross-cutting sweeps

Grep the whole repository for each of these and check every hit:

- Sim(3) call sites and the order they unpack: `umeyama`, `robust_sim3`, `yaw_only_sim3`,
  `robust_yaw_sim3`, `sim3_from_pairs`, `robust_sim3_from_pairs`, `apply_transform`.
- `float32`, `astype(`, `np.save`, PLY/LAS/glTF writers: any F6/F7 coordinate stored or
  written with less than float64 precision, or without an offset.
- `sys.path.insert`: import shadowing between `src/`, `src/pipeline/` and `tools/`
  (two modules with the same bare name, or a module importing a different file than the one
  its author meant).
- `subprocess`, `os.system`, `shell=True`: argument injection from filenames, env or
  uploaded data.
- Every environment variable read in Python and JS: default values, type conversion, and
  mismatches between the reader and whatever sets it (Dockerfiles, deploy yaml, `start.js`
  overrides, `run_upload.py` child overrides).
- `except` blocks: broad catches that turn a wrong result into a silent success, or that
  swallow the exception a caller needed to step down the ladder.
- Randomness: unseeded RNGs in code whose output is published as a measured number.

### Phase 5: verify, then try to kill your own findings

For every candidate finding:

1. Pin it to `file:line` and quote the lines.
2. Write the concrete failure scenario: these inputs, this state, then this wrong output or
   crash. "Could be wrong" is not a scenario.
3. Reproduce it when you can: a minimal script under `audit/codex/scratch/` that imports the
   real module, runs the failing case and prints the wrong value next to the right one. A
   reproduced finding is CONFIRMED. A finding you reasoned through carefully but could not
   run is PLAUSIBLE, and you must say what stopped you running it.
4. Argue against it. Look for the guard you might have missed: a caller that normalises the
   input, a check upstream, a docs statement that this is intended. Check CONTEXT.md
   section 4. If the finding survives, keep it; if it does not, move it to the "refuted"
   list with one line on why. Keeping refuted leads visible is worth more than a clean list.
5. Collapse duplicates to their root cause. Five symptoms of one bug are one finding with
   five locations.

### Phase 6: write `audit/codex/FINDINGS.md`

Use exactly this structure.

```markdown
# Core logic audit: findings

Date, commit (git rev-parse HEAD), model, total time spent.

## Summary
Counts by severity and by area. The three findings that matter most for the judged
targets, one sentence each.

## Findings
One block per finding, most severe first:

### F-01 <one-line title>
- Severity: S1 | S2 | S3 | S4
- Status: CONFIRMED | PLAUSIBLE
- Area: A-I
- Location: path:line (and any further locations of the same root cause)
- Invariant broken: which one, and its source
- What is wrong: two to four sentences
- Failure scenario: concrete inputs -> wrong output or crash
- Evidence: the quoted lines, plus the scratch command and its output if reproduced
- Impact: which R-O target, public claim, or cost it affects
- Suggested fix: the smallest change that fixes the root cause; do not apply it
- Test that would catch it: one sentence
- Related known issue: section 4 row, or "none"

## Refuted leads
Each lead from CONTEXT.md section 5 and each candidate you dropped, one line each, with why.

## Coverage
Every Tier 1 and Tier 2 file with: read in full / partially / not read, and a one-line
verdict. The invariant list from phase 2, each marked checked-holds, checked-broken (with
finding id), or not checked (with reason).

## Environment and tests
Phase 1 results. Every check you could not run and what it needed.

## Open questions for the maintainers
Things that depend on intent you could not determine from code or docs.
```

Severity scale:

- **S1**: silently wrong georeferencing, scale, units or verdict on a path the finale or the
  public site uses; a false metre or accuracy claim reaching a public surface; a crash on
  valid input on the finale path; anonymous abuse with real cost or credential exposure.
- **S2**: wrong under realistic but less common conditions, or latent and certain to bite
  when a recorded gap closes (for example, when C-3 wires real GNSS into S5).
- **S3**: robustness and edge cases that fail loudly, or wrong only on unusual inputs.
- **S4**: minor correctness issues with no effect on any number or claim. Cap these at ten
  and list them briefly at the end.

## Quality bar

- Depth beats breadth. One confirmed S1 with a reproduction is worth more than twenty
  speculative S3s. But do cover every Tier 1 file: the coverage section must show it.
- Numbers need units. Every length you quote says whether it is metres or model units.
- Do not trust a comment, docstring or doc that says something is handled. Find the line
  that handles it.
- Do not report style, naming, missing type hints, missing docstrings, or code you would
  have structured differently.
- Do not pad. If an area is clean after a real look, say so in the coverage section.
- When you finish, print the path of FINDINGS.md and the summary section to stdout.
