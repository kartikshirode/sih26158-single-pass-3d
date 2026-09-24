"""Small read-only checks for the core audit findings."""

import sys

import numpy as np

sys.path.insert(0, "src")

from eval3d.gnss import yaw_only_sim3
from eval3d.metrics import apply_transform
from pipeline.colmap_export import full_frame_camera
from tesseract.pipeline import Context, State
from tesseract.stages import Scale, Verdicts


class Input:
    def __init__(self, digest):
        self.digest = digest

    def inputs(self):
        return [{"sha256": self.digest}]


state = State("audit/codex/nonexistent-state.json")
a = Context("same-run", "unused", Input("first"))
b = Context("same-run", "unused", Input("second"))
print("source changed, scale cache key equal:", state.key(Scale(), a) == state.key(Scale(), b))

ctx = Context(
    "example", "unused", None,
    facts={
        "points": 100,
        "exports": ["ply", "las", "geotiff"],
        "recall_at_1m_observable": 0.95,
        "recall_at_1m_whole_scene": 0.40,
        "geometry_provider": "sense",
    },
    spent_s=100,
    budget_s=900,
)
verdicts = Verdicts().execute(ctx).facts["verdicts"]
for key in ("R-O2 processing time", "R-O4 coverage", "R-O5 formats"):
    print(key + ":", verdicts[key])

src = np.array([[x, 0, 100] for x in np.linspace(0, 1000, 30)])
scene = np.array([[x, y, 0] for x in np.linspace(0, 1000, 30) for y in (100, 300)])
angle = np.deg2rad(5)
roll = np.array([
    [1, 0, 0],
    [0, np.cos(angle), -np.sin(angle)],
    [0, np.sin(angle), np.cos(angle)],
])
offset = np.array([100, 200, 300])
bad_traj = apply_transform(src, roll, offset, 0.18)
bad_scene = apply_transform(scene, roll, offset, 0.18)
rot, shift, scale = yaw_only_sim3(bad_traj, src)
scene_err = np.linalg.norm(apply_transform(bad_scene, rot, shift, scale) - scene, axis=1)
traj_err = np.linalg.norm(apply_transform(bad_traj, rot, shift, scale) - src, axis=1)
print("rolled scene RMSE m:", round(float(np.sqrt(np.mean(scene_err**2))), 3))
print("rolled trajectory RMSE m:", round(float(np.sqrt(np.mean(traj_err**2))), 3))

height, width, crop_height, crop_width = 294, 518, 864, 1920
resize = max(height / crop_height, width / crop_width)
crop_x = (crop_width * resize - width) / 2
crop_y = (crop_height * resize - height) / 2
intrinsics = np.array([[1000 * resize, 1000 * resize,
                        960 * resize - crop_x, 324 * resize - crop_y]])
try:
    full_frame_camera(intrinsics, height, width, crop_height, crop_width, log=lambda _: None)
except SystemExit as exc:
    print("valid 20 percent top crop rejected:", exc)
