# QA report - codex-b3-v2

Source **video:test_flight.mp4**, 2026-09-26T21:47:47Z, git `b9fdd49`, config `56a8c5c97d3e`.

## What this run may claim

| | |
|---|---|
| Ladder level | **L0 - measured** (dense set at full resolution, mesh, texture) |
| Frame | F6 |
| Units | **metres** |
| Scale | gnss x69.318 - consumer GNSS track, residual 0.13 m |
| Georeferenced | yes |
| Region | not recorded |
| Codes | none |

## The PS targets

| Target | Standing |
|---|---|
| R-O1 reconstruction type | met |
| R-O2 processing time | not measurable (clip is 20 s; the target is for a 10-minute video) |
| R-O3 spatial accuracy | not measurable (no ground truth) |
| R-O4 coverage | not measurable (no ground truth) |
| R-O5 formats | met |
| R-O6 viewer | met (tools/build_viewer.py, demo/) |
| scale | gnss x69.318 |

## Stages

| Stage | Seconds | Outcome | Facts |
|---|---:|---|---|
| `S0-screen` | 1.71 | ran | admissible=True, remedied_by_crop=False |
| `S1-ingest` | 4.57 | ran | frames_in=600, keyframes=173, srt_records=600, has_telemetry=True |
| `S2-plan` | 0.01 | ran | pose_views=173, dense_views=173 |
| `S3-geometry` | 292.95 | ran | points=9757462, geometry_provider=local, registered_views=173 |
| `S4-scale` | 0.00 | ran | units=model units |
| `S5-georef` | 2.27 | ran | georeferenced=True, frame=F6, units=metres, crs=None, vertical=height above take-off (SRT), not orthometric, gnss_fixes_used=173, gnss_track_m=826.2, gnss_inlier_fraction=1, gnss_fit_rms_m=0.126, sim3_scale=69.3176, dof=6 |
| `S5b-level` | 0.00 | skipped |  |
| `S6-export` | 16.61 | ran | frame=F6, units=metres |
| `S7-score` | 0.00 | skipped |  |
| `S8-verdict` | 0.00 | ran |  |

Total **318.1 s** against a 900 s budget - within.

## Artefacts

| Name | Path | Frame | Units | Bytes |
|---|---|---|---|---:|
| cameras | `cameras.npy` | F4 | model units | 22272 |
| colors | `colors.npy` | F4 | rgb | 29272514 |
| export_fbx | `export/model.fbx` | F6 | metres | 41639216 |
| export_geotiff | `export/dsm.tif` | F6 | metres | 10024094 |
| export_glb | `export/model.glb` | F6 | metres | 31704648 |
| export_las | `export/cloud.las` | F6 | metres | 292725081 |
| export_obj | `export/model.obj` | F6 | metres | 46032109 |
| export_ply | `export/cloud.ply` | F6 | metres | 234179266 |
| exports | `export` | F6 | metres |  |
| georef_transform | `georef.json` | F6 |  | 1586 |
| keyframes | `ingest.json` | F0 |  | 60189 |
| plan | `dense_index.npy` | F0 | index | 1512 |
| points | `points.npy` | F4 | model units | 117089672 |
| points_geo | `points_geo.npy` | F6 | metres | 234179216 |
| screen | `screen.json` |  |  | 400 |

## Provenance

Every figure above is read from this run's `run_manifest.json`; the inputs are checksummed at intake and the artefacts are checksummed on write, so `tesseract verify` can tell whether the files still match the run that claimed them. What the run may *say* is bounded by the two lines that matter: the ladder level, and the scale status.
