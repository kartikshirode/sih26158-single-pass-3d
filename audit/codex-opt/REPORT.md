# Local GPU run: report

Branch `codex-opt`, not pushed. Details and every number's source: `research/11-codex-optimisation.md`
and `audit/codex-opt/RUNLOG.md`.

## Before and after

| Benchmark | Baseline (0340d7e) | Now |
|---|---|---|
| B5v, a 600 s clip end to end | not run; 792.3 s on the first defaults (R 1.32) | **502.5 s, R 0.84**, R-O2 met |
| B5v accuracy (synthetic truth) | cloud 1.37 m median | **0.338 m median, 98.6% within 1 m** |
| B3 test_flight accuracy | not georeferenced at all | **0.394 m median, 95.3% within 1 m** |
| B1 demo | 321.9 s, held-out 22.83 dB / 0.649 | 264.5 s, held-out the same (22.822 / 0.647 on b360949) |
| B2 Nicosia | a bent strip across a hidden edit | the edit cut off; a pan read as a pan |
| Formats (R-O5) | 3 of 6 | 6 of 6 (OBJ, GLB, FBX of the textured mesh added) |

## The three biggest wins

1. **Metric accuracy from the gimbal pitch.** On a straight pass the focal length can't be
   seen in the images, and its error sinks the whole ground by (k - 1) times half the
   flying height. The camera's pitch against the GNSS track gives it back. The synthetic
   clouds went from 1.4-12.6 m to 0.34-0.40 m median error (ADR-032).
2. **A ten-minute clip fits the budget.** 502.5 s for B5v: no mapper retriangulation, a
   coarser mesh before texturing, and the focal length held on straight passes. The
   prediction for a real 30 fps ten-minute clip is about 615-700 s, under the 900 s budget.
3. **Nothing silently drops or fakes data.** A long clip's keyframes now reach the end of
   the flight (they stopped 30% short); unplaced views no longer refuse the run; any crash
   leaves a manifest; a stale mesh is never exported; the SRT georeferences a real video.

## Open problems

- **The model doesn't look better.** Colour patches, holes and a shredded far edge
  remain. The fix for the patches, TextureMesh's seam levelling, blackens or crashes in
  this OpenMVS build; nothing else tried beat the noise.
- **The accuracy figures are synthetic and need a gimbal pitch in the SRT.** None of the
  20 real DJI fixtures has one. Without it, heights are only as good as MapAnything's
  focal length: 2% on B5v, 33% on the test_flight encode.
- **No real ten-minute 30 fps clip was available**, so its time is a prediction from
  measured rates.

## Phase 3 findings

Severity: S1 wrong model, number or crash on a finale path; S2 the same under less common
conditions; S3 fails loudly on unusual input; S4 minor.

| ID | Severity | Finding | Status |
|---|---|---|---|
| F1 | S1 | B2's edit at frame 558 was missed by the shot detector; the model was a bent strip | Fixed, e39dd18 |
| F2 | S2 | An ingest failure left no manifest | Fixed, b97ac13 |
| F3 | S1 | 46 featureless frames refused a 600-view run at the 100% gate | Fixed, 50% gate and GEO-UNREG, f51f038 and 6b16f51 |
| F4 | S2 | A densify failure redid the poses at the next ladder level | Fixed, f51f038 |
| F5 | S2 | The L1 ladder step changed nothing on the demo's 596 px crops | Fixed, f6e07f4 |
| F6 | S1 | MapAnything's focal length 33% long on the test_flight encode: ground 12.6 m low | Fixed with a gimbal pitch (ADR-032, 78bc9ac); open without one |
| F7 | S1 | Refining the focal length on a straight pass made it 6-9% long | Fixed, 5c479ae |
| F8 | S3 | The synthetic SRT's gimbal pitch had the wrong convention | Fixed, 39bde63 |
| F9 | S2 | The ladder's S3 estimate used stale rates (407 s estimated, 543 s measured) | Fixed, 425a027 |
| F10 | S1 | A long clip's keyframes stopped at 70% of the flight | Fixed, 2358c7e |
| F11 | S2 | The run page would put a pitch-corrected mesh metres off the cloud | Fixed, 1b9e609 |
| F12 | S2 | A failed rerun could export the previous run's mesh | Fixed, d547b90 |
| F13 | S2 | A mesh over several texture atlases exported only the last | Fixed, 8adf3ed |
| F14 | S3 | An unexpected exception left no manifest | Fixed, 02cdb45 |
| F15 | S3 | The held-out check crashed on an unplaced view | Fixed, 1b9e609 |
| F16 | S4 | The DSM's 5 cm floor applied in model units | Fixed, 11116da |
| F17 | S4 | 1 Hz SRT fixes were taken by nearest, up to 5 m off | Fixed, b9fdd49 |
| F18 | S2 | The first focal gate misread MapAnything's drift as a turn | Fixed, 2ece0fd |
| F19 | S3 | MapAnything out of GPU memory is reported as GEO-REPROJ and replayed | Open |
| F20 | S3 | A missing file inside S3 reads as "tools missing" and L1 solves the poses again | Open |
| F21 | S4 | On the non-default MapAnything pose path the recorded focal fact holds [f, cx] | Open |
| F22 | S4 | Local S3 has no `key_extra`; a DEFAULTS change needs a manual version bump | Open; every change here had one |

## Machine changes

The assimp 6.0.5 library in `C:\Users\Kartik\gpu-tools\assimp\Release` (5.8 MB) and
`pyassimp` 5.2.5 are installed and still in place, because S6 uses them for FBX. To undo,
delete the folder and run `pip uninstall pyassimp`. The pip cache was purged (3.68 GB).
Bulky intermediates under `out/` were deleted, about 4.8 GB, all regenerable. A
`python -m http.server` on port 8765 served a run page and may still be running. No
driver, power, registry, WSL or Docker setting was touched.
