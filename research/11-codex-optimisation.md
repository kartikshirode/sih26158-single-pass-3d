# 11 · Local GPU optimisation: what changed, what was tried, what is left

Branch `codex-opt`, 2026-09-26 to 2026-09-27, from `audit-fixes` commit 0340d7e. The
brief (`audit/codex-opt/PROMPT.md`) was a ten-minute 1080p clip in, a textured model
out, in under 15 minutes on the RTX 4060 laptop, with the best model this hardware and
these models allow. Three sessions worked on it. Every number below is in
`audit/codex-opt/RUNLOG.md` with its run folder; this file says what it means.

The short version. A 600 s clip now runs end to end in 502.5 s (R 0.84, was 1.32).
On the synthetic clips with a DJI-style SRT, the georeferenced cloud went from 1.4-12.6 m
median error to about 0.4 m, 95-99% of it within 1 m, once the focal length stopped
being the weak input. The demo model looks the same as before; nothing tried on this branch made
it look better, and section 12 says why.

## 1. How it was measured

| ID | Clip | What it tests |
|---|---|---|
| B1 | `SIH DEMO.mp4`, 18.9 s, 177 keyframes | the owner's reference, real, no GPS |
| B2 | `data/nicosia_1080p.mp4`, 40 s | real, a long-lens pan over a city with a hidden cut |
| B3 | `data/test_flight.mp4` + SRT, 20 s | synthetic with known truth and a DJI-style SRT |
| B4 | the demo looped to 600 s | S0 and S1 speed only |
| B5s | 600 sharp synthetic keyframes | S3 at 600 views |
| B5v | `out/codex/b5v.mp4` + SRT, 600 s at 1 fps | a genuine ten-minute file end to end, with truth |

Four checks, none of them tuned to the changes they judged:

- **Held-out views** (`tools/view_check.py`). Every tenth keyframe is kept out of
  densify and texture but keeps its pose. The textured mesh is rendered into those
  cameras and scored against the real frame on the pixels it covers (PSNR, SSIM), with
  coverage over the whole frame reported beside it. On B1 two identical runs differed by
  0.02 dB. Quarter-size scores hid a real loss once (T1 in the log), so every later
  comparison is at full size.
- **Shape** (`tools/geometry_check.py`, from research/10): sparse points on one ground
  plane, layered dense cells, the largest camera step.
- **Truth** (`out/codex/b3_truth.py`): on B3 and B5v, camera centres against the true
  path and the dense cloud against the true surface, in the F6 frame.
- **Time**: wall clock from the manifest, R = wall / clip length. Evening runs varied by
  about 20% with other use of the laptop.

## 2. Before and after

Baseline is `audit-fixes` at 0340d7e; "final suite" is b360949 on the second night; "now"
is the v2 runs on this branch (commits up to b9fdd49; the focal gate changed after them,
see section 9). All clean runs, verify PASS.

| Benchmark | Baseline | Final suite | Now |
|---|---|---|---|
| B1 demo, 18.9 s | 321.9 s; held-out 21.73 dB at quarter size, 98.0% (22.83 dB, 0.649 at full size on the same settings) | 318.5 s; held-out 22.822 dB, 0.647, 98.8% | 264.5 s; focal held |
| B2 Nicosia, 40 s | 490.8 s; a bent strip across a hidden edit (step ratio 112) | 283.9 s; the edit cut off; focal 751 to 1400 px | 282.6 s; the same model |
| B3 test_flight, 20 s | 367.2 s; not georeferenced | 352.7 s; F6, cloud 5.15 m median from truth | 318.1 s; cloud 0.394 m median, 95.3% within 1 m |
| B5v, 600 s | not run (792.3 s on the first defaults, cloud 1.37 m) | 576.1 s, R 0.96; cloud 4.54 m | 502.5 s, R 0.84; cloud 0.338 m, 98.6% within 1 m |
| Formats (R-O5) | 3 of 6 | 6 of 6 | 6 of 6 |

The short clips cannot meet R 1.5 at their own length: MapAnything's load and fit and the
fixed cost of each tool are about 60-100 s of every run. The target is the ten-minute clip,
and that one comes in under it.

## 3. Audit findings

Found by reading the new code, running the benchmarks, or both. S1 means a wrong model or
number, or a crash, on a path a finale clip takes; S2 the same under less common
conditions.

| ID | Severity | Finding | Fix |
|---|---|---|---|
| F1 | S1 | B2 has an edit at frame 558 that the shot detector missed (histogram correlation 0.685 against a 0.55 cut). Every view registered at 0.47 px, and the model was a bent strip | S1 also cuts on a flow jump over six times the median with a moderate histogram change (e39dd18) |
| F2 | S2 | An ingest failure left no manifest | Fatal `ING-REJECT`, manifest written (b97ac13) |
| F3 | S1 | One featureless stretch refused the whole run: 46 frames past the edge of the synthetic site failed the 100% registration gate at 554 of 600 | The local gate needs 50%; the rest are dropped and flagged `GEO-UNREG` (ADR-029, f51f038, 6b16f51) |
| F4 | S2 | A densify failure made the ladder redo MapAnything, matching and the mapper, 130 of B1's 314 s | S3 split into poses and dense halves; L1 and L2 reuse the poses on disk (f51f038) |
| F5 | S2 | The L1 ladder step raised the dense resolution level and changed nothing: OpenMVS will not go below 640 px, and the demo's crops are 596 px high | `--min-resolution 320` (f6e07f4) |
| F6 | S1 | MapAnything fitted 1414 px on test_flight against a true 1066, and the ground came out 12.6 m low | Section 9 |
| F7 | S1 | Letting the mapper refine the focal length (the first fix for F6) moved it 6-9% long on both straight synthetic passes | Section 9 (5c479ae) |
| F8 | S3 | The synthetic SRT's gimbal pitch was -30 for a camera 60 degrees down | Generator and `data/test_flight.SRT` fixed (39bde63) |
| F9 | S2 | The ladder's local S3 estimate used the old pose path's rates: B5v's S3 estimated at 407 s, measured 543 | Rates from the final runs (425a027) |
| F10 | S1 | On a long clip S1 met its 600-keyframe target early and stopped: the ten-minute loop's keyframes ended at frame 12,604 of 18,000, so the last 30% of the flight was never reconstructed. The budget assumed keyframes land on gated frames spaced by the median flow; the gap is summed over every frame and each keyframe overshoots | The budget is bisected up from where it was until the target reaches the end of the shot; short clips keep their selection (2358c7e) |
| F11 | S2 | The run page fitted a similarity from the F4 cloud to the export cloud, which cannot hold S5's depth stretch: the mesh would sit metres off the cloud | The page uses `georef.json` or `level.json`, chosen by the manifest (1b9e609) |
| F12 | S2 | A rerun into the same folder whose mesh or texture step failed kept the previous run's mesh, and S6 exported it through the new transform | `dense()` clears the old cloud, mesh and textured mesh first (d547b90) |
| F13 | S2 | Past 8192 px TextureMesh writes one atlas per material; the export and the page kept only the last. B3 and B5v already fill one | Every material and atlas is exported; the page and scorer place atlases side by side (8adf3ed) |
| F14 | S3 | Any exception other than StageError in S3 to S6 ended the run with no manifest | Recorded as a failed stage, `STAGE-UNAVAILABLE`, and the ladder steps down (02cdb45) |
| F15 | S3 | `view_check` stopped on a held-out view the mapper did not place, which the 50% gate now allows | Counted as uncovered, left out of PSNR and SSIM (1b9e609) |
| F16 | S4 | The DSM's 5 cm cell floor was applied to runs in model units | Floor only in metres (11116da) |
| F17 | S4 | A 1 Hz SRT gave each keyframe the nearest fix, up to half a second (5 m at 10 m/s) from where it was taken | Interpolated between fixes (b9fdd49) |
| F18 | S2 | The first focal gate (10 degrees, percentile) refined B5v: MapAnything's poses read a 9-14 degree turn on straight passes | Thirds measure at 30 degrees, the mapper's turn recorded beside it (2ece0fd) |

Found and left open, all S3 or S4: a CUDA out-of-memory error in MapAnything is reported
as `GEO-REPROJ` and replayed rather than retried; a missing file inside S3 is labelled
"tools missing" and makes L1 solve the poses again; on the non-default MapAnything pose
path the recorded focal fact holds [f, cx]; and local S3 has no `key_extra`, so a change
to `local_gpu.DEFAULTS` needs a manual version bump (every change on this branch had one).

## 4. Poses

The global mapper's last pass re-triangulates every track and adjusts again. On B5s it was
95 of 191 s, and without it the cameras landed closer to the true path (0.31 m RMS against
0.66). On B1 the held-out views did not move. It is off now (d923a02). Without it the mean
reprojection error rose about 10% and test_flight failed the 1 px gate at 1.002 px, so the
model goes through `point_filtering` (4 px, 1.5 degrees) before the gate, as the old
MapAnything path did (b360949).

Other mapper options did nothing measurable on B1: one BA iteration instead of three,
20,000 kept tracks, 50 global positioning iterations.

## 5. Dense, mesh and texture

All on B1 with the poses held (`sparse_from`), one setting at a time, full-size held-out
scores against a same-conditions baseline (22.830 dB, 0.6493).

| Change | Result | Kept |
|---|---|---|
| Mesh point spacing 4 px (was 2.5) and texture decimation 0.2 (was 0.1) | 22.817 dB, coverage up 0.8 points, mesh and texture 106 s against 129; on B2 22.656 against 22.578 | Yes |
| Densify at full resolution | 2.3 times the time, no better image, layered cells up 0.017 | No |
| Depth-map post-processing (speckle filter, gap fill) | ground much cleaner (layered 0.056 to 0.021) but coverage down 5 points | No |
| Mesh spacing 1.5 px | 0.15 dB for 2.4 times the mesh time | No |
| Spurious-face removal 10 or 5 | holes in the far-field houses, coverage down up to 2.1 points | No |
| Texture at half resolution | 0.6 dB better, visibly blockier: the check was flattered by softer texture | No |
| Per-image colour gains | the gains are real (0.92-1.22) but the renders look the same | No |
| Seam levelling | the atlas turns black | No, section 12 |

## 6. Exports

S6 now writes the textured mesh as OBJ, GLB and FBX next to the cloud's PLY, LAS and
GeoTIFF, carried by the same transform as the cloud (670c2af). R-O5 goes from 3 of 6 to 6
of 6 on a local run. FBX needs the assimp library (section 13).

## 7. Georeferencing from the SRT

S5 used to skip every real video. It now fits the SRT's fixes to the cameras (keyframe i
to camera i), levelled first, yaw and slope from the track and roll from gravity
(ADR-026), and writes F6: local ENU in metres about the first fix, heights above take-off
(ADR-030, c04d7d8). The LAS and GeoTIFF carry an orthographic CRS about that fix. On B3
the cameras land within 0.14 m of the true path.

## 8. The ten-minute clip

A 600 s render at 30 fps would take about 7 hours on this CPU, and it would not test
anything more: the synthetic pass covers the same 920 m whatever its length. B5v is the
same pass rendered as 600 frames at 1 fps, a genuine 600 s file with a 600-record SRT.

| Stage | codex-b5v (first defaults) | codex-b5v-v2 |
|---|---:|---:|
| S0 screen | 2.0 s | 1.8 s |
| S1 ingest (353 keyframes) | 9.2 s | 6.8 s |
| S3 MapAnything and camera | 59.6 s | 42.6 s |
| S3 SIFT, matching, mapper, filter | 182.2 s | 96.7 s |
| S3 undistort and densify (300 views) | 150.5 s | 137.2 s |
| S3 mesh | 159.9 s | 77.1 s |
| S3 texture | 190.3 s | 106.9 s |
| S5 georeference | 3.1 s | 6.9 s |
| S6 export (six formats) | 24.5 s | 16.6 s |
| **Whole run** | **792.3 s** | **502.5 s** |

The mapper halved with its retriangulation pass off, and mesh and texture halved with the
coarser mesh spacing (4 px) and 20% texture decimation. The GPU was busy in densify only.

## 9. The focal length

This is the finding that moved accuracy most.

On a straight pass at one attitude the images cannot tell focal length f from k f with the
scene stretched k times along the view axis: both reproject identically. The GNSS fit
cannot tell them apart either, because the cameras sit on the same track in both. What is
left is a vertical error, one offset over the whole cloud, about (k - 1) times half the
flying height at a 60 degree pitch:

| Run | Focal (truth 1066 px) | Ground offset | Cloud error, median |
|---|---|---:|---:|
| test_flight, MapAnything's value held | 1414 | -12.7 m | 12.6 m |
| test_flight, refined by the mapper | 1179 | -5.2 m | 5.2 m |
| B5v, held | 1091 | -1.3 m | 1.4 m |
| B5v, refined | 1160 | -4.6 m | 4.5 m |

The first fix for F6 let the mapper refine the focal length (ADR-031). It helped
test_flight and hurt B5v: with nothing in the images to go on it drifted 6-9% long from
either side. Nicosia is the opposite case. It is a long-lens pan through 63 degrees, where
the focal length is observable, and refining it from MapAnything's 751 px to 1400 turned a
thin curved strip into the fan a pan sees (`out/codex/b2_compare.jpg`). So the mapper now
refines only when MapAnything's views turn at least 10 degrees (95th percentile rotation
from the middle view). The demo turns 2.0, the synthetic passes under 0.1, Nicosia 52.5.

The stretch does change one thing the fit sees: the view's angle to the track.
tan(model pitch) = tan(true pitch) / k. So a gimbal pitch in the SRT gives k, and S5
stretches the model back by 1 / k along the mean view axis before fitting again
(ADR-032). Replayed on the saved outputs of the four runs above, the implied focal length
came to 1066.6-1067.3 px, and the cloud error to 0.34-0.40 m, 95-99% within 1 m.

The catch: none of the 20 real DJI SRT fixtures in the repository carries a gimbal pitch.
On most consumer clips the correction does not apply, the manifest says so, and accuracy
rests on MapAnything's focal length (2.3% off on B5v, 33% off on the test_flight encode).

End to end on the branch the correction did what the replay said: test_flight 0.394 m
median, 95.3% within 1 m, with k 1.325 and an implied focal length of 1067.4 px; B5v
0.338 m, 98.6%.

The same runs showed the first gate was too loose. It read the turn as the 95th
percentile rotation from the middle view, at 10 degrees, and MapAnything's own poses gave
9.6 degrees on test_flight and 14.2 on B5v, so B5v was refined (to 1179 px) and only S5
saved it. MapAnything's poses drift between its inference windows; averaging each third
of the clip barely helps (8.9 and 13.1 degrees), while the mapper's poses read 0.1. The
demo reads 6.5 and Nicosia 111, so the gate is now 30 degrees on that thirds measure, and
the mapper's own turn is written beside it with a flag if the two disagree. B5v rerun on
that gate (`codex-b5v-v3`): focal length held at 1091 px, corrected by S5, 502.2 s, cloud
0.346 m median, 98.5% within 1 m. Holding the
focal length also made the mapper faster: 56.5 s against 89.2 on the demo.

## 10. Time

Measured on the final runs, the local S3 estimate is 57 s fixed (MapAnything's load and its
60-view camera fit), about 0.5 s per pose view (SIFT, matching, mapper: 0.29 on B5v, 0.36
on test_flight, 0.59 on the demo, 0.90 on Nicosia's pan, whose tracks run 32 views) and
about 1.1 s per dense view (undistortion, densify, mesh and texture: 1.25, 1.22, 0.90 and
0.22). The ladder now uses those rates; the old ones put B5v's S3 at 407 s against 543.

For a real ten-minute clip at 30 fps, from B5v-v2's 502.5 s: S1 decodes 30 times the
frames (the 10-minute loop took 51.5 s against 6.8), about +45 s; S1 can pick up to 600
keyframes instead of 353, and at B5v's 0.27 s per pose view that is about +67 s; the dense
set stays at 300. That predicts about 615 s, R 1.03. At the demo's pose rate it is about
700 s, R 1.17. A clip that pans like Nicosia, with the focal length refined and 32-view
tracks, would be the slow case, around 900 s; the ladder then drops to L1. These are
predictions from measured per-stage rates, not a run: no real ten-minute 30 fps clip was
available.

## 11. Tried and rejected

Beyond section 5: seam levelling on the CPU (black, like CUDA), and with CUDA with and without decimation (TX1 crashed, TX2 black); closing holes up to 300 edges (TX3, 6.8 dB worse); virtual face images (TX5, 0.17 dB worse); a grey empty colour (TX4, no measurable change); RefineMesh at image level 1 (no better, 76 s more) and level 2 (0.24 dB worse); TextureMesh's lens-mask
label (it exits after cleaning the mesh); free-space support in the mesh (no change, 13 s
slower); PINHOLE with the focal refined (fx and fy drifted apart, 1599 and 1146 px on
test_flight); the focal length refined on straight passes (section 9).

## 12. Still wrong

- **The demo looks the same.** Nothing tested on this branch improved it past the held-out noise.
  Its visible faults are colour patches between photos, holes and a shredded far edge.
  Seam levelling is what fixes the patches, and in this OpenMVS 2.4 Windows build it
  blackens most of the atlas or crashes, with or without decimation (TX1, TX2). Closing
  holes in ReconstructMesh bridges them with wrong surfaces (TX3).
- **Accuracy on real footage is unmeasured.** The 0.3-0.4 m figures are synthetic and need
  a gimbal pitch in the SRT, which none of the 20 real DJI fixtures has. Without one the
  height error is whatever MapAnything's focal length leaves: 2% (1.4 m) on B5v, 33%
  (12.6 m) on the test_flight encode.
- **Heights are above take-off**, not orthometric: the SRT gives nothing better.
- **Nicosia covers less** once its focal length is right (72% of held-out pixels against
  97%): a far scene seen from one spot has little parallax to densify.
- **The focal gate is a threshold** on MapAnything's reading. A real clip that turns 20-30
  degrees would be held; the mapper's turn and `focal_gate_doubtful` make that visible.
- **No real ten-minute 30 fps run** (section 10), and B4 no longer tests S1 at length: the
  shot-cut fix splits the looped demo at its loop points.
- The open S3 and S4 findings in section 3.

## 13. Machine changes

| Change | Where | Size | Undone |
|---|---|---:|---|
| assimp 6.0.5 library (BSD-3), official release | `C:\Users\Kartik\gpu-tools\assimp\Release` | 5.8 MB | No, S6 uses it for FBX. Delete the folder to undo |
| `pip install pyassimp==5.2.5` | global Python 3.12 | 0.1 MB | No. `pip uninstall pyassimp` |
| `pip cache purge` | `%LOCALAPPDATA%\pip\cache` | 3.68 GB freed | Nothing to undo |
| Deleted duplicate dense PLYs, depth maps, databases and aborted runs under `out/` | `out/` | about 4.8 GB freed | Regenerable by rerunning |
| Synthetic renders B5s and B5v | `out/codex/` | about 0.5 GB | No; delete to undo |

A local web server for the run pages was started on port 8765 (`python -m http.server`)
and may still be running. Nothing else outside the repository changed: no driver, power
plan, registry, WSL or Docker change.

## 14. How to reproduce

Set `SIH_COLMAP`, `SIH_OPENMVS`, `SIH_ASSIMP` (FBX) and `HF_HUB_OFFLINE=1` as in
`audit/codex-opt/CONTEXT.md` section 5, then:

```
python tesseract.py run data/test_flight.mp4 --horizon crop --geometry local --name b3 --no-resume
python tesseract.py verify out/runs/b3
python out/codex/b3_truth.py out/runs/b3        # truth check, synthetic clips only
python tools/view_check.py out/runs/<run> --build --out <json>
python tools/build_run_page.py out/runs/<run>
```

B5v is `python src/ingest/make_test_video.py out/codex/b5v.mp4 --seconds 600 --fps 1`
(about 16 minutes), run without `--horizon crop`. The experiment scripts named in the
run log (`exp.py`, `tex_exp.py`, `replay_s5.py`, `err_decomp.py`, `ma_turn.py`) are under
`out/codex/`, which is not in git.
