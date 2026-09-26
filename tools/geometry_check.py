"""
Shape checks for a local GPU reconstruction of mostly flat ground, with pictures.

Run:  python tools/geometry_check.py out/runs/<run>/geometry [--out prefix]

Reads points_fused.npy, colors_fused.npy, cameras.npy and sparse_txt/ from the
geometry folder. No ground truth is needed; each number catches one failure seen on
the demo clip (research/10-reconstruction-quality.md):

  sparse on plane   share of sparse points within 3% of the flight height of one
                    RANSAC ground plane. Poses that drift stack the ground in tilted
                    sheets and pull this down (0.47 before the fix, 0.77 after)
  layered cells     share of ground cells (5% of the flight height across) whose
                    dense heights spread over 10% of it (0.35 before, 0.06 after)
  step ratio        largest camera step over the median one. A hole in the keyframe
                    chain shows as one huge step (25 before, 2.2 after)

--out also writes <prefix>_side.jpg and <prefix>_top.jpg: the dense cloud seen from
the side and from above in the ground plane's frame, with the cameras in orange.
"""
from __future__ import annotations

import argparse
import os

import numpy as np


def ground_frame(P: np.ndarray, cams: np.ndarray, seed: int = 0):
    """RANSAC plane through the points: centre, unit normal toward the cameras."""
    rng = np.random.default_rng(seed)
    alt0 = np.ptp(cams, 0).max() + 1e-9
    best = (-1, None, None)
    for _ in range(400):
        s = P[rng.choice(len(P), 3, replace=False)]
        n = np.cross(s[1] - s[0], s[2] - s[0])
        if np.linalg.norm(n) < 1e-12:
            continue
        n /= np.linalg.norm(n)
        h = np.abs((cams - s[0]) @ n)
        k = int((np.abs((P - s[0]) @ n) < 0.02 * max(np.median(h), 1e-3 * alt0)).sum())
        if k > best[0]:
            best = (k, n, s[0])
    _, n, c = best
    if ((cams - c) @ n).mean() < 0:
        n = -n
    return c, n


def read_sparse(txt: str):
    P = []
    for ln in open(os.path.join(txt, "points3D.txt")):
        if ln[0] != "#":
            P.append(ln.split()[1:4])
    return np.asarray(P, float)


def check(geo: str, out: str | None = None) -> dict:
    P = np.load(os.path.join(geo, "points_fused.npy")).astype(float)
    C = np.load(os.path.join(geo, "colors_fused.npy"))
    cams = np.load(os.path.join(geo, "cameras.npy"))[:, :3, 3]
    cams = cams[np.isfinite(cams).all(1)]        # unregistered views are NaN rows
    S = read_sparse(os.path.join(geo, "sparse_txt"))
    c, n = ground_frame(S, cams)
    alt = float(np.median((cams - c) @ n))
    on_plane = float(np.mean(np.abs((S - c) @ n) < 0.03 * alt))

    d = cams[-1] - cams[0]
    d -= (d @ n) * n
    e1 = d / (np.linalg.norm(d) or 1.0)
    e2 = np.cross(n, e1)
    Q = np.stack([(P - c) @ e1, (P - c) @ e2, (P - c) @ n], 1)
    K = np.stack([(cams - c) @ e1, (cams - c) @ e2, (cams - c) @ n], 1)
    ij = np.floor(Q[:, :2] / (0.05 * alt)).astype(np.int64)
    key = ij[:, 0] * 1_000_003 + ij[:, 1]
    o = np.argsort(key, kind="stable")
    k, h = key[o], Q[o, 2]
    starts = np.flatnonzero(np.r_[True, k[1:] != k[:-1]])
    ends = np.r_[starts[1:], len(k)]
    spread = np.array([np.percentile(h[a:b], 90) - np.percentile(h[a:b], 10)
                       for a, b in zip(starts, ends) if b - a >= 20]) / alt
    steps = np.linalg.norm(np.diff(cams, axis=0), axis=1)
    res = {"dense_points": int(len(P)), "cameras": int(len(cams)),
           "sparse_on_plane": round(on_plane, 3),
           "layered_cells": round(float(np.mean(spread > 0.1)), 3),
           "cell_spread_median": round(float(np.median(spread)), 4),
           "step_ratio": round(float(steps.max() / np.median(steps)), 1)}
    if out:
        _pictures(Q, C, K, alt, out)
    return res


def _pictures(Q, C, K, alt, out):
    import cv2

    lo = np.minimum(np.percentile(Q, 0.5, 0), K.min(0)) - 0.1 * alt
    hi = np.maximum(np.percentile(Q, 99.5, 0), K.max(0)) + 0.1 * alt
    res = (hi[0] - lo[0]) / 1400

    def view(a, b, depth, stretch=1):
        W, H = int((hi[a] - lo[a]) / res) + 1, int((hi[b] - lo[b]) / res) + 1
        u = ((Q[:, a] - lo[a]) / res).astype(int)
        v = H - 1 - ((Q[:, b] - lo[b]) / res).astype(int)
        m = (u >= 0) & (u < W) & (v >= 0) & (v < H)
        order = np.argsort(depth[m])
        img = np.zeros((H, W, 3), np.uint8)
        img[v[m][order], u[m][order]] = C[m][order][:, ::-1]
        for p in K:
            cv2.circle(img, (int((p[a] - lo[a]) / res), H - 1 - int((p[b] - lo[b]) / res)),
                       2, (0, 160, 255), -1)
        return cv2.resize(img, None, fx=1, fy=stretch) if stretch != 1 else img

    cv2.imwrite(out + "_side.jpg", view(0, 2, -Q[:, 1], stretch=2))
    cv2.imwrite(out + "_top.jpg", view(0, 1, Q[:, 2]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("geometry", help="a local GPU work folder, e.g. out/runs/<run>/geometry")
    ap.add_argument("--out", default=None, help="prefix for the side and top pictures")
    a = ap.parse_args()
    for k, v in check(a.geometry, a.out).items():
        print(f"  {k:<20} {v}")
