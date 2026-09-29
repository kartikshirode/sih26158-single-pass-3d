# QA report - night-b5v-2

Source **video:b5v.mp4**, 2026-09-28T21:39:50Z, git `782118f`, config `0385fc584dc2`.

## What this run may claim

| | |
|---|---|
| Ladder level | **L0 - measured** (dense set at full resolution, mesh, texture) |
| Frame | F6 |
| Units | **metres** |
| Scale | gnss x64.415 - consumer GNSS track, residual 0.13 m |
| Georeferenced | yes |
| Region | not recorded |
| Codes | none |

## The PS targets

| Target | Standing |
|---|---|
| R-O1 reconstruction type | met |
| R-O2 processing time | met |
| R-O3 spatial accuracy | not measurable (no ground truth) |
| R-O4 coverage | not measurable (no ground truth) |
| R-O5 formats | met |
| R-O6 viewer | met (tools/build_viewer.py, demo/) |
| scale | gnss x64.415 |

## Stages

| Stage | Seconds | Outcome | Facts |
|---|---:|---|---|
| `S0-screen` | 1.79 | ran | admissible=True, remedied_by_crop=False |
| `S1-ingest` | 6.66 | ran | frames_in=600, keyframes=353, srt_records=600, has_telemetry=True |
| `S2-plan` | 0.01 | ran | pose_views=353, dense_views=300 |
| `S3-geometry` | 514.05 | ran | points=23180136, geometry_provider=local, registered_views=353 |
| `S4-scale` | 0.00 | ran | units=model units |
| `S5-georef` | 6.28 | ran | georeferenced=True, frame=F6, units=metres, crs=None, vertical=height above take-off (SRT), not orthometric, gnss_fixes_used=353, gnss_track_m=829.3, gnss_inlier_fraction=1, gnss_fit_rms_m=0.126, sim3_scale=64.4151, dof=6 |
| `S5b-level` | 0.00 | skipped |  |
| `S6-export` | 19.46 | ran | frame=F6, units=metres |
| `S7-score` | 0.00 | skipped |  |
| `S8-verdict` | 0.00 | ran |  |

Total **548.2 s** against a 900 s budget - within.

## Artefacts

| Name | Path | Frame | Units | Bytes |
|---|---|---|---|---:|
| cameras | `cameras.npy` | F4 | model units | 45312 |
| colors | `colors.npy` | F4 | rgb | 69540536 |
| export_fbx | `export/model.fbx` | F6 | metres | 44743536 |
| export_geotiff | `export/dsm.tif` | F6 | metres | 21558914 |
| export_glb | `export/model.glb` | F6 | metres | 34235480 |
| export_las | `export/cloud.las` | F6 | metres | 695405301 |
| export_obj | `export/model.obj` | F6 | metres | 48890604 |
| export_ply | `export/cloud.ply` | F6 | metres | 556323443 |
| exports | `export` | F6 | metres |  |
| georef_transform | `georef.json` | F6 |  | 1588 |
| keyframes | `ingest.json` | F0 |  | 122376 |
| plan | `dense_index.npy` | F0 | index | 2528 |
| points | `points.npy` | F4 | model units | 278161760 |
| points_geo | `points_geo.npy` | F6 | metres | 556323392 |
| screen | `screen.json` |  |  | 393 |

## Provenance

Every figure above is read from this run's `run_manifest.json`; the inputs are checksummed at intake and the artefacts are checksummed on write, so `tesseract verify` can tell whether the files still match the run that claimed them. What the run may *say* is bounded by the two lines that matter: the ladder level, and the scale status.
