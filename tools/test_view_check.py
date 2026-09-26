"""Small camera projection check for the held-out renderer."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from view_check import project_points


camera = np.eye(4)
camera[:3, 3] = [1.0, 2.0, 3.0]
points = np.array([[2.0, 4.0, 5.0], [1.0, 2.0, 2.0]])
uv, depth = project_points(points, camera, (100.0, 120.0, 320.0, 240.0))
assert np.allclose(uv[0], [370.0, 360.0]), uv[0]
assert depth[0] == 2.0, depth[0]
assert depth[1] == -1.0, depth[1]
print("PASS: known camera and point project to pixel (370, 360)")

# A held-out view the mapper did not place (ADR-029 lets up to half go) is counted as
# uncovered and left out of PSNR/SSIM, rather than stopping the check.
import tempfile  # noqa: E402

import cv2  # noqa: E402

from view_check import score  # noqa: E402

with tempfile.TemporaryDirectory() as run:
    geo = os.path.join(run, "geometry")
    os.makedirs(os.path.join(run, "keyframes"))
    os.makedirs(os.path.join(geo, "sparse_txt"))
    img = np.full((48, 64, 3), 120, np.uint8)
    for n in ("a.jpg", "b.jpg"):
        cv2.imwrite(os.path.join(run, "keyframes", n), img)
    cv2.imwrite(os.path.join(geo, "atlas.png"), np.full((8, 8, 3), 120, np.uint8))
    with open(os.path.join(geo, "sparse_txt", "cameras.txt"), "w") as f:
        f.write("1 PINHOLE 64 48 40 40 32 24\n")
    with open(os.path.join(geo, "sparse_txt", "images.txt"), "w") as f:
        f.write("1 1 0 0 0 0 0 0 1 a.jpg\n\n")
    with open(os.path.join(geo, "scene_tex.mtl"), "w") as f:
        f.write("newmtl m\nmap_Kd atlas.png\n")
    with open(os.path.join(geo, "scene_tex.obj"), "w") as f:
        f.write("mtllib scene_tex.mtl\nv -10 -10 5\nv 10 -10 5\nv 10 10 5\nv -10 10 5\n"
                "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nf 1/1 2/2 3/3\nf 1/1 3/3 4/4\n")
    got = score(run, geo, ["a.jpg", "b.jpg"], scale=1)
    assert got["unposed"] == ["b.jpg"] and len(got["views"]) == 1, got
    assert abs(got["mean_coverage"] - got["views"][0]["coverage"] / 2) < 1e-6, got
    print("PASS: an unplaced held-out view counts as uncovered, not as a crash")
