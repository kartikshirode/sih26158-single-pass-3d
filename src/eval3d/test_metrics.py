"""
Self-tests for eval3d.metrics with analytically known answers.

Run:  python src/eval3d/test_metrics.py
"""
import sys, os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eval3d.metrics import (  # noqa: E402
    evaluate, nn_distances, umeyama, apply_transform, rotation_angle_deg, summarise
)

RNG = np.random.default_rng(42)
FAILED = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def make_ground(n=4000, extent=50.0):
    """A near-flat ground sheet. Horizontally featureless by construction."""
    pts = RNG.uniform([-extent, -extent, 0], [extent, extent, 0], size=(n, 3))
    pts[:, 2] = 0.1 * np.sin(pts[:, 0] / 10) + 0.1 * np.cos(pts[:, 1] / 10)
    return pts


def make_building(cx, cy, w, d, h, n=1500):
    """A box with sampled roof AND vertical walls - this is what constrains alignment."""
    out = np.empty((n, 3))
    face = RNG.integers(0, 5, size=n)
    u, v = RNG.random(n), RNG.random(n)
    out[:, 0] = np.where(face == 0, cx - w / 2 + u * w,
                np.where(face == 1, cx - w / 2,
                np.where(face == 2, cx + w / 2, cx - w / 2 + u * w)))
    out[:, 1] = np.where(face == 0, cy - d / 2 + v * d,
                np.where(face <= 2, cy - d / 2 + u * d,
                np.where(face == 3, cy - d / 2, cy + d / 2)))
    out[:, 2] = np.where(face == 0, h, v * h)
    return out


def make_scene(n=4000):
    """
    An urban-like scene with genuine vertical structure.

    Alignment tests MUST use a scene with vertical walls. A ground-dominated scene
    has a horizontal sliding ambiguity (see T2b) and cannot constrain a rigid fit.
    """
    return np.vstack([
        make_ground(n),
        make_building(-25, -20, 14, 10, 18, 2500),
        make_building(20, 15, 10, 16, 25, 2500),
        make_building(0, 30, 20, 8, 9, 2500),
    ])


print("\n=== T1: identical clouds -> zero error, perfect scores ===")
gt = make_scene()
r = evaluate(gt.copy(), gt, align=True)
check("absolute accuracy RMSE == 0", r["absolute"].accuracy.rmse < 1e-9,
      f"got {r['absolute'].accuracy.rmse:.2e}")
check("absolute completeness RMSE == 0", r["absolute"].completeness.rmse < 1e-9)
s1 = [s for s in r["absolute"].scores if s.tau == 1.0][0]
check("precision == 1.0", abs(s1.precision - 1.0) < 1e-12)
check("recall == 1.0", abs(s1.recall - 1.0) < 1e-12)
check("F == 1.0", abs(s1.fscore - 1.0) < 1e-12)


print("\n=== T2: known translation -> absolute sees it, aligned removes it ===")
OFFSET = np.array([3.0, -4.0, 0.0])          # magnitude exactly 5.0 m
shifted = gt + OFFSET
r = evaluate(shifted, gt, align=True)
# Absolute error must reveal the offset. (NN distance <= 5 because the sheet is
# broad and a shifted point finds a different nearby GT point; but it must be large.)
check("absolute RMSE is large (offset detected)", r["absolute"].accuracy.rmse > 0.5,
      f"got {r['absolute'].accuracy.rmse:.3f} m")
check("aligned RMSE much smaller than absolute",
      r["aligned"].accuracy.rmse < r["absolute"].accuracy.rmse,
      f"aligned {r['aligned'].accuracy.rmse:.4f} < absolute {r['absolute'].accuracy.rmse:.4f}")
check("recovered translation ~= 5.0 m",
      abs(r["aligned"].alignment_translation_m - 5.0) < 0.6,
      f"got {r['aligned'].alignment_translation_m:.4f} m (true 5.0)")


print("\n=== T2b: DOCUMENTED LIMITATION - flat terrain slides under ICP ===")
# A ground-only scene is horizontally featureless, so a rigid fit cannot recover a
# horizontal offset: the plane slides freely. This is a property of the geometry, not
# a bug. It is exactly why R-O3 must be judged on the ABSOLUTE metric, and why
# georeferencing must come from GPS rather than from post-hoc alignment to a DSM.
ground = make_ground(6000)
rg = evaluate(ground + OFFSET, ground, align=True)
recovered_flat = rg["aligned"].alignment_translation_m
check("flat scene under-recovers the true 5 m offset (sliding ambiguity)",
      recovered_flat < 2.5,
      f"recovered only {recovered_flat:.3f} m of 5.0 m -> aligned metric is "
      f"NOT trustworthy on flat scenes")
check("but the ABSOLUTE metric still reports the error honestly",
      rg["absolute"].accuracy.rmse > 0.4,
      f"absolute RMSE {rg['absolute'].accuracy.rmse:.3f} m")


print("\n=== T3: umeyama recovers a known similarity transform exactly ===")
theta = np.radians(23.0)
R_true = np.array([[np.cos(theta), -np.sin(theta), 0],
                   [np.sin(theta),  np.cos(theta), 0],
                   [0, 0, 1.0]])
t_true = np.array([12.0, -7.0, 3.0])
s_true = 1.35
src = make_scene(1500)
dst = apply_transform(src, R_true, t_true, s_true)
R, t, s = umeyama(src, dst, with_scale=True)
check("rotation recovered", np.allclose(R, R_true, atol=1e-8),
      f"angle err {abs(rotation_angle_deg(R) - 23.0):.2e} deg")
check("translation recovered", np.allclose(t, t_true, atol=1e-6))
check("scale recovered", abs(s - s_true) < 1e-9, f"got {s:.10f} vs {s_true}")


print("\n=== T4: reflection guard (degenerate/planar input must not mirror) ===")
planar = RNG.uniform([-10, -10, 0], [10, 10, 0], size=(800, 3))
planar[:, 2] = 0.0
R, t, s = umeyama(planar, planar, with_scale=True)
check("det(R) == +1 (no reflection)", np.linalg.det(R) > 0.99,
      f"det={np.linalg.det(R):.6f}")


print("\n=== T5: partial reconstruction -> recall drops, precision stays high ===")
# Reconstruct only half the scene: we missed a lot, but what we built is correct.
partial = gt[gt[:, 0] < 0]
r = evaluate(partial, gt, align=False)
s1 = [s for s in r["absolute"].scores if s.tau == 1.0][0]
check("precision stays high (what we built is right)", s1.precision > 0.99,
      f"precision {s1.precision:.4f}")
check("recall drops (we missed half)", s1.recall < 0.65, f"recall {s1.recall:.4f}")
check("F between the two", s1.precision > s1.fscore > s1.recall,
      f"P {s1.precision:.3f} > F {s1.fscore:.3f} > R {s1.recall:.3f}")


print("\n=== T6: known noise -> RMSE matches the injected sigma ===")
SIGMA = 0.30
noisy = gt + RNG.normal(0, SIGMA, gt.shape)
d = nn_distances(noisy, gt)
# NN distance to a dense cloud underestimates true per-point noise, so we assert a
# band rather than equality - the point is that it tracks sigma, not that it equals it.
check("RMSE responds to injected noise", 0.05 < float(np.sqrt(np.mean(d**2))) < 3 * SIGMA,
      f"RMSE {np.sqrt(np.mean(d**2)):.4f} m for sigma={SIGMA}")


print("\n=== T7: threshold monotonicity (tau up -> scores never decrease) ===")
noisy2 = gt + RNG.normal(0, 0.6, gt.shape)
r = evaluate(noisy2, gt, align=False, taus=(0.25, 0.5, 1.0, 2.0))
fs = [s.fscore for s in r["absolute"].scores]
check("F-score is non-decreasing in tau", all(a <= b + 1e-12 for a, b in zip(fs, fs[1:])),
      " ".join(f"{f:.3f}" for f in fs))


print("\n=== T8: end-to-end report renders and verdicts correctly ===")
good = gt + RNG.normal(0, 0.05, gt.shape)     # well within 1 m
r = evaluate(good, gt, align=True)
txt = summarise(r, tau=1.0)
check("report contains PASS for a sub-metre model", "PASS" in txt,
      f"absolute RMSE {r['absolute'].accuracy.rmse:.4f} m")
bad = gt + np.array([25.0, 0.0, 0.0])         # 25 m off - must fail
r2 = evaluate(bad, gt, align=True)
check("report contains FAIL for a 25 m-offset model", "FAIL" in summarise(r2, tau=1.0),
      f"absolute RMSE {r2['absolute'].accuracy.rmse:.4f} m")


print("\n" + "=" * 62)
if FAILED:
    print(f"{len(FAILED)} TEST(S) FAILED: {FAILED}")
    sys.exit(1)
print("ALL TESTS PASSED")
print("=" * 62)
