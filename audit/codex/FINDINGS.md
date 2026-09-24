# Core logic audit: findings

Date: 2026-09-24. Commit: `f1c4a1c7587ff872a448aca9e0e94196c1d90a35`. Model: GPT-6. Time spent: roughly 12 minutes. This is the first report at this path; it supersedes no earlier Codex audit.

## Summary

Six S1 findings and seven S2 findings. By area: A 1, B 1, C 1, D 1, E 2, F 2, G 3, H 1, I 1. The strongest evidence is local reproduction of the cache key, verdicts, unlevelled yaw fit and crop guard. No live service or container was touched.

The three issues most likely to change a judged result are these:

- A resumed run can attach a new input checksum to old geometry because the source hash is absent from the cache key.
- The run manifest calls R-O5 met with only PLY, LAS and GeoTIFF.
- The synthetic RTK case starts gravity aligned. A 5 degree roll in a 0.18 scale reconstruction gave 21.369 m scene RMSE while its camera track fit at 0.0 m RMSE.

## Findings

### F-01 Resuming after an input or calibration change reuses old results

- Severity: S1
- Status: CONFIRMED
- Area: F
- Location: `src/tesseract/pipeline.py:123`, `src/tesseract/pipeline.py:174`, `src/tesseract/stages.py:321`, `src/tesseract/sources.py:45`
- Invariant broken: source, config, calibration and upstream content must invalidate resume, per docs/09 section 4 and CONTEXT section 3.6.
- What is wrong: `State.key` hashes stage needs and config, but not `ctx.source.inputs()` or calibration file content. `Screen` and `Ingest` have no declared input artifact, so even replacing the clip at the same path leaves their keys unchanged. `Scale` can likewise keep a previous factor after `tesseract calibrate` updates a calibration JSON.
- Failure scenario: Run a clip as `same-run`, replace its bytes at that path, then rerun with the same options. The new manifest records the new input checksum while cached keyframes, geometry and verdicts still describe the old clip. Recalibrating the same run can leave the previous metric factor in exports.
- Evidence: `State.key` builds `inputs` only from `stage.needs` at lines 123-129; `man.inputs = ctx.source.inputs()` at line 179 is only a record. `python audit/codex/scratch/repro_core.py` printed `source changed, scale cache key equal: True`.
- Impact: R-O1 through R-O5 and the reliability of the run manifest.
- Suggested fix: put source hashes and relevant calibration JSON hashes into the dependent stage keys, then make downstream stages depend on those outputs.
- Test that would catch it: Run twice with the same run name after changing the video bytes and calibration factor; require S0, S1, S4 and every dependent stage to rerun.
- Related known issue: none.

### F-02 The formats verdict says met after three outputs

- Severity: S1
- Status: CONFIRMED
- Area: I
- Location: `src/tesseract/stages.py:549`, `src/tesseract/stages.py:665`, `src/tesseract/stages.py:678`
- Invariant broken: R-O5 requires OBJ, PLY, LAS, GeoTIFF, glTF or GLB, and FBX; docs/09 section 3 says seven export files.
- What is wrong: The local `Export` stage writes a cloud PLY, LAS and DSM only. `Verdicts` requires exactly those three names, so it says `met` although OBJ, glTF or GLB and FBX are absent. The false verdict reaches the manifest and QA report.
- Failure scenario: A normal synthetic or adopted run reaches S6 with all three writers succeeding. R-O5 is reported as met with four required file entries missing.
- Evidence: Lines 549-588 populate only `ply`, `las`, `geotiff`; line 665 sets `need = {"ply", "las", "geotiff"}`. `python audit/codex/scratch/repro_core.py` printed `R-O5 formats: met` for that exact list.
- Impact: R-O5 and the submitted QA verdict.
- Suggested fix: require each mandated format and count a format only after a readable file exists. Mark the local stage partial until its other writers exist.
- Test that would catch it: Feed `Verdicts` the three current export names and assert R-O5 is not met.
- Related known issue: none. The separate legacy export writer does not repair the local verdict.

### F-03 Georeferenced PLY loses its projected origin

- Severity: S1
- Status: PLAUSIBLE; the exact writer could not run without `trimesh`
- Area: H
- Location: `src/tesseract/stages.py:530`, `src/tesseract/stages.py:546`, `src/tesseract/stages.py:549`, `src/tesseract/stages.py:593`
- Invariant broken: all exported files share one F7 frame and origin when georeferenced, per docs/09 sections 1 and 3.
- What is wrong: S6 loads projected F7 coordinates into `P`, then writes `P - origin` to PLY. LAS and GeoTIFF use `P` with the projected offset. The PLY artifact is still stamped F7 and has no sidecar carrying `origin`.
- Failure scenario: A valid RTK run has a point at easting 500000 m and northing 3000000 m. LAS retains those coordinates, while PLY starts near zero, yet both are described as F7.
- Evidence: `origin = P.min(0)` at line 546, `trimesh.PointCloud(P - origin).export(p)` at line 550, and the shared `frame=frame` stamp at line 593. A direct third-party readback was unavailable here.
- Impact: R-O3 and R-O5; a GIS consumer cannot overlay these two outputs without an undocumented transform.
- Suggested fix: write the same projected coordinates to PLY, or record and apply an explicit shared origin for every format and in the manifest.
- Test that would catch it: Export three known F7 points, read PLY and LAS with third-party readers, then compare their coordinates within each format's precision.
- Related known issue: none.

### F-04 Anonymous callers can restart a run and bypass the daily compute cap

- Severity: S1
- Status: PLAUSIBLE; the live API was intentionally not called
- Area: G
- Location: `demo/api/start.js:20`, `demo/api/start.js:30`, `demo/api/start.js:39`, `demo/api/runs.js:30`
- Invariant broken: one concurrent execution and twelve starts per day, per CONTEXT section 3.7.
- What is wrong: `/api/start` checks whether an upload exists and whether a job is running, then calls `runJob`. It neither checks `startedToday()` nor claims a run ID once. Any holder of a valid run ID can call it again after the prior job ends, and concurrent requests can both pass `runningCount()` before either starts.
- Failure scenario: Upload one small valid clip, keep its run ID and call `/api/start` thirteen times, waiting for each execution to finish. All thirteen calls pass the single-run check; the twelfth-run cap in `/api/runs` never runs again.
- Evidence: `/api/runs` checks `startedToday()` at line 30; `/api/start` lines 20-44 have no daily count or durable claim. Its concurrency check and `runJob` are separate calls.
- Impact: real anonymous compute cost and capacity loss for the public service.
- Suggested fix: atomically claim each run ID once and reserve a daily slot before launching. Reject duplicate starts, including concurrent ones.
- Test that would catch it: Mock storage and JobsClient, call start twice for one ID and after the daily cap, and assert only one launch.
- Related known issue: none.

### F-05 The signed upload URL has no enforced byte bound

- Severity: S1
- Status: PLAUSIBLE; no cloud upload was attempted
- Area: G
- Location: `demo/api/runs.js:19`, `demo/api/runs.js:44`, `demo/api/runs.js:50`, `run_job/run_upload.py:197`
- Invariant broken: the public upload limit is 600 MiB and public requests must not create unbounded cost, per CONTEXT section 3.7.
- What is wrong: `/api/runs` trusts the caller's `size` and signs a 30 minute GCS PUT without a content length bound. The worker checks the stored object's size only after the upload has completed and a job has started. Since URL minting is not counted as a run, an anonymous client can request many URLs and leave oversized objects in the bucket.
- Failure scenario: Send `size: 1` to `/api/runs`, PUT a multi-gigabyte body using the returned URL and never call `/api/start`. No worker size check runs, but storage and ingress are consumed.
- Evidence: The only `/api/runs` size test is `if (size > L.MAX_BYTES)` at line 21. The signed URL options at lines 50-55 specify method, expiry and content type, with no size restriction. The worker limit appears at `run_upload.py:197`.
- Impact: storage cost and availability of the public upload service.
- Suggested fix: enforce the byte cap at GCS upload time, cap URL issuance and set object expiration for abandoned uploads.
- Test that would catch it: Mock URL signing and assert the returned upload method cannot store a body above the configured cap.
- Related known issue: none.

### F-06 Unvalidated runs still publish metre-named length fields

- Severity: S1
- Status: CONFIRMED by the manifest writer and report path
- Area: B
- Location: `src/tesseract/stages.py:495`, `src/tesseract/stages.py:500`, `src/tesseract/stages.py:504`, `src/tesseract/report.py:72`
- Invariant broken: `unvalidated` may print only model units, per docs/09 section 2 and ADR-014.
- What is wrong: `Level` uses factor 1.0 for an unvalidated run but always records `extent_m`. It also retains gravity keys ending `_m`. The manifest stores those names and `report.render` prints scalar facts, including `extent_m`, in the QA report.
- Failure scenario: Adopt a real clip with no GNSS and no calibration. Its run-level units are `model units`, while its S5b stage table prints `extent_m` with numbers measured in model units.
- Evidence: `k` defaults to 1.0 at line 495; line 504 unconditionally sets `facts["extent_m"]`. `RunManifest.add` stores facts at `contracts.py:239`, and `report.py:72-76` prints scalar facts.
- Impact: the scale claim on an unvalidated final output.
- Suggested fix: name length fields by the actual units, or attach a units field to every such fact and render it from scale status.
- Test that would catch it: Render an unvalidated real-video manifest with S5b facts and assert no metre-labelled lengths appear.
- Related known issue: none.

### F-07 The yaw fit receives an unlevelled F3 cloud

- Severity: S2
- Status: CONFIRMED for the synthetic perturbation; effect on a real GNSS path is latent until gap C-3 closes
- Area: A
- Location: `src/tesseract/stages.py:284`, `src/tesseract/stages.py:380`, `src/tesseract/stages.py:468`, `src/pipeline/run_demo.py:196`
- Invariant broken: F4 must be levelled to F5 before a yaw-only F5 to F6 fit, per docs/09 section 1 and ADR-008.
- What is wrong: `Georeference` fits yaw to raw `points` and `cameras` before `Level` runs. `Level` skips if `points_geo` exists. The synthetic source hides the ordering bug by adding only yaw and translation at scale 1.0, so it arrives gravity aligned.
- Failure scenario: Give the synthetic reconstruction a 5 degree roll and a 0.18 scale factor, which are allowed in an arbitrary F3 gauge. A yaw-only fit perfectly overlays the straight camera track but leaves the off-track scene 21.369 m RMSE wrong.
- Evidence: `python audit/codex/scratch/repro_core.py` printed `rolled scene RMSE m: 21.369` and `rolled trajectory RMSE m: 0.0`. `stages.py:380` fits before the levelling code at lines 467-498.
- Impact: R-O3 when real GNSS is wired in; the current synthetic RTK number does not test this condition.
- Suggested fix: estimate gravity and level both points and cameras before the yaw fit, then make synthetic tests vary roll, pitch and scale.
- Test that would catch it: Inject a known roll, pitch and non-unit scale into the synthetic F3 arrays, then check scene error against truth, not only camera residual.
- Related known issue: C-3, but the missing pre-fit levelling is a separate latent consequence.

### F-08 R-O4 uses the flattering completeness denominator

- Severity: S2
- Status: CONFIRMED
- Area: C
- Location: `src/tesseract/stages.py:634`, `src/tesseract/stages.py:643`, `src/tesseract/stages.py:675`
- Invariant broken: completeness needs both observable and whole-scene denominators, per ADR-022 and CONTEXT section 3.4.
- What is wrong: S7 calculates both recalls, but S8 declares R-O4 met from `recall_at_1m_observable` alone. A reconstruction that covers the easiest visible surface can pass while whole-scene recall is far lower. The two metrics are correctly recorded; the verdict chooses the wrong one.
- Failure scenario: Observable recall is 0.95 and whole-scene recall is 0.40. S8 says R-O4 met despite most of the whole scene missing.
- Evidence: `python audit/codex/scratch/repro_core.py` supplied those values and printed `R-O4 coverage: met`.
- Impact: R-O4.
- Suggested fix: define the R-O4 pass threshold against the whole-scene denominator, while still showing the observable metric separately.
- Test that would catch it: Feed high observable recall and low whole-scene recall to S8 and require a non-met verdict.
- Related known issue: none; limited facades are disclosed, but this false verdict is not.

### F-09 R-O2 can pass on a short or cached synthetic run

- Severity: S2
- Status: CONFIRMED
- Area: F
- Location: `src/tesseract/stages.py:668`, `src/tesseract/pipeline.py:142`, `src/tesseract/pipeline.py:244`
- Invariant broken: R-O2 is under 15 minutes for a 10 minute input video, per docs/01 and CONTEXT section 1.
- What is wrong: S8 compares only this invocation's `spent_s` with the budget. It does not check input duration, and cached stages add zero seconds. A short synthetic scene or a resumed synthetic run can be reported as meeting the 10 minute video target.
- Failure scenario: A 240-frame synthetic source with 100 seconds of work and a 900 second budget reports R-O2 met. That result gives no measured throughput for an 18,000-frame video.
- Evidence: `python audit/codex/scratch/repro_core.py` printed `R-O2 processing time: met` with `spent_s=100` and no input duration. Cached `StageResult.seconds=0.0` at `pipeline.py:142`.
- Impact: R-O2 and any QA claim based on the verdict.
- Suggested fix: require a verified 10 minute input and end-to-end wall time for `met`; use `not measurable` for synthetic or cached timing.
- Test that would catch it: Score a short synthetic and a fully cached run and assert neither meets R-O2.
- Related known issue: CPU speed is already disclosed; the false verdict on a short source is new.

### F-10 A valid top crop fails the intrinsics guard

- Severity: S2
- Status: CONFIRMED
- Area: E
- Location: `src/ingest/video_ingest.py:570`, `src/ingest/video_ingest.py:637`, `src/pipeline/colmap_export.py:126`, `mvs_job/run_mvs.py:162`
- Invariant broken: S1 crops must preserve their F0 to F1 camera transform, per docs/09 section 1 and the crop policy in CONTEXT section 3.5.
- What is wrong: The ingest stage can remove the top of every keyframe, so the physical principal point moves off the centre of that cropped image. `full_frame_camera` treats more than 8 percent off-centre as bad resize geometry without accounting for the intentional crop. The web path always requests horizon crop.
- Failure scenario: A 1920 by 1080 frame with a valid 20 percent top crop becomes 1920 by 864. Its correct principal point is `(960, 324)` in the cropped image, 12.5 percent of image height off centre, so MVS exits before COLMAP.
- Evidence: `python audit/codex/scratch/repro_core.py` printed `valid 20 percent top crop rejected: principal point is 12.5% off centre`.
- Impact: R-O1 and R-O4 on valid horizon-cropped videos; the web run pays for pose inference before failing.
- Suggested fix: pass S1's crop box to MVS and compare the recovered principal point with the correctly shifted source-camera centre.
- Test that would catch it: Derive intrinsics for a known pinhole camera after a 20 percent top crop and require S3b to accept it.
- Related known issue: none.

### F-11 MVS does not enforce its bundle adjustment quality gate

- Severity: S2
- Status: PLAUSIBLE; COLMAP is available only inside its container
- Area: E
- Location: `mvs_job/run_mvs.py:97`, `mvs_job/run_mvs.py:201`, `mvs_job/run_mvs.py:211`, `mvs_job/run_mvs.py:213`
- Invariant broken: all views registered and mean error after BA at most 1.0 px, per docs/09 section 3.
- What is wrong: `reproj_error` parses and records COLMAP's image count and reprojection error. After BA, the code proceeds to undistortion and dense reconstruction without comparing either number with the contract. A bad seed can therefore be published as a finished MVS model.
- Failure scenario: BA returns successfully but registers only 35 of 60 images or reports 4.0 px mean error. S3b continues to S4 and the final web status can become `done`.
- Evidence: Lines 201 and 211 assign `before` and `after`; lines 213-299 have no test of `after` or registered count before densification and upload. This could not be exercised locally without the container.
- Impact: R-O3 and R-O4, plus wasted densification cost.
- Suggested fix: parse these values as numbers and stop before S4 when the gate fails, recording the reason in `mvs_result.json` and status.
- Test that would catch it: Mock analyzer output with fewer registered images and more than 1.0 px error, then assert DensifyPointCloud is never invoked.
- Related known issue: none.

### F-12 A killed worker can leave status running forever

- Severity: S2
- Status: PLAUSIBLE; job termination was not tested on the live service
- Area: G
- Location: `run_job/run_upload.py:75`, `run_job/run_upload.py:94`, `run_job/run_upload.py:383`, `demo/api/status.js:15`, `tools/run_template.html:150`
- Invariant broken: a run must return a labelled terminal result, per CONTEXT sections 1 and 3.7.
- What is wrong: Only the worker writes `status.json`. Its exception handler can write `failed` for Python exceptions, but OOM, SIGKILL or a job timeout cannot execute that handler. The status API returns the last `running` state, and the browser polls until it sees one of four terminal strings, with no deadline.
- Failure scenario: The worker is killed during densification after it wrote `state: running`. Cloud Run marks the execution failed, but the page keeps showing densification in progress indefinitely.
- Evidence: `run_upload.py:94-100` writes only from the process; `tools/run_template.html:150-159` has no timeout or execution-state fallback. No live job was started during this audit.
- Impact: final result honesty and user trust on a failure mode already seen for memory-heavy ingest.
- Suggested fix: reconcile the status object with the Cloud Run execution state in `/api/status`, or run a watchdog that marks timed-out executions terminal.
- Test that would catch it: Freeze `status.json` in `running` while a mocked execution is failed and assert the API returns a terminal state.
- Related known issue: the earlier ingest OOM is documented, but this stale status consequence is not.

### F-13 Time-keyed telemetry assumes a constant frame rate

- Severity: S2
- Status: PLAUSIBLE; no variable-frame-rate fixture was available
- Area: D
- Location: `src/ingest/video_ingest.py:188`, `src/ingest/video_ingest.py:212`, `src/ingest/video_ingest.py:493`, `src/ingest/video_ingest.py:606`
- Invariant broken: SRT records must attach to the actual keyframe time when no FrameCnt is available, per CONTEXT section 3.5.
- What is wrong: Ingest keeps absolute decode indices, which is correct for FrameCnt, but its time fallback computes `index / average_rate`. Variable-frame-rate video can place a decoded frame at a different presentation timestamp. That picks a valid looking but wrong GPS record.
- Failure scenario: On a clip whose average rate is 30 fps, decoded frame 30 appears at 2.0 s after a rate change. A time-only SRT lookup asks for 1.0 s and can attach the 1.0 s fix instead.
- Evidence: `telemetry_for_frames` computes `t = int(fi) / fps * 1e6` at line 212; ingest passes only indices and `fps` at line 606, not frame PTS. The second full decode retains indices correctly.
- Impact: R-O3 once real telemetry is wired to georeferencing.
- Suggested fix: keep each selected frame's presentation timestamp from PyAV and use it for time-keyed SRT lookup.
- Test that would catch it: Use a variable-frame-rate fixture where frame 30 has PTS 2.0 s and require it to match the 2.0 s telemetry record.
- Related known issue: C-3 is the current unwired telemetry gap; this is a separate timing error when it closes.

## Refuted leads

1. Synthetic levelling: confirmed as F-07, not refuted.
2. Projected float32: the F7 `.npy` array remains float64 and LAS uses a local millimetre offset. A cast at northing 3000000 m would have 0.25 m spacing, but this pass did not find that cast on the F7 path. PLY's missing origin is F-03.
3. Recalibration resume: covered by F-01.
4. Frame index: the second decode and FrameCnt path retain absolute indices. The time fallback on variable-frame-rate input is F-13.
5. Upload abuse: duplicate starts and unbounded signed PUTs are F-04 and F-05. Pagination and raw exception messages were not promoted without an observed cost or exposure.
6. Two calibration readers: both take the first matching file in sorted order and both validate status. `tools/scale_cal.for_page` assumes a bracket for every non-unvalidated status, but current calibration files did not establish a reachable failure, so this stayed out of findings.
7. Axis swap: the glTF transform `(x,y,z)` to `(x,z,-y)` has determinant +1. Winding is preserved by that rotation.
8. GeoTIFF: `flipud` matches the south-origin binning and north-up transform. The half-cell convention describes pixel areas; no reversed rows were found.
9. Crop-aware intrinsics: confirmed as F-10.
10. Completeness denominators: both are calculated, but S8 uses the observable one for the pass verdict, F-08.

## Coverage

Invariants checked: F0 to F1 crop and intrinsics broken (F-10); F1 to F2 and F2 to F3 pose mapping partially checked, no counterexample; F3 to F4 same gauge partially checked; F4 to F5 levelling broken at the georeference seam (F-07); F5 to F6 yaw-only requirement checked in the fit but broken by ordering (F-07); F6 to F7 local ENU projection and EGM2008 guard checked in code, no counterexample; scale status to units broken for metre-named facts (F-06); factor applied once partially checked, stale after recalibration (F-01); absolute and aligned metrics checked-holds; 7-DOF refusal checked-holds; telemetry keyed matching checked-holds except time fallback (F-13); ladder checked-holds for expected `StageError`, general exception handling not fully tested; resume broken (F-01); `status.json` lifecycle broken on hard termination (F-12); web limits broken (F-04, F-05); India region defaults checked-holds in the active web path, deployment overrides not checked.

Tier 1 coverage follows. "Partial" means the named seam was read but other logic in that file was not checked line by line. This is a limit of this report, not a clean bill of health.

| File | Read | Verdict |
|---|---|---|
| `src/eval3d/gnss.py` | Full | Yaw-only fit assumes level input, F-07. |
| `src/eval3d/metrics.py` | Full | Absolute and aligned are separate; denominator choice fails downstream. |
| `src/tesseract/contracts.py` | Full | Units validator does not inspect individual fact names. |
| `src/tesseract/pipeline.py` | Full | Source and calibration absent from cache key, F-01. |
| `src/tesseract/stages.py` | Full | F-02, F-03, F-06, F-07, F-08 and F-09. |
| `src/tesseract/scale.py` | Partial | Calibration lookup is sensible; cache around it is not. |
| `src/tesseract/cli.py` | Partial | Verify checks recorded artifact hashes but cannot repair stale provenance. |
| `src/tesseract/report.py` | Full | Prints metre-named unvalidated facts from manifest. |
| `src/tesseract/sources.py` | Partial | Source hashes are recorded but do not enter stage keys. |
| `src/ingest/video_ingest.py` | Partial | Absolute decode index survives; VFR timing does not, F-13. |
| `src/ingest/screen.py` | Full | Sampling and empty-input behavior not exercised. |
| `src/pipeline/colmap_export.py` | Full | Crop guard rejects a valid shifted principal point, F-10. |
| `src/pipeline/export_formats.py` | Partial | Legacy export writes more formats; glTF rotation is proper. |
| `src/pipeline/gravity.py` | Full | Up estimate is downstream of the synthetic yaw fit. |
| `src/pipeline/fuse_mesh.py` | Partial | No additional high-confidence defect found. |
| `src/pipeline/window_fuse.py` | Partial | Return tuple order at visible call sites is correct. |
| `src/pipeline/run_demo.py` | Partial | Synthetic arbitrary frame is yaw plus translation only. |
| `mvs_job/run_mvs.py` | Full | BA metrics are parsed but do not gate S4, F-11. |
| `mapanything_job/run_mapanything.py` | Full | Active checkpoint is Apache; the known view cap remains documented. |
| `run_job/run_upload.py` | Full | Hard termination has no status writer, F-12. |
| `demo/api/_lib.js`, `runs.js`, `start.js`, `status.js`, `file.js` | Full | F-04 and F-05; path and run ID checks held. |
| `tools/scale_cal.py` | Full | First matching calibration wins; bracket assumption remains an open edge. |
| `tools/finish_kolu.py`, `finish_mvs.py` | Full | Final export subprocess failure is logged but not fatal in `finish_mvs.py`. |
| `tools/build_viewer.py`, `gcs_io.py` | Partial | Viewer quantization formula seen; no new confirmed defect. |

Tier 2 coverage: `src/simscene/scene.py`, `render.py`, `visibility.py` were not read line by line; synthetic generation was reached through its callers. `src/pipeline/render_views.py` was partially read for gravity fallback. `tools/build_console.py`, `build_gallery.py`, `build_demo.py`, `build_qa.py`, `build_run.py`, `pack_textured.py`, `footage.py`, and the console, gallery, demo and run HTML templates were searched for units, scale and measurement formulas; only `run_template.html` was read in its polling path. `viewer/index.html`, the Dockerfiles, deploy YAML, CI workflow, requirements and `demo/vercel.json` were not checked line by line. No finding is asserted from the unreviewed sections.

The cross-cutting grep covered Sim(3) call sites, float32 casts, `.npy` saves, path insertion, subprocess use and scale display code. Environment-variable setters and every broad exception handler were not exhausted. Real output artifacts and five high-value Q&A figures were unavailable on this machine, so they were not recomputed.

## Environment and tests

`PYTHONIOENCODING=utf-8` and `PYTHONDONTWRITEBYTECODE=1` were set for Python checks. `python src/eval3d/test_metrics.py` passed all checks. `python src/ingest/test_srt.py` passed all checks. `python src/pipeline/test_window_fuse.py` passed T-SCALE-01. `python src/tesseract/test_tesseract.py` passed T1 to T3 and stopped at T4 with `ModuleNotFoundError: No module named 'trimesh'`. `python tesseract.py run synthetic --gnss rtk --name audit-rtk` stopped at S1 with the same error. `python tesseract.py verify out/runs/audit-rtk` returned `no run_manifest.json in out/runs/audit-rtk`.

`python audit/codex/scratch/repro_core.py` passed and printed the values cited above. A real export readback needed `trimesh`, `laspy` and output artifacts. A full MVS quality-gate check needed its container and COLMAP. Live upload abuse and worker timeout checks were excluded by the audit prompt. No packages were installed and no network call was made.

## Open questions for the maintainers

- Is R-O4 meant to require a numeric whole-scene threshold, or should any unknown hidden surface force `not measurable`? The code and ADR-022 do not give one shared pass rule.
- Should the local S6 path own all seven output formats, or should its R-O5 verdict explicitly defer to the separate legacy exporter?
- Which service owns cleanup of uploaded GCS objects that never start a run, and what retention period is intended?
- Should a hard-failed Cloud Run execution be shown as `failed` by the status API, even when `status.json` could not be updated?
