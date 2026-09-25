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
