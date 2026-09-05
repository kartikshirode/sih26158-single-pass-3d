"""
S2-SCALE - reconstruct a long pass as overlapping windows and stitch them.

The PS budget is a 10-minute video, which our ingest keyframes to roughly 600 views.
No feed-forward multi-view model takes 600 views in one forward pass: they attend
across views, so both memory and time grow superlinearly in the view count. The
architecture therefore has to be windowed, and windowing is only sound if the
windows can be put back into one frame without drift.

They can, and cheaply, because consecutive windows SHARE views. For a shared view
the model emits a point map in each window's own frame, pixel for pixel - so the
correspondence is exact and needs no matching at all. A similarity fit on those
paired points carries window k into window k-1's frame.

Two details decide whether this works:

  * Fit a SIMILARITY, not a rigid transform. Each window sets its own scale; a
    rigid fit silently accumulates scale error along the pass.
  * Chain, do not fit to the first window. Each window overlaps only its
    neighbour, so a global fit has nothing to constrain distant pairs.

Drift is bounded by the overlap: more shared views means a better-conditioned fit
per hop, at the cost of more inference. `plan_windows` reports both.
"""
from __future__ import annotations
import numpy as np


def plan_windows(n_views: int, window: int = 24, overlap: int = 8) -> list[tuple[int, int]]:
    """
    Contiguous windows of `window` views, each sharing `overlap` with the previous.

    Overlap must be >= 3 for a similarity fit to be determined at all, and in
    practice >= 6 to be conditioned: the shared views of a single straight pass are
    nearly collinear, which is the same degeneracy that makes a full 6-DOF fit on
    one pass unreliable (see gnss.yaw_only_sim3).
    """
    if overlap >= window:
        raise ValueError("overlap must be smaller than the window")
    step = window - overlap
    out, s = [], 0
    while s < n_views:
        e = min(s + window, n_views)
        out.append((s, e))
        if e >= n_views:
            break
        s += step
    # A final stub window shares almost everything with its predecessor and adds
    # nothing; fold it back instead.
    if len(out) > 1 and out[-1][1] - out[-1][0] <= overlap:
        out[-2] = (out[-2][0], out[-1][1])
        out.pop()
    return out


def sim3_from_pairs(src: np.ndarray, dst: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """Umeyama similarity: scale, rotation, translation carrying src onto dst."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    S, Dm = src - mu_s, dst - mu_d
    C = (Dm.T @ S) / len(src)
    U, sig, Vt = np.linalg.svd(C)
    D = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:      # reflection guard
        D[2, 2] = -1
    R = U @ D @ Vt
    var_s = (S ** 2).sum() / len(src)
    s = float((sig * np.diag(D)).sum() / max(var_s, 1e-12))
    t = mu_d - s * R @ mu_s
    return s, R, t


def robust_sim3_from_pairs(src, dst, *, iters=64, min_inl=0.35, seed=0):
    """
    RANSAC around `sim3_from_pairs` with a MAD-derived threshold.

    A fixed threshold is worse than none: set below the noise floor it rejects good
    correspondences and the fit degrades. The threshold is therefore derived from
    the residuals of an all-points fit.
    """
    rng = np.random.default_rng(seed)
    s0, R0, t0 = sim3_from_pairs(src, dst)
    res = np.linalg.norm((s0 * (R0 @ src.T).T + t0) - dst, axis=1)
    thr = max(3.0 * 1.4826 * np.median(np.abs(res - np.median(res))), 1e-9)

    best = (s0, R0, t0, int((res < thr).sum()))
    for _ in range(iters):
        i = rng.choice(len(src), 4, replace=False)
        try:
            s, R, t = sim3_from_pairs(src[i], dst[i])
        except np.linalg.LinAlgError:
            continue
        r = np.linalg.norm((s * (R @ src.T).T + t) - dst, axis=1)
        n = int((r < thr).sum())
        if n > best[3]:
            best = (s, R, t, n)
    s, R, t, n = best
    if n >= max(int(min_inl * len(src)), 4):
        inl = np.linalg.norm((s * (R @ src.T).T + t) - dst, axis=1) < thr
        s, R, t = sim3_from_pairs(src[inl], dst[inl])     # refit on inliers
    return s, R, t, n / len(src), thr


def stitch(window_points: list[list[np.ndarray]], windows: list[tuple[int, int]],
           *, conf: list[list[np.ndarray]] | None = None, log=print):
    """
    Chain windows into one frame.

    `window_points[k][j]` is the point map of the j-th view OF WINDOW k, flattened
    to (N,3) and in window k's own coordinate frame. Views are matched by their
    global index, which `windows` supplies.
    """
    out, S, R, T = [], 1.0, np.eye(3), np.zeros(3)
    out.append([p.copy() for p in window_points[0]])
    report = []

    for k in range(1, len(window_points)):
        prev_lo, prev_hi = windows[k - 1]
        lo, hi = windows[k]
        shared = range(max(lo, prev_lo), min(hi, prev_hi))
        if len(list(shared)) < 3:
            raise ValueError(f"window {k} shares fewer than 3 views with {k-1}")

        src, dst = [], []
        for g in shared:
            a = window_points[k][g - lo]                 # in window k's frame
            b = out[k - 1][g - prev_lo]                  # already in world frame
            n = min(len(a), len(b))
            m = np.isfinite(a[:n]).all(1) & np.isfinite(b[:n]).all(1)
            if conf is not None:
                c = conf[k][g - lo][:n]
                m &= c >= np.percentile(c, 60)           # fit on confident points only
            idx = np.flatnonzero(m)
            if len(idx) > 4000:                          # subsample: the fit is closed-form
                idx = np.random.default_rng(g).choice(idx, 4000, replace=False)
            src.append(a[idx]); dst.append(b[idx])
        src, dst = np.concatenate(src), np.concatenate(dst)

        s, Rk, tk, inl, thr = robust_sim3_from_pairs(src, dst)
        out.append([(s * (Rk @ p.T).T + tk) for p in window_points[k]])
        rms = float(np.sqrt(((s * (Rk @ src.T).T + tk - dst) ** 2).sum(1).mean()))
        report.append({"window": k, "shared_views": len(list(shared)), "scale": s,
                       "inlier_frac": round(float(inl), 3),
                       "residual_rms": round(rms, 5), "threshold": round(float(thr), 5)})
        log(f"  window {k:>2}  {len(list(shared))} shared  scale {s:.4f}  "
            f"inliers {inl:6.1%}  residual RMS {rms:.4f}")

    fused = np.concatenate([p for w in out for p in w], 0)
    return fused, report


def stitch_gnss(window_cams: list[np.ndarray], window_points: list[list[np.ndarray]],
                windows: list[tuple[int, int]], gnss_enu: np.ndarray, *,
                yaw_only: bool = True, log=print):
    """
    Anchor every window to GNSS independently. No chaining, so no accumulation.

    `stitch` chains window k onto window k-1, and each hop is well conditioned - the
    shared views give exact pixel correspondences and the measured per-hop residual
    sits near the noise floor. The problem is arithmetic, not conditioning: 36 hops
    compound, and a chain that is excellent locally still ends up 15x worse at the
    far end than at the near end (see test_window_fuse.py).

    Anchoring each window's camera centres to GNSS instead makes every window an
    independent absolute fit. End-to-end error then equals GNSS error and stops
    depending on how long the pass is - which is precisely why the problem statement
    lists GPS as a mandatory input rather than an optional aid.

    yaw_only is the default because a single straight pass is DEGENERATE for full
    6-DOF rotation: the camera centres are near-collinear, so roll and pitch are
    unconstrained by the fit and must come from gravity instead. Fitting all six
    leaves the trajectory looking fine while the scene swings hundreds of metres
    about the flight axis (eval3d/gnss.py: yaw_only_sim3).
    """
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from eval3d.gnss import robust_yaw_sim3, robust_sim3

    fit = robust_yaw_sim3 if yaw_only else robust_sim3
    out, report = [], []
    for k, (lo, hi) in enumerate(windows):
        src = np.asarray(window_cams[k], float)
        dst = np.asarray(gnss_enu[lo:hi], float)
        # gnss.robust_yaw_sim3 returns (R, t, s, inliers) - NOT (s, R, t). It also
        # assumes ENU with Z UP, because that is the frame the yaw constraint is
        # defined in; a Y-up model frame must be rotated into ENU before this call.
        R, t, s = fit(src, dst, with_scale=True)[:3]
        out.append([(s * (R @ p.T).T + t) for p in window_points[k]])
        rms = float(np.sqrt((((s * (R @ src.T).T + t) - dst) ** 2).sum(1).mean()))
        report.append({"window": k, "views": hi - lo, "scale": float(s),
                       "cam_rms_m": round(rms, 4)})
        log(f"  window {k:>2}  {hi-lo} views  scale {s:.4f}  camera RMS {rms:.3f} m")
    fused = np.concatenate([p for w in out for p in w], 0)
    return fused, report
