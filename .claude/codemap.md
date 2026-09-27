<!-- codemap-format: v1 -->

# Codemap: sih26158-single-pass-3d

## Overview

Smart India Hackathon 2026 problem statement SIH26158 (PS 17, NTRO, Software, Drone/Robotics): turn one monocular drone video from a single flight pass, plus GPS and flight metadata, into a georeferenced, metrically accurate, textured 3D model. Binding targets (only in docs/SIH26158.pdf, image-only PDF): R-O1 mesh or point cloud, R-O2 under 15 min for a 10-min video, R-O3 spatial accuracy 1 m or better, R-O4 entire visible scene, R-O5 OBJ/PLY/LAS/GeoTIFF/glTF/FBX, R-O6 web or desktop viewer. Scoring: accuracy 30, completeness 20, speed 20, innovation 15, scalability 10, UI 5. The product is called Tesseract.

Stack: Python 3.12 (3.11 inside the mvs image), numpy/scipy/open3d/trimesh/pyproj/laspy/rasterio. PyAV + OpenCV for ingest. MapAnything (Apache checkpoint facebook/map-anything-apache, never VGGT or the CC-BY-NC checkpoint) for poses and a metric prior. COLMAP for triangulation and bundle adjustment, OpenMVS (AGPL, run unmodified as a process) for densify, mesh and texture, assimp for FBX. GCP asia-south1 only (data residency, DST 2021 guidelines): project agentbillboard, bucket sih26158-mumbai, Cloud Run Jobs, CPU only because GPU quota is zero. The public site is a Vercel static site with Node 22 functions in demo/.

Stages (docs/00-start-here.md 5.3, contracts in docs/09): S0 screen (admissibility, src/ingest/screen.py), S1 ingest (decode, crop, shots, SRT telemetry, keyframes, src/ingest/video_ingest.py), S2 plan, S3 geometry (MapAnything, mapanything_job/), S3b bundle adjust + S4 dense (mvs_job/), scale service, S5 georeference (5-DOF yaw+translation+scale fit in local ENU, EGM2008, UTM last), S5b level, S6 export (seven files), S7 score (src/eval3d/), S8 verdict (three-valued: met / not met / not measurable).

Three ways the code runs:
- Local orchestrator: `python tesseract.py run <clip|synthetic>` runs src/tesseract/ (stage DAG, content-addressed resume, budget, degradation ladder L0 full ... L5 screen-only). Output in out/runs/<name>/ (run_manifest.json, qa_report.md, export/). On a real clip S3 only works with `--adopt out/<run>`; S5 georeferencing only runs on the synthetic source.
- Web upload path: demo/run/ page -> demo/api/*.js -> Cloud Run job sih26158-run (run_job/run_upload.py) -> child jobs kolu-ma (MapAnything v2 image) then sih26158-mvs (COLMAP + OpenMVS) -> tools/finish_kolu.py (preview) and tools/finish_mvs.py (final). Contract is gs://sih26158-mumbai/web/<runId>/status.json. Bypasses the tesseract ladder on purpose.
- Legacy synthetic job: cloud_job.py + root Dockerfile run src/pipeline/run_demo.py (simulated depth, not MapAnything).

Frames and scale (read docs/08 before trusting any length): every coordinate is in one of F0-F7 (src/tesseract/contracts.py). F5 is gravity-level with arbitrary heading, not ENU. Scale status is unvalidated / calibrated / gnss / gnss+rtk; unvalidated runs print "model units", never metres. Kolu was found 5.3-5.8x too small (EXP-14); research/calibration/kolu.json holds factor 5.54 and applies only to runs listed in it. No global scale constant exists by design.

Where things live: docs/ is the engineering suite (00 narrative, 01 SRS, 09 contracts, 10 ADRs, 14 claims ledger, 18 roadmap and backlog). research/ holds findings and recorded experiment output. out/ is gitignored and holds every real run, but the tools/build_*.py builders read it, so built pages and mesh blobs under demo/ are committed. data/ holds sample clips (large raw data under data/cand, data/raw is gitignored).

Commands:
- `pip install -r requirements.txt`
- Tests (plain scripts, exit 1 on failure, not pytest): `python src/tesseract/test_tesseract.py`, `python src/eval3d/test_metrics.py`, `python src/ingest/test_srt.py`, `python src/ingest/test_frames.py`, `python src/pipeline/test_local_gpu.py`, `python src/pipeline/test_window_fuse.py`, `python src/pipeline/test_colmap_export.py`, `python mvs_job/test_ba_gate.py`, `python tools/test_console.py` (Playwright).
- `python tesseract.py run synthetic --gnss rtk` then `python tesseract.py verify out/runs/<name>`.
- `python tools/build_all.py` rebuilds console, demo, gallery and qa and runs the design and wiring audits; `tools/build_run.py` is separate. Deploy with `vercel deploy --prod --yes` from demo/ (git integration is disconnected).
- CI: .github/workflows/ci.yml runs the tests, a synthetic run + verify, the console test, the onboarding check and a licence check on requirements.txt pins.

Project-wide gotchas:
- Imports are sys.path based: scripts insert src/ (and sometimes src/pipeline/) and import `ingest.*`, `eval3d.*`, `pipeline.*`, or bare `gravity` / `render_views`. src/simscene has no __init__.py.
- The EGM2008 geoid grid must be available (baked into images; locally PROJ networking). PROJ silently returns heights unchanged without it, so the code raises instead.
- research/ is in .gcloudignore, so containers never see calibrations and their runs stay unvalidated.
- demo/**/index.html (except viewer/) are generated: edit tools/*_template.html or tools/build_qa.py, then rebuild and commit. The console carries a source-hash stamp that CI checks.
- DJI SRT fixtures are byte-exact test inputs (-text in .gitattributes).
- notebooks/*.ipynb are generated by notebooks/_build_nb*.py.
- Sim(3) fit return order differs: eval3d returns (R, t, s), window_fuse returns (s, R, t). A full 7-DOF fit on a straight pass is degenerate; use the yaw-only fit.
- Any change to a public number must update the claims ledger in docs/14 in the same change.
- Shared repo: commit on branches, never directly to master.

## (repo root)

### tesseract.py
Root launcher. Puts src/ on sys.path and calls tesseract.cli.main().
Used by: .github/workflows/ci.yml, run_job/Dockerfile (COPY), hint text in src/tesseract/test_tesseract.py and tools/build_console.py

### cloud_job.py
Entrypoint for the original synthetic-demo Cloud Run job. Runs src/pipeline/run_demo.run() twice (consumer and RTK GNSS) into /tmp/out/<gnss>, uploads to GCS and prints an RMSE/runtime table.
Exports: upload(local_dir, bucket, prefix) -> list[gs:// uris]; main()
Used by: Dockerfile (ENTRYPOINT)
Gotcha: env OUT_BUCKET (upload skipped if empty) and OUT_PREFIX (default "runs"). sys.path "src" is relative to the working directory. upload() is flat (os.listdir), so subdirectories in the output break it. Old run_demo path, not the tesseract pipeline.

### Dockerfile
Image for cloud_job.py: python:3.12-slim with requirements.txt and the EGM2008 grid baked in (build fails if the grid is unavailable). Copies src/ and cloud_job.py. No cloudbuild yaml references it.

### requirements.txt
Pinned core deps: numpy 2.2.6, scipy, trimesh, pyproj, laspy, rasterio, google-cloud-storage. CI fails if a pin is missing from the licence register in docs/11-state-of-the-art.md.

### .gcloudignore
Keeps .git, out/, docs/, research/, notebooks/, data/ and *.md out of Cloud Build uploads, so research/calibration never reaches images.

### .gitattributes
Marks src/ingest/fixtures/dji_srt/* as -text so DJI SRT fixtures keep exact bytes, BOMs and line endings, and pins .claude/codemap*.md to LF.

### CLAUDE.md
Agent instructions: the codemap pointer block (read the map first, staleness check, subagent forwarding, update entries in the same commit as the change).

### .gitignore
Ignores caches, venvs, out/, viewer/model.glb and viewer/run_manifest.json, data/raw, data/cache, data/cand, data/*.zip and .vercel.

## .github/workflows/

### .github/workflows/ci.yml
CI gate on push and PR (ubuntu, Python 3.12, PROJ_NETWORK=ON): compileall; test_metrics, test_srt, test_frames, test_local_gpu, test_mesh_export, test_window_fuse, mvs_job/test_ba_gate.py, src/pipeline/test_colmap_export.py, test_tesseract; a synthetic `tesseract.py run` then `verify`; tools/test_console.py (Playwright chromium); tools/check_onboarding.py; the upload API tests (`node --test "demo/test/*.test.js"`); a licence check that every requirements.txt pin is named in docs/11-state-of-the-art.md.
Gotcha: needs network for the geoid grid and a Playwright install. The demo build and audit gates are local only.

## src/tesseract/

### src/tesseract/__init__.py
Package barrel for the rebuilt pipeline; re-exports contracts, orchestrator, sources and DEFAULT_STAGES.
Exports: Artefact, Code, Frame, LADDER, LEVELS, RunManifest, StageError, StageResult, Units, validate_manifest, BaseStage, Context, Pipeline, State, SyntheticSource, VideoSource, DEFAULT_STAGES
Used by: tesseract.py (via tesseract.cli), tools/build_console.py (via tesseract.contracts), src/tesseract/test_tesseract.py
Gotcha: importing any submodule, even tesseract.contracts, runs this file, which pulls in stages.py (numpy, and src/ inserted on sys.path).

### src/tesseract/cli.py
argparse CLI with five verbs: `screen` (admissibility), `run` (Pipeline(DEFAULT_STAGES); `--geometry local` computes S3 on this machine's GPU), `calibrate` (writes a known-length scale JSON), `report` (prints qa_report.md), `verify` (checks a run against its contracts).
Exports: main(argv=None) -> int; cmd_screen/cmd_run/cmd_calibrate/cmd_report/cmd_verify(args) -> int
Used by: tesseract.py; .github/workflows/ci.yml
Gotcha: runs go to ROOT/out/runs/<name> and resume is on by default (--no-resume to disable). `calibrate` writes ROOT/research/calibration/<run>.json and has no effect until the pipeline is re-run. `verify` exits 1 on any problem, including sha256 mismatch or metres claimed on an unvalidated scale.

### src/tesseract/contracts.py
docs/09 as code: frames F0-F7, units (MODEL vs METRES), outcome codes, the L0-L5 ladder, Artefact/StageResult dataclasses, RunManifest (schema sih26158/run-manifest/1) and its validator. Does no work itself.
Exports: ROOT; SCHEMA_RUN_MANIFEST, SCHEMA_STATE; Frame (F0..F7, METRIC, is_georeferenced()); Units; SCALE_STATUS; units_for(status) -> str (raises on unknown); Code; StageError(code, msg, fatal=False); Level, LADDER, LEVELS; step_down(level) -> str | None; Artefact(path, kind, frame, units, sha256, bytes).stamp(root); StageResult; file_sha256(), config_sha256(), git_sha(); RunManifest.add(res)/write(path); validate_manifest(dict) -> list[str] (empty = valid)
Used by: src/tesseract/pipeline.py, stages.py, cli.py, report.py, sources.py, test_tesseract.py, tools/build_console.py
Gotcha: ROOT is three dirnames up from this file. Invariant: units must equal units_for(scale.status), so "unvalidated" means model units. georeferenced=true is only allowed with frame F6 or F7. ING_REJECT records an ingest refusal without dropping the manifest.

### src/tesseract/pipeline.py
Orchestrator: runs stages in order with content-addressed resume (state.json), a time budget and the degradation ladder, then writes run_manifest.json. No geometry knowledge.
Exports: Context(run_id, workdir, source, config, level, budget_s, spent_s, artefacts, facts, cached, ...).path()/remaining()/need(name); Stage Protocol; BaseStage (override execute(); fields id, version, needs, produces, levels, cacheable, level_sensitive; estimate(); key_extra(ctx) for files read outside the run); State(path).key(stage, ctx, *, source=None, upstream="")/cached/record; Pipeline(stages).run(ctx, resume=True) -> RunManifest
Used by: src/tesseract/stages.py, cli.py, __init__.py, test_tesseract.py
Gotcha: a budget overrun or non-fatal StageError steps down one level and restarts from stage 0, and manifest.stages gets duplicates. Any other exception from a stage is recorded as STAGE_UNAVAILABLE with note "unexpected <Type>: <msg>" and handled the same way, so a crash still ends in a manifest. Only level_sensitive stages key on ctx.level, so the others are reused from the earlier attempt (logged "reused", not added to ctx.cached). Pipeline() raises ValueError at construction if a stage needs something no earlier stage produces. Missing scale fact defaults to "unvalidated". A stage with cacheable=False always re-runs; ctx.cached lists the stage ids this invocation took from the cache (their seconds count as 0). The key covers id, version, level (level_sensitive only), config, declared input hashes, the source fingerprint (sha256 of source.inputs(), video bytes included), key_extra and the previous stage's key, so any upstream change re-runs everything after it; changing the key formula invalidates every existing state.json once.

### src/tesseract/report.py
Renders the per-run QA report (markdown) from run_manifest.json: ladder level, frame, units, scale, verdicts, stage and artefact tables. Every figure comes from the manifest.
Exports: render(man: dict) -> str; write_report(rundir) -> path of rundir/qa_report.md
Used by: src/tesseract/cli.py, src/tesseract/test_tesseract.py
Gotcha: render() raises KeyError without run_id or source; a run with no geometry prints its frame as none; adds a "no external ruler" warning whenever scale.status is unvalidated.

### src/tesseract/scale.py
Scale service (docs/08): decides what a run may call a metre. GNSS/RTK fit, else known-object calibration from research/calibration/*.json, else unvalidated at factor 1.0. Also the footprint plausibility check that would have caught the Kolu 5.5x error.
Exports: ROOT, CAL_DIR, UNVALIDATED; load(run) -> dict (factor, bracket, status, method, summary, source, references, floor_checks); from_gnss(scale, rtk=, residual_m=) -> dict; for_page(cal) -> {factor, status, label, basis}; footprint_check(focal_px, image_width_px, camera_height, factor, content_span_m=None) -> dict with "ok"; implied_factor(...) -> float; describe(cal) -> str
Used by: src/tesseract/stages.py (S4, S5), src/tesseract/cli.py (imported, unused), src/tesseract/test_tesseract.py
Gotcha: a calibration file applies only if the run name is in its "runs" list; a matching file with a status other than calibrated/gnss/gnss+rtk raises ValueError. No global default factor on purpose. tools/scale_cal.py duplicates this lookup.

### src/tesseract/sources.py
Pipeline inputs. VideoSource wraps a real clip plus optional telemetry sidecar; SyntheticSource builds a known-truth single-pass scene with simulated GNSS error (consumer/sbas/rtk plus 2% wild fixes) from src/simscene and src/eval3d.
Exports: Source (describe(), inputs()); VideoSource(path, telemetry=None); SyntheticSource(seed=7, n_frames=240, pitch_deg=60, gnss="consumer", site=Delhi lat/lon/h).world() -> dict(scene, pos, R, gps, cam, gt, gt_fidx, occ, gnss_spec, rng, site)
Used by: src/tesseract/cli.py, __init__.py, test_tesseract.py
Gotcha: stages tell sources apart by hasattr(ctx.source, "path") vs hasattr(ctx.source, "world"). world() is cached per instance and samples 460k surface points on first call. inputs() is the resume fingerprint: any new parameter that changes the scene must be added there (VideoSource hashes the file every run).

### src/tesseract/stages.py
The ten DEFAULT_STAGES: S0-screen, S1-ingest, S2-plan, S3-geometry, S4-scale, S5-georef, S5b-level, S6-export, S7-score, S8-verdict. Wrap code in src/ingest, src/eval3d, src/simscene and src/pipeline (gravity, render_views).
Exports: Screen, Ingest, PlanKeyframes, Geometry (providers adopt / sense / local (src/pipeline/local_gpu.py, config geometry="local") / request; key_extra hashes the adopted files; sense hands S5 a gauge tilted up to 25 deg and scaled 0.1-2x, with 4x4 poses), Scale (key_extra is the resolved calibration), Georeference (levels, then robust_track_sim3, dof 6; _from_srt on a video: SRT fixes to F6), Level, Export, Score, Verdicts; DEFAULT_STAGES; R_O5_FORMATS, R_O2_VIDEO_S, R_O4_RECALL; _verdict_formats(exports) -> str; _verdict_time(ctx) -> str; _verdict_coverage(facts) -> str; _level_basis(P, cams) -> (B, gravity facts, centres) (NaN camera rows skipped); _level(X, B, origin); _apply_frame_json(X, tf) (level.json or georef.json, any stretch first); _stretch(X, st); _focal_from_pitch(cam, ok, tel, tf, f_used) -> dict; PITCH_RANGE_DEG, PITCH_MAX_ATTITUDE_SPREAD_DEG, PITCH_MIN_CHANGE, PITCH_K_RANGE, PITCH_MAX_K_SPREAD; _gravity_lengths(grav, k, units); _write_ply_f64(path, P)
Used by: src/tesseract/cli.py, __init__.py, test_tesseract.py
Gotcha: on a real video S3 needs config "adopt" (out/<run> with points_fused.npy) or geometry="local" (a CUDA GPU with COLMAP and OpenMVS; missing tools are STAGE_UNAVAILABLE, a sparse failure GEO_REPROJ and replayed, not recomputed, at L1/L2; a dense failure MVS_RC, after which L1/L2 reuse the poses on disk through local_gpu's sparse_from; views the mapper could not place add GEO_UNREG and registered_views, not a failure; facts carry pose_method, textured_mesh, texture_error, unregistered, and under local_gpu focal_after_mapper_px, views_turn_deg, focal_refined). S1 is version 6 (shot cut, bridged keyframes, a long clip's keyframes spanning the shot, 1 Hz fixes interpolated) and S3 version 9 (global-mapper poses, the focal refined only past a 30 degree turn, no retriangulation, mesh -d 4, texture 20%), so older cached runs recompute. S1 maps a no-usable-frames RuntimeError to fatal ING_REJECT so the run gets a manifest. The local S3 estimate is S_LOCAL_FIXED 57 s + 0.5 s per pose view + 1.1 s per dense view, measured on the global-mapper path (research/11 section 10: B5v 563 s estimated against 543 measured); at L1 the local dense term is scaled by LOCAL_L1_DENSE_FACTOR 0.65. S1 clears old kf_*.jpg before writing, otherwise non-fatal STAGE_UNAVAILABLE walks the ladder down to L5. On a video S5 fits the SRT fixes in ingest.json (keyframe i to camera i) and writes F6, local ENU about the first fix with heights above take-off, plus georef.json (ADR-030); under 8 usable fixes or a 20 m track it skips with ING_NOGNSS. S5 is version 6: with 8 or more fixes carrying a gb_pitch 15-75 degrees down and views turning under 10 degrees (95th percentile), it takes the focal length's error k = tan(SRT pitch) / tan(model pitch), stretches the F4 model 1/k along the mean view axis and fits again (ADR-032; test_flight's cloud 12.6 m to 0.39 m median); georef.json then carries "stretch", applied first by _apply_frame_json, and facts focal_from_pitch record the result or why it was not applied (most consumer DJI SRTs have no gimbal pitch). It reads the focal length from facts local_gpu.focal_after_mapper_px. S6 gives F6 files an orthographic CRS about that fix. A 7-DOF fit is refused. S5 and S5b share _level_basis so both use one vertical; B's rows [e1, up, e2] are left-handed and _level reorders them to [e1, e2, up]. The PLY is written in doubles with no origin shift, so it overlays the LAS. _orthometric raises fatal REF_BALLPARK if the EGM2008 grid is missing. S5b (version 3) writes level.json (basis rows, origin, scale) and S6 (version 3) uses it to export geometry/scene_tex.obj as OBJ, GLB and FBX beside PLY, LAS and GeoTIFF, so a local run can meet R-O5 (6 of 6; FBX needs SIH_ASSIMP); a georeferenced run exports the mesh through georef.json; R-O2 is met only for a timed, uncached video of 600 s or more. The DSM cell follows point density, floored at 0.05 only when the units are metres. R-O4 is judged on observable recall with the whole-scene figure printed beside it, and is not measurable for sensed (synthetic) geometry. Level names lengths `_m` only when units are metres, else `_model`; S5 scales gravity lengths by the fit's scale into metres. PlanKeyframes is the one level_sensitive stage. R-O6 is met only when something was exported. Verdict strings must start with met / not met / not measurable (tools/build_console.py checks). Importing inserts src/ on sys.path.

S5 rejects a pitch correction when the 10th to 90th percentile spread of per-view focal scale exceeds 5%; this prevents mixed or drifting SRT pitch from silently stretching an otherwise fixed-attitude model.

### src/tesseract/test_tesseract.py
Plain-assert test script: T1 contracts, T2 scale service and footprint check, T3 orchestrator cache/version/budget/ladder (including reuse across a ladder step), uncacheable stages and resume keys (source change, outside-file change and the chain, recalibration, re-run adopted geometry), T3b R-O2, R-O4 and R-O5 verdict rules, T3c unit-named Level lengths, T3d track-aligned georef fit against yaw-only on a tilted gauge plus the double-precision PLY, T3e the local GPU provider's error mapping with a fake local_gpu (GEO_REPROJ, replay at L1 without recomputing, SystemExit caught, time order past 999, L1 reusing poses after a dense failure, GEO_UNREG for unplaced views, NaN-safe levelling, a lower local estimate at L1), T3f ingest rejection leaves a labelled manifest, T3i an unexpected ValueError in a stage still leaves one, named and coded, T3j the DSM's 5 cm floor applied to metres only, T3g SRT georeferencing of a video to F6 (0.010 m RMS on a rotated, scaled gauge) and the CRS on its LAS and GeoTIFF, T3h the gimbal pitch undoing a focal length 12% long on an oblique pass (ground 5.8 m low without the pitch, 0.017 m RMS with it, k and the implied focal length recovered, georef.json reproducing points_geo), T4 synthetic end to end rtk vs consumer (also checks the recovered up is not the gauge's Z and S5's camera height is in metres), T5 real Kolu runs (skipped when out/runs is absent).
Used by: .github/workflows/ci.yml (run as `python src/tesseract/test_tesseract.py`, exit 1 on any FAIL)
Gotcha: not pytest. T2 FAILs (not skips) if research/calibration/kolu.json is missing or lacks run "kolumvs3d". T3h checks a mixed gimbal-pitch track against a fixed camera attitude. T4 needs pyproj network access for the geoid grid.

## src/ingest/

### src/ingest/__init__.py
Empty package marker; makes ingest.video_ingest and ingest.screen importable once src/ is on sys.path.

### src/ingest/video_ingest.py
S1 ingest. Decodes with PyAV (frame-threaded; time segments on threads for constant-rate clips of a minute or more), scores about 15 frames a second with OpenCV at 0.25 scale, picks keyframes (longest shot, overlay crop, horizon reject/crop, sky gate, slate gate, blur percentile, optical-flow baseline budget; gated stretches are bridged with their sharpest usable frame) and attaches DJI SRT telemetry. CLI writes kf_NNN_fNNNNN.jpg plus ingest.json to --out.
Exports: select_keyframes(ok, usable, flows, scores, flow_budget, target, *, bridge=1.5) -> (indices, n_bridged); keyframe_budget(ok, usable, flows, scores, target, *, floor, bridge=1.5) -> (budget, indices, n_bridged); ingest_video(path, *, target_keyframes=600, blur_reject_pct=25, max_sky=0.15, horizon_policy="reject"|"crop", single_shot=True, skip_start_s, end_s, analyse_every=None (auto, ~15 fps), flow_method="dis"|"farneback", workers=None (auto), srt_path=None, bridge=1.5, bridge_max_sky=0.5) -> IngestResult(keyframe_indices, frames: list[BGR uint8], telemetry: list[dict], stats: dict); parse_dji_srt(path) -> list[dict] (latitude, longitude, height or None, flags, optional t_us/frame_cnt/satellites/focal_len/gb_yaw/gb_pitch/abs_alt/wall_us); telemetry_for_frames(records, frame_idx, fps, times_s=None) -> list[dict] ({} where no match); timed_frames(container) -> (index, frame, seconds since first PTS or None); sharpness, is_slate, letterbox_rows(small) -> (top, bottom), letterbox_box(frames) -> (t,b,l,r), sky_mask, sky_fraction, horizon_present, sky_and_horizon(small) -> (sky, horizon), horizon_row, horizon_crop_fraction, static_overlay_mask, overlay_crop_box -> (t,b,l,r), apply_crop, detect_shots, frame_hist
Used by: src/ingest/screen.py, src/ingest/test_srt.py, src/ingest/test_frames.py, src/tesseract/stages.py, run_job/run_upload.py (as a subprocess script)
Gotcha: the flow budget starts at the median gated-frame flow and is bisected up only until the target's keyframes reach the end of the shot (keyframe_budget); the old median x count / target budget stopped the 10-minute loop at frame 12,604 of 18,000. The gates only prefer frames: past 1.5 flow budgets with no gated frame, the sharpest non-slate frame under 50% sky past one budget is taken (demo: 42 of 177 bridged, largest gap 66 frames to 6); the budget counts all in-shot motion; stats.bridged_keyframes. detect_shots uses histogram correlation and a high flow jump with moderate histogram change, which splits B2 at frame 558. Sky, horizon and overlay tests work below letterbox bars, and the crop removes the bars. S1 on a 10-min 1080p clip: 55 s, 6.0 GB peak RSS (was 402 s, 10.7 GB); threaded and sequential scans select identical keyframes. The parallel scan and second pass map presentation times to frame numbers, so they run only after a constant-rate probe and fall back to the sequential pass on any count mismatch or a missing flow reference; the sequential second pass then also numbers by timestamp. DIS flow uses a fresh object per pair (one object carries state between calls). Telemetry matches by FrameCnt, then by time, never by position; between two time-keyed fixes (the 1 Hz legacy files) position, heights, gb_pitch and gb_yaw (the short way round) are interpolated, a frame up to one interval past the last fix keeps it, up to half an interval before the first takes it, and a gap over two intervals is not bridged. The time is each keyframe's presentation timestamp (index / fps only when a frame has none), and skip_start_s / end_s compare PTS too, so variable-frame-rate clips line up; stats.variable_frame_rate says which. SRT is auto-found at <video>.SRT. abs_alt is barometric, never GNSS height. Two decode passes bound memory to O(keyframes) at full resolution (keeping every frame needed ~112 GB for a 10-min clip). The CLI deletes old kf_*.jpg in --out first.

### src/ingest/screen.py
S0 admission test. Samples about 140 frames and returns ACCEPT or REJECT with reasons before any GPU time: rejects when the horizon shows in more than 30% of frames, median sky is above 0.15, or the longest shot is under 8 s.
Exports: screen(path, n_samples=140) -> dict (file, resolution, fps, duration_s, shots_detected, longest_shot_s, median_sky, horizon_frac, median_sharpness, static_overlay_px_frac, overlay_crop, verdict, reasons)
Used by: src/tesseract/cli.py, src/tesseract/stages.py, run_job/run_upload.py
Gotcha: decodes every frame (frame-threaded, ~10 s for a 10-min 1080p clip) to sample about 140. Inserts src/ into sys.path itself. The CLI writes to relative out/screen.json and fails if out/ does not exist.

### src/ingest/make_test_video.py
CLI that renders the synthetic single-pass scene into a real H.264 1080p30 MP4 (every 6th frame motion-blurred) plus a Mavic-3-style DJI .SRT with simulated GNSS noise.
Exports: enu_to_geodetic(enu, lat0, lon0, h0) -> (lat, lon, h); srt_timestamp(s); write_srt(path, lat, lon, rel_alt, abs_alt, yaw, pitch, fps, focal_mm=24); main() (out, --seconds, --fps, --gnss consumer|rtk, --lat/--lon, --crf, --seed)
Used by: standalone script
Gotcha: needs simscene and eval3d.gnss via a sys.path insert of src/. abs_alt is rel_alt plus a constant, mimicking real barometric DJI files. Gimbal angles follow DJI: gb_yaw 90 (the pass flies east), gb_pitch -pitch (60 degrees down is -60); it used to write -(90 - pitch), and data/test_flight.SRT was corrected to match, since S5 reads the pitch.

### src/ingest/test_frames.py
Plain-script test of the frame gates on a synthetic letterboxed frame: bars measured, sky and horizon found below a top bar, horizon row counted past it, the clip crop removes the bars, a watermark above the bottom bar is cropped even with a black sample mid-clip; frames without bars unchanged; the variable-frame-rate flag with a scoring stride; select_keyframes bridges gated stretches and never takes an unusable frame (T3b); keyframe_budget spans a 9000-frame clip where the old budget stopped at 7272, and leaves a clip under the cap unchanged (T3d); T3c splits a high-flow, moderately changed histogram but keeps fast motion with unchanged histograms; a threaded scan of an encoded clip equals the sequential one, also when the first timestamp is not 0. Run `python src/ingest/test_frames.py`.

### src/ingest/test_srt.py
EXP-23 telemetry test script (68 checks, plain prints). T1 pins the first record of each real DJI fixture, T2 runs 21 fuzz deformations (CRLF, BOM, UTF-16, binary, NaN, "longtitude", x10 focal, legacy GPS tuples) in a tempdir, T3 checks telemetry_for_frames is keyed, not positional, interpolates between 1 Hz fixes (yaw across +-180 the short way), refuses a frame well before the first fix, and encodes a variable-frame-rate clip with PyAV to check PTS keying (skipped without av).
Used by: .github/workflows/ci.yml (run as `python src/ingest/test_srt.py`)
Gotcha: exits 1 on any FAIL. Expected values are hard-coded per fixture filename, so renaming or re-cutting a fixture breaks it.

### src/ingest/fixtures/dji_srt/
22 files, 1.4 MB: 20 real DJI .SRT/.srt sidecars across five format families (MAVIC3, air2s, mavic_air2, m2zoom, matrice_300, mavic_pro, p4_rtk, Mini_SE and more, plus broken_empty/broken_incomplete variants), LICENSE.DJI_SRT_Parser (MIT) and README.md (provenance, which files were cut to a block boundary). Test inputs for test_srt.py only; never re-encode or normalise them.

## src/pipeline/

### src/pipeline/colmap_export.py
S2 to S3 bridge. Turns MapAnything cameras.npy (cam2world 4x4) plus points.npy into a COLMAP text model for point_triangulator and OpenMVS, fitting intrinsics from the point map and mapping them from the model's centre-cropped grid back onto the full keyframe.
Exports: derive_intrinsics(points, cams, H, W, mask=None) -> ((N,4) fx,fy,cx,cy, median_resid); full_frame_camera(K, H, W, h0, w0, log, crop_trbl=None) -> dict (pp_reference names the centre it passed against); parse_crop(value) -> (t,b,l,r) or None; qvec_from_R(R) -> (w,x,y,z); db_image_ids(db_path) -> {name: (image_id, camera_id)}; write_model(outdir, cams, names, cam, db_path, log)
Used by: mvs_job/run_mvs.py, mvs_job/run_mvs_sharded.py (both via /app, copied by mvs_job/Dockerfile), src/pipeline/local_gpu.py, src/pipeline/test_colmap_export.py
Gotcha: image and camera ids must come from COLMAP's database.db. SystemExit if the principal point is more than 8% off both the keyframe centre and (given S1's crop) the crop-shifted source centre, if KF_CROP_TRBL is malformed, the database has more than one camera, or a name is missing. SIMPLE_RADIAL model; poses inverted to world-to-camera.

### src/pipeline/export_formats.py
S5/S6 export: PLY, OBJ, GLB, glTF, LAS 1.4, GeoTIFF DSM and FBX in one gravity-aligned local level frame centred on the cloud centroid, plus export_manifest.json. CLI: indir holding points_fused/colors_fused/mesh_v/f/c .npy, optional --cameras, --gsd, --no-scale.
Exports: export_all(out, points, colors, V, F, C, cams=None, gsd=0.10, scale=None, log) -> manifest dict; write_mesh_formats(out, V, F, C); write_fbx(out) -> bool; write_las(out, xyz, C); write_dem(out, xyz, gsd, units) -> dict; FORMATS; GRAVITY_LENGTHS
Used by: tools/finish_mvs.py (subprocess); copied into mvs_job/Dockerfile but not imported there
Gotcha: dem.tif is written with crs=None on purpose (no GNSS). The tools/scale_cal.py factor is applied once, here, to every file. glTF/GLB are swapped to Y-up; other formats stay Z-up. FBX needs assimp or Blender on PATH, else skipped. `from gravity import` needs src/pipeline on sys.path.

### src/pipeline/fuse_mesh.py
S3/S4 on a MapAnything output dir (points/colors/conf/mask/cameras .npy + mapanything_result.json): confidence gate, valid mask, conditional far-field range gate, statistical outlier removal, voxel fusion at one view's point spacing, screened Poisson mesh with normals toward camera centres. CLI writes points_fused/colors_fused/cam_centres/mesh_v/f/c .npy, cloud.ply, model.ply, fuse_diag.json.
Exports: load(dir) -> (P, C, conf, mask, cams, meta); camera_centres(cams); view_point_spacing(P, shapes); filter_fuse(P, C, F, M, *, cams, shapes, conf_pct=30, sor_sigma=1.2) -> (P, C, voxel, diag); mesh(P, C, vox, *, centres, depth=10, trim=0.06) -> (o3d pcd, o3d mesh); SUB, SLICE
Used by: tools/finish_kolu.py (subprocess)
Gotcha: a constant conf channel skips the confidence gate (and logs it). Without camera centres the normal sign is unverified and Poisson can come out inside-out. Neighbour queries run on a 400k subsample or 1M slices to bound memory.

### src/pipeline/gravity.py
Recovers the world up-vector from cam2world poses and the cloud: PCA ground normal projected so camera roll is zero, sign fixed so cameras sit above ground, with diagnostics.
Exports: estimate(cams (N,4,4), points, log) -> dict(up, heading_spread, heading_degenerate, ground_correction_deg, residual_roll_deg, residual_roll_max_deg, camera_above_ground_m, horiz_track_m, altitude_spread_m); frame(up) -> 3x3 rows [e1, up, e2]; DEGENERATE=0.03
Used by: src/pipeline/export_formats.py, src/pipeline/render_views.py, src/tesseract/stages.py, src/experiments/exp14_scale_audit.py, mvs_job/Dockerfile (copied)
Gotcha: imported as bare `gravity`, so src/pipeline must be on sys.path. Warns when ground_correction_deg is over 15. Roll check is weak when heading_degenerate. The "_m" lengths are model units until scaled.

### src/pipeline/render_views.py
matplotlib (Agg) diagnostic PNGs of a fused result: points row and flat-shaded mesh row (plan, oblique, low angle), a height-coloured plan and two vertical sections. CLI: `indir --out render.png --theme light|dark`.
Exports: upright_frame(P, centres=None, cams=None) -> 3x3 rows [right, up, fwd]; frame_from_up(up); rot(az, el); shade_mesh(...); shade_points(...); section(ax, P, C, title); main(d, out); THEMES, MAX_TRIS=400k
Used by: src/tesseract/stages.py, tools/build_viewer.py, tools/pack_textured.py, tools/make_ppt_figs.py, src/analysis/qual.py, src/analysis/scale2.py, tools/finish_kolu.py and tools/finish_mvs.py (subprocess)
Gotcha: upright_frame uses gravity.estimate only when cams is passed; main() never passes cams, so it falls back to PCA plus a centre sign. Meshes over 400k triangles are quadric-decimated. Module-global T is set to the theme only under __main__.

### src/pipeline/run_demo.py
Synthetic end to end with no GPU: simscene flight, GPS with correlated error and 2% wild fixes, blur and keyframe mask, visibility-sensed noisy geometry in an arbitrary frame, robust yaw-only Sim(3) to GPS, ENU to UTM plus EGM2008 height, 2.5D DSM and mesh; exports PLY, OBJ, GLB, LAS (with CRS) and dsm.tif and scores into run_manifest.json.
Exports: run(outdir, *, gnss=CONSUMER_GNSS, n_frames=600, pitch_deg=60, site_lat/lon/h, seed, label) -> manifest dict; utm_epsg_for(lon, lat) -> int; orthometric_height(lon, lat, h_ell); enu_to_geodetic(enu, ref_lat, ref_lon, ref_h); stage() context manager; TIMINGS
Used by: cloud_job.py
Gotcha: orthometric_height turns PROJ networking on and raises if the EGM2008 grid is missing or only a ballpark transform exists. Georeferencing is solved in local ENU, never UTM. DSM starts filled with -inf, not NaN. The depth model is simulated. Its manifest uses the old flat keys that viewer/index.html reads.

### src/pipeline/local_gpu.py
S3 and S4 on one machine with an NVIDIA GPU (research/09, research/10, research/11). run() is sparse() then dense(). Default pose_method "global": MapAnything bf16 on 60 spread views fits one camera, then COLMAP GPU SIFT with that camera as SIMPLE_PINHOLE, sequential matching over 30 neighbours, global_mapper refining that one focal length only when MapAnything's views turn at least refine_focal_min_turn_deg (30 degrees between the mean rotations of the clip's thirds, attitude_turn_deg), else holding it (ADR-031 as revised; recorded as views_turn_deg, focal_refined and focal_after_mapper_px, plus the mapper's own turn views_turn_mapper_deg and focal_gate_doubtful when that disagrees with the choice) with principal point and distortion fixed and its retriangulation pass off, then point_filtering (4 px, 1.5 deg) into sparse_gf (mapper_retriangulate False: half the mapper time on 600 views, cameras no worse), the S3b gate (at least min_registered, default 50%, of the views; the rest are listed in result["unregistered"], left out of the dense set and NaN in cameras.npy). "mapanything" keeps the old path. Then OpenMVS CUDA densify (fusion filter 1, no ROI, tower mode off, --min-resolution 320 so a higher level really downscales the 1920x596 demo crops), ReconstructMesh at 4 px, TextureMesh on the mesh decimated to 20% into scene_tex.obj/.mtl/_Kd.jpg. sparse_from reuses a finished run's poses (reuse_sparse) so only the dense half runs. Writes points_fused/colors_fused/cameras.npy and local_gpu_result.json (also once after the gate, so a dense failure leaves reusable poses). CLI: `python src/pipeline/local_gpu.py <keyframes> --work <dir> [--set k=v] [--sparse-from dir]`.
Exports: DEFAULTS; SparseError; with_extra(args, extra) -> args; frame_order(name); find_tools() (SIH_COLMAP, SIH_OPENMVS, else PATH; four OpenMVS tools incl. TextureMesh, torch, mapanything); Runner(work).timed/sh; mapanything_poses(paths, *, window, overlap); pose_window_for(H, W, total_bytes); attitude_turn_deg(cams) -> degrees; attitude_spread_deg(cams) -> degrees; fit_camera(ma, h0, w0, crop, *, views); analyze(r, colmap, model, label); global_sparse(r, colmap, img, db, cam, o) -> model dir (filtered unless mapper_retriangulate); mapanything_sparse(r, colmap, img, db, names, cams_ma, cam, o) -> (before, model dir); read_images_txt(path) -> {name: cam2world}; read_ply_points(path) -> (xyz, rgb); run(images_dir, work, *, crop_trbl, dense_names, options, sparse_from, log) -> result dict; SPARSE_KEYS; DENSE_OPTIONS; reuse_sparse(src, work, names, o) -> result; sparse(r, colmap, img, names, h0, w0, crop, o, log) -> result with "model"; dense(r, mvs, colmap, img, sp_txt, names, dense_names, o, result, finish, log); INTERMEDIATE; clear_products(work) -> removed names (an earlier run's cloud, mesh and scene_tex*, deleted as dense() starts so S6 cannot export a stale mesh); clean_work(work) -> removed names
Used by: src/tesseract/stages.py (Geometry provider "local"), src/pipeline/test_local_gpu.py, tools/view_check.py
Gotcha: mapper_extra, densify_extra, mesh_extra and texture_extra are appended through with_extra, which replaces a default flag of the same name (the tools refuse an option given twice). reuse_sparse refuses a different view count, a failed gate or any changed option outside DENSE_OPTIONS. global_mapper keeps the largest model if views split. Self-calibration from scratch curled the demo ground (focal 576 vs 1100 px), so the focal length is only refined from MapAnything's start; PINHOLE with refinement splits fx and fy. On a straight pass at one attitude refinement cannot observe the focal length and drifted 6-9% long (1091 to 1160, 1414 to 1179 px against 1066), hence the turn gate; Nicosia's pan refines 751 to 1400 px. MapAnything's poses drift between its inference windows: straight synthetic passes read 8.9 and 13.1 degrees of turn (the mapper's 0.1), the demo 6.5, Nicosia 111, so the gate is 30. MapAnything's focal was 33% long on the H.264 test_flight clip (research/11). Without retriangulation the mean reprojection error rose ~10% and failed the 1 px gate until point_filtering was added. Seam levelling is off in TextureMesh (on, 73% of faces sampled black). A SIMPLE_RADIAL camera with k=0 passes the undistorter unchanged and OpenMVS refuses it, hence PINHOLE. Mesh and texture failures are recorded (mesh_error, texture_error), not raised. SparseError for anything up to the S3b gate, RuntimeError for a dense tool, FileNotFoundError when tools are missing. Unless keep_intermediate, clean_work deletes depth maps, the database, undistorted images, intermediate models (sparse_g too) and scene_dense.ply (the same cloud as points_fused/colors_fused.npy, 3.7x their size); sparse_txt, the mesh and the textured OBJ stay.

### src/pipeline/test_local_gpu.py
Plain-script test of local_gpu's GPU-free parts: OpenMVS-style PLY with variable-length view lists read back exactly, a COLMAP images.txt pose read back to cam2world, keyframe time order past 999, clean_work removing intermediates while keeping the cloud, cameras, mesh, sparse model, logs and images, reuse_sparse copying poses and refusing changed pose options, a different view count or a failed gate, with_extra replacing default flags, clear_products removing an earlier run's cloud, mesh and textured mesh while keeping poses (T8), and attitude_spread_deg (T7: zero for a straight pass, about 28 degrees for a 60 degree pan, unchanged by a window's scale in the rotation block, NaN views ignored; attitude_turn_deg reads 5 degrees of per-view noise as under 4 where the percentile reads 18, and a noisy 60 degree pan as about 39). Run `python src/pipeline/test_local_gpu.py`.

### src/pipeline/mesh_export.py
S6's textured mesh exports: geometry/scene_tex.obj carried F4 to F5 or F6 with the transform S5b (level.json) or S5 (georef.json) wrote and written as model.obj/.mtl/model_Kd.jpg, model.glb (trimesh, Y-up, atlas embedded) and model.fbx (assimp through pyassimp, from a Y-up copy). A mesh TextureMesh split over several atlases keeps every material: model_Kd_<i>.jpg, one MTL block each, and a GLB with one mesh per material.
Exports: to_frame(V, basis_rows, origin, scale) -> F5 vertices; z_up_to_y_up(V); export_textured(obj, out, transform) -> (paths {obj, glb, fbx}, notes)
Used by: src/tesseract/stages.py (Export), src/pipeline/test_mesh_export.py
Gotcha: FBX needs the assimp library: SIH_ASSIMP names its folder or DLL (C:\Users\Kartik\gpu-tools\assimp\Release on the laptop), else PATH; without it FBX is skipped with a note. pyassimp's AssimpError is a BaseException, hence the broad catch. OpenMVS writes `Tr 1` in its MTL, which some readers take as transparent, so the MTL is rewritten.

### src/pipeline/test_mesh_export.py
Plain-script test of mesh_export on a two-triangle textured OBJ: vertices transformed as S5b transforms the cloud, UVs and faces unchanged, a clean MTL beside the copied atlas, a Y-up textured GLB, and FBX written or its absence named; T2 a mesh over two atlases keeps both materials in the MTL and both textures in the GLB. Run `python src/pipeline/test_mesh_export.py`.

### src/pipeline/window_fuse.py
S2-SCALE: plans overlapping view windows for long passes and brings them into one frame. stitch chains a Umeyama Sim(3) on shared-view correspondences window to window; stitch_gnss anchors each window's camera centres to GNSS independently.
Exports: plan_windows(n_views, window=24, overlap=8) -> list[(lo, hi)]; sim3_from_pairs(src, dst) -> (s, R, t); robust_sim3_from_pairs(src, dst, *, iters=64, min_inl=0.35) -> (s, R, t, inlier_frac, thr); stitch(window_points, windows, *, conf) -> (fused, report); stitch_gnss(window_cams, window_points, windows, gnss_enu, *, yaw_only=True) -> (fused, report)
Used by: src/pipeline/local_gpu.py, src/pipeline/test_window_fuse.py, src/experiments/exp13_windowed_scale.py
Gotcha: returns (s, R, t), unlike eval3d's (R, t, s). stitch_gnss with yaw_only needs ENU Z-up inputs. Overlap must be less than the window with at least 3 shared views. Chained error still grows (about 15x at the far end).

### src/pipeline/test_window_fuse.py
T-SCALE-01 drift test: 128 synthetic views in 24-view windows with 8 overlapping, each in a random Sim(3) frame; asserts median residual under 0.05 and first-to-last-third drift under 3x.
Exports: rand_sim3(rng, scale_sigma); main() -> 0 or 1
Used by: .github/workflows/ci.yml

## src/eval3d/

### src/eval3d/__init__.py
Empty package marker, needed for the relative import in gnss.py.

### src/eval3d/gnss.py
GNSS error model and georeferencing maths: WGS84 geodetic/ECEF/ENU conversions, Gauss-Markov bias + random walk + white noise simulator, RANSAC Umeyama Sim(3), a yaw-only (gravity-constrained) variant, and a track-aligned fit for straight passes.
Exports: geodetic_to_ecef, ecef_to_enu, geodetic_to_enu; GnssSpec; CONSUMER_GNSS, SBAS_GNSS, RTK_GNSS; simulate_gnss_error(n, dt, spec, rng) -> (n,3) ENU; robust_sim3(src, dst, *, with_scale, thresh="auto") -> (R, t, s, inlier_mask); yaw_only_sim3(src, dst) -> (R, t, s); robust_yaw_sim3(...) -> (R, t, s, inliers); track_sim3(src, dst, *, with_scale) -> (R, t, s); robust_track_sim3(...) -> (R, t, s, inliers); georeference_error(...) -> dict; straight_pass(n, ...); WGS84_A, WGS84_E2; re-exports umeyama, apply_transform
Used by: src/pipeline/run_demo.py, src/pipeline/window_fuse.py, src/ingest/make_test_video.py, src/tesseract/stages.py, src/tesseract/sources.py, cloud_job.py, src/experiments/exp05_gps_noise.py, src/experiments/exp09_straight_line_degeneracy.py, and 1 more (grep to enumerate)
Gotcha: full Sim(3) on a straight pass leaves roll free and throws the scene hundreds of metres. track_sim3 takes yaw and slope from the track and only the roll about it from the input's Z, so both inputs must already be level and Z-up (ADR-026); robust_track_sim3 picks inliers with robust_yaw_sim3 first. A fixed RANSAC threshold below the noise floor is worse than least squares, so keep "auto". Import as eval3d.gnss (relative import).

### src/eval3d/metrics.py
Accuracy harness, Tanks-and-Temples style (precision, recall, F at tau, NN distance stats). Every result is reported twice: ABSOLUTE with no alignment (what R-O3 is judged on) and ALIGNED after trimmed ICP. numpy and scipy only.
Exports: evaluate(recon, gt, *, taus=(0.25,0.5,1,2), align=True, align_with_scale=False) -> {"absolute": EvalResult, "aligned": EvalResult}; summarise(results, tau=1.0) -> str with PASS/FAIL; umeyama(src, dst, with_scale) -> (R, t, s); icp(...) -> (R, t, s, rmse); apply_transform(pts, R, t, s); nn_distances; prf_at_tau; rotation_angle_deg; DistanceStats, ScoreAtThreshold, EvalResult; DEFAULT_TAUS
Used by: src/eval3d/gnss.py, src/eval3d/test_metrics.py, src/pipeline/run_demo.py, src/tesseract/stages.py, src/experiments/exp05_gps_noise.py, src/experiments/exp09_straight_line_degeneracy.py
Gotcha: alignment leaves scale out on purpose; a scale diagnostic is always reported. alignment_translation_m is mean point displacement, not ||t||. The aligned metric is unreliable on flat terrain because ICP slides.

### src/eval3d/test_metrics.py
21 self-checks for metrics.py with analytic answers: identical clouds, a known 5 m offset, the flat-terrain slide (T2b), Umeyama recovery, reflection guard, partial recall, noise tracking, tau monotonicity, report text.
Used by: .github/workflows/ci.yml, README.md
Gotcha: alignment tests need vertical walls; a ground-only scene cannot constrain a rigid fit and T2b asserts that failure on purpose.

## src/simscene/

### src/simscene/scene.py
Synthetic ground-truth site built with trimesh: rolling terrain, two crossing roads, up to 26 box buildings and 40 trees merged into one mesh with per-face labels (0 terrain, 1 building, 2 road, 3 vegetation), plus a straight single-pass flight.
Exports: SceneSpec(extent=400, n_buildings=26, building_h, road_width, n_trees, terrain_relief, seed); Scene(mesh, labels, spec, parts) with LABELS, face_label_mask(), sample_surface(); build_scene(spec) -> Scene; Camera(width=3840, height=2160, hfov_deg=84) with fx, K; single_pass(scene, n_frames=600, alt=110, pitch_deg=90, heading_deg, offset) -> (pos (N,3), R (N,3,3) cam to world)
Used by: src/pipeline/run_demo.py, src/ingest/make_test_video.py, src/experiments/exp08_coverage_ceiling.py, src/experiments/exp09_straight_line_degeneracy.py, src/tesseract/sources.py
Gotcha: no __init__.py (namespace package), so src/ must be on sys.path. Every frame of a pass shares one R. pitch_deg=90 is nadir.

### src/simscene/render.py
CPU barycentric rasteriser with a z-buffer: lambertian per-class albedo plus world-space aperiodic value-noise texture, so frames are matchable across views.
Exports: render_view(V, F, face_rgb, cam_pos, cam_R, K, width, height, *, rng, exposure) -> (rgb uint8, depth float32 with NaN where empty); render_flight(scene, positions, rotations, K, w, h, *, blur_px) -> (frames, depths); shade_faces; world_texture(P); apply_motion_blur(img, px); CLASS_RGB, SUN
Used by: src/ingest/make_test_video.py
Gotcha: per-triangle loop is pure Python and slow on big frames. Keep texture world-space and aperiodic: periodic or screen-space texture made MapAnything collapse its baselines.

### src/simscene/visibility.py
Which surface points a camera or flight can see, via a z-buffer built from a dense occluder cloud with backface, grazing-angle (75 deg) and range limits.
Exports: build_depth_buffer(occluders, cam_pos, cam_R, K, w, h, bin_scale) -> (buf, bw, bh); visible_mask(points, normals, cam_pos, cam_R, K, w, h, *, occluders=None, depth_buffer=None, ...) -> bool mask; coverage(points, normals, positions, rotations, K, w, h, occluders, *, stride, min_views=2) -> dict(counts, seen_any, reconstructable, frac_any, frac_reconstructable, mean_views_where_seen)
Used by: src/pipeline/run_demo.py, src/experiments/exp08_coverage_ceiling.py, src/tesseract/stages.py
Gotcha: a buffer built from the query points alone gets occlusion wrong (a hidden wall scored 70.6% visible); always pass a dense occluder cloud or prebuilt buffer.

## src/analysis/

### src/analysis/compare_mvs.py
Compares a baseline cloud (MapAnything fused .npy) with the OpenMVS dense .ply on one shared vertical: plane-fit roughness at radii 3 cm to 1 m, relief above per-cell local ground, share of points above 1.0/1.5/2.5 m, planimetric occupancy on a 20 cm grid. CLI: `--baseline <points_fused.npy> --mvs <scene_dense.ply> --json path`.
Exports: load(path); roughness(P, radii) -> [(r, median_resid, n)]; relief(P, up, cell=1.0); occupancy(P, up, origin, cell) -> set; ground_normal(P); report(name, P, up=None) -> (up, stats)
Used by: tools/finish_mvs.py (subprocess); its --json feeds tools/make_ppt_figs.py, tools/build_sih_ppt.py, tools/build_gallery.py
Gotcha: results are model units, not metres. The vertical always comes from the baseline so both clouds share one frame.

### src/analysis/qual.py
One-off script with hard-coded runs (kolu3d/kolu_raw, yt3d/yt_raw, ytd3d/ytd_raw under out/): prints confidence stats, footprint, flatness, share above local ground and density. Run from the repo root; imports render_views.upright_frame.

### src/analysis/scale2.py
One-off: compares the PCA thin-axis up-vector (the one that ships) with the camera-centroid direction on kolu3d/yt3d/ytd3d, printing relief percentiles, angle between them, track length and camera height. Run from the repo root.

### src/analysis/spectrum2.py
One-off: detrends per-view depth in k x k blocks (k 3 to 129) on out/ytd_raw view 20 and out/kolu_raw view 22 to get roughness vs ground size, locating the information floor of MapAnything point maps. Run from the repo root.

### src/analysis/spectrum3.py
Control for spectrum2 on out/ytd_raw view 20: measured roughness vs depth downsampled to 14 px patches and bicubically upsampled, and vs a pure quadratic. Shows sub-patch detail is interpolation (the 14x finding in docs/05 and tools/build_qa.py). Run from the repo root.

## src/experiments/

### src/experiments/exp01_classical_cost.py
EXP-01: times OpenCV SIFT and brute-force kNN matching on synthetic 1080p/4K frames and projects cost at 600 keyframes (exhaustive vs sequential x12) against the 900 s budget. Lower bound only. Output in research/exp01-results.txt.

### src/experiments/exp05_gps_noise.py
EXP-05: absolute georeferencing error vs GNSS class over 40 trials of a 600-keyframe straight pass, plus frame-count averaging, RANSAC vs least squares, the residual and aligned-metric traps, bias sigma sensitivity. Output in research/exp05-results.txt.
Gotcha: uses a trajectory-only full Sim(3) fit, so it misses the scene-level roll degeneracy EXP-09 found.

### src/experiments/exp08_coverage_ceiling.py
EXP-08: completeness ceiling of a single pass on the simscene site (800 m, 26 buildings, 60 of 600 cameras at 110 m) per class, for nadir, 60 and 45 deg passes and a crossed two-pass comparison, inside the corridor and over the whole scene. Output in research/exp08-results.txt.

### src/experiments/exp09_straight_line_degeneracy.py
EXP-09: trajectory RMSE vs scene RMSE for full 7-DOF robust_sim3 vs robust_yaw_sim3 across consumer, SBAS and RTK, error by cross-track distance, straight vs gently curved flight. Output in research/exp09-results.txt.

### src/experiments/exp13_windowed_scale.py
EXP-13: 600-view synthetic pass in 24-view windows (8 overlap), each in its own yaw+scale frame; compares chain only, per-window GNSS anchor, and chain plus one GNSS anchor. No results file saved.
Gotcha: window frames are yaw-only on purpose; a full random rotation makes the yaw anchor look broken.

### src/experiments/exp14_scale_audit.py
EXP-14: audits metric scale on the Kolu MVS export (out/kolumvs3d) in LLF using lane width (3.5-3.75 m), ecoduct waist (21-22 m) and the 5.0 m arch clearance floor. Writes research/exp14-results.txt and research/calibration/kolu.json.
Used by: tools/scale_cal.py and export_formats.py read its kolu.json output
Gotcha: needs out/kolumvs3d/points_fused.npy, colors_fused.npy and export/export_manifest.json. ROI boxes are hard-coded to this clip. Running it overwrites the calibration file.

## run_job/

### run_job/run_upload.py
Web orchestrator, one Cloud Run Job execution per uploaded clip: fetch web/<RUN_ID>/source*, S0 screen, S1 ingest (subprocess video_ingest.py --horizon crop), poses via job kolu-ma, preview via tools/finish_kolu.py, densify via job sih26158-mvs, final via tools/finish_mvs.py. Rewrites web/<RUN_ID>/status.json (schema sih26158/web-run/1) after every transition.
Exports: main(); run_cloud_job(job, env, label, expect_s, sid); publish_model(bucket, out_run, label) -> {mesh, points, triangles, halfExtent, files}; put_status/stage/expect/fail helpers; status.json carries "execution" from CLOUD_RUN_EXECUTION so /api/status can detect a killed worker
Used by: run_job/Dockerfile (ENTRYPOINT); started as job sih26158-run by demo/api/start.js; status.json read by demo/api/status.js
Gotcha: env RUN_ID is required; others BUCKET (sih26158-mumbai), GCP_PROJECT (agentbillboard), REGION (asia-south1), MA_JOB, MVS_JOB, MAX_VIEWS=60, MIN_VIEWS=8, MAX_SECONDS=600, MAX_BYTES=600MB, mirrored in demo/api/_lib.js and tools/build_run.py. S0/S1 are called directly, bypassing the ladder. Child jobs get per-execution env overrides, never `jobs update`; densify gets KF_CROP_TRBL from ingest.json overlay_crop_trbl. Retries once, only on Cloud Run "Internal error running task". Outputs go to web/<RUN_ID>3d (preview) and web/<RUN_ID>mvs3d (final). Expected durations use measured rates (10.68 s/view poses, 2003 s densify per 60 views).

### run_job/Dockerfile
python:3.12-slim image for run_upload.py, built from the repo root: requirements.txt plus opencv-headless, av, open3d, google-cloud-run, baked EGM2008 grid, assimp-utils. No torch or OpenMVS (delegated to child jobs). Copies src/, tools/, tesseract.py, run_upload.py. Built by deploy/cloudbuild-run.yaml.

## mvs_job/

### mvs_job/run_mvs.py
MVS Cloud Run job (sih26158-mvs): pulls keyframes (KF_PREFIX) and MapAnything outputs (MA_PREFIX), fits intrinsics from point maps (conf-gated at the 30th percentile), runs COLMAP SIFT, exhaustive match, triangulation against known poses, bundle adjustment, the S3b gate, undistortion, then OpenMVS DensifyPointCloud, ReconstructMesh, optional RefineMesh, TextureMesh (OBJ). Results to OUT_PREFIX.
Exports: main(); fetch(); push(paths); reproj_error(model_dir, label) -> dict; ba_gate(after, n_views, *, max_px, min_registered) -> list[str] problems (empty = pass)
Used by: mvs_job/Dockerfile (ENTRYPOINT); run_job/run_upload.py; mvs_job/test_ba_gate.py; src/pipeline/local_gpu.py (ba_gate); outputs (scene_dense.ply, scene_dense_mesh*.ply/obj, mvs_result.json) consumed by tools/finish_mvs.py
Gotcha: env BUCKET, KF_PREFIX, MA_PREFIX, OUT_PREFIX, RESOLUTION_LEVEL, REFINE_MESH, MESH_BLOB (non-empty = texture-only mode), TEXTURE_ARGS (default "--local-seam-leveling 0"; seam levelling blacked out charts), KF_CROP_TRBL (S1's crop, so the principal-point guard accepts the crop-shifted centre). Exits if the intrinsics residual is over 2.0 px, and before densifying if BA registered fewer than BA_MIN_REGISTERED (default 1.0) of the views or ended above BA_MAX_PX (default 1.0 px); that failure still uploads mvs_result.json with ba_gate.problems. Imports colmap_export from /app. Files of 900 MB or more are not uploaded.

### src/pipeline/test_colmap_export.py
Plain-script test of the principal-point guard (audit F-10): a known pinhole with a 20% top crop, pushed onto a 518x224 model grid; the true crop-shifted centre passes with the crop and is refused without it, the keyframe centre passes, far from both is refused; parse_crop accepts four fractions and refuses the rest. Run `python src/pipeline/test_colmap_export.py` (numpy only).

### mvs_job/test_ba_gate.py
Plain-script test of run_mvs.ba_gate: the three recorded Kolu MVS results in research/run-evidence/ must pass; a lost view, 4 px after BA, an empty analyzer dict must fail; the threshold override works. Run `python mvs_job/test_ba_gate.py` (numpy only, no COLMAP).

### mvs_job/run_mvs_sharded.py
Horizontally sharded MVS variant selected by env STAGE: prep (global SfM + BA, prep.json, sparse_ba/), densify (N tasks, one view window each, shards/dense_NNN.ply), fuse (concat, voxel dedupe, Poisson mesh).
Exports: stage_prep(), stage_densify(), stage_fuse(); windows(n_views, n_shards, overlap); filter_model(src, dst, keep_names)
Used by: mvs_job/Dockerfile (COPY only; entrypoint must be overridden); src/pipeline/local_gpu.py (filter_model). No deploy config invokes it.
Gotcha: reads KF_CROP_TRBL like run_mvs.py. Known defect: prep does not pull conf.npy or apply the conf gate, so the intrinsics fit can fail the 2.0 px guard (fixed in run_mvs.py only). Env N_SHARDS=5, SHARD_OVERLAP=4, CLOUD_RUN_TASK_INDEX. Densify re-plans windows from its own env rather than prep.json.

### mvs_job/Dockerfile
ubuntu:24.04 (OpenMVS 2.4.0 prebuilt binaries need GLIBC 2.38): CPU COLMAP, Python 3.11 via micromamba, open3d 0.18/trimesh/laspy/rasterio, OpenMVS binaries symlinked into /usr/local/bin with a loader smoke test. Copies src/pipeline/{colmap_export,gravity,export_formats}.py and both run_mvs scripts. Built by deploy/cloudbuild-mvs.yaml.

## mapanything_job/

### mapanything_job/run_mapanything.py
CPU MapAnything inference job (facebook/map-anything-apache): downloads images from IN_PREFIX, infers per-view point maps and poses, uploads points/colors/conf/mask/cameras/intrinsics/depth_z .npy plus mapanything_result.json to OUT_PREFIX.
Exports: main(); fetch() -> sorted image names
Used by: mapanything_job/Dockerfile (ENTRYPOINT); Cloud Run job kolu-ma (image mapanything:v2) started by run_job/run_upload.py; deploy/batch_kolu*.json; outputs consumed by mvs_job/run_mvs*.py and tools/finish_kolu.py
Gotcha: MAX_VIEWS defaults to 8 and silently truncates the sorted image list. Colours are sampled with the model's own scale and centre-crop (a plain resize shears colour off the geometry). Job "sih26158-mapanything" runs the older v1 synthetic-harness image, not this.

### mapanything_job/Dockerfile
python:3.12-slim with CPU torch 2.6, map-anything installed from source, Apache weights baked into HF_HOME=/opt/hf, OMP/MKL threads 8. Build context is mapanything_job/ itself. No cloudbuild yaml.

## deploy/

### deploy/batch_kolu.json
GCP Batch spec: mapanything:v2 on n2-highmem-16 over mapanything/kolu_input -> kolu_out, MAX_VIEWS=45, 5400 s max run time, 1 retry.

### deploy/batch_kolu_us.json
Byte-identical to batch_kolu.json despite the "_us" name.

### deploy/cloudbuild-mvs.yaml
Cloud Build: mvs_job/Dockerfile from the repo root into asia-south1-docker.pkg.dev/$PROJECT_ID/sih26158/mvs:v9, 2400 s timeout. Bump the tag when rebuilding.

### deploy/cloudbuild-probe.yaml
Cloud Build step that runs inside mvs:v1 and dumps COLMAP and OpenMVS CLI flags. Discovery only.

### deploy/cloudbuild-run.yaml
Cloud Build: run_job/Dockerfile from the repo root into .../sih26158/run:v3.

### deploy/vertex_a100test.yaml
Vertex AI probe on a spot A100 that prints torch.cuda availability (GPU quota test).

### deploy/vertex_gputest.yaml
Vertex AI probe on a spot T4 that prints torch/CUDA info and nvidia-smi (GPU quota test).

### deploy/web-bucket-cors.json
Proposed CORS rule for gs://sih26158-mumbai: PUT from https://tesseract-demo.vercel.app with Content-Type and x-goog-content-length-range allowed. Apply it (merged with any existing rules) with `gcloud storage buckets update gs://sih26158-mumbai --cors-file=deploy/web-bucket-cors.json` before deploying the upload page that sends the header.

## demo/

### demo/.gitignore
Ignores .vercel, .env*, node_modules/, package-lock.json.

### demo/.vercelignore
Keeps README.md, gallery/README.md, .env*, .vercel and test/ out of the Vercel deploy.

### demo/package.json
Vercel project sih26158-demo on Node 22.x; deps @google-cloud/storage 7.14.0 and @google-cloud/run 1.5.0 for api/*.js. Use npm, not pnpm (pnpm's global store redirect breaks builds on this machine).

### demo/vercel.json
Functions pinned to region bom1 (Mumbai), api/*.js maxDuration 30 s; Cache-Control max-age 86400 with swr 7 d on /assets, /gallery/assets, /gallery/mesh.

### demo/robots.txt
Disallows all crawlers; pages are shared by link.

### demo/README.md
Operator notes for the one-clip walkthrough: the three acts, lectern keys, the "replay, not live" answer, design-system audit, rebuild commands.
Gotcha: partly stale: still says metres are 5.5x too small "until calibration lands" (x5.54 is now applied) and that build_all builds three pages (now four).

### demo/api/_lib.js
Shared plumbing for the Vercel functions: lazily required GCP clients from a service-account key, env-driven limits, run-id minting and validation, the running-execution count, atomic claim objects (per-run start claim, numbered daily slots, a start lease), JSON response helper.
Exports: BUCKET, PROJECT, REGION, JOB, MAX_BYTES, MAX_CONCURRENT, MAX_PER_DAY, PAUSED; storage(), jobs() (Run v2 JobsClient), execs() (ExecutionsClient), bucket(); newRunId() -> 32-hex; isRunId(s) -> bool; runningCount() -> Promise<number>; claim(name, body) -> Promise<bool> (create with ifGenerationMatch=0, nonce-checked on 412); release(name) (delete, errors swallowed); slotsUsedToday() -> Promise<number>; reserveSlot(runId) -> Promise<slot name | null> (web/_slots/<UTC day>/NNN.json); execution(shortName) -> Promise<Execution | null> (short name regex-checked); START_LEASE; acquireLease(name, ttlMs) -> Promise<bool> (claim, or take over a lease older than 120 s by generation-matched delete); json(res, code, body) (no-store); _inject({storage, jobs, execs}) for tests
Used by: demo/api/runs.js, demo/api/start.js, demo/api/status.js, demo/api/file.js, demo/test/api.test.js
Gotcha: env GCP_SA_KEY (whole SA JSON; throws on first client use if missing), GCS_BUCKET, GCP_PROJECT, GCP_REGION, RUN_JOB (sih26158-run), MAX_UPLOAD_BYTES (600 MiB), MAX_CONCURRENT (1), MAX_RUNS_PER_DAY (12), PAUSED ("1" = kill switch without redeploy). No auth: the 128-bit run id is the only capability. The daily cap counts slot objects per UTC day, not executions. Listing executions must use ExecutionsClient (JobsClient fails at runtime). The SA needs objects.create/get/delete for claims and the lease (web/_lock/start.json). Limits must match run_job/run_upload.py and tools/build_run.py.

### demo/api/runs.js
POST /api/runs {name, size, type}: checks pause, declared size, running count and daily slots used (advisory), mints a runId, returns a 30-min v4 signed PUT URL for gs://BUCKET/web/<runId>/source<ext> with x-goog-content-length-range 0..MAX_BYTES signed in.
Exports: default handler -> 200 {runId, uploadUrl, uploadHeaders, object} | 405 | 503 paused | 413 | 429 | 500
Used by: demo/run/index.html, demo/test/api.test.js
Gotcha: the video never passes through the function; the browser PUTs to GCS so imagery stays in asia-south1. The PUT must send uploadHeaders exactly (content-type and the signed length range) or GCS rejects it, and the bucket CORS must allow x-goog-content-length-range (deploy/web-bucket-cors.json).

### demo/api/start.js
POST /api/start {runId}: validates the id, confirms web/<runId>/source* exists and is under MAX_BYTES, takes the start lease, then (startUnderLease) re-checks concurrency, claims web/<runId>/started.json, reserves a daily slot, then JobsClient.runJob on job sih26158-run (run_job/run_upload.py) with env override RUN_ID.
Exports: default handler -> 202 {runId, state: "starting"} | 400 | 409 already started | 413 | 429 busy, another start in progress, or daily cap | 503 | 500
Used by: demo/run/index.html, demo/test/api.test.js
Gotcha: claim and slot are atomic (GCS ifGenerationMatch=0). The lease makes the running-count check and the launch one step across different ids. Unless the job launched, everything created (including a claim whose write errored after landing) is released, and the lease always is, before the response is sent. Does not wait for the execution; run_upload.py writes status.json.

### demo/test/api.test.js
node:test suite for the upload API against in-memory fakes of GCS and Cloud Run (no SDKs, no network): status reconciliation for killed workers and starts that never reported; one start per run id, concurrent starts for one id and for different ids at the last free slot, daily cap at start, release on failed launch and on storage errors, lease blocking and stale takeover, runs and start sharing slots, the signed byte bound, the declared-size check. Run `node --test "demo/test/*.test.js"`.
Gotcha: sets MAX_RUNS_PER_DAY=2 and MAX_CONCURRENT=3 before requiring _lib; the fake lists every launched execution as running; lives outside demo/api/ because Vercel deploys every file there as a function.

### demo/api/status.js
GET /api/status?id=<runId>: proxies web/<runId>/status.json (schema sih26158/web-run/1) with no-store. While the file is non-terminal it asks Cloud Run whether the execution it names has ended, and if so returns it as failed (or partial when a preview exists) with error code WEB-ENDED.
Exports: default handler -> 200 status JSON | 200 {runId, state: "starting", stages: [{id: "boot"}]} while the file does not exist | 200 failed when started.json is over 15 min old and no status exists | 400 | 500
Used by: demo/run/index.html (polled every 5 s), demo/test/api.test.js
Gotcha: a proxy, not a signed URL, because a signed URL would expire mid-run. Never writes back; a terminal state from the job is returned untouched. If the execution lookup fails, the job's own status is returned as is. Needs run.executions.get on the SA.

### demo/api/file.js
GET /api/file?id=<runId>&p=<preview|final>/<name>: checks the object exists, 302 to a 15-min signed download URL (attachment). preview maps to web/<runId>3d/export/<name>, final to web/<runId>mvs3d/export/<name>.
Exports: default handler -> 302 | 400 | 404 | 500
Used by: demo/run/index.html
Gotcha: p must match /^(preview|final)\/[A-Za-z0-9._-]{1,64}$/ (no traversal). Redirects because exports reach hundreds of MB. Prefixes must match publish_model() in run_job/run_upload.py.

### demo/index.html
One-clip walkthrough (Kolu), about 6.5 MB self-contained with mesh and keyframes inlined: replays input, run and result, then a WebGL viewer with measure, points and mesh toggles. Only external file is assets/clip.mp4.
Gotcha: generated from tools/demo_template.html by tools/build_demo.py; edit the template. The build reads out/kf_kolu, out/kolu_mvs and out/kolumvs3d, none of which are in the repo.

### demo/console/index.html
"Tesseract - reconstruction console": every run from out/runs/*/run_manifest.json and calibrations, WebGL workspace that prints metres on calibrated runs and model units on unvalidated ones. Meshes load from ../gallery/mesh/<key>.js.
Gotcha: generated from tools/console_template.html (with tools/console_ds.css and demo/console/fonts/faces.css inlined) by tools/build_console.py; edit the template. The meta "tesseract-sources" stamp hashes template and CSS and CI fails if stale, so rebuild and commit after any edit.

### demo/console/fonts/faces.css
@font-face rules for IBM Plex Mono 400/500 and Plex Sans 400/500/600 from local woff2; inlined by tools/build_console.py via __FACES__.

### demo/gallery/index.html
Gallery of Kolu and Toolse: source video beside interactive 3D, baseline vs MVS toggle in a shared frame, calibrated or unvalidated scale label per clip. Geometry from mesh/*.js.
Gotcha: generated from tools/gallery_template.html by tools/build_gallery.py; edit the template. Village clips are excluded (rights not cleared, docs/16 L-8; builders gate on a WITHHELD set).

### demo/gallery/README.md
Operator notes for the gallery: per-tab narrative, keys, table number sources (out/ppt/measure_*.json from compare_mvs.py), A/B toggle normalisation, rebuild command.
Gotcha: stale: describes three tabs including Village; the page now has Kolu and Toolse only.

### demo/gallery/mesh/
Generated data blobs, 6-11 MB each (kolu_base, kolu_mvs, kolu_tex + kolu_tex.jpg atlas, toolse_base, toolse_mvs), each setting window.__MESH[key]. Written by tools/build_gallery.py (textured run via tools/pack_textured.py); read by the gallery and console. Never hand-edit.

### demo/qa/index.html
Viva technical Q&A, tiered by exposure; every answer tagged measured/designed/open with a cited source file; search box.
Gotcha: generated by tools/build_qa.py, whose HTML and answers live in the Python (no template); edit that file. The build re-greps about 54 headline figures against their sources and fails if any is missing.

### demo/run/index.html
Upload page: drag-drop or pick a clip, then POST /api/runs, PUT to the signed URL with the returned uploadHeaders, POST /api/start, poll /api/status every 5 s until done/failed/refused/partial. Renders stage rows (elapsed vs expected) and preview/final cards with /api/file links. Run id lives in location.hash so reopening resumes polling.
Gotcha: generated from tools/run_template.html by tools/build_run.py (__LIMITS__ injected); edit the template. tools/build_all.py does not build this page. No 3D view yet: the packed.json run_upload.py publishes is not read here.

## viewer/

### viewer/index.html
Standalone hand-written three.js 0.160 viewer (cdnjs, own minimal GLB reader). Fetches model.glb and run_manifest.json from its own directory, rotates the Z-up UTM mesh to Y-up, HUD shows CRS, geoid separation, absolute and aligned RMSE, completeness, points, runtime.
Gotcha: needs HTTP serving and network for the CDN. Reads the old run_demo.py flat manifest keys (crs, accuracy_absolute_rmse_m, total_s), not the sih26158/run-manifest/1 schema. No build tool writes it.

## notebooks/

### notebooks/README.md
Free GPU options (Kaggle chosen: T4 x2, about 30 h/week) and how to run kaggle_mapanything_real_drone.ipynb (ODM Aukerman CC0, 77 photos, Apache checkpoint, yaw-only georeference). The notebook measures speed, not accuracy.

### notebooks/_build_nb.py
Generates notebooks/kaggle_mapanything_real_drone.ipynb from md()/code() builders and ast-checks each code cell. Run `python notebooks/_build_nb.py`.
Gotcha: the .ipynb is generated; edit this script.

### notebooks/_build_nb_video.py
Generates notebooks/kaggle_video_to_3d.ipynb the same way. Run `python notebooks/_build_nb_video.py`.
Gotcha: the .ipynb is generated; edit this script. Markdown embeds screen verdicts and S1 numbers as fixed text.

### notebooks/kaggle_mapanything_real_drone.ipynb
Generated by _build_nb.py (19 cells, no outputs): Kaggle GPU MapAnything on Aukerman images with EXIF GPS to ENU, timing against 600 views in 900 s, inline yaw-only georeference, plots. No repo imports.

### notebooks/kaggle_video_to_3d.ipynb
Generated by _build_nb_video.py (21 cells, no outputs): MapAnything on Kolu keyframes (dataset input), full-video time extrapolation, inline filter and fuse, open3d Poisson mesh, renders, PCA structure check.

## tools/

Build graph (template -> generator -> output): console_template.html + console_ds.css + demo/console/fonts/faces.css -> build_console.py -> demo/console/index.html; demo_template.html -> build_demo.py -> demo/index.html; gallery_template.html -> build_gallery.py -> demo/gallery/index.html + demo/gallery/mesh/*.js; build_qa.py (inline HTML) -> demo/qa/index.html; run_template.html -> build_run.py -> demo/run/index.html; viewer_template.html -> build_viewer.py -> out/<run>/viewer.html. Two design systems: design_system.css (demo, gallery, qa, run; audited by check_design.py) and console_ds.css (console only, not audited). deck_theme.py is a third for the deck.

### tools/build_all.py
Build gate: runs build_console, build_demo, build_gallery, build_qa, test_console, check_design, check_wiring as subprocesses with PYTHONIOENCODING=utf-8; exits 1 if any step fails.
Used by: docs/15-engineering-handbook.md (build before deploying)
Gotcha: does NOT run build_run.py, check_onboarding.py or build_viewer.py. The console loads ../gallery/mesh/*.js at runtime, so both builds are needed.

### tools/build_console.py
Generates demo/console/index.html (ADR-025) from console_template.html, console_ds.css and faces.css. For every out/runs/*/run_manifest.json it injects one JSON blob (verdicts, stages, artefacts, scale, codes, credit, models) plus build info and the ladder from src/tesseract/contracts.
Exports: sources_sha() -> 12-hex sha256 of template+css (CRLF normalised); verify(rundir, man) -> {ok, problems}; host_line(h); flat_facts(facts); check(data, page) (sys.exit on violation); main() -> int
Used by: tools/test_console.py (sources_sha), tools/build_all.py
Gotcha: needs gitignored out/, so CI never rebuilds it. The sources hash is stamped as meta "tesseract-sources" and test_console fails on a stale page: rebuild and commit after editing template or css. Hard-coded WITHHELD (yt_short.mp4 drops the whole run), MODELS, NOTES (a real-footage run without a NOTES entry stops the build). check() rejects metres on an unvalidated scale, em/en dashes, unfilled __X__ placeholders and verdicts not starting with met / not met / not measurable.

### tools/build_demo.py
Generates demo/index.html (one-clip replay) from demo_template.html, injecting __DS_CSS__, __MESH__ (lifted from out/kolumvs3d/viewer.html), __RUN__ (phases, timings, exports, verdict, scale, base64 keyframe thumbs), __OGIMG__, __DESC__, __TITLE__; also writes demo/assets/og.jpg.
Exports: jload, mesh_from_viewer(path) -> dict, thumbs(dir, width, quality), og_card, probe(path) -> ffprobe dict, main()
Used by: tools/build_all.py
Gotcha: reads out/kf_kolu, out/kolu_mvs/mvs_result.json, out/kolumvs3d/* and data/cand/kolu.webm; demo/assets/clip.mp4 must already exist. Verdict prose and some counts are typed into the script.

### tools/build_gallery.py
Generates demo/gallery/index.html from gallery_template.html (Kolu and Toolse tabs) and writes demo/gallery/mesh/<key>.js for kolu_base, kolu_mvs, kolu_tex, toolse_base, toolse_mvs plus mesh/kolu_tex.jpg and assets/og.jpg.
Exports: packed(run) -> (D dict with centroid, half-extent): reads out/<run>/packed.json, else regex-lifts `const D = {...}, S = {` from out/<run>/viewer.html; probe(path) -> (w, h, dur); poster(clip_rel); og_card; main()
Used by: tools/build_console.py, tools/pack_textured.py, run_job/run_upload.py (all import packed), tools/build_all.py
Gotcha: comparison figures come from out/ppt/measure_kolu.json and measure_toolse.json, not the meshes. Exits if two models of one clip have different calibrations. gallery/assets/*.mp4 must exist. footage.credit(..., sys.exit) stops the build on an unrecorded clip.

### tools/build_qa.py
Generates demo/qa/index.html with no template: PAGE, CSS and JS are string constants, about 55 hand-written questions in QA, tiered settled / mechanism / challenged / exposed, tagged measured / designed / open.
Exports: Q(tier, q, a, tag, src, detail) -> dict; QA, TIERS, CHECKS; render() -> (html, n); check_numbers() -> [(needle, rel, why)]; main()
Used by: tools/build_all.py
Gotcha: check_numbers() greps about 64 literal figures in their cited files (out/ runs, docs/*.md, research/calibration/kolu.json) and exits 1 if any is missing, so editing a figure in a doc can break this build.

### tools/build_run_page.py
Writes <run>/index.html for one tesseract run from run_page_template.html: the textured mesh (geometry/scene_tex.obj, per-corner int16 positions and uint16 UVs, atlas re-encoded as a 4096 px JPEG) or else a thinned vertex-coloured mesh, points and camera path in the levelled F5 frame, plus stages, S3 breakdown, verdicts, codes, screen/ingest/level/DSM facts, file links and keyframe thumbnails.
Exports: read_mesh_ply(path) -> (V, F); read_obj(path) -> (V, T, F, FT, texture path) (several atlases are placed side by side in one temp JPEG and each face's UVs moved into its strip); similarity(src, dst) -> (s, R, t); cluster_decimate(V, F, target) -> (V, F); pack(run, tri_budget, pt_budget); describe(run) -> dict; main(argv) (CLI `<run> --out --tris --points`)
Used by: tools/view_check.py and run manually; not in build_all
Gotcha: no open3d. Faces whose UV centroid samples TextureMesh's orange empty colour (0xFF7F27) are dropped. The mesh and cameras go F4 to the export frame through georef.json (when the manifest says georeferenced) or level.json via stages._apply_frame_json, so S5's depth stretch is carried; only a run without either file falls back to a similarity fitted between points.npy and points_llf/points_geo. File and keyframe links are relative, so the page must stay in its run folder. ING_REJECT has a readable label. NaN camera rows (unregistered views) are skipped. A textured demo page is about 17 MB.

### tools/view_check.py
Reads PINHOLE or SIMPLE_PINHOLE cameras. Builds held-out geometry by excluding every tenth keyframe from the OpenMVS dense and texture model, then renders its textured OBJ into each held-out registered camera at quarter resolution. Reports covered-pixel PSNR and SSIM with coverage separately in JSON. A held-out view the mapper did not place is listed under "unposed", counts as zero coverage and is left out of PSNR/SSIM; only no posed view at all raises.
Exports: project_points(vertices, camera, intrinsics) -> (uv, depth); rasterize(...); score(run_dir, geometry_dir, holdout_names, scale=4) -> dict; main() (CLI `<run> --build --geometry <dir> --out <json>`)
Used by: tools/test_view_check.py and local audit runs
Gotcha: imports numba and skimage, plus src/pipeline/local_gpu.py and tools/build_run_page.py. Use identical keyframe sets when comparing runs; poses are fitted on all keyframes but dense and texture inputs exclude held-out views.

### tools/test_view_check.py
Projection test for one camera and point with known pixel (370, 360), score() on a two-view scene where one held-out view is unplaced (counted uncovered, not a crash), and build_run_page.read_obj on a mesh over two atlases. Run `python tools/test_view_check.py`.
Used by: local audit runs
Gotcha: plain-script test; fails with exit code 1 on a projection mismatch.

### tools/geometry_check.py
Shape checks for a local GPU geometry folder with no ground truth (research/10): sparse points within 3% of the flight height of one RANSAC ground plane, share of dense cells layered over 10% of it, largest camera step over the median; --out writes side and top pictures.
Exports: ground_frame(P, cams) -> (centre, up); read_sparse(txt dir) -> (N,3); check(geo, out=None) -> dict (dense_points, cameras, sparse_on_plane, layered_cells, cell_spread_median, step_ratio)
Used by: run manually (research/10 section 1)
Gotcha: assumes mostly flat ground under the flight; on a hill or a facade the plane numbers mean nothing. Needs sparse_txt/, which local_gpu keeps. NaN camera rows (unregistered views) are skipped.

### tools/build_run.py
Generates demo/run/index.html (upload page) from run_template.html, injecting __DS_CSS__, __TITLE__, __DESC__, __LIMITS__.
Exports: main(); TITLE, DESC, LIMITS
Used by: run manually; not in build_all
Gotcha: LIMITS text (10 min, 600 MB, 60 keyframes, ~70 min) must match run_job/run_upload.py. Exits if an __X__ placeholder survives before the first <script>.

### tools/build_sih_ppt.py
Edits the official SIH2026 idea template into out/ppt/SIH26158_IdeaSubmission.pptx and exports a PDF via PowerPoint COM (Windows only).
Exports: measurements() -> dict; build() -> pptx path; to_pdf(path); write, textbox, metric, header, drop_slide, fetch_template
Used by: documented in docs/07-idea-submission.md
Gotcha: SUPERSEDED 2026-09-22 by the team's Google Slides deck, and still reads the withdrawn Village (ytd) run. Writes *_DRAFT.pdf while TEAM_NAME/TEAM_ID are placeholders; exits unless Kolu is calibrated.

### tools/build_viewer.py
Packs one run into a self-contained out/<run>/viewer.html from viewer_template.html (not viewer/index.html): __DATA__ (base64 int16-quantised mesh and points), __STATS__, __TITLE__, __SUBTITLE__.
Exports: pack(dir, tri_budget=160_000, pt_budget=220_000) -> {vpos, vcol, idx, ppos, pcol, nv, nt, np, scale}; CLI `build_viewer.py <indir> --stats f --out f`
Used by: tools/finish_kolu.py, tools/finish_mvs.py (subprocess); output regex-read by build_demo.py and build_gallery.packed()
Gotcha: the `const D = {...}, S = {` text is a contract downstream builders regex-match. Positions quantised to +-32000 about mid/scale and rotated by render_views.upright_frame. Non-ASCII rewritten as numeric entities. Needs open3d.

### tools/check_design.py
Audits built demo/index.html, gallery and qa against the design system: font sizes, spacing, radii, off-token hex colours, WCAG AA contrast. Exits 1 on any violation.
Exports: audit(name, path) -> dict; contrast_report(); lum, ratio; main() -> int
Used by: tools/build_all.py
Gotcha: FONT_SIZES, SPACING, RADII, TOKEN_HEX are hand-mirrored from design_system.css; add new tokens in both places. Does not audit console or run pages.

### tools/check_onboarding.py
Re-greps about 50 figures quoted in docs/00-start-here.md against their source documents (after normalising dashes, the multiplication sign, <= and >=), and fails on an em/en dash in docs/00 or a URL found nowhere else in docs/, research/ or README.
Exports: CLAIMS, norm(s), main() -> int (2 if docs/00 missing)
Used by: .github/workflows/ci.yml
Gotcha: two-way: a figure missing from its source fails, and so does a figure dropped from docs/00 but still in CLAIMS.

### tools/check_wiring.py
Greps demo, gallery and qa pages for getElementById/querySelector/classList targets and checks the markup has each one; lists styled classes nothing applies.
Exports: scan(name, path) -> (problems, dead); main() -> int
Used by: tools/build_all.py
Gotcha: RUNTIME_OK and SYSTEM allow-lists must be extended when adding JS-only classes. An unbuilt page counts as a failure.

### tools/console_ds.css
Console stylesheet inlined as __DS__: monotone greyscale, radius 0, IBM Plex Sans/Mono, dark default with light theme via prefers-color-scheme or [data-theme]. Tokens --bg/--panel/--raised/--line/--fg/--fg-2/--fg-3, --t-xs..--t-xl (11-20px), --sp-1..--sp-6 (4-32px).
Used by: tools/build_console.py (inlined and hashed)
Gotcha: separate token set from design_system.css and not audited. Any edit changes the sources stamp: rebuild the console and commit or CI fails.

### tools/console_template.html
Console template. Placeholders __TITLE__, __DESC__, __SRCSHA__, __FACES__, __DS__, __QA__, __DATA__. Vanilla JS, hash routing `#/<run>/<tab>` (overview/stages/model/artefacts/contracts), filterable run rail (#q, j/k), theme toggle in localStorage "tess.theme", WebGL2 workspace lazy-loading DATA.meshDir + "<key>.js" into window.__MESH, textured and per-vertex packs, measure tool.
Used by: tools/build_console.py
Gotcha: tools/test_console.py drives globals (RUNS, BY, cur, curTab, active, marks, measuring, curMVP) and ids (#runs, #main, #gl, #ovl .m-txt, #hud, #bMeasure, #bClear, #bTheme, #q, [data-m]); renaming any breaks CI. r.credit is inserted unescaped (trusted HTML from footage.py).

### tools/deck_theme.py
Visual system for the SIH deck and its matplotlib figures: NAVY #1F497D, RUST #A8552F, greys, Segoe UI / Consolas, T_* point sizes, 12-column grid, FIG placed sizes.
Exports: colour/type constants; X(n) -> column left edge (in); SPAN(n); FIG {beforeafter, accuracy, missions, timing: (w, h)}
Used by: tools/build_sih_ppt.py, tools/make_ppt_figs.py

### tools/demo_template.html
Template for demo/index.html: three-act replay (Input, Run with phase timeline, Result as WebGL2 viewer with mesh/points/measure), "Replay" banner, nav to gallery/ and qa/. Placeholders __DS_CSS__, __TITLE__, __DESC__, __OGIMG__, `var D = __MESH__, R = __RUN__;`.
Used by: tools/build_demo.py
Gotcha: measurement multiplies by R.scale.factor only when status is not unvalidated; rendering must never see the factor (docs/09 section 5). Must stay file:// safe (classic scripts, no fetch).

### tools/design_system.css
Shared stylesheet for /, /gallery/, /qa/, /run/. BASE layer: :root tokens (surfaces, AA text colours, single amber --accent #e8a84a, --ok, --bad, type 11-28px, spacing 4-48px, radii 3px/6px), type, controls, chips, tables, site chrome. VIEWER layer after the `LAYER:VIEWER` sentinel comment: canvas, #ovl .m-*, .hud, .dock, .mtip, .loading.
Used by: tools/design_system.py; values mirrored in tools/check_design.py
Gotcha: do not remove or rename the sentinel. Keep BASE under about 15 KB. New scale values also go into check_design.py.

### tools/design_system.py
Loads design_system.css and returns the minified BASE or BASE+VIEWER layer for inlining.
Exports: css(layer="viewer"|"base", minify=True) -> str; token(name) -> value (KeyError if absent); SENTINEL = "LAYER:VIEWER"
Used by: tools/build_demo.py, tools/build_gallery.py, tools/build_qa.py, tools/build_run.py
Gotcha: _min() is a naive regex minifier; CSS relying on whitespace around {}:;,> breaks.

### tools/finish_kolu.py
Feed-forward (MapAnything) finishing: pulls gs://sih26158-mumbai/<GCS_PREFIX> into out/<RUN>_raw, runs fuse_mesh.py and render_views.py into out/<RUN>3d, writes viewer_stats.json (funnel scraped from fuse_mesh stdout), then build_viewer.py.
Exports: main(); env RUN (default kolu), GCS_PREFIX, KF_DIR, TITLE, SUBTITLE
Used by: run_job/run_upload.py (subprocess, preview stage)
Gotcha: skips the pull when out/<RUN>_raw/points.npy exists. Needs out/<KF_DIR>/ingest.json. Funnel values depend on fuse_mesh's printed line prefixes. sys.executable must have open3d.

### tools/finish_mvs.py
OpenMVS finishing: pulls MVS outputs into out/<RUN>_mvs, converts scene_dense.ply and the best mesh (textured OBJ > refined > plain) into points_fused/colors_fused/mesh_v/f/c .npy + model.ply in out/<RUN>mvs3d, copies cam_centres.npy from the baseline, colours a colourless mesh from nearest dense points, then runs render_views, compare_mvs, export_formats (non-fatal) and build_viewer.
Exports: main(); env RUN (default ytd), GCS_PREFIX, BASELINE, TITLE, SUBTITLE
Used by: run_job/run_upload.py (subprocess, final stage)
Gotcha: pull skipped only when scene_dense.ply, scene_dense_mesh.ply and mvs_result.json all exist. export_formats reads out/<RUN>_raw/cameras.npy if present. docs/15 still says the interpreter is hard-coded; it now uses sys.executable.

### tools/footage.py
Rights record for every published clip, keyed by the filename manifests store in `source`: title, author, licence and URLs for kolu.webm (CC0), toolse.webm (CC BY-SA 4.0), bahai.webm (CC BY 3.0); builds attribution HTML.
Exports: FOOTAGE; is_synthetic(source) -> bool; clip_of(source); known(clip); share_alike(clip); credit(clip, subject="The 3D model", refuse=None, clip_published=False) -> HTML str
Used by: tools/build_console.py, tools/build_gallery.py
Gotcha: callers pass refuse=sys.exit, so an unrecorded clip stops the build (docs/16 F-4). Uploaded clips have no record, which is why web runs never appear on the gallery or console.

### tools/gcs_io.py
Downloads every object under a GCS prefix into a local dir with google-cloud-storage (no gsutil, no shell).
Exports: pull(prefix, dest, bucket="sih26158-mumbai", log=print) -> [local paths]; DEFAULT_BUCKET
Used by: tools/finish_kolu.py, tools/finish_mvs.py
Gotcha: keys are flattened to basenames, so nested keys collide. SystemExit when nothing is found. Needs GCP application credentials.

### tools/kaggle_run.py
Pushes notebooks/kaggle_video_to_3d.ipynb as a private Kaggle GPU kernel (hard-coded slugs), polls up to an hour, downloads output.
Exports: push_kernel(), wait(poll=30, limit_s=3600), pull_output(dst="out/kolu3d")
Used by: manual (EXP-11/12 era)
Gotcha: needs ~/.kaggle/kaggle.json; dst is relative to cwd. ADR-010 limits Kaggle to non-Indian public footage.

### tools/make_ppt_figs.py
Renders four deck figures at 300 dpi and deck_theme.FIG sizes into out/ppt: fig_beforeafter, fig_accuracy, fig_missions, fig_timing.
Exports: series(clip), before_after(az, el), accuracy(), missions(), timing()
Used by: PNGs embedded by tools/build_sih_ppt.py
Gotcha: needs out/kolu3d and out/kolumvs3d mesh and point .npy plus render_views.

### tools/make_share_images.py
Standalone share PNGs into out/share (summary, before/after crops, resolution vs scale chart).
Used by: manual
Gotcha: numbers are hand-typed and predate the docs/08 calibration; metre labels are uncalibrated and several figures stale. Never use as a source.

### tools/gallery_template.html
Template for demo/gallery/index.html: clip tabs with source video beside a WebGL viewer, baseline vs MVS toggle in a shared view scale, measure tool, scale label per clip. Placeholders __TITLE__, __DESC__, __OGIMG__, __DS_CSS__, __EXAMPLES__, __NOTE__. Meshes lazy-load from mesh/<key>.js via a classic script tag into window.__MESH (file:// safe).
Used by: tools/build_gallery.py
Gotcha: measurement multiplies by the clip's scale.factor and prints " units" when unvalidated, " m" otherwise; uScale and rendering never see the factor.

### tools/pack_textured.py
Packs a textured OpenMVS OBJ for the console: pymeshlab texture-aware decimation, vertex split at UV seams, atlas cropped to used rows, re-quantised into the reference run's exact frame and int16 mid/scale. Writes OUT/packed.json and OUT/atlas.jpg.
Exports: decimate(obj, target), main() -> int; env SRC (out/kolu_tex_mvs), REF (out/kolumvs3d), OUT (out/kolutex3d), TRI (300000), ALIGN
Used by: its packed.json is read by build_gallery.packed()
Gotcha: exits if the cropped atlas is over 50% fill or the reference quantisation cannot be recovered. Atlas name "kolu_tex.jpg" is hard-coded.

### tools/run_page_template.html
Template for <run>/index.html: summary chips, WebGL2 viewer (textured or vertex-coloured mesh, points, flight path, four presets), stage/S3/verdict/code tables, fact lists, file table, lazy keyframe grid. Placeholders __TITLE__, `const D = __DATA__, R = __RUN__;`.
Used by: tools/build_run_page.py
Gotcha: dark-only tokens and Google Fonts over the network; keyframe images load from relative keyframes/ paths. The textured mesh is drawn unshaded with UNPACK_FLIP_Y (OBJ v runs bottom-up) and only once the atlas image has loaded.

### tools/run_template.html
Template for demo/run/index.html: pick or drop a video, POST /api/runs, PUT to the signed URL sending the server's uploadHeaders, POST /api/start, poll /api/status?id=, render stages and preview/final downloads via /api/file. Placeholders __DS_CSS__, __TITLE__, __DESC__, __LIMITS__.
Used by: tools/build_run.py
Gotcha: fixed relative "/api" base, so it is the one page that cannot open from file://. Not audited by check_design or check_wiring.

### tools/scale_cal.py
Per-run metric scale read from research/calibration/*.json (the builders' reader; src/tesseract/scale.py duplicates it).
Exports: load(run) -> {factor, bracket, status, method, summary[, source]} (default factor 1.0, "unvalidated"); for_page(cal) -> {factor, status, label e.g. "calibrated x5.54 (5.32-5.77)", basis}; CAL_DIR, UNVALIDATED
Used by: tools/build_console.py, tools/build_demo.py, tools/build_gallery.py, tools/build_sih_ppt.py, tools/make_ppt_figs.py, src/pipeline/export_formats.py
Gotcha: matches by membership in a file's "runs" list; first file in sorted order wins. Status outside calibrated/gnss/gnss+rtk raises ValueError. No global default factor (ADR-014).

### tools/test_console.py
Drives the committed demo/console/ in headless Chromium via Playwright over a local HTTP server, about 21 checks: runs and tabs render, calibrated vs unvalidated wording, the L5 refusal, the F7 run "demo", WebGL renders, uScale never carries the factor, atlas loads, measure prints " m" vs " units", theme, j-key, filter, phone overflow, no page errors.
Exports: serve(dir) -> (httpd, url); main() -> int; `--shots DIR`
Used by: .github/workflows/ci.yml, tools/build_all.py
Gotcha: FAILS if the page stamp differs from build_console.sources_sha(). Returns 0 (SKIP) without Playwright. Assumes run ids "kolu" and "demo" and an L5 run exist; unvalidated-run checks SKIP while no run has both a mesh and an unvalidated scale (backlog B-33).

### tools/viewer_template.html
Template for per-run out/<run>/viewer.html: standalone WebGL2 viewer with side rail (ingest, funnel, geometry, caveat), mesh/points toggles, HUD. Placeholders __TITLE__, __SUBTITLE__, `const D = __DATA__, S = __STATS__;`.
Used by: tools/build_viewer.py
Gotcha: own :root tokens and Google Fonts over the network. Keep the `const D = {...}, S = {` line exact; build_demo and build_gallery regex-parse it.

## docs/

### README.md
Project front page: the six PDF targets and scoring weights, six design-changing findings (VGGT licensed out, straight-pass degeneracy, 1 m unreachable on consumer GNSS, facades cap completeness, India residency, geoid/UTM traps), run commands, measured synthetic results, a CORRECTED note that real video now runs end to end, open questions for the organisers, layout.

### docs/SIH26158.pdf
The binding problem statement (PS 17, pp. 37-39 of the NTRO document), image-only with no text layer; the sih.gov.in listing has a placeholder instead of the target tables.

### docs/00-start-here.md
Narrative introduction to the whole project: PS as given, seven findings, stages S0-S8, frames F0-F7, the scale contract and the Kolu 5.5x lesson, the ladder, feasibility numbers, proven vs not, research tracks, compliance, commands, glossary and full references. tools/check_onboarding.py re-greps its figures and bans em/en dashes in it.

### docs/README.md
Suite index: what each numbered doc answers, reading paths by role, and the rules (numbers name their file, CORRECTED marker plus date, decisions change by new ADR, contracts change in the same commit as code).

### docs/01-SRS-requirements.md
Requirements traced to the PDF: R-O1..R-O6, scoring weights, R-C1..R-C9 challenges (R-C9 input admissibility added by the team), R-NF5 licensing and R-NF8 India residency. R-O3 is absolute and georeferenced. FBX via assimp. PDF re-verified 2026-09-22.

### docs/02-architecture.md
Architecture v1: the 900 s budget rules out classical SfM (EXP-01) and per-scene NeRF/3DGS, so feed-forward spine plus classical export tail. MapAnything Apache chosen over VGGT (AUP bans military), Pi3 (NC), DA3. Stages S1-S5 with budgets, keyframing, georef traps, bounded completion, two-layer dynamic-object defence. Extended by docs/13.

### docs/03-plan-sdlc.md
Plan against the SIH calendar (phases A/B/C), compute ladder (GCP GPU quota auto-denied, hidden global CPU quota 12, Baramati unreachable off campus, rented GPUs for non-Indian benchmarks only), trap list and risks. Superseded by docs/18 where they differ.

### docs/04-test-plan.md
Test register (T-ACC, T-COMP, T-PERF, T-ROB, T-EXPORT, T-UI) and the rule that no accuracy figure is quoted unless src/eval3d produced it. Recorded runs T-ROB-08, T-E2E-01, T-ROB-09. Permitted claim: 1 m absolute only with RTK.

### docs/05-quality-analysis.md
Why feed-forward geometry is patch-limited (2.2 cm sampling vs 30-50 cm information, DINOv2 patch 14) and the fix: keep poses, bundle-adjust (1.73 to 0.37 px on Kolu), densify with OpenMVS (1.8-3.6x finer, coverage 135% Kolu / 83% Village). Absolute lengths superseded by docs/08.

### docs/06-gcp-deployment.md
GPU survey (quota auto-denied; only reachable GPU is outside India), Cloud Run Jobs at 8 vCPU in asia-south1 (Kolu 32m43s, Short 18m03s), sharding results (5x4 vCPU 7% slower; 2x8 overlap 2 13% faster), 600 views about 36 min even fanned out; 15 min would need about 216 vCPU.

### docs/07-idea-submission.md
Portal fields (paste-ready idea text), SIH rules and the generated-deck build steps. Superseded 2026-09-22 by the team's Google Slides deck (research/05); do not rebuild the generated deck for submission.

### docs/08-measurement-validation.md
EXP-14 scale audit: Kolu 5.3-5.8x too small (lane 0.650 model m vs 3.5-3.75 m; waist 3.95 vs 21-22 m; clearance floor at least 3.85). Factor x5.54 in research/calibration/kolu.json, applied to viewers and all 7 exports. Global x2 rejected; plausibility band retired as validation. Read before trusting any length.

### docs/09-interface-contracts.md
Binding frames (F0-F7), units, stage I/O and failure codes. F4 to F5 via gravity up and scale.factor; F5 to F6 by a levelled, track-aligned 6-DOF Sim(3) (ADR-026), never 7-DOF. Scale contract schema sih26158/scale-calibration/1; only calibrated/gnss/gnss+rtk may print "m"; factor applied once at S6. Per-stage artefacts (screen.json, ingest.json, S3 .npy set, BA gate 1.0 px, georef.json, export_manifest.json), run_manifest.json (sih26158/run-manifest/1), viewer data contract (int16 /32000; factor enters measurement only). Codes ADM-*, ING-*, GEO-*, MVS-RC, REF-*, EXP-FORMAT. The S3b gate is registered = N, except the local GPU path (ADR-029): 50% of N, the rest dropped under GEO-UNREG. S5 on a video: SRT to F6, heights above take-off (ADR-030); with a gimbal pitch in the SRT a depth stretch in georef.json undoes the focal length's error first (ADR-032). Open gaps: C-3 closed 2026-09-26, C-4 metric_scaling_factor not saved, C-5 no priors passed to MapAnything.
Gotcha: ING-REJECT is fatal for unusable video but still written into run_manifest.json.

### docs/10-decision-log.md
ADRs 001-032, changed only by a new ADR or a dated amendment: 001 feed-forward spine (amended by 004); 002 MapAnything Apache; 003 harness before pipeline; 004 feed-forward for poses and scale only, geometry from MVS; 005 OpenMVS unmodified as a process (AGPL); 006 BA before densify; 007 vertical from ground plane; 008 5-DOF georef in ENU, project last, EGM2008 (amended by 026); 009 no CRS without GNSS; 010 India-resident compute; 011 CPU first; 012 shard densify 2x8 overlap 2; 013 screen before inference; 014 per-run evidenced scale, no global correction; 015 one frame for every export, assimp FBX; 016 per-vertex colour (fallback only since 2026-09-22); 017 demo is a file:// replay; 018 Python 3.12; 019 PyAV; 020 robust Sim(3) with MAD threshold; 021 chain windows, anchor once; 022 completeness against two denominators; 023 COLMAP PatchMatch GPU path (rejected by 027); 024 aerial metric-depth scale witness (proposed); 025 run console built from manifests; 026 level before georeferencing, yaw and slope from the track, roll from gravity; 027 the GPU path on one machine (MapAnything, COLMAP sequential, OpenMVS CUDA); 028 local poses from COLMAP's global mapper with MapAnything's camera fixed, OpenMVS fuse filter, textured mesh (partly supersedes 027); 029 the local S3b gate needs 50% of views registered, the rest dropped under GEO-UNREG; 030 a clip's SRT track georeferences it to F6, heights above take-off; 031 the global mapper refines one focal length from MapAnything's (amends 028; amended 2026-09-27: only when the views turn 10 degrees or more); 032 S5 corrects a straight pass's depth from the SRT's gimbal pitch.

### docs/11-state-of-the-art.md
Incumbents (Pix4D 75/60% overlap, 85% corridor), method families, benchmarks and what each proves, the licence register (section 5.1 pins checked by CI, 5.2 console fonts), and the world-class targets (600 s for a 10-min 4K clip on one 24 GB GPU, scale error 1%, 0.15 m with RTK, 90% observable surface).

### docs/12-research-program.md
Pre-registered experiments with pass/kill criteria, maturity gates G0-G4 (present at G2, claim at G3), tracks R1-R7, experiment register (EXP-14 done; 14b, 15, 16, 17, 20, 21, 22, 23 and more), data plan, current sprint.

### docs/13-target-architecture.md
Architecture v2: scale service priority (GNSS > known object > witness > model prior, plus footprint check), stage-DAG orchestrator with pluggable executors, separate pose (~600) and dense (~150-300) sets, optional GPU dense path, ladder L0-L5 with placement degrading separately, 900 s budget table, three topologies (Cloud CPU, Baramati GPU, air-gapped field kit). Built as src/tesseract/ on 2026-09-18; Slurm/Cloud Run executors and L1 not built. Texture row stale.

### docs/14-quality-gates.md
Metric definitions, commit/merge/milestone gates, regression thresholds on Kolu at 8 vCPU, benchmark protocol, and the claims ledger (items 1-28; 24 and 25 are the console's R-O5 and R-O2 verdicts, fixed in code 2026-09-24, not yet rebuilt; 26 relabels the README's RTK 0.098 m, measured in an already-level frame; 27 marks synthetic completeness and R-O4 as placement, not coverage; 28 is the 10-minute laptop GPU figure, run on the 1 fps B5v clip in 502.5 s and predicted for 30 fps; 20, 1 m accuracy, is valid as simulation with a gimbal pitch since 2026-09-27): every public figure with its source and status. Any change to a public number updates the ledger in the same change.

### docs/15-engineering-handbook.md
Onboarding: pins (Python 3.12, open3d only on 3.11 locally, COLMAP/OpenMVS/assimp in containers only, Windows needs PYTHONIOENCODING=utf-8 and MSYS_NO_PATHCONV=1), repo map, command table, conventions (comments record the defect behind a line, fail loudly, frame and unit in identifiers, deterministic), review checklist, demo deployment rules, trap register. Stale on finish_mvs's interpreter.

### docs/16-security-and-compliance.md
STRIDE threat model across cloud, Baramati and field kit; findings F-1 PROJ_NETWORK leaks the area of interest, F-2 runtime DINOv2 download, F-3 untracked demo/ (fixed), F-4 third-party footage (closed via WITHHELD); licence rows L-n (OpenMVS AGPL unmodified, footage provenance), field-kit baseline, drone operations.

### docs/17-operations-runbook.md
SLOs (first labelled result within 20 min, L0 within 15, zero crashes on unknown schemas), observability, incident playbooks, and the 36-hour finale runbook with a decision table from stage outcomes to ladder steps, on-day scale calibration, capture guidance.

### docs/18-roadmap.md
Calendar (idea submission 2026-09-30; finale December 2026 with the dataset on the day), milestones M0-M4, backlog B-01..B-33 with priorities, risk register R1-R17. Status note 2026-09-22: one person, Baramati unreachable, no aircraft. Open P1 items include B-08 priors, B-10 telemetry alignment, B-11 offline image, B-30 pick warnings, B-31 progressive output, B-32 dynamic objects, B-33 replacement clip.

### docs/architecture-prompt.md
Self-contained prompt for regenerating the architecture without repo access; quotes the PS and the measured state, bans invented numbers.

### docs/output.html
Static early results page: synthetic georeferenced run (consumer 2.260 m FAIL vs RTK 0.098 m PASS) and MapAnything on Kaggle T4 over ODM Aukerman.

### docs/report.html
Early one-page published findings report.

### docs/video3d.html
EXP-12 results page for the Nicosia clip (1,199 frames, 20 keyframes, about 260k points, 0.42 s/view on T4) with an embedded viewer.

## research/ (findings)

### research/01-licensing-findings.md
Licence verdicts for NTRO use: VGGT barred (AUP); MapAnything only via facebook/map-anything-apache; Pi3 weights non-commercial; Depth Anything 3 Apache checkpoints only.

### research/02-ingestion-export-findings.md
DST 2021 geospatial rules (process in India), geoid and UTM traps, DJI sidecar contents, why intrinsics are fixed, FBX via assimp, PyAV over decord, and an explicit "do not rely on these" list.

### research/03-usegeo-protocol.md
UseGeo chosen over H3D as the LiDAR-referenced benchmark (EXP-22): 829 images, GSD 1.7-1.9 cm, CC BY-NC-SA 4.0 evaluation only; protocol and rented-GPU pricing.

### research/04-dji-srt-formats.md
EXP-23: the five DJI SRT format families across 20 fixtures (including the misspelt `longtitude`), abs_alt is barometric; parser fixed and fuzzed (65 checks, 68 with the variable-frame-rate cases); time-keyed lookup uses frame PTS since 2026-09-25.

### research/05-deck-audit.md
Audit of the 2026-09-22 Google Slides deck: run-derived numbers correct, five things to change (an unsourced synthetic figure, barred-licence model references, "0 GCPs" implying GPS scale, live 3D claimed, unbuilt stages in present tense) plus a visual pass.

### research/06-deck-rebuild.md
Deck rebuild brief: cut to the 6-slide limit, slide-by-slide decisions, images to make, pre-send checks.

### research/07-gallery-clip-attempt.md
Adding Toolse (CC BY-SA 4.0) as a second gallery clip: MapAnything at 10.68 s/view at 60 views, MVS intrinsics-guard refusal fixed with a conf gate, build_console verdict-guard and Vercel token snags, MVS drops open water.

### research/09-gpu-pipeline.md
The local GPU pipeline (2026-09-25): every change made to the laptop and whether it was reverted, the demo clip, the baseline, both optimisation passes (with what was tried and rejected), both review passes, the 10-minute prediction (8 to 12 min on an RTX 4060, predicted not run; no longer holds after research/10), how to run it, and a table of every smoke run.

### research/10-reconstruction-quality.md
Why the demo model came out as stacked ground sheets and the fix (2026-09-25): keyframe gate holes (bridged now), MapAnything window drift the short BA never saw (poses now from COLMAP global_mapper with the camera fixed), OpenMVS dense-fuse and ROI dropping depth maps (fuse filter 1, no ROI), TextureMesh seam levelling blackening the atlas (off). Every experiment E1-E5 with numbers, before/after table, what is still wrong, the time cost, and nothing installed.

### research/11-codex-optimisation.md
The local GPU optimisation write-up for branch codex-opt: benchmarks B1-B5v and the held-out, shape, truth and time checks; before and after; audit findings F1-F18; poses (retriangulation off, point filtering); dense, mesh and texture experiments; mesh exports; SRT georeferencing; the 600 s clip; the focal length (the straight-pass ambiguity, the turn gate, the gimbal-pitch correction); time rates and the ten-minute projection; what was rejected and what is still wrong; machine changes; how to reproduce.
Gotcha: its numbers come from audit/codex-opt/RUNLOG.md; accuracy figures are synthetic, and the ten-minute 30 fps time is a prediction. Code comments cite its sections 9 and 10.

### research/08-web-upload.md
Design of the upload feature (one Cloud Run job per upload, preview before final, status.json contract, limits, uploads kept off curated pages) and two defects it exposed: packing scripts pinned to one laptop, and S1 retaining every full-res frame (~112 GB for a 10-min clip) now fixed with a two-pass decode. A 10-minute clip was first ingested on 2026-09-25 (402 s as the code stood, 55 s after research/09). A 2026-09-24 addendum records the start claim, daily slots and signed byte bound (audit F-04, F-05) and the CORS dependency.

### research/exp10-mapanything-cpu.md
EXP-10: MapAnything Apache (1.228B params) at 6.4-8.1 s/view on 8 vCPU; 600 keyframes about 75 min, so a GPU is required. Synthetic renders are inadequate for testing a learned model.

### research/exp11-mapanything-gpu.md
EXP-11: Kaggle T4 at 0.55 s/view (14x over 8 vCPU); 600 views about 330 s; peak VRAM 11.5 GB.

### research/exp12-video-to-3d.md
EXP-12: first real-video run (Nicosia, 40 s, CC BY 3.0): 1,199 frames, 20 keyframes, about 260k points, 0.42 s/view on T4; far-field density falls 6.6x; no GPS so no georeference.

## data/

### data/
Committed sample inputs: nicosia_1080p.mp4 and a 30 s cut, nicosia_contact.png, test_flight.mp4 with its test_flight.SRT sidecar. Larger candidate clips (data/cand/*.webm such as kolu, toolse, bahai) and raw data are gitignored and local only.

## research/ (recorded output)

### research/exp01-results.txt
EXP-01 output: SIFT 310 ms/frame at 1080p, 1789 ms at 4K; exhaustive matching 10.3 h / 13.7 h; features + sequential x12 = 1671 s (186% of budget) at 1080p, 3053 s (339%) at 4K, before any SfM or MVS.

### research/exp05-results.txt
EXP-05 output: absolute RMSE 4.119 m consumer, 1.858 m SBAS, 0.097 m RTK (only RTK passes); flat about 4 m from 50 to 2400 frames; fit residual 6.725 m; aligned-vs-absolute trap 0.209 m vs 2.679 m.

### research/exp08-results.txt
EXP-08 output: a 198 m swath reaches at most 25.9% of the 800 m scene; corridor coverage 86.5% nadir, 89.2% at 60 deg; along-track facades 14.3% nadir to 52.0% at 60/45 deg; two crossed passes 58.4% facade.

### research/exp09-results.txt
EXP-09 output: full 7-DOF scene RMSE 311 m consumer, 273 m SBAS, 267 m RTK (RTK trajectory 0.042 m); yaw-only 3.707 / 1.692 / 0.041 m; error 216 m to 725 m with cross-track distance; a curved path brings the full fit to 7.91 m.

### research/exp14-results.txt
EXP-14 output: lane factor 5.38-5.77, waist 5.32-5.57, arch floor at least 3.85; Kolu is 5.3-5.8x too small (central 5.5x); a declared 0.10 m DSM cell is really 0.53-0.58 m.

### research/calibration/kolu.json
Scale calibration contract (schema sih26158/scale-calibration/1) for runs kolumvs3d and kolu3d: factor 5.54, bracket [5.32, 5.77], status "calibrated", method known-object, with lane, waist and arch-floor references. Written by exp14_scale_audit.py; read by src/tesseract/scale.py, tools/scale_cal.py, tools/build_qa.py, test_tesseract.py.

### research/run-evidence/
Frozen evidence (about 9 MB): JSON results for MapAnything CPU and Kolu model runs (8.14 and 11.45 s/view), Kolu ingest and fuse diagnostics, three textured-MVS results (0.2214 px intrinsics residual, 45/45 registered), run_demo manifests (consumer 2.26 m, RTK 0.098 m absolute), screen-verdicts.json, toolse-intrinsics-gates.txt (10.69 px fit fixed to 0.214 px by a conf gate), gpu-2026-09-25/ (local_gpu_result.json timings of the laptop GPU smokes and the S0/S1 10-minute benchmarks, research/09), and PNG/JPG figures. research/10's demo pictures are not here: they come from the gitignored demo clip and live in out/evidence/.

## audit/codex/

### audit/codex/PROMPT.md
Instructions for an external Codex core-logic audit: ground rules (write only under audit/codex/, no network, cloud, installs, git writes or builders), six phases (baseline, invariants, deep passes by area A-I, cross-cutting sweeps, verify and self-refute, report), severity scale S1-S4, and the required structure of audit/codex/FINDINGS.md.
Gotcha: point Codex at it with `codex exec -s workspace-write "Read audit/codex/PROMPT.md and follow it exactly."` from the repo root; it expects CONTEXT.md beside it.

### audit/codex/CONTEXT.md
Reference facts for that audit: PS targets and status, architecture and the three runtimes, contracts and invariants (frames, scale, georef maths, harness, telemetry, orchestrator, web path, residency), known issues not to re-report, ten unverified leads, the local environment and baseline test results as of 2026-09-24, and a risk-ranked file list.
Gotcha: the baseline and known-issue tables are dated snapshots; refresh them before reusing the prompt after the code moves.

## audit/codex-opt/

### audit/codex-opt/PROMPT.md
Instructions for a Codex audit and optimisation run on the local GPU pipeline: target a 10-minute 1080p30 clip in under 15 min (ratio 1.5, short clips at the same ratio); phases 0 machine check, 1 baseline plus a new held-out view check (tools/view_check.py), 2 research (RESEARCH.md), 3 audit of the new local GPU code, 4 optimise (quality first, keep rules with numeric tolerances), 5 final measurement, 6 write-up (research/11, ADRs, REPORT.md). Commits on branch codex-opt only; installs logged and capped at 15 GB; no cloud, no push, no .env.
Gotcha: launch from the repo root with a sandbox that can run the GPU tools and git, e.g. `codex exec -s danger-full-access "Read audit/codex-opt/PROMPT.md and follow it exactly."`; it expects CONTEXT.md beside it and writes RUNLOG.md, RESEARCH.md and REPORT.md there.

### audit/codex-opt/CONTEXT.md
Facts for that run as of 2026-09-26 (commit 254aa0d): PS targets and weights, the current S3 chain and the demo's stage times, what is still wrong, what was already tried, benchmarks B1-B5 with scaled budgets (demo 28 s, nicosia 60 s, test_flight 30 s, 10-min 900 s), the machine and tool paths, licence and data rules, out-of-scope items (the GC-1 files, the web path, master).
Gotcha: stage times and shape numbers are the demo_gpu2 snapshot; refresh before reusing after the code moves.

### audit/codex-opt/RUNLOG.md
Ordered machine and experiment record for the local GPU audit. Holds baseline B1-B3 quality and timing, B4 ingest throughput, the B5 render probe, the 600-view sparse failure, profile samples, the held-out dense/mesh/texture experiments, the mapper option tests, the B5v 600 s clip, and the third session: the final suite on b360949, F7 (focal refinement drifting on straight passes), F8 (the synthetic SRT's gimbal angles), P1 (the gimbal-pitch correction replayed), the ladder rates, the line-by-line audit F10-F17, the v2 end-to-end runs, F18 (MapAnything's turn reading) and the TX texture tests.
Exports: machine table, experiment table, per-benchmark measurements
Used by: audit/codex-opt/REPORT.md and research/11-codex-optimisation.md
Gotcha: B5 as a 30 fps render is absent; B5v is a genuine 600 s file at 1 fps, so S1 decodes 1/30 of a real clip's frames. Timings after 02:14 on 2026-09-27 shared the laptop with a simulator in WSL and are marked.

### audit/codex-opt/REPORT.md
The owner's one-screen summary of the codex-opt run: before and after on B1, B2, B3 and B5v, the three biggest wins, the open problems, phase 3 findings F1-F22 with severity and fixing commit, and the machine changes with their undo.

### audit/codex-opt/RESEARCH.md
Stage-by-stage options for keyframes, cameras, dense reconstruction, mesh, models, throughput and missing outputs on the 8 GiB Windows laptop, with licence and source links, risks and ranked experiments.
Exports: ranked experiment list and per-option cost, licence, risk and test
Used by: audit/codex-opt/RUNLOG.md and research/11-codex-optimisation.md
Gotcha: expected gains are predictions unless a named local run supports them; the 600-view sparse run failed before dense work.

## audit/codex-7of10/

### audit/codex-7of10/PROMPT.md
Instructions for a Codex audit and planning run after codex-opt, aiming the model at 7/10: no reconstruction or GPU work, no installs, no deletions; phases 0 machine and tests, 1 audit the four final runs' claims against their files and score the 7/10 scorecard, 2 diagnose colour patches, holes, far field, no-pitch accuracy and Nicosia coverage on saved outputs, 3 line-by-line audit of codex-opt's code (fix S1/S2 with tests), 4 research by problem with licences, 5 NEXTRUN.md (a one-night, timed experiment plan the next run follows), 6 REPORT.md. Commits on branch codex-7of10 only.
Gotcha: launch from the repo root, e.g. `codex exec -s danger-full-access "Read audit/codex-7of10/PROMPT.md and follow it exactly."`; it expects CONTEXT.md beside it and writes LOG.md, FINDINGS.md, RESEARCH.md, NEXTRUN.md and REPORT.md there.

### audit/codex-7of10/CONTEXT.md
Facts for that run as of 2026-09-27 (codex-opt 4de9efa): the 7/10 scorecard with current values and bars, the four final runs and their files under out/runs, useful scratch under out/codex, the open problems and F19-F22, unfollowed leads (SRT focal_len, iso/shutter/ev and rel_alt in the real fixtures, the horizon as a pitch sensor, constant-light synthetic clips, levelling outside OpenMVS), disk (107 GB free, superseded runs listed), the shared GPU, licences and tests.
Gotcha: disk, run folders and the scorecard's current values are a dated snapshot; refresh before reusing.

### audit/codex-7of10/LOG.md
CPU-only saved-output and test command ledger for this audit, including replay inputs, altitude probes, results and scratch paths under out/codex/7of10. Read before interpreting FINDINGS.md numbers.

### audit/codex-7of10/FINDINGS.md
Phases 0-3: machine and tests, four-run manifest and export verification, the numeric 7/10 scorecard, CPU seam/hole/far-field and no-pitch analysis, and code findings C1/F19-F22 including the SIMPLE_RADIAL F21 schema issue. The rel_alt discussion accounts for rolling terrain. Replay and sampling limits are stated explicitly; source scripts and outputs are in LOG.md.

### audit/codex-7of10/RESEARCH.md
Phase 4 options ranked by scorecard impact: texture patch correction, holes/far field, independent focal scale including rel_alt with rolling terrain, B2 visibility, viewer/gsplat, and speed. Each option labels predicted gain, runtime, 8 GB and Windows feasibility, install size, separate code/weight licence and risk; links to primary project sources.

### audit/codex-7of10/NEXTRUN.md
Phase 5 instructions for an eight-hour next run: owner-approved disk/dependency preflight, unique held-out baselines, six ordered single-change experiments, time slots, source-specific clean-run command templates, exact keep/stop rules and final scorecard proof. Never treat its predicted gains as measured results.

### audit/codex-7of10/REPORT.md
One-screen owner summary: current numeric 7/10 scorecard, three consequential audit findings, visible fault causes, five next-run experiments with predicted gains and slots, and the requested disk/dependency decisions. Links to full FINDINGS, RESEARCH and NEXTRUN records.
