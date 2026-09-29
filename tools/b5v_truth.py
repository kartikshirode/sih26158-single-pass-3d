"""Absolute error of a georeferenced synthetic run (B3 or B5v) against the scene it shows.

python tools/b5v_truth.py out/runs/<run> [--frames 600]    -> out/runs/<run>/truth.json

The scene is rebuilt from make_test_video's defaults (seed 7, 110 m, 60 degrees down,
site 28.6139, 77.2090 at 250 m), so the run must come from a clip rendered with them.
--frames is the clip's rendered frame count: 600 for B5v, whatever --seconds x --fps gave
for B3. Errors are also given in ground sample distances at the image centre, the unit
vendors quote accuracy in (Pix4D and DJI Terra: 1 to 2 GSD with RTK).
"""
import argparse
import json
import os
import sys

import numpy as np
from scipy.spatial import cKDTree

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
from simscene.scene import Camera, SceneSpec, build_scene, single_pass  # noqa: E402
from eval3d.gnss import geodetic_to_enu  # noqa: E402
from src.tesseract.stages import _apply_frame_json, _enu_to_geodetic  # noqa: E402

SITE = (28.6139, 77.2090, 250.0)
ALT, PITCH = 110.0, 60.0

ap = argparse.ArgumentParser()
ap.add_argument("run")
ap.add_argument("--frames", type=int, default=600)
a = ap.parse_args()
tf = json.load(open(os.path.join(a.run, "georef.json")))
lat0, lon0 = tf["enu_reference"]["latitude"], tf["enu_reference"]["longitude"]


def to_ours(X):
    """Scene ENU (about SITE) to the run's ENU (about the first fix, take-off at z = 0)."""
    la, lo, h = _enu_to_geodetic(X, *SITE)
    return np.asarray(geodetic_to_enu(la, lo, h - SITE[2], lat0, lon0, 0.0))


scene = build_scene(SceneSpec(seed=7))
pos, _ = single_pass(scene, n_frames=a.frames, alt=ALT, pitch_deg=PITCH)
kf = np.asarray(json.load(open(os.path.join(a.run, "ingest.json")))["keyframes"])
cams = np.load(os.path.join(a.run, "cameras.npy"))
ok = np.isfinite(cams.reshape(len(cams), -1)).all(1)
dc = _apply_frame_json(cams[ok][:, :3, 3], tf) - to_ours(pos[kf[ok]])
P = np.load(os.path.join(a.run, "points_geo.npy")).astype(np.float64)
S = to_ours(scene.mesh.sample(3_000_000))
sel = np.random.default_rng(0).choice(len(P), min(len(P), 200_000), replace=False)
d, _ = cKDTree(S).query(P[sel])
gsd = ALT / np.sin(np.radians(PITCH)) / Camera(width=1920, height=1080).fx   # slant range / focal
rms_c = float(np.sqrt((dc ** 2).sum(1).mean()))
res = {
    "cameras": int(ok.sum()),
    "gsd_centre_m": round(float(gsd), 4),
    "camera_error_m": {"rms_3d": round(rms_c, 3),
                       "mean_offset_enu": np.round(dc.mean(0), 3).tolist(),
                       "rms_horizontal": round(float(np.sqrt((dc[:, :2] ** 2).sum(1).mean())), 3),
                       "rms_vertical": round(float(np.sqrt((dc[:, 2] ** 2).mean())), 3),
                       "rms_3d_gsd": round(rms_c / gsd, 2)},
    "cloud_to_truth_m": {"median": round(float(np.median(d)), 3),
                         "rmse": round(float(np.sqrt((d ** 2).mean())), 3),
                         "p90": round(float(np.percentile(d, 90)), 3),
                         "p95": round(float(np.percentile(d, 95)), 3),
                         "within_1m": round(float((d < 1.0).mean()), 4),
                         "median_gsd": round(float(np.median(d)) / gsd, 2)},
}
print(json.dumps(res, indent=1))
json.dump(res, open(os.path.join(a.run, "truth.json"), "w"), indent=1)
