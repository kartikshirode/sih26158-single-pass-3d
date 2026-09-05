"""
EXP-13 - can a 10-minute pass be reconstructed in windows without losing accuracy?

The problem statement budgets 900 s for a 10-minute video, which our ingest keyframes
to roughly 600 views. No feed-forward multi-view model takes 600 views in one forward
pass - they attend across views, so memory and time grow superlinearly in view count.
The architecture is therefore forced to be windowed, and the question this experiment
answers is what that costs.

Three schemes, measured against the same ground truth:

  A  chain only          window k fitted onto window k-1 through their shared views
  B  per-window anchor   each window fitted to GNSS independently
  C  chain + one anchor  chain for shape, then a single GNSS fit over the whole pass

The shared-view correspondence is exact - the model emits a point map per view, so
for a view in two windows the same pixel is the same point in both frames. There is
no matching step and no matching error; every number below is the geometry.

Frames: ENU metres, Z up. Window frames differ by yaw, translation and scale only,
because a gravity-aligned reconstruction has roll and pitch pinned by the IMU. Using
a full random rotation instead makes the yaw-only anchor look broken when in fact the
scene model is wrong - that mistake cost an hour here, and is the same class of error
as an evaluation scene with no vertical structure.
"""
from __future__ import annotations
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eval3d.gnss import apply_transform, robust_yaw_sim3
from pipeline.window_fuse import plan_windows, robust_sim3_from_pairs

N_VIEWS, PER_VIEW = 600, 400
WINDOW, OVERLAP = 24, 8
GNSS_SIGMA_M = 1.5          # consumer-grade, matching the EXP-05 regime
BIAS_STEP_M = 0.08          # correlated bias random walk - this is what does not average out
POINT_NOISE_M = 0.01        # per-point model noise, the floor everything is measured against


def yaw_sim3(rng, scale_sigma=0.06):
    a = rng.uniform(0, 2 * np.pi)
    c, s = np.cos(a), np.sin(a)
    R = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    return float(np.exp(rng.normal(0, scale_sigma))), R, rng.normal(0, 2.0, 3)


def build(rng):
    """A 600 m straight pass at 100 m, over a ridge with along-track relief."""
    cams = np.stack([np.arange(N_VIEWS) * 1.0,
                     np.zeros(N_VIEWS),
                     np.full(N_VIEWS, 100.0)], 1)
    truth = []
    for v in range(N_VIEWS):
        x = rng.uniform(v * 1.0, v * 1.0 + 6.0, PER_VIEW)
        y = rng.uniform(-5, 5, PER_VIEW)
        z = np.exp(-((y / 2.0) ** 2)) * 2.0 + 0.15 * np.sin(x)
        truth.append(np.stack([x, y, z], 1))
    return cams, truth


def chain(wp, wcam, windows, rng):
    """Fit each window onto its predecessor through the shared views."""
    outP = [[p.copy() for p in wp[0]]]
    outC = [wcam[0].copy()]
    hops = []
    for k in range(1, len(wp)):
        plo, phi = windows[k - 1]
        lo, hi = windows[k]
        src, dst = [], []
        for g in range(max(lo, plo), min(hi, phi)):
            a, b = wp[k][g - lo], outP[k - 1][g - plo]
            i = rng.choice(len(a), min(2000, len(a)), replace=False)
            src.append(a[i]); dst.append(b[i])
        s, R, t, inl, _ = robust_sim3_from_pairs(np.concatenate(src), np.concatenate(dst))
        outP.append([(s * (R @ p.T).T + t) for p in wp[k]])
        outC.append(s * (R @ wcam[k].T).T + t)
        hops.append((s, inl))
    return outP, outC, hops


def stats(err, label, extra=""):
    t = len(err) // 3
    print(f"  {label:34s} median {np.median(err):7.3f} m   p95 {np.percentile(err,95):7.3f} m"
          f"   growth {np.median(err[-t:])/max(np.median(err[:t]),1e-9):5.2f}x  {extra}")
    return float(np.median(err))


def main():
    rng = np.random.default_rng(11)
    cams, truth = build(rng)
    windows = plan_windows(N_VIEWS, WINDOW, OVERLAP)
    passes = sum(b - a for a, b in windows)

    wp, wcam = [], []
    for (a, b) in windows:
        s, R, t = yaw_sim3(rng)
        wp.append([(s * (R @ truth[g].T).T + t) + rng.normal(0, POINT_NOISE_M, (PER_VIEW, 3))
                   for g in range(a, b)])
        wcam.append(s * (R @ cams[a:b].T).T + t)

    gnss = (cams + np.cumsum(rng.normal(0, BIAS_STEP_M, (N_VIEWS, 3)), 0)
            + rng.normal(0, GNSS_SIGMA_M, (N_VIEWS, 3)))
    ref = np.concatenate([truth[g] for (a, b) in windows for g in range(a, b)], 0)

    print("=" * 88)
    print(f"EXP-13  windowed reconstruction of a {N_VIEWS}-view pass")
    print("=" * 88)
    print(f"  {len(windows)} windows of {WINDOW} (overlap {OVERLAP}), {len(windows)-1} hops")
    print(f"  inference cost {passes} view-passes vs {N_VIEWS} un-windowed "
          f"({passes/N_VIEWS:.2f}x) - the price of never exceeding {WINDOW} views at once")
    print(f"  GNSS 1-sigma {GNSS_SIGMA_M} m white + a {BIAS_STEP_M} m/step correlated bias")
    print(f"  point noise {POINT_NOISE_M} m - the floor every number below is measured against\n")

    outP, outC, hops = chain(wp, wcam, windows, rng)
    P = np.concatenate([p for w in outP for p in w], 0)
    print(f"  per-hop scale {min(h[0] for h in hops):.4f}-{max(h[0] for h in hops):.4f}, "
          f"worst inlier fraction {min(h[1] for h in hops):.1%}\n")

    # A - chain only. Shape is excellent; absolute position is undefined, because the
    # chain has no anchor at all. Reporting an absolute number for it would be
    # meaningless, so it is reported after a single global alignment - which is exactly
    # the absolute-vs-aligned distinction eval3d/metrics.py exists to keep honest.
    i = rng.choice(len(P), 20000, replace=False)
    from pipeline.window_fuse import sim3_from_pairs
    s, R, t = sim3_from_pairs(P[i], ref[i])
    a_med = stats(np.linalg.norm((s * (R @ P.T).T + t) - ref, axis=1),
                  "A  chain only, SHAPE (aligned)", "<- no absolute frame at all")

    # B - per-window GNSS anchor. Independent fits, so no accumulation, but each fit
    # sees only WINDOW views: 24 m of baseline against 1.5 m of noise cannot determine
    # scale, and the scale estimate wanders by tens of percent.
    outB, sc = [], []
    for k, (lo, hi) in enumerate(windows):
        R2, t2, s2 = robust_yaw_sim3(wcam[k], gnss[lo:hi], with_scale=True)[:3]
        sc.append(s2)
        outB.append([apply_transform(p, R2, t2, s2) for p in wp[k]])
    b_med = stats(np.linalg.norm(np.concatenate([p for w in outB for p in w], 0) - ref, axis=1),
                  "B  per-window anchor, ABSOLUTE",
                  f"scale {min(sc):.3f}-{max(sc):.3f} over 24 m of baseline")

    # C - chain for shape, then ONE anchor over the whole pass. Scale is now solved
    # against 600 m of baseline instead of 24 m.
    cam_world = np.zeros((N_VIEWS, 3)); seen = np.zeros(N_VIEWS, bool)
    for k, (lo, hi) in enumerate(windows):
        for j, g in enumerate(range(lo, hi)):
            if not seen[g]:
                cam_world[g] = outC[k][j]; seen[g] = True
    R3, t3, s3 = robust_yaw_sim3(cam_world, gnss, with_scale=True)[:3]
    crms = float(np.sqrt(((apply_transform(cam_world, R3, t3, s3) - gnss) ** 2).sum(1).mean()))
    c_med = stats(np.linalg.norm(apply_transform(P, R3, t3, s3) - ref, axis=1),
                  "C  chain + ONE anchor, ABSOLUTE",
                  f"scale {s3:.4f}, camera RMS {crms:.2f} m")

    print(f"\n  C beats B by {b_med/c_med:.2f}x, and the difference is baseline alone:")
    print(f"  the same GNSS, the same estimator, {WINDOW} m of it versus {N_VIEWS} m.")
    print(f"\n  The absolute floor is GNSS, not the reconstruction: shape is good to "
          f"{a_med*100:.1f} cm")
    print(f"  while the best absolute result is {c_med:.2f} m. Consumer GNSS cannot reach")
    print(f"  the PS's 1 m; RTK can, and the ingest already reports which one it has.")


if __name__ == "__main__":
    main()
