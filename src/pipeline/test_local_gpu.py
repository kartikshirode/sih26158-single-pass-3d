"""
The parts of local_gpu.py that need no GPU and no COLMAP: reading OpenMVS's PLY and a
COLMAP text model back into arrays.

Run:  python src/pipeline/test_local_gpu.py

The first dense read returned coordinates up to 3.4e38: OpenMVS writes two list
properties per vertex, and a fixed-size read walked straight through them.
"""
from __future__ import annotations

import os
import struct
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from local_gpu import read_images_txt, read_ply_points  # noqa: E402

FAILED: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def write_openmvs_style_ply(path, P, C, rng):
    """The vertex layout DensifyPointCloud 2.4.0 writes, with variable-length lists."""
    head = ("ply\nformat binary_little_endian 1.0\n"
            f"element vertex {len(P)}\n"
            "property float32 x\nproperty float32 y\nproperty float32 z\n"
            "property uint8 red\nproperty uint8 green\nproperty uint8 blue\n"
            "property float32 nx\nproperty float32 ny\nproperty float32 nz\n"
            "property list uint8 uint32 view_indices\n"
            "property list uint8 float32 view_weights\nend_header\n")
    with open(path, "wb") as f:
        f.write(head.encode("ascii"))
        for p, c in zip(P, C):
            k = int(rng.integers(0, 6))
            f.write(struct.pack("<3f3B3f", *p, *c, 0.0, 0.0, 1.0))
            f.write(struct.pack("<B", k) + struct.pack(f"<{k}I", *range(k)))
            f.write(struct.pack("<B", k) + struct.pack(f"<{k}f", *([0.5] * k)))


tmp = tempfile.mkdtemp(prefix="lgpu-")
rng = np.random.default_rng(3)

print("\nT1: OpenMVS dense PLY")
P = rng.normal(0, 50, (2000, 3)).astype(np.float32)
C = rng.integers(0, 256, (2000, 3)).astype(np.uint8)
p = os.path.join(tmp, "dense.ply")
write_openmvs_style_ply(p, P, C, rng)
Q, D = read_ply_points(p)
check("points survive variable-length view lists", np.array_equal(P, Q),
      f"max |diff| {np.abs(P - Q).max():.3g}")
check("colours too", D is not None and np.array_equal(C, D))

print("\nT2: COLMAP images.txt back to cam2world")
from scipy.spatial.transform import Rotation  # noqa: E402
R_c2w = Rotation.from_euler("xyz", [10, -20, 35], degrees=True).as_matrix()
c = np.array([1.5, -2.0, 30.0])
R = R_c2w.T                                           # world -> camera, as COLMAP stores
t = -R @ c
qx, qy, qz, qw = Rotation.from_matrix(R).as_quat()
with open(os.path.join(tmp, "images.txt"), "w") as f:
    f.write("# IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n")
    f.write(f"7 {qw} {qx} {qy} {qz} {t[0]} {t[1]} {t[2]} 1 kf_000.jpg\n")
    f.write("10.0 20.0 -1\n")
got = read_images_txt(os.path.join(tmp, "images.txt"))
M = got.get("kf_000.jpg")
check("the camera centre comes back", M is not None and np.allclose(M[:3, 3], c, atol=1e-6))
check("and the rotation", M is not None and np.allclose(M[:3, :3], R_c2w, atol=1e-6))

print()
if FAILED:
    print(f"{len(FAILED)} TEST(S) FAILED: {FAILED}")
    sys.exit(1)
print("ALL PASS")
