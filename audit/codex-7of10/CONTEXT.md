# Context: auditing the codex-opt results and planning the next run

Reference for `audit/codex-7of10/PROMPT.md`. Checked on 2026-09-27 against branch `codex-opt`
at 4de9efa, which is on origin. Where this file disagrees with the code or the run files,
the files win, and the disagreement is a finding.

---

## 1. The target for this round

Same problem statement and requirements as `audit/codex-opt/CONTEXT.md` section 1 (R-O1 to
R-O6). Judging weights: accuracy 30, completeness 20, speed 20, innovation 15, scalability
10, UI 5. The finale clip is unknown, so it must never crash the system and never produce
a confident wrong number.

The owner rated the demo model 5/10 before the last run. That run made it faster, metric
on synthetic clips with a gimbal pitch, and harder to break, but the model looks the same.
**This round aims for 7/10.** Not 10/10, not 100% accuracy. The scorecard below turns 7/10
into numbers. It's a proposal. The audit checks every bar against the evidence and may
move one with a written reason, but never just so the current state passes.

| Area (weight) | 7/10 means | Measured by | Now |
|---|---|---|---|
| Looks right (completeness 20, UI 5) | On B1 at the run page's default view, no patchwork of colours on roads and roofs, far-field houses read as blocks rather than shreds, no hole bigger than a house | The owner's eye on a before and after pair, plus the seam metric the audit defines, uncovered faces and held-out scores | Patches, holes and a shredded far edge. Held-out 22.822 dB, SSIM 0.647, coverage 98.8% (b360949, full size) |
| Held-out views, B1 | At least 23.3 dB and SSIM 0.66, coverage at least 98%; a run-to-run difference of 0.02 dB is noise | `tools/view_check.py --build` | 22.822 dB, 0.647, 98.8% |
| Accuracy without a gimbal pitch (30) | B3 and B5v with `gb_pitch` taken out of the SRT: cloud median at most 1.0 m, at least 75% within 1 m | truth check, S5 replay | 12.6 m on B3, 1.4 m on B5v |
| Accuracy with a gimbal pitch | Stays at or under 0.5 m median | truth check | 0.394 m (B3), 0.346 m (B5v) |
| Real clips, no truth | An independent focal estimate agrees with the one used within 5%, or the manifest flags the run | a new check | Only MapAnything's estimate exists |
| Speed (20) | B5v R at most 1.0; B1 at most 300 s; no ladder step-down on any benchmark | manifest | B5v 502.2 s (R 0.84); B1 264.5 s |
| Completeness | 6 of 6 formats; B2 held-out coverage at least 80% | S6, view_check | 6 of 6; B2 72% |
| Robustness (scalability 10) | No S1 or S2 finding open; F19 and F20 closed; every SRT fixture parses or is refused cleanly | tests | F19 to F22 open (S3, S4) |
| Innovation (15) | At least one new capability a judge sees in under a minute | the owner | Metric focal length from the gimbal pitch (ADR-032) |

## 2. What the last run left

Read these in full before auditing: `research/11-codex-optimisation.md` (every number and
its source), `audit/codex-opt/REPORT.md` (owner summary, findings F1 to F22),
`audit/codex-opt/RUNLOG.md` (every experiment, kept and rejected), and ADR-029 to ADR-032
in `docs/10-decision-log.md`.

The final runs, all under `out/runs/` (gitignored, on this laptop only):

| Run | Clip | Time | Key numbers | Notes |
|---|---|---:|---|---|
| `codex-b1-v2` | B1 demo, 18.9 s | 264.5 s | focal held | no held-out split in this run |
| `codex-b2-v2` | B2 Nicosia, 40 s | 282.6 s | focal 751 to 1400 px (refined, a pan) | coverage 72% held out, from the final suite |
| `codex-b3-v2` | B3 test_flight + SRT, 20 s | 318.1 s | cloud 0.394 m median, 95.3% within 1 m, k 1.325 | `truth_check.json` |
| `codex-b5v-v3` | B5v, 600 s at 1 fps + SRT | 502.2 s | cloud 0.346 m median, 98.5% within 1 m | the only run on the final focal gate (2ece0fd) |

research/11 says B1, B2 and B3 would take the same focal decision under the final gate, so
their v2 runs stand for the final code. That claim is worth checking (section 9 of
research/11 gives the turn readings).

Each run folder holds `run_manifest.json`, `state.json`, `ingest.json` (with the per-keyframe
telemetry), `screen.json`, `qa_report.md`, `level.json` or `georef.json`, the cloud and
cameras as `.npy`, `geometry/` (`local_gpu_result.json`, the OpenMVS logs, `scene.mvs`,
`scene_dense.mvs`, `scene_dense_mesh.ply`, `scene_tex.obj` with its MTL and atlas,
`sparse_txt/`), `export/` (PLY, LAS, GeoTIFF, OBJ, GLB, FBX), `keyframes/` and `index.html`.
The depth maps and COLMAP databases were deleted to save disk.

The pipeline runs used every keyframe for densify and texture, so their meshes cannot be
scored on held-out views. Held-out numbers need `tools/view_check.py --build`, which reruns
the dense half on the GPU. The latest held-out figures are from the final suite on b360949
(RUNLOG.md).

Useful scratch under `out/codex/` (not committed, read freely):

- `b3_truth.py`: camera and cloud error against the synthetic truth, in F6.
- `replay_s5.py`: reruns S5 alone on a finished run's saved outputs with a chosen gimbal
  pitch. CPU only, a few seconds. With a small change it can replay S5 with no pitch at
  all, or with a different focal length.
- `tex_exp.py`, `mesh_exp.sh`, `texexp/`: the TX texture experiments. The TX1 crash and
  TX2 black atlas logs are the seam-levelling evidence (RUNLOG.md rows Q1, TX1, TX2).
- `codex-b1-v2.png`, `codex-b2-v2.png`, `codex-b3-v2.png`, `codex-b5v-v3.png`: the run page
  screenshots. `cmp_8.jpg`, `b2_compare.jpg`: comparison renders.
- `b5v.mp4`, `b5v.SRT`: the B5v clip.

## 3. The open problems, as the owner sees them

1. **The model doesn't look better.** Colour patches between photos, holes, a shredded far
   edge. Seam levelling in TextureMesh blackens the atlas or crashes in this OpenMVS 2.4
   Windows build, on the CPU too (Q1), with and without decimation (TX1, TX2). Per-image
   colour gains were real (0.92 to 1.22) and changed nothing visible. Closing holes in
   ReconstructMesh bridged them with wrong surfaces. RefineMesh gained nothing.
2. **Accuracy rests on a gimbal pitch no real SRT has.** None of the 20 real DJI fixtures
   carries `gb_pitch`. Without it the height error is whatever MapAnything's focal length
   leaves: 2% (1.4 m) on B5v, 33% (12.6 m) on the test_flight encode.
3. **Nicosia's coverage fell** from 97% to 72% once its focal length was right.
4. **No real ten-minute 30 fps clip** has been run; about 615 to 700 s is a prediction.
5. **Findings left open:** F19 (MapAnything out of memory reported as GEO-REPROJ and
   replayed), F20 (a missing file inside S3 reads as "tools missing" and L1 solves the
   poses again), F21 (the focal fact holds [f, cx] on the non-default pose path), F22 (no
   `key_extra` on local S3, so a DEFAULTS change needs a manual version bump).

## 4. Leads nobody has followed yet

Found while preparing this run. Each is a lead to check, not a result.

- **Most real SRTs carry a focal length and exposure.** Of the 20 fixtures in
  `src/ingest/fixtures/dji_srt/`, air2s, mavic_air2, m2zoom, MAVIC3, mavic_2pro_new,
  mix_p4rtk_mavic2pro and broken_incomplete2 have `focal_len` (35 mm equivalent; some
  write it times ten, which the parser already flags as `focal_len_x10`). Most carry
  `iso`, `shutter`, `fnum` and `ev` per frame. MAVIC3 and test_flight carry `rel_alt`.
  S1 parses `focal_len`, but nothing downstream uses it. A 35 mm equivalent is defined on
  the photo sensor's diagonal; video modes crop the sensor, so turning it into pixels
  needs a crop factor per drone and mode, and that error is the thing to measure. B3's
  SRT says 24.00 mm and its true focal length is 1066 px, which gives one check.
- **The horizon is a pitch sensor.** B1 has a horizon in every frame, and S1 already finds
  it to crop it. The horizon's row relative to the principal point is set by the focal
  length and the camera pitch together, which is exactly the pair ADR-032 needs.
- **`rel_alt` is a height above take-off.** Where take-off is near the scene's ground, the
  model's ground plane distance below the cameras fixes the stretch along the view axis.
- **Synthetic clips have constant lighting.** If B3 and B5v show the same colour patches
  as B1, the patches come from geometry or view selection, not exposure.
- **The seam levelling that OpenMVS fails at can be done outside it.** The global part of
  Waechter et al. (2014) solves one colour offset per texture patch so patch borders
  agree. On a finished OBJ and atlas that's a sparse least-squares problem in numpy.

## 5. Machine

As `audit/codex-opt/CONTEXT.md` section 5, with these changes:

- **Free space on C: is 107 GB, 7 GB above the 100 GB floor.** A B5v run takes 2.9 GB, a
  B3 run 1.4 GB. Superseded runs of the last round that the next run could delete
  (about 12.8 GB, all regenerable): `out/runs/codex-b3-geo`, `codex-b5v`, `codex-b3-final`,
  `codex-b1-final`, `codex-b2-final`, `codex-b5v-final`, `codex-b5v-v2`, `codex-b4-ingest`.
  The baselines (`codex-b1-base2`, `codex-b2-base`, `codex-b3-base`) and the four final runs
  stay.
- **The laptop is shared.** Another agent session (UAV-X, a PX4 and Gazebo simulator in
  WSL) uses the CPU and GPU at times. Before any heavy job, `nvidia-smi` shows whether
  another process holds the GPU. Timings taken while it runs are marked in the log.
- assimp 6.0.5 (`C:\Users\Kartik\gpu-tools\assimp\Release`) and pyassimp 5.2.5 are
  installed for FBX export.
- A `python -m http.server` on port 8765 serves `out/runs/` for the run pages. Leave it
  running.
- `gh` is not installed and the GitHub repository is private, so there are no GitHub
  issues to read. The open problems are sections 3 and 4.

## 6. Licences

Unchanged from `audit/codex-opt/CONTEXT.md` section 6. Only the Apache MapAnything
checkpoint ships. Barred from any product build: VGGT, MASt3R, DUSt3R, UniDepth, Inria
3DGS and 2DGS code, Pi3, and the CC-BY-NC MapAnything checkpoint. Every candidate's
licence is checked at its own repository or model card, for the code and the weights
separately, and the source link goes in RESEARCH.md. A permissive reimplementation of a
barred method (for example a Gaussian splatting library under Apache 2.0) is judged on
its own licence and recorded as such.

## 7. Tests

`src/tesseract/test_tesseract.py` (99 pass, 1 skip), `src/pipeline/test_local_gpu.py`,
`src/ingest/test_srt.py`, `src/ingest/test_frames.py`, `src/pipeline/test_mesh_export.py`,
`src/pipeline/test_colmap_export.py`, `src/pipeline/test_window_fuse.py`,
`tools/test_view_check.py`, `mvs_job/test_ba_gate.py`, `src/eval3d/test_metrics.py`,
`tools/check_onboarding.py`, and `node --test "demo/test/*.test.js"` (17 pass). All passed
on 4de9efa.
