# Codex run: audit and optimise the local GPU pipeline

You are taking a working drone-video-to-3D pipeline on one laptop and making it as good and
as fast as this hardware and these models allow. The owner's target: a 10-minute 1080p
30 fps video, video in to textured 3D model out, in under 15 minutes, with the best model
the machine can make. Today the model is correct in shape but rated 5/10, and the run is
about 11 times over its time budget on the reference clip.

This is four jobs in one run: **measure** the current state honestly, **research** what
could be better, **audit** the code that was just written, and **optimise**, keeping only
changes that the numbers support. You may change code. Every change is measured, committed
on its own, and written up.

## Before anything else

1. Read `audit/codex-opt/CONTEXT.md` in full: the target, where the pipeline stands, what
   was already tried (do not repeat it), the benchmarks and budgets, the machine, the
   licence rules and what is out of scope.
2. Read the Overview of `.claude/codemap.md` and `CLAUDE.md`. Route with the codemap, then
   read the files themselves; an entry is a summary, the file is the authority.
3. Read `research/10-reconstruction-quality.md` and `research/09-gpu-pipeline.md`, then
   ADR-027 and ADR-028 in `docs/10-decision-log.md`.
4. Create the branch: `git switch -c codex-opt` from `audit-fixes` (commit 254aa0d or
   later). Every commit of this run goes on `codex-opt`.

## Ground rules

Allowed:

- Read anything in the repository except `.env`.
- Run the pipeline, the tests, COLMAP, OpenMVS, MapAnything and headless Chrome locally.
  Put run outputs under `out/runs/codex-*` and scratch output under `out/codex/`.
- Edit and add code, tests and docs, and commit them on `codex-opt`.
- Research on the web: papers, project pages, release notes, licences.
- Install a Python package or download model weights, but only when an experiment needs it,
  its licence allows it (CONTEXT.md section 6), the total added stays under 15 GB, and each
  install goes in the machine table in `RUNLOG.md` with the command that undoes it. Install
  into the global Python 3.12; there is no venv, and the owner asked for none.

Forbidden, no exceptions:

- Reading, printing or using `.env` (it holds a vast.ai key).
- Any cloud compute or paid service: `gcloud`, `gsutil`, `bq`, `vercel`, vast.ai, Colab,
  Kaggle, or anything that rents a GPU. `docker`. Calls to `tesseract-demo.vercel.app` or
  `storage.googleapis.com`.
- `git push`, and any git command on `master` or `audit-fixes`. No `commit --amend`,
  `rebase`, `reset --hard`, `clean`, `stash drop`, `checkout -- <path>`, `--no-verify`, or
  force of any kind. No new branch other than `codex-opt`. No change to git config.
- Committing `.gitignore` (it holds the owner's uncommitted edit), `.env`, anything under
  `out/`, the two GC-1 files in the repo root, `SIH DEMO.mp4`, or any frame, crop or
  render made from it.
- Changing the machine outside the repository beyond the installs above: no driver, power
  plan, WSL, Docker, registry or system setting; no deleting anything you did not create.
- Running `tools/build_*.py` other than `tools/build_run_page.py` (the others overwrite
  committed pages under `demo/`), or `src/experiments/exp14_scale_audit.py`.
- Letting free disk space on C: fall below 100 GB. Delete your own bulky intermediates
  (depth maps, undistorted images, databases, experiment runs you have finished with) as
  you go, and say what you deleted.

If a step needs something forbidden, write what you would have done and why in
`RUNLOG.md`, and carry on with the rest.

## Keeping records

Three files under `audit/codex-opt/`, written as you go, not at the end:

- `RUNLOG.md`: a machine table (installs, downloads, deletions: what, where, size, how to
  undo), then one row per experiment in order: id, hypothesis, the single change, the
  benchmark, time, the quality numbers, kept or rejected, commit hash if kept.
- `RESEARCH.md`: phase 2.
- `REPORT.md`: phase 6.

Commit these files at the end of each phase. They are the audit trail; a result that is not
in `RUNLOG.md` did not happen.

## Phase 0: check the machine

Confirm `SIH_COLMAP` and `SIH_OPENMVS` point at working tools (CONTEXT.md section 5), that
torch sees the GPU, and that free disk is above 100 GB. Run every test in CONTEXT.md
section 8 and record pass or fail. A failure here is a finding, not a reason to stop.

## Phase 1: baseline, and the missing quality check

1. **Build the held-out view check first.** Add `tools/view_check.py`. Hold out every Nth
   keyframe (N = 10 unless you have a reason) from densification and texturing; `local_gpu`
   already takes `dense_names`, so the held-out views still get poses but never feed the
   model. Render the textured mesh into each held-out camera. Score it against the real
   frame over the pixels the mesh covers (PSNR and SSIM), and report coverage separately so
   a model cannot score well by covering less. The held-out views must be the same frames
   before and after every change you compare. Add a small test for the projection maths:
   a known point, a known camera, the expected pixel.
2. **Measure the baseline** with the code as it is on `audit-fixes`, on B1, B2 and B3 at
   least (CONTEXT.md section 4). For each, record in `RUNLOG.md`:
   - wall time, R, and the per-stage table;
   - `tools/geometry_check.py`;
   - the S3b figures from `geometry/local_gpu_result.json`;
   - the held-out view check;
   - a screenshot of `tools/build_run_page.py`'s page (it stays under `out/`, never
     committed).
3. **Measure the long clip.** Run B4 for S0 and S1 timing. Build B5 (CONTEXT.md section 4)
   or, if a 600 s render is too slow, the longest render you can justify. Time S3 on
   roughly 600 keyframes; the global mapper's cost at that size is the biggest unknown in
   the time budget.
4. **Profile.** For B1 and the long clip, record GPU utilisation and memory, CPU
   utilisation, and which stages leave the GPU idle. Find where the time goes before you
   try to save any.

Commit `tools/view_check.py`, its test and the baseline section of `RUNLOG.md`.

## Phase 2: research

Write `RESEARCH.md`. For each stage below, list the realistic options, what each should
gain in quality or time on this hardware, its cost, its licence, its risk, and a source.
End with one ranked list of candidates across all stages, each with the experiment that
would test it. Be concrete about this laptop: 8 GB of VRAM, CPU-only bundle adjustment,
Windows builds.

1. **Keyframes and cropping.** The 37% horizon crop throws away most of what sees the far
   field. Compare full frames with a sky mask (OpenMVS and COLMAP both take masks) against
   the crop. Keyframe count against quality and time: is 177 for 19 s more than the
   geometry needs? Frame spacing by baseline rather than flow.
2. **Camera and poses.** Reusing MapAnything's poses as priors (`pose_prior_mapper`,
   position priors, or initialising the global mapper) instead of discarding them.
   global_mapper options and their cost; whether this COLMAP build can run bundle
   adjustment on the GPU at all; splitting long sequences into overlapping sub-models and
   merging. Feature choice: SIFT count, and whether COLMAP 4.2 offers learned features
   and matchers (ALIKED, LightGlue, or others) on Windows, with their licences.
3. **Dense.** Resolution level 0 against 1, views per depth map, views to fuse, geometric
   iterations, depth-map filtering, and a depth or range gate for grazing far-field points.
   Whether MapAnything's own depth can seed or fill in where PatchMatch fails.
4. **Mesh and texture.** ReconstructMesh settings, RefineMesh (quality against time),
   decimation, texture resolution. Why seam levelling blackens the atlas here (image
   format, gamma, a Windows-build bug, an option combination) and how to get levelling
   back. The uncovered faces.
5. **Models.** Any feed-forward reconstruction or depth model released under a permissive
   licence that could beat or complement MapAnything here: poses, depth, or intrinsics.
   Check each licence at its source. Barred models (CONTEXT.md section 6) may appear in
   the table for comparison only.
6. **Throughput.** Overlapping CPU and GPU stages, keeping one process and loaded weights
   warm, decode and JPEG costs, OpenMVS thread settings, anything that leaves the GPU idle.
7. **What the pipeline does not do yet** (additions): the textured mesh carried into
   `export/` in the levelled frame as OBJ, glTF/GLB and FBX (R-O5 to 6 of 6); feeding SRT
   GPS into S5 so a clip with telemetry comes out georeferenced and in metres (gap C-3, B3
   exercises it); anything else that moves a judged number. Rank these by judged value
   (CONTEXT.md section 1) against effort.

## Phase 3: audit the new code

Before optimising code, check it is right. Audit, line by line:

- `src/pipeline/local_gpu.py`
- `select_keyframes` and its callers in `src/ingest/video_ingest.py`
- the local provider and the S3 estimate in `src/tesseract/stages.py`
- `tools/build_run_page.py`, `tools/run_page_template.html`
- `tools/geometry_check.py`

Look for:

- anything that would crash or mislead on an unknown clip: views split into several
  models, a mapper that registers too few views, a clip with no horizon, a very short clip,
  a clip with no texture, 8 GB running out;
- frames and units: every length in model units unless validated;
- failure paths that leave no manifest;
- cache keys that miss a new option.

Pin each finding to `file:line` with a concrete failure scenario, reproduce it when you
can, and argue against it before you keep it. Fix S1 and S2 findings on the branch, each
with a test that fails before the fix and passes after, one commit per fix. List the rest
in `REPORT.md`.

Severity: S1 wrong model, wrong number or crash on a path a finale clip takes; S2 wrong
under realistic but less common conditions; S3 fails loudly on unusual input; S4 minor.

## Phase 4: optimise

Work through `RESEARCH.md`'s ranked list. **Quality first, then speed.** A faster wrong
model is worth nothing; a better model that busts the budget is a finding, not a result.

For each experiment:

1. Write the hypothesis and the single change in `RUNLOG.md` before running it.
2. Change one thing. Run it on B1 first; take anything that survives to B2 and B3.
3. Compare against the current best, not the original baseline.

Keep a change only if all of these hold on every benchmark it ran on:

- every view registered, reprojection error at most 1 px;
- sparse_on_plane falls by no more than 0.02, layered_cells rises by no more than 0.01,
  and step_ratio stays at or under 3;
- held-out PSNR falls by no more than 0.3 dB and held-out coverage by no more than 2
  points, unless the change is a deliberate time-for-quality trade you justify in
  `RUNLOG.md`;
- the change improves at least one of: held-out PSNR or SSIM, coverage, the geometry
  numbers, or wall time.

A kept change is one commit: the code, its test where one makes sense, the codemap
entries for every file it touched (CLAUDE.md), and a line in `RUNLOG.md` with the commit
hash. A rejected change is reverted in the working tree (never with a destructive git
command on committed work) and recorded with its numbers. Rejected results are as useful
as kept ones; do not drop them from the log.

Then, with the best settings found, work on time until B5, or the long clip you built,
comes in at R <= 1.5 end to end. If it cannot, say by how much it misses, which stage
holds it back, and what hardware or model change would close the gap. Update
`Geometry.S_PER_VIEW_LOCAL_*` in `src/tesseract/stages.py` to the rates you measured, so
the ladder budgets match reality.

Take the additions from phase 2 in their ranked order once the core pipeline is settled,
each under the same rules.

## Phase 5: final measurement

On the final branch state:

1. Run every test in CONTEXT.md section 8.
2. Rerun B1, B2, B3 and the long clip end to end from a clean run directory (no resume),
   with `python tesseract.py verify <run>` on each.
3. Rebuild each run's page and take the screenshots.
4. Build the before and after table: baseline against final, every benchmark, every
   number from phase 1.

## Phase 6: write it up

1. `research/11-codex-optimisation.md`, for the team:
   - what changed and why, with the numbers;
   - what was tried and rejected;
   - what is still wrong;
   - the machine changes and whether each was undone;
   - how to reproduce.

   Follow the house style of `research/10`. No em dashes or en dashes anywhere in the
   prose: use commas, colons or new sentences, and plain hyphens for ranges.
2. A new ADR in `docs/10-decision-log.md` for every architectural decision (a new model, a
   new stage, a change of tool), in the existing ADR format.
3. `audit/codex-opt/REPORT.md`: a one-screen summary for the owner (the before and after
   table, the three biggest wins, the open problems), then the phase 3 findings in full.
4. Commit, then print `git log --oneline audit-fixes..codex-opt` and the summary of
   `REPORT.md` to stdout.

## Commit style

- Plain sentence-case subject in the imperative, no prefix like `feat:`, 50 to 72
  characters, no trailing full stop. Match `git log --oneline -20` on `audit-fixes`.
- A body when the why is not obvious: what was measured and what it showed.
- No `Co-Authored-By` line, no tool or model name, no "generated by", no emoji.
- One concern per commit. Stage explicit paths; never `git add -A` or `git add .`.

## Quality bar

- Numbers need units and a benchmark: "B1, 2.1 dB better held-out PSNR", never "better".
- Measured beats predicted. When you do predict, say it is a prediction and what it rests
  on.
- Never print metres for a model whose scale was not validated from outside it; say
  "model units".
- Do not optimise the checks. If a change improves a number by changing how the number is
  computed, it is not an improvement.
- If the evidence says the target cannot be met on this laptop, say so plainly with the
  numbers. That is a useful result.
