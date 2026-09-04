"""
Which parts of a scene can a SINGLE drone pass actually observe?

This answers the completeness ceiling (R-O4, 20% of the score) and the facade
question (R-F2) analytically, before any reconstruction model exists. If a surface is
never observed by any frame, no algorithm can recover it from measurement - it can
only be inferred, which is R-C7 and must be labelled as such.

METHOD - and one trap that had to be fixed by measurement.

Visibility is computed with a z-buffer rather than per-ray casting, because trimesh's
pure-Python caster runs at ~1 ms/ray here (no embree), i.e. ~9 minutes for one sweep,
versus well under a second for this.

The trap: a z-buffer built only from the QUERY points does not detect occlusion. With
points sparse relative to the buffer, an occluded point is usually the only sample in
its pixel bin, so it wins its own depth test and is wrongly called visible. Measured
on a two-wall test, a far wall fully hidden behind a near wall was reported 70.6%
visible.

The fix is to separate the two roles: build the depth buffer from a DENSE occluder
cloud sampled over the whole mesh, then test the query points against that buffer.
Same test now reports 0.0% for the hidden wall.
"""

from __future__ import annotations

import numpy as np


def _project(points: np.ndarray, cam_pos: np.ndarray, cam_R: np.ndarray,
             K: np.ndarray):
    """World -> camera -> pixel. Returns (u, v, z) with z the camera-frame depth."""
    rel = np.asarray(points, dtype=np.float64) - cam_pos[None, :]
    cam = rel @ cam_R                      # cam_R is cam->world, so (rel @ R) == R^T rel
    z = cam[:, 2]
    with np.errstate(invalid="ignore", divide="ignore"):
        u = K[0, 0] * cam[:, 0] / z + K[0, 2]
        v = K[1, 1] * cam[:, 1] / z + K[1, 2]
    return u, v, z, rel


def build_depth_buffer(occluders: np.ndarray, cam_pos: np.ndarray,
                       cam_R: np.ndarray, K: np.ndarray,
                       width: int, height: int, bin_scale: float):
    """Nearest-depth-per-bin buffer from a dense occluder cloud."""
    bw = max(int(width * bin_scale), 1)
    bh = max(int(height * bin_scale), 1)
    buf = np.full(bw * bh, np.inf)

    u, v, z, _ = _project(occluders, cam_pos, cam_R, K)
    ok = (z > 1e-6) & (u >= 0) & (u < width) & (v >= 0) & (v < height)
    if ok.any():
        ub = np.clip((u[ok] * bin_scale).astype(np.int64), 0, bw - 1)
        vb = np.clip((v[ok] * bin_scale).astype(np.int64), 0, bh - 1)
        np.minimum.at(buf, vb * bw + ub, z[ok])
    return buf, bw, bh


def visible_mask(points: np.ndarray, normals: np.ndarray,
                 cam_pos: np.ndarray, cam_R: np.ndarray, K: np.ndarray,
                 width: int, height: int, *,
                 occluders: np.ndarray | None = None,
                 depth_buffer=None,
                 bin_scale: float = 0.125,
                 max_view_angle_deg: float = 75.0,
                 max_range: float = 1500.0,
                 depth_tol: float = 1.0) -> np.ndarray:
    """
    Boolean mask of which `points` are visible from ONE camera.

    Pass either `occluders` (a dense cloud, buffer built here) or a prebuilt
    `depth_buffer` from `build_depth_buffer` (faster when reused).
    """
    P = np.asarray(points, dtype=np.float64)
    N = np.asarray(normals, dtype=np.float64)

    u, v, z, rel = _project(P, cam_pos, cam_R, K)

    ok = (z > 1e-6) & (z < max_range)
    ok &= (u >= 0) & (u < width) & (v >= 0) & (v < height)

    # Backface / grazing-angle: the surface must face the camera
    dist = np.maximum(np.linalg.norm(rel, axis=1, keepdims=True), 1e-9)
    cos_ang = -np.sum((rel / dist) * N, axis=1)
    ok &= cos_ang > np.cos(np.radians(max_view_angle_deg))

    if not ok.any():
        return np.zeros(len(P), dtype=bool)

    # Occlusion against the dense buffer
    if depth_buffer is None:
        if occluders is None:
            raise ValueError("provide `occluders` or `depth_buffer`")
        depth_buffer = build_depth_buffer(occluders, cam_pos, cam_R, K,
                                          width, height, bin_scale)
    buf, bw, bh = depth_buffer

    ub = np.clip((u[ok] * bin_scale).astype(np.int64), 0, bw - 1)
    vb = np.clip((v[ok] * bin_scale).astype(np.int64), 0, bh - 1)
    nearest = buf[vb * bw + ub]

    out = np.zeros(len(P), dtype=bool)
    out[ok] = z[ok] <= nearest + depth_tol
    return out


def coverage(points: np.ndarray, normals: np.ndarray,
             positions: np.ndarray, rotations: np.ndarray,
             K: np.ndarray, width: int, height: int,
             occluders: np.ndarray, *,
             stride: int = 1, min_views: int = 2, **kw) -> dict:
    """
    Observation count per point across a whole flight.

    `min_views >= 2` matters: a point seen by only ONE camera cannot be triangulated,
    so it is not reconstructable geometry even though it appears in the imagery. That
    is the honest coverage number, and it is what R-O4 should be judged on.
    """
    counts = np.zeros(len(points), dtype=np.int32)
    bin_scale = kw.get("bin_scale", 0.125)
    for i in range(0, len(positions), stride):
        db = build_depth_buffer(occluders, positions[i], rotations[i], K,
                                width, height, bin_scale)
        counts += visible_mask(points, normals, positions[i], rotations[i],
                               K, width, height, depth_buffer=db, **kw)
    return {
        "counts": counts,
        "seen_any": counts >= 1,
        "reconstructable": counts >= min_views,
        "frac_any": float(np.mean(counts >= 1)),
        "frac_reconstructable": float(np.mean(counts >= min_views)),
        "mean_views_where_seen": float(counts[counts > 0].mean()) if (counts > 0).any() else 0.0,
    }
