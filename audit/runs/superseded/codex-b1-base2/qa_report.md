# QA report - codex-b1-base2

Source **video:SIH DEMO.mp4**, 2026-09-25T19:56:30Z, git `0340d7e`, config `56a8c5c97d3e`.

## What this run may claim

| | |
|---|---|
| Ladder level | **L0 - measured** (dense set at full resolution, mesh, texture) |
| Frame | F5 |
| Units | **model units** |
| Scale | unvalidated (model units) - no external ruler or GNSS for this clip |
| Georeferenced | no |
| Region | not recorded |
| Codes | ADM-HORIZON, ADM-SKY, ADM-OVERLAY, ING-NOGNSS |

## The PS targets

| Target | Standing |
|---|---|
| R-O1 reconstruction type | met |
| R-O2 processing time | not measurable (clip is 19 s; the target is for a 10-minute video) |
| R-O3 spatial accuracy | not measurable (no ground truth) |
| R-O4 coverage | not measurable (no ground truth) |
| R-O5 formats | not met (3 of 6 written; missing obj, gltf, fbx) |
| R-O6 viewer | met (tools/build_viewer.py, demo/) |
| scale | unvalidated (model units) |

## Stages

| Stage | Seconds | Outcome | Facts |
|---|---:|---|---|
| `S0-screen` | 1.68 | ran (ADM-HORIZON, ADM-SKY, ADM-OVERLAY) | admissible=True, remedied_by_crop=True |
| `S1-ingest` | 4.17 | ran (ING-NOGNSS) | frames_in=568, keyframes=177, srt_records=0, has_telemetry=False |
| `S2-plan` | 0.01 | ran | pose_views=177, dense_views=177 |
| `S3-geometry` | 313.62 | ran | points=7024575, geometry_provider=local |
| `S4-scale` | 0.00 | ran | units=model units |
| `S5-georef` | 0.00 | skipped (ING-NOGNSS) | georeferenced=False, frame=F5 |
| `S5b-level` | 0.80 | ran | frame=F5 |
| `S6-export` | 1.65 | ran | frame=F5, units=model units |
| `S7-score` | 0.00 | skipped |  |
| `S8-verdict` | 0.00 | ran |  |

Total **321.9 s** against a 900 s budget - within.

## Artefacts

| Name | Path | Frame | Units | Bytes |
|---|---|---|---|---:|
| cameras | `cameras.npy` | F4 | model units | 22784 |
| colors | `colors.npy` | F4 | rgb | 21073853 |
| export_geotiff | `export/dsm.tif` | F5 | model units | 280163 |
| export_las | `export/cloud.las` | F5 | model units | 238835925 |
| export_ply | `export/cloud.ply` | F5 | model units | 168589978 |
| exports | `export` | F5 | model units |  |
| keyframes | `ingest.json` | F0 |  | 4203 |
| plan | `dense_index.npy` | F0 | index | 1544 |
| points | `points.npy` | F4 | model units | 84295028 |
| points_llf | `points_llf.npy` | F5 | model units | 84295028 |
| screen | `screen.json` |  |  | 521 |

## Provenance

Every figure above is read from this run's `run_manifest.json`; the inputs are checksummed at intake and the artefacts are checksummed on write, so `tesseract verify` can tell whether the files still match the run that claimed them. What the run may *say* is bounded by the two lines that matter: the ladder level, and the scale status.

> **This run has no external ruler.** Its lengths are model units. They may not be printed as metres, and they are not comparable with another run's (docs/08).
