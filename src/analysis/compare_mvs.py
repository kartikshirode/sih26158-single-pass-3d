"""
Judge the MVS rebuild against the feed-forward baseline on the SAME axis.

The original finding was that MapAnything samples at 2.2 cm but carries information
at 30-50 cm, because geometry is predicted per 14 px DINOv2 patch and interpolated
below it. The rebuild only counts if that floor moved, so this measures the same
thing on both clouds rather than counting points (which the smooth version wins).

Two measurements, because either alone can be gamed:

  roughness(r)   plane fitted in a ball of radius r, median |residual|. Small-scale
                 roughness rising is NECESSARY but not sufficient - noise raises it
                 too. What separates them is the shape of the curve: an interpolated
                 surface has residual falling linearly to zero as r shrinks, while
                 both real detail and noise keep a floor.
  relief         height above a locally fitted ground plane. This is the one that
                 cannot be faked by noise: buildings either have vertical extent or
                 they are paint on a sheet. MapAnything's dense window put 0.000% of
                 points above 1.5 m where the structures are visibly 3-4 m.
"""
from __future__ import annotations

import argparse
import os

import numpy as np
from scipy.spatial import cKDTree

SUB = 300_000


def load(path: str) -> np.ndarray:
    if path.endswith(".npy"):
        return np.load(path).astype(np.float64)
    import open3d as o3d
    return np.asarray(o3d.io.read_point_cloud(path).points, dtype=np.float64)


def roughness(P: np.ndarray, radii, n_query=4000, seed=0):
    rng = np.random.default_rng(seed)
    sub = P[rng.choice(len(P), min(SUB, len(P)), replace=False)]
    tree = cKDTree(sub)
    q = sub[rng.choice(len(sub), min(n_query, len(sub)), replace=False)]
    out = []
    for r in radii:
        idx = tree.query_ball_point(q, r, workers=-1)
        res = []
        for qi, nb in zip(q, idx):
            if len(nb) < 12:
                continue
            X = sub[nb] - qi
            # plane through the neighbourhood: smallest singular direction
            n = np.linalg.svd(X - X.mean(0), full_matrices=False)[2][-1]
            res.append(np.median(np.abs((X - X.mean(0)) @ n)))
        out.append((r, float(np.median(res)) if res else np.nan, len(res)))
    return out


def relief(P: np.ndarray, up: np.ndarray, cell=1.0, min_pts=25):
    """Height above a per-cell local ground, using a supplied vertical."""
    a = up / np.linalg.norm(up)
    t = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = np.cross(a, t); e1 /= np.linalg.norm(e1)
    e2 = np.cross(a, e1)
    c = P.mean(0)
    u, v, y = (P - c) @ e1, (P - c) @ e2, (P - c) @ a
    iu = ((u - u.min()) / cell).astype(int)
    iv = ((v - v.min()) / cell).astype(int)
    key = iu * (iv.max() + 1) + iv
    order = np.argsort(key)
    ks, ys = key[order], y[order]
    edges = np.searchsorted(ks, np.arange(ks.max() + 2))
    g = np.full(ks.max() + 1, np.nan)
    for i in range(len(g)):
        a0, b0 = edges[i], edges[i + 1]
        if b0 - a0 >= min_pts:
            g[i] = np.percentile(ys[a0:b0], 5)
    h = y - g[key]
    return h[np.isfinite(h)]


def ground_normal(P: np.ndarray, seed=0) -> np.ndarray:
    """Thin principal axis of the cloud. Reliable only when the scene is planar,
    which both of these are (flatness 0.027-0.14) - see docs/05-quality-analysis.md
    section 6 for why the camera-derived alternative is worse here."""
    rng = np.random.default_rng(seed)
    q = P[rng.choice(len(P), min(SUB, len(P)), replace=False)]
    return np.linalg.svd(q - q.mean(0), full_matrices=False)[2][-1]


def report(name: str, P: np.ndarray, up=None, radii=(0.03, 0.06, 0.12, 0.25, 0.5, 1.0)):
    up = ground_normal(P) if up is None else up
    a = up / np.linalg.norm(up)
    t = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = np.cross(a, t); e1 /= np.linalg.norm(e1)
    e2 = np.cross(a, e1)
    c = P.mean(0)
    fu, fv = np.ptp((P - c) @ e1), np.ptp((P - c) @ e2)
    print(f"\n=== {name} ===")
    print(f"  points {len(P):>12,}   footprint {fu:6.1f} x {fv:6.1f} m   "
          f"density {len(P)/max(fu*fv,1e-9):8.1f} pts/m^2")
    print(f"  {'radius':>8} {'plane residual':>16} {'queries':>9}")
    for r, m, n in roughness(P, radii):
        print(f"  {r*100:>6.0f}cm {m*100:>14.3f} cm {n:>9,}")
    h = relief(P, up)
    print(f"  relief above local ground:  p90 {np.percentile(h,90):5.2f}  "
          f"p99 {np.percentile(h,99):5.2f}  p99.9 {np.percentile(h,99.9):5.2f}  "
          f"max {h.max():6.2f} m")
    for thr in (1.0, 1.5, 2.5):
        print(f"     above {thr:3.1f} m: {(h>thr).mean():7.3%}")
    return up


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="out/ytd3d/points_fused.npy")
    ap.add_argument("--mvs", default="out/ytd_mvs/scene_dense.ply")
    a = ap.parse_args()
    B = load(a.baseline)
    # Same vertical for both, taken from the baseline, so the relief numbers are
    # measured in one frame and stay comparable.
    up = report("MapAnything fused (feed-forward point maps)", B)
    if os.path.exists(a.mvs):
        report("OpenMVS dense (per-pixel photometric)", load(a.mvs), up=up)
    else:
        print(f"\n(no MVS cloud at {a.mvs} yet)")
