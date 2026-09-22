# UseGeo as the accuracy reference: what is known before the download (Phase 2 prep)

Date: 2026-09-22. Status: research only, nothing downloaded yet. Feeds `docs/12` EXP-22
and the plan's Phase 2.1.

## Why UseGeo and not H3D

`docs/14` §3.2 needs a LiDAR-referenced survey block whose *images* are published, so one
flight strip can be run as keyframes through S3 to S6 and scored. H3D is a segmentation
benchmark and its release is the labelled point cloud and mesh. UseGeo is a photogrammetry
dataset built for exactly this comparison, with a published evaluation code base.

## The dataset, from `github.com/3DOM-FBK/UseGeo` (README read 2026-09-22)

| | |
|---|---|
| Sensors | RIEGL miniVUX-3UAV scanner, SONY ILCE-7RM3 camera (Nex et al. 2023, ISPRS Archives XLVIII-1/W3-2023, 123-130) |
| Area, height | 1100 x 650 m, 80 m above ground on average |
| Images | 829 across three datasets, 7952 x 5304 px, GSD 1.7 / 1.8 / 1.9 cm, 80% forward and 60% side overlap, "a minimum of 8 images on each object point" |
| Strips | 8 per dataset: 224, 328 and 277 images |
| LiDAR | "ca 50 points/m2" in the README; the 2023 paper's figure caption says "more than 100 pts/sqm" for the dataset it used |
| Also provided | per-image ground-truth depth at 1989 x 1320 (quarter resolution), camera poses as X0 Y0 Z0 omega phi kappa in degrees, interior c x0 y0 in px, and an MVS point cloud |
| Licence | CC BY-NC-SA 4.0. Non-commercial. Fine for the evaluation; it cannot become deliverable data and its derived clouds cannot be published under a different licence (`docs/16` needs an L-row) |
| Download | three Synology sharing links on `eostore.itc.utwente.nl:5001` (`1gJRLdQ71`, `c4LlTkVjT`, `r4o1tdCNv`). Browser only; the page is JavaScript. The README warns institutional firewalls block it. Sizes not stated |
| Citation | Nex et al. 2024, ISPRS Open Journal of Photogrammetry and Remote Sensing 13, 100070 |

**Not learnable without downloading:** the coordinate reference system and height datum,
the point-cloud file format, and the file sizes. The README and the 2023 paper do not say;
the 2024 dataset paper is open access but both hosts refused a scripted fetch (403). The
evaluation code reads whatever `open3d.io.read_point_cloud` reads (PLY, PCD, XYZ, and so
on), which suggests PLY but does not prove it. If the clouds arrive as LAS/LAZ, `laspy`
is already in the MVS container (commit 33fb172) and can convert.

## The evaluation protocol, from `UseGeoEvaluation/DepthEstimationAnd3DReconstruction` (MIT)

Three scripts. `eval_pointcloud.py` and `eval_mesh.py` are the ones this project would
use; `eval_depth_maps.py` needs per-image depth, which S3 has but S4 does not preserve.

| | point cloud | mesh |
|---|---|---|
| Loader | `o3d.io.read_point_cloud` | `o3d.io.read_triangle_mesh` for the estimate, point cloud for truth |
| Distance | point to nearest point (KD-tree) | ground-truth point to nearest triangle (raycasting scene) |
| Accuracy | mean L1 over the estimate points within the `-cpl` quantile (default 0.9); RMSE alongside | same, over the triangles processed |
| Completeness | fraction of truth points within `-abs` (default 0.2 m) | same |
| Alignment | both clouds translated to the origin first; optional `-icp` (point-to-point, *with scaling*); optional 4x4 from `-transform` | same |
| Pre-filter | `filter_ground_truth_pointcloud.py` drops truth points more than 5 (units) from any estimate point in XY, so LiDAR beyond the camera footprint does not count against completeness | |
| Pins | `open3d==0.17.0`, `numpy==1.25.2`: Python 3.11 or 3.12, the same constraint as `compare_mvs.load()` (ADR-018) | |

Published thresholds are 0.5, 0.1 and 0.05 m for accuracy and completeness. Numbers the
repository README attributes to the companion paper (Hermann et al. 2024, ISPRS Open
Journal 13, 100065), **read from the README, not yet from the paper**: COLMAP at 8K,
point-cloud L1 0.0453 m on Dataset 1; ACMMP completeness 0.6331; OpenMVS mesh L1
0.0261 m on Dataset 1; COLMAP depth-map L1 0.2765 m. The 2023 paper gives a NeRF-based
cloud-to-cloud mean of 0.175 m with a 0.253 m standard deviation, and a depth MAE of
1.72 m at 88% completeness. Those are the bars a single strip of ours would stand next to.

## What the protocol does to our scoring, and what it does not

The protocol's `-icp` fits **scale**. Run that way it answers `docs/14`'s "shape error"
question and nothing about absolute accuracy, which is the R-O3 claim. The plan's order
stands: score absolute first (no alignment, in the dataset's own CRS), then rigid, then
report the scale factor separately. The protocol's scripts can produce the rigid-plus-
scale number; `src/eval3d` produces the other two and must not adopt the origin-centring
step, which discards the absolute offset before anything is measured.

Completeness in the protocol is against *filtered* LiDAR, filtered by XY proximity to the
estimate. That is a looser denominator than `docs/14` §1's observable surface (visibility
from two or more cameras). Report both; the protocol's number will be higher.

## The four pieces of work the plan already lists, re-checked against this

1. A reference loader: still needed, format unknown until download.
2. Normal estimation for the observable-surface denominator: still needed; the protocol
   side-steps it with the XY filter.
3. Tiling: `nn_distances` builds one cKDTree over the whole reference. 1100 x 650 m at
   50 to 100 pts/m2 is 36 to 72 million points before any strip crop. Crop to the strip's
   footprint before building the tree; the protocol's own filter is the same idea.
4. CRS: unknown, see above. Omega-phi-kappa poses mean a projected, right-handed,
   photogrammetric frame; expect ETRS89-based UTM or a local frame, and verify on arrival.

## Rented compute for Phase 2.2, priced 2026-09-22

Aggregator snapshots (`gpuperhour.com`, `getdeploying.com/gpus`, RunPod and Lambda price
pages), marketplace floors change hourly:

| Card | On-demand, per hour | Notes |
|---|---|---|
| RTX 4090 24 GB | $0.34 RunPod community, $0.51 Vast.ai, $0.69 RunPod secure | enough for MapAnything at 11.5 GB (EXP-11) and for OpenMVS CUDA on 45 views |
| A100 80 GB | $0.47 Vast.ai floor, $1.59 RunPod PCIe, $1.76 September median, $2.06 Lambda | EXP-25's 10-minute clip end to end |
| L40S 48 GB | $1.09 to $1.29 | |
| H100 SXM | $1.49 Vast.ai floor, $2.99 to $3.99 Lambda | not needed |

At these rates EXP-16 and EXP-25 together are under $10 of card time; the cost is the
COLMAP-with-CUDA build for the card's compute capability, which the plan already budgets a
session for. ADR-010 permits this for benchmarking on non-Indian public footage; UseGeo
is Italian (the 2023 paper thanks the Autonomous Province of Trento), so the accuracy run
can go to a rented card too. Supplied NTRO data cannot.
