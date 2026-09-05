"""
T-SCALE-01 - does windowed stitching recover one frame, or does it drift?

The claim under test is that a long pass can be reconstructed in overlapping windows
and reassembled without accumulating error. That is a claim about DRIFT, so the test
has to be long enough to drift: 128 views across 20 hops, each window observing the
scene in its own arbitrary similarity frame, is where a rigid-only fit or a
first-window anchor visibly fails.
"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline.window_fuse import plan_windows, stitch


def rand_sim3(rng, scale_sigma=0.06):
    Q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    if np.linalg.det(Q) < 0:
        Q[:, 0] *= -1
    return float(np.exp(rng.normal(0, scale_sigma))), Q, rng.normal(0, 2.0, 3)


def main():
    rng = np.random.default_rng(7)
    N_VIEWS, PER_VIEW, W, O = 128, 900, 24, 8

    truth = []
    for v in range(N_VIEWS):                       # a corridor of structure along +X
        x = rng.uniform(v * 1.0, v * 1.0 + 6.0, PER_VIEW)
        z = rng.uniform(-5, 5, PER_VIEW)
        y = -np.exp(-((z / 2.0) ** 2)) * 2.0 + 0.15 * np.sin(x)
        truth.append(np.stack([x, y, z], 1))

    windows = plan_windows(N_VIEWS, W, O)
    passes = sum(b - a for a, b in windows)
    print(f"{N_VIEWS} views -> {len(windows)} windows of {W} (overlap {O})")
    print(f"inference cost {passes} view-passes vs {N_VIEWS} un-windowed "
          f"({passes/N_VIEWS:.2f}x) - the price of never exceeding {W} views at once")

    wp, wc, gts = [], [], []
    for (a, b) in windows:                         # each window in its OWN frame
        s, R, t = rand_sim3(rng); gts.append((s, R, t))
        wp.append([(s * (R @ truth[g].T).T + t) + rng.normal(0, 0.01, (PER_VIEW, 3))
                   for g in range(a, b)])
        wc.append([rng.uniform(0.3, 1.0, PER_VIEW) for _ in range(a, b)])

    print()
    fused, rep = stitch(wp, windows, conf=wc)

    s0, R0, t0 = gts[0]                            # truth expressed in window 0's frame
    ref = np.concatenate([s0 * (R0 @ truth[g].T).T + t0
                          for (a, b) in windows for g in range(a, b)], 0)
    err = np.linalg.norm(fused - ref, axis=1)
    third = len(err) // 3
    first_m, last_m = np.median(err[:third]), np.median(err[-third:])
    drift = last_m / max(first_m, 1e-9)

    print(f"\nresidual vs truth   median {np.median(err):.4f}   p95 {np.percentile(err,95):.4f}")
    print(f"first third {first_m:.4f}   last third {last_m:.4f}   drift {drift:.2f}x")
    scales = [r['scale'] for r in rep]
    print(f"per-hop scale       min {min(scales):.4f}  max {max(scales):.4f}")
    print(f"worst inlier frac   {min(r['inlier_frac'] for r in rep):.1%}")
    print(f"worst hop residual  {max(r['residual_rms'] for r in rep):.5f}")

    ok = np.median(err) < 0.05 and drift < 3.0
    print("\nT-SCALE-01", "PASS" if ok else "FAIL",
          "- noise floor is 0.01 per point by construction")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
