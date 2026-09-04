"""
EXP-05 - Achievable georeferencing accuracy vs GNSS quality.

Answers the central question of SIH26158 before any GPU is available:

    R-O3 demands <= 1 m spatial accuracy with no GCPs.
    Is that physically reachable from the GPS a drone actually carries?

Run:  python src/experiments/exp05_gps_noise.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from eval3d.gnss import (  # noqa: E402
    CONSUMER_GNSS, SBAS_GNSS, RTK_GNSS, GnssSpec,
    georeference_error, straight_pass, simulate_gnss_error,
)

TRIALS = 40
FPS_KEYFRAME = 1.0          # ~600 keyframes over a 600 s flight -> ~1 Hz
N_KEYFRAMES = 600
FLIGHT_S = 600.0
DT = FLIGHT_S / N_KEYFRAMES


def run(spec: GnssSpec, n=N_KEYFRAMES, use_ransac=True, trials=TRIALS):
    out = []
    for k in range(trials):
        rng = np.random.default_rng(1000 + k)
        traj = straight_pass(n, rng=rng)
        out.append(georeference_error(n, FLIGHT_S / n, spec, traj, rng,
                                      use_ransac=use_ransac))
    agg = {}
    for key in out[0]:
        agg[key] = float(np.mean([o[key] for o in out]))
    agg["rmse_3d_p95_over_trials"] = float(np.percentile([o["rmse_3d"] for o in out], 95))
    return agg


def bar(v, scale=8.0, width=34):
    n = min(width, int(round(v / scale * width)))
    return "#" * n


print("=" * 88)
print("EXP-05  Achievable ABSOLUTE georeferencing accuracy (no GCPs)")
print(f"         single straight pass, {N_KEYFRAMES} keyframes over {FLIGHT_S:.0f} s, "
      f"{TRIALS} trials each")
print("=" * 88)

print("\n--- 1. Error by GNSS class (RANSAC + Umeyama, 2% wild fixes injected) ---\n")
print(f"{'GNSS class':<12} {'RMSE 3D':>9} {'RMSE H':>9} {'RMSE V':>9} "
      f"{'p95 3D':>9} {'scale ppm':>10}  R-O3?")
results = {}
for spec in (CONSUMER_GNSS, SBAS_GNSS, RTK_GNSS):
    r = run(spec)
    results[spec.name] = r
    verdict = "PASS" if r["rmse_3d"] <= 1.0 else "FAIL"
    print(f"{spec.name:<12} {r['rmse_3d']:>8.3f}m {r['rmse_h']:>8.3f}m "
          f"{r['rmse_v']:>8.3f}m {r['p95_3d']:>8.3f}m {r['scale_err_ppm']:>9.1f}  {verdict}")

print("\n--- 2. Does averaging more frames fix it?  (consumer GNSS) ---\n")
print(f"{'keyframes':>10} {'RMSE 3D':>10}   {'1/sqrt(N) would predict':>24}")
base = None
for n in (50, 150, 300, 600, 1200, 2400):
    r = run(CONSUMER_GNSS, n=n, trials=25)
    if base is None:
        base, base_n = r["rmse_3d"], n
    predicted = base * np.sqrt(base_n / n)
    print(f"{n:>10} {r['rmse_3d']:>9.3f}m   {predicted:>23.3f}m   {bar(r['rmse_3d'])}")

print("""
    Reading: the measured error is FLAT while the 1/sqrt(N) column keeps falling.
    The correlated bias (ionosphere / multipath / orbit) does not average away over a
    single 10-minute flight. Collecting more frames does NOT buy absolute accuracy.
""")

print("--- 3. What does RANSAC actually buy?  (measured across outlier rates) ---\n")
print("    Naive expectation: 'RANSAC is more accurate.' The data says otherwise.\n")
print(f"{'outlier %':>10} {'least squares':>15} {'auto-RANSAC':>13} {'gain':>8}")
_lsq_curve = []
for frac in (0.0, 0.02, 0.05, 0.10, 0.20, 0.35):
    ls_r, rs_r = [], []
    for k in range(20):
        rng = np.random.default_rng(3000 + k)
        traj = straight_pass(N_KEYFRAMES, rng=rng)
        ls_r.append(georeference_error(N_KEYFRAMES, DT, CONSUMER_GNSS, traj, rng,
                                       outlier_frac=frac, use_ransac=False)["rmse_3d"])
        rng = np.random.default_rng(3000 + k)
        traj = straight_pass(N_KEYFRAMES, rng=rng)
        rs_r.append(georeference_error(N_KEYFRAMES, DT, CONSUMER_GNSS, traj, rng,
                                       outlier_frac=frac, use_ransac=True)["rmse_3d"])
    ls, rs = float(np.mean(ls_r)), float(np.mean(rs_r))
    _lsq_curve.append((frac, ls, rs))
    print(f"{frac*100:>9.0f}% {ls:>14.3f}m {rs:>12.3f}m {100*(1-rs/ls):>7.1f}%")

print("""
    Reading: RANSAC does NOT improve the typical case - at 0-2% bad fixes it is a
    fraction of a percent WORSE, because robustness always costs a little efficiency.
    What it does is BOUND THE WORST CASE: its error stays flat near 4.1 m however bad
    the GPS gets, while least squares degrades without limit. For a system whose input
    dataset is unknown until the day, a bounded worst case is the property worth
    buying. (R-C5)

    Second, harder-won lesson: the inlier threshold must be derived from the observed
    residual scale (MAD), not hard-coded. A threshold BELOW the noise floor is worse
    than no RANSAC at all - a fixed 1 m threshold scored 5.29 m vs 4.08 m for plain
    least squares, because it discarded 93% of perfectly good data to fit a lucky
    subset. See the table in eval3d.gnss.robust_sim3.""")

print("\n--- 4. Two reporting traps, in opposite directions ---\n")
r = results["consumer"]

# Trap A: the fit residual. Note it is LARGER, not smaller, than the true error.
print(f"  (a) residual of the fit TO THE GPS TRACK : {r['residual_to_gps']:.3f} m")
print(f"      true error vs GROUND TRUTH          : {r['rmse_3d']:.3f} m")
print("""      -> The residual is PESSIMISTIC, not flattering: it charges us for the
         GPS's own scatter about its mean. Fitting to a noisy sensor and then
         measuring against that same noisy sensor double-counts the noise. So
         "our residual is 6.7 m" understates the system - but it is still the
         wrong number to quote, because it measures agreement with the sensor
         rather than with reality.""")

# Trap B: the aligned metric. THIS is the one that flatters.
_rng = np.random.default_rng(7)
_traj = straight_pass(N_KEYFRAMES, rng=_rng)
from eval3d.metrics import evaluate  # noqa: E402
_placed = _traj + np.array([3.0, 2.0, 1.5])          # a 3.9 m georeferencing offset
_ev = evaluate(_placed, _traj, align=True)
print(f"\n  (b) ABSOLUTE error (no alignment) : "
      f"{_ev['absolute'].accuracy.rmse:.3f} m   <- the truth")
print(f"      ALIGNED error (after ICP)     : "
      f"{_ev['aligned'].accuracy.rmse:.3f} m   <- flattering")
print("""      -> THIS is the dangerous one. Best-fit alignment silently absorbs the
         entire georeferencing offset, so a model tens of metres out of place
         can report near-zero error. Every accuracy claim must state which of
         the two it is. The harness always prints both.
""")

print("--- 5. Sensitivity: is the conclusion robust to the assumed bias? ---\n")
print(f"{'bias sigma':>11} {'RMSE 3D':>10}  R-O3?")
for bs in (0.5, 1.0, 1.5, 2.2, 3.5, 5.0):
    spec = GnssSpec("sweep", bias_sigma=bs, bias_tau_s=300.0,
                    walk_psd=0.010, white_sigma=0.8)
    r = run(spec, trials=20)
    print(f"{bs:>10.1f}m {r['rmse_3d']:>9.3f}m  "
          f"{'PASS' if r['rmse_3d'] <= 1.0 else 'FAIL'}   {bar(r['rmse_3d'])}")

print(f"""
{'=' * 88}
CONCLUSION (EXP-05)
{'=' * 88}
  1. With consumer GNSS, absolute georeferencing error is ~{results['consumer']['rmse_3d']:.1f} m.
     R-O3's <= 1 m is NOT achievable from consumer GPS alone, at ANY frame count.
     The limit is the sensor, not the algorithm. No amount of clever fitting fixes it.

  2. With RTK/PPK (PS input R-I7, "optional"), error is
     ~{results['rtk']['rmse_3d']:.3f} m -> R-O3 PASSES comfortably.
     Whether we can claim <= 1 m absolute depends ENTIRELY on whether the supplied
     dataset carries RTK corrections. This must be asked of the organisers (A2/A4).

  3. Vertical error is consistently the worst axis (~1.7x horizontal), so the
     altitude channel governs the budget. Barometric altitude (R-I5) is worth fusing.

  4. Therefore the system reports TWO numbers, always:
       - relative / shape accuracy   -> achievable well below 1 m, and is what
                                        "accuracy without GCPs" normally means
       - absolute georeferencing     -> GNSS-class limited, reported truthfully
     Reporting only the flattering one is the failure mode this experiment exists
     to prevent.
{'=' * 88}""")
