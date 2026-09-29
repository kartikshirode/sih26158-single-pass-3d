# QA report - codex-b3-base

Source **video:test_flight.mp4**, 2026-09-25T20:27:50Z, git `0340d7e`, config `56a8c5c97d3e`.

## What this run may claim

| | |
|---|---|
| Ladder level | **L0 - measured** (dense set at full resolution, mesh, texture) |
| Frame | F5 |
| Units | **model units** |
| Scale | unvalidated (model units) - no external ruler or GNSS for this clip |
| Georeferenced | no |
| Region | not recorded |
| Codes | STAGE-UNAVAILABLE |

## The PS targets

| Target | Standing |
|---|---|
| R-O1 reconstruction type | met |
| R-O2 processing time | not measurable (clip is 20 s; the target is for a 10-minute video) |
| R-O3 spatial accuracy | not measurable (no ground truth) |
| R-O4 coverage | not measurable (no ground truth) |
| R-O5 formats | not met (3 of 6 written; missing obj, gltf, fbx) |
| R-O6 viewer | met (tools/build_viewer.py, demo/) |
| scale | unvalidated (model units) |

## Stages

| Stage | Seconds | Outcome | Facts |
|---|---:|---|---|
| `S0-screen` | 1.66 | ran | admissible=True, remedied_by_crop=False |
| `S1-ingest` | 4.40 | ran | frames_in=600, keyframes=173, srt_records=600, has_telemetry=True |
| `S2-plan` | 0.01 | ran | pose_views=173, dense_views=173 |
| `S3-geometry` | 357.24 | ran | points=9669064, geometry_provider=local |
| `S4-scale` | 0.00 | ran | units=model units |
| `S5-georef` | 0.00 | skipped (STAGE-UNAVAILABLE) | georeferenced=False, frame=F5, telemetry_unwired=True |
| `S5b-level` | 1.11 | ran | frame=F5 |
| `S6-export` | 2.81 | ran | frame=F5, units=model units |
| `S7-score` | 0.00 | skipped |  |
| `S8-verdict` | 0.00 | ran |  |

Total **367.2 s** against a 900 s budget - within.

## Artefacts

| Name | Path | Frame | Units | Bytes |
|---|---|---|---|---:|
| cameras | `cameras.npy` | F4 | model units | 22272 |
| colors | `colors.npy` | F4 | rgb | 29007320 |
| export_geotiff | `export/dsm.tif` | F5 | model units | 75489 |
| export_las | `export/cloud.las` | F5 | model units | 328748551 |
| export_ply | `export/cloud.ply` | F5 | model units | 232057714 |
| exports | `export` | F5 | model units |  |
| keyframes | `ingest.json` | F0 |  | 60016 |
| plan | `dense_index.npy` | F0 | index | 1512 |
| points | `points.npy` | F4 | model units | 116028896 |
| points_llf | `points_llf.npy` | F5 | model units | 116028896 |
| screen | `screen.json` |  |  | 400 |

## Provenance

Every figure above is read from this run's `run_manifest.json`; the inputs are checksummed at intake and the artefacts are checksummed on write, so `tesseract verify` can tell whether the files still match the run that claimed them. What the run may *say* is bounded by the two lines that matter: the ladder level, and the scale status.

> **This run has no external ruler.** Its lengths are model units. They may not be printed as metres, and they are not comparable with another run's (docs/08).
