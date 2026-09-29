# QA report - b2-rep1

Source **video:nicosia_1080p.mp4**, 2026-09-28T21:49:10Z, git `782118f`, config `56a8c5c97d3e`.

## What this run may claim

| | |
|---|---|
| Ladder level | **L0 - measured** (dense set at full resolution, mesh, texture) |
| Frame | F5 |
| Units | **model units** |
| Scale | unvalidated (model units) - no external ruler or GNSS for this clip |
| Georeferenced | no |
| Region | not recorded |
| Codes | ADM-HORIZON, ADM-SKY, ADM-SHOTS, ADM-OVERLAY, ING-NOGNSS |

## The PS targets

| Target | Standing |
|---|---|
| R-O1 reconstruction type | met |
| R-O2 processing time | not measurable (clip is 40 s; the target is for a 10-minute video) |
| R-O3 spatial accuracy | not measurable (no ground truth) |
| R-O4 coverage | not measurable (no ground truth) |
| R-O5 formats | met |
| R-O6 viewer | met (tools/build_viewer.py, demo/) |
| scale | unvalidated (model units) |

## Stages

| Stage | Seconds | Outcome | Facts |
|---|---:|---|---|
| `S0-screen` | 3.68 | ran (ADM-HORIZON, ADM-SKY, ADM-SHOTS, ADM-OVERLAY) | admissible=True, remedied_by_crop=True |
| `S1-ingest` | 6.65 | ran (ING-NOGNSS) | frames_in=1199, keyframes=209, srt_records=0, has_telemetry=False |
| `S2-plan` | 0.01 | ran | pose_views=209, dense_views=209 |
| `S3-geometry` | 336.93 | ran | points=1345370, geometry_provider=local, registered_views=209 |
| `S4-scale` | 0.00 | ran | units=model units |
| `S5-georef` | 0.00 | skipped (ING-NOGNSS) | georeferenced=False, frame=F5 |
| `S5b-level` | 0.47 | ran | frame=F5 |
| `S6-export` | 3.02 | ran | frame=F5, units=model units |
| `S7-score` | 0.00 | skipped |  |
| `S8-verdict` | 0.00 | ran |  |

Total **350.8 s** against a 900 s budget - within.

## Artefacts

| Name | Path | Frame | Units | Bytes |
|---|---|---|---|---:|
| cameras | `cameras.npy` | F4 | model units | 26880 |
| colors | `colors.npy` | F4 | rgb | 4036238 |
| export_fbx | `export/model.fbx` | F5 | model units | 4156080 |
| export_geotiff | `export/dsm.tif` | F5 | model units | 793282 |
| export_glb | `export/model.glb` | F5 | model units | 3206172 |
| export_las | `export/cloud.las` | F5 | model units | 45742955 |
| export_obj | `export/model.obj` | F5 | model units | 4278002 |
| export_ply | `export/cloud.ply` | F5 | model units | 32289058 |
| exports | `export` | F5 | model units |  |
| keyframes | `ingest.json` | F0 |  | 4951 |
| level_transform | `level.json` | F5 |  | 515 |
| plan | `dense_index.npy` | F0 | index | 1800 |
| points | `points.npy` | F4 | model units | 16144568 |
| points_llf | `points_llf.npy` | F5 | model units | 16144568 |
| screen | `screen.json` |  |  | 530 |

## Provenance

Every figure above is read from this run's `run_manifest.json`; the inputs are checksummed at intake and the artefacts are checksummed on write, so `tesseract verify` can tell whether the files still match the run that claimed them. What the run may *say* is bounded by the two lines that matter: the ladder level, and the scale status.

> **This run has no external ruler.** Its lengths are model units. They may not be printed as metres, and they are not comparable with another run's (docs/08).
