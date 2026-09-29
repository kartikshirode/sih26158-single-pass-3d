# QA report - demo_gpu

Source **video:SIH DEMO.mp4**, 2026-09-25T00:25:55Z, git `b886f24`, config `56a8c5c97d3e`.

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
| `S0-screen` | 1.66 | ran (ADM-HORIZON, ADM-SKY, ADM-OVERLAY) | admissible=True, remedied_by_crop=True |
| `S1-ingest` | 4.10 | ran (ING-NOGNSS) | frames_in=568, keyframes=134, srt_records=0, has_telemetry=False |
| `S2-plan` | 0.01 | ran | pose_views=134, dense_views=134 |
| `S3-geometry` | 133.53 | ran | points=931348, geometry_provider=local |
| `S4-scale` | 0.00 | ran | units=model units |
| `S5-georef` | 0.00 | skipped (ING-NOGNSS) | georeferenced=False, frame=F5 |
| `S5b-level` | 0.32 | ran | frame=F5 |
| `S6-export` | 0.39 | ran | frame=F5, units=model units |
| `S7-score` | 0.00 | skipped |  |
| `S8-verdict` | 0.00 | ran |  |

Total **140.0 s** against a 1800 s budget - within.

## Artefacts

| Name | Path | Frame | Units | Bytes |
|---|---|---|---|---:|
| cameras | `cameras.npy` | F4 | model units | 17280 |
| colors | `colors.npy` | F4 | rgb | 2794172 |
| export_geotiff | `export/dsm.tif` | F5 | model units | 978147 |
| export_las | `export/cloud.las` | F5 | model units | 31666207 |
| export_ply | `export/cloud.ply` | F5 | model units | 22352529 |
| exports | `export` | F5 | model units |  |
| keyframes | `ingest.json` | F0 |  | 3362 |
| plan | `dense_index.npy` | F0 | index | 1200 |
| points | `points.npy` | F4 | model units | 11176304 |
| points_llf | `points_llf.npy` | F5 | model units | 11176304 |
| screen | `screen.json` |  |  | 521 |

## Provenance

Every figure above is read from this run's `run_manifest.json`; the inputs are checksummed at intake and the artefacts are checksummed on write, so `tesseract verify` can tell whether the files still match the run that claimed them. What the run may *say* is bounded by the two lines that matter: the ladder level, and the scale status.

> **This run has no external ruler.** Its lengths are model units. They may not be printed as metres, and they are not comparable with another run's (docs/08).
