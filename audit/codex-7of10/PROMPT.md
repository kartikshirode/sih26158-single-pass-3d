# Codex run: audit the last results and plan the run that gets to 7/10

A drone-video-to-3D pipeline runs on one laptop. The last run (branch `codex-opt`) made it
fast enough for a ten-minute clip and metric on synthetic clips, but the model still
looks the way the owner rated it: 5/10. The owner wants 7/10, not perfection.

This run doesn't reconstruct anything. It does four things with what's already on disk:

1. **audit** the last run's results and code, checking each claim against its files;
2. **diagnose** why the model looks wrong (colour patches, holes, a shredded far edge) and
   why real clips aren't metric, using the saved outputs;
3. **research** technology that could fix those problems on this hardware under the
   licence rules;
4. **plan** the next run: a ranked, timed, one-night experiment plan that the next run can
   follow as its instructions.

## Before anything else

1. Read `audit/codex-7of10/CONTEXT.md` in full. Section 1 has the 7/10 scorecard, section
   3 the open problems, section 4 the leads nobody has followed yet.
2. Read `research/11-codex-optimisation.md`, `audit/codex-opt/REPORT.md` and
   `audit/codex-opt/RUNLOG.md` in full, then ADR-029 to ADR-032 in `docs/10-decision-log.md`.
   Don't propose anything RUNLOG.md already rejected unless you name the new reason.
3. Read the Overview of `.claude/codemap.md` and `CLAUDE.md`. Route with the codemap, then
   read the files themselves.
4. Create the branch: `git switch -c codex-7of10` from `codex-opt` (4de9efa or later).
   Every commit of this run goes on `codex-7of10`.

## Ground rules

Allowed:

- Read anything in the repository and under `out/` except `.env`.
- Run the tests in CONTEXT.md section 7.
- CPU-only analysis of saved outputs: Python scripts over the run folders' `.npy`, OBJ,
  atlas, PLY, logs and keyframes; `tools/geometry_check.py`; `tools/view_check.py`
  without `--build`; `out/codex/b3_truth.py`; S5 replays in the style of
  `out/codex/replay_s5.py`. Put scripts and their output under `out/codex/7of10/`. Stop
  any single job that goes past 10 minutes, and move it to the next run's plan instead.
- `--help` or version probes of COLMAP and OpenMVS (they write logs into the working
  folder; run them from `out/codex/7of10/` and delete the logs).
- Web research: papers, project pages, release notes, licences, issue trackers.
- Code changes on the branch for S1 and S2 findings only, each with a test that fails
  before the fix and passes after.

Forbidden, no exceptions:

- **Any reconstruction or GPU work.** No `tesseract.py run`, no `view_check.py --build`, no
  COLMAP or OpenMVS processing, no MapAnything, no model inference, nothing that loads
  the GPU. The next run does that.
- Installing packages or downloading weights or binaries. Write the install into the plan
  with its size, licence and undo instead.
- Deleting anything under `out/`, including the superseded runs listed in CONTEXT.md
  section 5. The plan says what to delete; the owner approves it.
- Reading, printing or using `.env`.
- Cloud compute or paid services of any kind (`gcloud`, `vercel`, vast.ai, Colab, Kaggle),
  and `docker`.
- `git push`, any git command on `master`, `audit-fixes` or `codex-opt`, `commit --amend`,
  `rebase`, `reset --hard`, `clean`, `stash drop`, `checkout -- <path>`, `--no-verify`,
  force of any kind, a branch other than `codex-7of10`, or a git config change.
- Committing `.gitignore` (the owner's uncommitted edit), `.env`, anything under `out/`,
  the two GC-1 files in the repo root, `SIH DEMO.mp4`, or any frame, crop or render made
  from it. Pictures from B1 stay under `out/`.
- Running `tools/build_*.py`, including `build_run_page.py` (it overwrites the final
  runs' pages), or `src/experiments/exp14_scale_audit.py`.
- Starting a web server. The run pages open from disk as `file://` URLs.

If a step needs something forbidden, write it into the next-run plan and carry on.

## Records

Everything goes under `audit/codex-7of10/`, written as you go:

- `LOG.md`: every script or command you ran on the outputs, one row each: what, why, the
  result, the path of its output.
- `FINDINGS.md`: phases 1 to 3.
- `RESEARCH.md`: phase 4.
- `NEXTRUN.md`: phase 5.
- `REPORT.md`: phase 6.

Commit at the end of each phase.

## Phase 0: the machine

Record free disk on C: and whether another process holds the GPU (`nvidia-smi`). Run every test in CONTEXT.md section 7 and record pass or
fail. A failure is a finding, not a reason to stop.

## Phase 1: audit the results

For each of the four final runs (CONTEXT.md section 2), check each number research/11 and
REPORT.md state against the files on disk: wall time and stage times from the manifest,
focal lengths and the gate facts from `local_gpu_result.json` and the manifest, the S3b
figures, `truth_check.json` on B3 and B5v, the formats in `export/`, the verdicts. Recompute
what you can cheaply (`b3_truth.py`, `geometry_check.py`).

Then check the claims that aren't just numbers:

- that B1, B2 and B3 take the same focal decision under the final gate as in their v2 runs;
- that each export is in the frame the manifest says, and that the mesh and the cloud line
  up in it (sample vertices against the nearest cloud points);
- that the atlases in `export/` match the ones in `geometry/`;
- that the ten-minute prediction in research/11 section 10 follows from the stage rates it
  cites.

Any claim that doesn't hold is a finding with the file, the stated value and the value on
disk.

Score the current state against every row of the scorecard (CONTEXT.md section 1), with the
number and where it came from. Where a bar can't be measured without a GPU run, say so,
and put that measurement first in the next-run plan.

## Phase 2: diagnose what looks wrong

Work on the saved outputs only. The goal is the cause of each fault, with evidence, so the
next run tests fixes rather than guesses.

1. **Colour patches.** Define a seam metric before you use it, and write the definition
   into FINDINGS.md. One option: the colour step across texture-patch borders against the
   step between neighbouring texels inside patches, from the OBJ's UVs and the atlas.
   Check it against the pictures: it must rank B1's visible patchwork worse than B3's.
   Then find the cause:
   - B3 and B5v are rendered with constant lighting. Do they show patches too? If they
     do, exposure isn't the cause.
   - For B1, compare neighbouring patches with the keyframes they came from: exposure
     (a gain across the whole patch), view angle, misregistration (edges that don't meet),
     or blur.
   - Read the TextureMesh logs of the final runs and of TX1, TX2 and Q1, and OpenMVS's
     seam-levelling source at the version in use, to explain why levelling blackens the
     atlas. Name the suspected cause and the cheapest test that would confirm it.
2. **Holes.** Count the mesh's uncovered faces and the held-out pixels the mesh misses.
   Sort the holes by cause: never seen, seen only at a grazing angle, filtered out in
   densify or fusion, or removed as spurious faces. Use the dense cloud, the cameras and
   `scene_dense.mvs`.
3. **Far field.** Point density, mean view angle and triangle size against distance from
   the cameras on B1. How much of the far field does the horizon crop remove, in pixels
   and in fraction of the views that see it?
4. **Metric accuracy without a gimbal pitch.** Replay S5 on B3 and B5v with the pitch taken
   out, and record the error (the scorecard's accuracy bar). Then test the leads in
   CONTEXT.md section 4 offline:
   - the SRT's `focal_len` turned into pixels (B3: 24.00 mm against a true 1066 px);
     report the crop factor it implies and what is known about DJI video crops per model;
   - the horizon row in B1's keyframes and what it implies for pitch and focal length
     together;
   - `rel_alt` against the model's ground plane on B3.

   For each, the error it would leave on B3 and B5v if S5 used it, from a replay. A
   replay is evidence, not a result: the next run confirms it end to end.
5. **Nicosia's coverage.** Why 72%: where the missing pixels are, and whether any setting
   could recover them or the scene simply has no parallax there.

## Phase 3: audit the code

Read, line by line, what `codex-opt` changed since `audit-fixes` (0340d7e); `git diff
audit-fixes..codex-opt -- src tools` is about 1,800 lines. Spend most of the time on the
last night's changes:

- the gimbal-pitch correction and the stretch in `src/tesseract/stages.py` (`_from_srt`,
  `_focal_from_pitch`, `_stretch`, `_apply_frame_json`) and its constants;
- the turn gate in `src/pipeline/local_gpu.py` (`attitude_turn_deg`, `_mean_rotation`,
  the mapper cross-check in `run()`);
- `keyframe_budget` and SRT interpolation in `src/ingest/video_ingest.py`;
- the multi-material export in `src/pipeline/mesh_export.py`;
- the catch-all in `src/tesseract/pipeline.py`;
- `tools/build_run_page.py` and `tools/view_check.py`.

Look for a confident wrong number on an unknown clip first: a pitch correction applied
when it shouldn't be (a clip that climbs, a gimbal that moves during the clip, a pitch
field in a different convention, a nadir camera), a stretch that doesn't reach every
output, a turn gate fooled by one bad window. Then crashes and missing manifests, then
cache keys that miss an option. Re-check F19 to F22 and say whether each still stands.

Pin each finding to `file:line` with a concrete scenario, reproduce it with a unit test or
a replay when you can, and argue against it before you keep it. Severity as before: S1
wrong model, number or crash on a finale path; S2 the same under less common conditions;
S3 fails loudly on unusual input; S4 minor. Fix S1 and S2 on the branch, one commit per
fix, each with its test, plus the codemap entries for the files it touches. List the rest.

## Phase 4: research

Write `RESEARCH.md`, organised by problem, not by stage:

1. colour patches and seam levelling;
2. holes and the far field;
3. metric scale and focal length without a gimbal pitch;
4. B2-style scenes with little parallax;
5. what a judge sees first: the viewer, and anything that makes the model look better
   without changing its geometry (for example a Gaussian-splat view trained on the same
   poses beside the mesh);
6. speed, only where a fix above would cost time.

For each option: what it would change, on which benchmark, the expected gain (a
prediction, labelled as one), the time it adds to B1 and B5v, the VRAM it needs on 8 GB,
whether it runs on Windows without WSL, the licence of the code and of the weights, each
checked at the source with a link, the install size, and the risk.

Cover at least these, and add whatever you find that fits better:

- fixing OpenMVS seam levelling: another OpenMVS release or build, image format or gamma,
  option combinations, the cause found in phase 2;
- `mvs-texturing` (texrecon) as the texturing step;
- levelling outside OpenMVS, on the finished OBJ and atlas, in numpy (CONTEXT.md section 4);
- exposure normalisation from the SRT's `iso`, `shutter` and `ev`;
- screened Poisson or another surface fitted to the dense cloud to close holes, trimmed by
  point density;
- depth from MapAnything or another permissively licensed model to fill where PatchMatch
  fails, and full frames with a sky mask instead of the horizon crop;
- ALIKED with LightGlue in COLMAP 4.2 for the far field and low texture;
- single-image calibration models (for example GeoCalib) and the SRT's `focal_len`, `rel_alt`
  and the horizon for the focal length;
- Gaussian splatting under a permissive licence (for example gsplat) for a photoreal view,
  with its training time on this GPU;
- feed-forward reconstruction or depth models released in 2026, licences checked.

End with one ranked list across all problems, ranked by how much each moves the scorecard
per hour of work and run time, each with the experiment that tests it.

## Phase 5: the next-run plan

Write `NEXTRUN.md` so that the next run can follow it as its instructions. It has to fit
one night (about 8 hours) on this laptop, with another session sometimes using the GPU.

1. **Before the first run:** the disk clean-up the owner needs to approve (from CONTEXT.md
   section 5), the installs and downloads in order with size, licence and undo command,
   and the GPU check to do before every heavy job.
2. **The measurement that comes first:** the scorecard rows phase 1 couldn't measure
   (held-out scores on the current code, with `--build`), so every experiment compares
   against a fresh baseline.
3. **The experiments, in order.** For each: the scorecard row it targets, the hypothesis,
   the single change (the exact option, command or code change), the benchmark order
   (which clip first, and why), the expected time and disk, the numbers that decide it, and
   the keep rule. The keep rules from `audit/codex-opt/PROMPT.md` phase 4 still apply,
   plus: the seam metric doesn't get worse, uncovered faces don't rise, and the accuracy
   bar holds with and without a gimbal pitch.
4. **A schedule:** each experiment's slot and a running total of hours. Put the ones most
   likely to reach 7/10 early, so a night that ends halfway still delivers.
5. **Stop rules:** when to abandon an experiment, what to do if the disk falls near 100 GB,
   and what to do if the GPU is busy.
6. **The final measurement:** which clean runs, which checks, which screenshots, and the
   before and after table against the scorecard.
7. **What a 7/10 claim needs:** the list of numbers and pictures the owner should see
   before calling it 7/10.

Keep the plan honest: if the evidence says a bar can't be reached on this laptop in one
night, say which bar, why, and what it would take.

## Phase 6: report

`REPORT.md`, one screen for the owner:

1. the scorecard: each row, its number now, and the bar;
2. the three findings that matter most from phases 1 to 3;
3. the cause of each visible fault, one line each;
4. the top five experiments for the next run, with the expected gain and the hours;
5. what the owner has to decide or approve (disk clean-up, installs, anything forbidden
   here that the plan needs).

Then commit, and print `git log --oneline codex-opt..codex-7of10` and REPORT.md to stdout.

## Writing and commits

- Prose: no em dashes or en dashes; commas, colons or new sentences, and plain hyphens for
  ranges. Plain words. Follow the house style of research/11.
- Numbers carry units and a source: "B1, 22.822 dB held out (RUNLOG.md, b360949)", never
  "better". A prediction says it's one and what it rests on. Model units unless a scale
  was validated from outside the model.
- Don't improve a number by changing how it's computed.
- Commits: plain sentence-case subject in the imperative, no prefix, 50 to 72 characters,
  no full stop, matching `git log --oneline -20`. A body when the why isn't obvious. No
  `Co-Authored-By`, no tool or model name, no "generated by", no emoji. One concern per
  commit, explicit paths, never `git add -A` or `git add .`.
- Update `.claude/codemap.md` for every file you add or change, in the same commit (LF
  line endings in the codemap; `docs/09`, `docs/10` and `docs/14` use CRLF).
