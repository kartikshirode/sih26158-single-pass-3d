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
from local_gpu import (DEFAULTS, attitude_spread_deg, SparseError, clean_work, frame_order,  # noqa: E402
                       read_images_txt, read_ply_points, reuse_sparse, with_extra)

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

print("\nT3: keyframes in time order")
names = ["kf_1000_f30000.jpg", "kf_100_f03000.jpg", "kf_999_f29970.jpg", "kf_001_f00030.jpg"]
check("past 999 keyframes the order is numeric, not by string",
      sorted(names, key=frame_order) ==
      ["kf_001_f00030.jpg", "kf_100_f03000.jpg", "kf_999_f29970.jpg", "kf_1000_f30000.jpg"],
      str(sorted(names, key=frame_order)))

print("\nT4: S3 keeps its products and drops its intermediates")
with tempfile.TemporaryDirectory() as tmp:
    for d in ("dense", "sparse_g", "sparse_txt", "logs", "images"):
        os.makedirs(os.path.join(tmp, d))
    for f in ("db.db", "depth0000.dmap", "scene_dense.ply", "points_fused.npy",
              "colors_fused.npy", "cameras.npy", "scene_dense_mesh.ply", "scene_tex.obj",
              "local_gpu_result.json"):
        open(os.path.join(tmp, f), "wb").close()
    gone = clean_work(tmp)
    left = sorted(os.listdir(tmp))
    check("bulky intermediates are removed",
          gone == ["db.db", "dense", "depth0000.dmap", "scene_dense.ply", "sparse_g"], str(gone))
    check("the cloud, cameras, mesh, sparse model, logs and images stay",
          left == ["cameras.npy", "colors_fused.npy", "images", "local_gpu_result.json", "logs",
                   "points_fused.npy", "scene_dense_mesh.ply", "scene_tex.obj", "sparse_txt"],
          str(left))

print("\nT5: a dense-only rerun takes the poses of a finished run")
import json  # noqa: E402


def refused(fn):
    try:
        fn()
    except SparseError as e:
        return str(e)
    return None


with tempfile.TemporaryDirectory() as tmp:
    src, work = os.path.join(tmp, "src"), os.path.join(tmp, "work")
    os.makedirs(os.path.join(src, "sparse_txt"))
    os.makedirs(work)
    open(os.path.join(src, "sparse_txt", "images.txt"), "w").write("# poses\n")
    np.save(os.path.join(src, "cameras.npy"), np.eye(4)[None].repeat(3, 0))
    prev = {"n_views": 3, "options": dict(DEFAULTS), "ba_gate": {"passed": True},
            "camera": {"f": 1100.0}, "dense_points": 7, "stages": []}
    json.dump(prev, open(os.path.join(src, "local_gpu_result.json"), "w"))
    names = ["kf_0.jpg", "kf_1.jpg", "kf_2.jpg"]
    dense_change = dict(DEFAULTS, dense_resolution_level=0, texture_decimate=0.2)
    got = reuse_sparse(src, work, names, dense_change)
    check("the sparse model and cameras are copied",
          os.path.isfile(os.path.join(work, "sparse_txt", "images.txt"))
          and os.path.isfile(os.path.join(work, "cameras.npy")))
    check("only the poses half of the result is carried over",
          got.get("camera") == {"f": 1100.0} and "dense_points" not in got
          and "stages" not in got, str(sorted(got)))
    check("a pose option change is refused",
          refused(lambda: reuse_sparse(src, work, names,
                                       dict(DEFAULTS, global_match_overlap=10)))
          is not None)
    check("a different view count is refused",
          refused(lambda: reuse_sparse(src, work, names[:2], dict(DEFAULTS))) is not None)
    prev["ba_gate"] = {"passed": False}
    json.dump(prev, open(os.path.join(src, "local_gpu_result.json"), "w"))
    check("poses that failed the S3b gate are refused",
          refused(lambda: reuse_sparse(src, work, names, dict(DEFAULTS))) is not None)

print("\nT6: an extra flag replaces the default rather than repeating it")
base = ["TextureMesh", "scene.mvs", "--decimate", 0.1, "--global-seam-leveling", "0",
        "--cuda-device", "0"]
got = with_extra(base, "--global-seam-leveling 1 --cuda-device -2 --sharpness-weight 0")
check("defaults named in the extra are replaced, the rest kept in order",
      got == ["TextureMesh", "scene.mvs", "--decimate", 0.1, "--global-seam-leveling", "1",
              "--cuda-device", "-2", "--sharpness-weight", "0"], str(got))
check("an empty extra changes nothing", with_extra(base, "") == base)

print("\nT7: how far the views turn decides whether the mapper refines the focal length")
rot = Rotation.from_euler("x", 120, degrees=True).as_matrix()     # looking down and ahead
straight = np.repeat(np.eye(4)[None], 60, 0)
straight[:, :3, :3] = rot
straight[:, :3, 3] = np.linspace(0, 1, 60)[:, None] * [1.0, 0, 0]
check("a straight pass at one attitude does not turn",
      attitude_spread_deg(straight) < 1e-6, f"{attitude_spread_deg(straight):.2e}")
pan = straight.copy()
for i, a in enumerate(np.linspace(-30, 30, 60)):
    pan[i, :3, :3] = Rotation.from_euler("z", a, degrees=True).as_matrix() @ rot
check("a 60 degree pan turns about 28 degrees either side of its middle view",
      25 < attitude_spread_deg(pan) < 30, f"{attitude_spread_deg(pan):.1f}")
scaled = pan.copy()
scaled[:, :3, :3] *= 0.37                          # a stitched window's scale
check("a window's scale in the rotation block does not count as turning",
      abs(attitude_spread_deg(scaled) - attitude_spread_deg(pan)) < 1e-6)
lost = pan.copy()
lost[5] = np.nan
check("a view with no pose is ignored", np.isfinite(attitude_spread_deg(lost)))

print()
if FAILED:
    print(f"{len(FAILED)} TEST(S) FAILED: {FAILED}")
    sys.exit(1)
print("ALL PASS")
