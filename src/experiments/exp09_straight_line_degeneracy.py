"""
EXP-09 - The straight-line degeneracy, and why "IMU optional" is misleading.

THE FINDING, in one sentence: a single straight pass cannot constrain rotation about
the flight axis, so an unrestricted Sim(3) georeferencing fit looks excellent on the
trajectory and is catastrophic on the scene - and a GPS upgrade does not help at all.

This is the most consequential result in the project. It was found by the end-to-end
pipeline producing a 201 m error that the trajectory-only experiment (EXP-05) had said
should be ~4 m. EXP-05 was not wrong; it was measuring the wrong thing.

Run:  python src/experiments/exp09_straight_line_degeneracy.py
"""
import os
import sys

import numpy as np
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from simscene.scene import build_scene, SceneSpec, single_pass          # noqa: E402
from eval3d.metrics import apply_transform                              # noqa: E402
from eval3d.gnss import (                                               # noqa: E402
    CONSUMER_GNSS, SBAS_GNSS, RTK_GNSS, simulate_gnss_error,
    robust_sim3, robust_yaw_sim3,
)

N = 600
TRIALS = 12

scene = build_scene(SceneSpec(seed=7))
pts, _ = trimesh.sample.sample_surface(scene.mesh, 20_000, seed=1)
pts = np.asarray(pts)


def trial(spec, fitter, seed, curved=False):
    rng = np.random.default_rng(seed)
    pos, _ = single_pass(scene, n_frames=N, alt=110.0, pitch_deg=60.0)
    if curved:
        # bend the path into a gentle arc - enough to break collinearity
        t = np.linspace(-1, 1, N)
        pos = pos.copy()
        pos[:, 1] += 120.0 * (t ** 2 - 0.33)
    gps = pos + simulate_gnss_error(N, 1.0, spec, rng)
    nb = max(1, int(N * 0.02))
    gps[rng.choice(N, nb, replace=False)] += rng.normal(0, 25.0, (nb, 3))

    th = rng.uniform(0, 2 * np.pi)
    Ra = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1.0]])
    ta = rng.uniform(-400, 400, 3)

    R, t_, s, _ = fitter(apply_transform(pos, Ra, ta, 1.0), gps, rng=rng)
    traj_err = np.linalg.norm(
        apply_transform(apply_transform(pos, Ra, ta, 1.0), R, t_, s) - pos, axis=1)
    scene_err = np.linalg.norm(
        apply_transform(apply_transform(pts, Ra, ta, 1.0), R, t_, s) - pts, axis=1)
    return (float(np.sqrt(np.mean(traj_err ** 2))),
            float(np.sqrt(np.mean(scene_err ** 2))))


print("=" * 82)
print("EXP-09  Straight-line degeneracy in single-pass georeferencing")
print("=" * 82)

print("\n--- 1. Trajectory error vs SCENE error, straight pass ---\n")
print(f"{'GNSS':<10}{'fit':<24}{'trajectory RMSE':>17}{'SCENE RMSE':>14}   R-O3")
rows = {}
for gname, spec in (("consumer", CONSUMER_GNSS), ("sbas", SBAS_GNSS), ("rtk", RTK_GNSS)):
    for fname, fn in (("full Sim(3), 7-DOF", robust_sim3),
                      ("yaw-only (gravity)", robust_yaw_sim3)):
        tr = [trial(spec, fn, 500 + k) for k in range(TRIALS)]
        t_rmse = float(np.mean([a for a, _ in tr]))
        s_rmse = float(np.mean([b for _, b in tr]))
        rows[(gname, fname)] = (t_rmse, s_rmse)
        verdict = "PASS" if s_rmse <= 1.0 else "FAIL"
        print(f"{gname:<10}{fname:<24}{t_rmse:>16.3f}m{s_rmse:>13.3f}m   {verdict}")

print(f"""
    Read the RTK row twice. Under an unrestricted 7-DOF fit, RTK gets the TRAJECTORY to
    {rows[('rtk','full Sim(3), 7-DOF')][0]:.3f} m - essentially perfect - while the SCENE is still
    {rows[('rtk','full Sim(3), 7-DOF')][1]:.0f} m out. Centimetre GPS buys nothing here
    ({rows[('rtk','full Sim(3), 7-DOF')][1]:.0f} m vs {rows[('consumer','full Sim(3), 7-DOF')][1]:.0f} m
    for consumer - the same order, and the ordering flips between seeds). That is the
    signature of a DEGENERACY rather than of noise: the error lives in a direction the
    data does not constrain, so improving the data does not touch it. No GPS upgrade
    fixes an under-determined system.""")

print("\n--- 2. Error grows with distance from the flight line ---\n")
rng = np.random.default_rng(500)
pos, _ = single_pass(scene, n_frames=N, alt=110.0, pitch_deg=60.0)
gps = pos + simulate_gnss_error(N, 1.0, CONSUMER_GNSS, rng)
th = rng.uniform(0, 2 * np.pi)
Ra = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1.0]])
ta = rng.uniform(-400, 400, 3)
print(f"{'cross-track band':<22}{'full Sim(3)':>14}{'yaw-only':>12}")
for fname, fn in (("full", robust_sim3), ("yaw", robust_yaw_sim3)):
    R, t_, s, _ = fn(apply_transform(pos, Ra, ta, 1.0), gps, rng=np.random.default_rng(1))
    e = np.linalg.norm(apply_transform(apply_transform(pts, Ra, ta, 1.0), R, t_, s) - pts, axis=1)
    globals()[f"err_{fname}"] = e
d = np.abs(pts[:, 1])
for lo, hi in ((0, 25), (25, 75), (75, 150), (150, 300), (300, 500)):
    m = (d >= lo) & (d < hi)
    if m.any():
        print(f"  {lo:>3d}-{hi:>3d} m from line   "
              f"{np.sqrt(np.mean(err_full[m]**2)):>12.1f}m"
              f"{np.sqrt(np.mean(err_yaw[m]**2)):>11.2f}m")

print("\n--- 3. Does a non-straight flight fix it? ---\n")
print(f"{'flight path':<22}{'full Sim(3) SCENE':>20}{'yaw-only SCENE':>17}")
for label, curved in (("straight (the PS)", False), ("gently curved", True)):
    f_ = float(np.mean([trial(CONSUMER_GNSS, robust_sim3, 700 + k, curved)[1]
                        for k in range(TRIALS)]))
    y_ = float(np.mean([trial(CONSUMER_GNSS, robust_yaw_sim3, 700 + k, curved)[1]
                        for k in range(TRIALS)]))
    print(f"{label:<22}{f_:>19.2f}m{y_:>16.2f}m")

print(f"""
{'=' * 82}
CONCLUSION (EXP-09)
{'=' * 82}
  1. THE PROBLEM STATEMENT'S DEFINING CONSTRAINT CREATES A GEOMETRIC DEGENERACY.
     "Single pass" means near-collinear camera centres. Collinear points cannot
     constrain rotation about their own axis. Georeferencing a SCENE from such a
     trajectory with an unrestricted similarity transform is ill-posed - and the
     failure is invisible if you only measure trajectory error, which is exactly what
     a naive evaluation does.

  2. THE FIX IS PHYSICAL, NOT NUMERICAL. Roll and pitch are not unknown: gravity fixes
     them. Constraining the fit to yaw + translation + scale (5 DOF) removes the free
     direction and collapses scene error from hundreds of metres to
     {rows[('consumer','yaw-only (gravity)')][1]:.1f} m (consumer) and
     {rows[('rtk','yaw-only (gravity)')][1]:.3f} m (RTK) - the latter comfortably inside R-O3.

  3. THEREFORE "IMU: optional" IN THE PROBLEM STATEMENT IS MISLEADING.
     For a single straight pass a vertical reference is NOT optional - without it the
     problem is under-determined. The reference can come from the IMU (R-I4), from
     gravity via the terrain, or from the gimbal attitude in the video metadata, but it
     must come from somewhere. This is worth saying explicitly to the evaluators.

  4. A CURVED FLIGHT PATH WOULD ALSO FIX IT, and the contrast is the proof that this is
     a degeneracy rather than a bug - but we do not control the flight, so the gravity
     constraint is the only lever available on our side.
{'=' * 82}""")
