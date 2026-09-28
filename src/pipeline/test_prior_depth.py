"""
prior_depth.py's pieces that need no GPU: tiling, windows, the ratio field, projection and
the z-buffer, the fusion of a synthetic plane, hole closing, the far field, the Poisson
remesh and the gap fill.

Run:  python src/pipeline/test_prior_depth.py
"""
from __future__ import annotations

import os
import sys
import tempfile

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prior_depth as pd  # noqa: E402

FAILED: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


print("\nT1: tiles and windows")
xs, tw = pd.tile_columns(1920, 595, 3)
check("three tiles span the width", xs[0] == 0 and xs[-1] + tw == 1920, f"{xs} {tw}")
check("a tile has the grid's aspect", abs(tw / 595 - pd.GRID[0] / pd.GRID[1]) < 0.01, str(tw))
check("a narrow frame is one tile", pd.tile_columns(600, 595, 3)[0] == [0])
w = pd.windows(20, 8)
check("windows cover every view", sorted({i for a, b in w for i in range(a, b)}) == list(range(20)), str(w))
check("windows share two views", all(w[k][1] - w[k + 1][0] == 2 for k in range(len(w) - 1)), str(w))
check("a short clip is one window", pd.windows(5, 8) == [(0, 5)])

print("\nT2: the ratio field")
D = np.full((96, 120), 2.0)
M = np.full((96, 120), 3.0)
ok = np.ones_like(D, bool)
ok[:48] = False                                   # the top half has no MVS surface
R = pd.ratio_field(D, M, ok, cell=24)
check("constant ratio is recovered", np.allclose(R, 1.5, atol=1e-3), f"{R.min():.4f}-{R.max():.4f}")
check("no MVS at all gives None", pd.ratio_field(D, M, np.zeros_like(ok), cell=24) is None)
M2 = M.copy()
M2[60:66, 60:66] = 30.0                            # a spike in the MVS depth
R2 = pd.ratio_field(D, M2, np.ones_like(ok), cell=24)
check("a small MVS spike does not move the field", abs(float(R2[63, 63]) - 1.5) < 0.05,
      f"{float(R2[63, 63]):.3f}")

print("\nT3: projection and z-buffer")
K = np.array([[100.0, 0, 50], [0, 100.0, 40], [0, 0, 1]])
c2w = np.eye(4)
V = np.array([[-1, -1, 5], [1, -1, 5], [1, 1, 5], [-1, 1, 5]], float)
F = np.array([[0, 1, 2], [0, 2, 3]])
uv, z = pd.project(V, c2w, K)
check("a point projects where expected", np.allclose(uv[0], [30, 20]) and np.allclose(z, 5))
zb = pd.zbuffer(uv, z, F, 100, 80)
check("the square is at depth 5", np.isclose(zb[40, 50], 5.0) and np.isinf(zb[0, 0]),
      f"{zb[40, 50]} {zb[0, 0]}")

print("\nT4: fusing a plane seen by two views")
with tempfile.TemporaryDirectory() as tmp:
    tiles, imgs = os.path.join(tmp, "tiles"), os.path.join(tmp, "img")
    os.makedirs(tiles)
    os.makedirs(imgs)
    Wg, Hg = pd.GRID
    Kt = np.array([[300.0, 0, Wg / 2], [0, 300.0, Hg / 2], [0, 0, 1]], np.float32)
    poses = {}
    for i, x in enumerate((-0.2, 0.2)):
        name = f"kf_{i:03d}_f{i:05d}.jpg"
        P = np.eye(4)
        P[0, 3] = x
        poses[name] = P
        cv2.imwrite(os.path.join(imgs, name), np.full((Hg, Wg, 3), 120, np.uint8))
        depth = np.full((Hg, Wg), 1.0, np.float32)       # the network says 1
        mvs = np.full((Hg, Wg), 2.0, np.float32)         # the photos say 2
        np.savez_compressed(os.path.join(tiles, f"t0_{name[:-4]}.npz"), depth=depth,
                            conf=np.ones((Hg, Wg), np.float16), mask=np.ones((Hg, Wg), bool),
                            mvs=mvs, K=Kt, x0=0)
    names = sorted(poses)
    check("median MVS depth", abs(pd.median_mvs_depth(tiles) - 2.0) < 1e-6)
    # Two views give each voxel at most two observations, under the default threshold.
    empty, _ = pd.fuse(tiles, imgs, names, poses, voxel=0.02, max_depth=4.0, graze=0.0,
                       up=1, faces=0, log=lambda *_: None)
    check("a surface two views saw is below the default weight", len(empty.triangles) == 0)
    mesh, info = pd.fuse(tiles, imgs, names, poses, voxel=0.02, max_depth=4.0, graze=0.0,
                         up=1, faces=0, min_weight=1.0, log=lambda *_: None)
    Vm = np.asarray(mesh.vertices)
    check("the plane lands at the MVS depth", len(Vm) > 100 and abs(np.median(Vm[:, 2]) - 2.0) < 0.03,
          f"{np.median(Vm[:, 2]) if len(Vm) else None}")
    check("both tiles fused", info["tiles_fused"] == 2, str(info))

print("\nT5: closing holes and adding the far field")
import open3d as o3d  # noqa: E402


def grid_mesh(x0, x1, y0, y1, n, z=0.0, hole=None):
    xs_, ys_ = np.meshgrid(np.linspace(x0, x1, n), np.linspace(y0, y1, n))
    Vg = np.column_stack([xs_.ravel(), ys_.ravel(), np.full(n * n, z)])
    Fg = []
    for r_ in range(n - 1):
        for c in range(n - 1):
            a = r_ * n + c
            cx, cy = Vg[a, 0], Vg[a, 1]
            if hole and hole[0] <= cx <= hole[1] and hole[0] <= cy <= hole[1]:
                continue
            Fg += [[a, a + 1, a + n], [a + 1, a + n + 1, a + n]]
    return Vg, np.array(Fg)


Vf, Ff = grid_mesh(0, 1, 0, 1, 41, hole=(0.4, 0.6))
fused = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(Vf), o3d.utility.Vector3iVector(Ff))
Vm, Fm = grid_mesh(-1, 2, -1, 2, 61, z=0.01)
up = np.array([0.0, 0, 1])
closed, added = pd.close_holes(fused, Vm, Fm, up, cell=0.025)
cen = Vm[Fm].mean(1)
inner = ((cen[:, 0] > 0.45) & (cen[:, 0] < 0.55) & (cen[:, 1] > 0.45) & (cen[:, 1] < 0.55)).sum()
check("the enclosed hole is filled", added >= inner > 0, f"added {added}, inner {inner}")
check("nothing past the edge is added", added < 60, str(added))
far, n_far = pd.add_far_field(fused, Vm, Fm, up, 0.025, np.array([[0.5, 0.5, 1.0]]), reach=1.6)
check("the far field is added within reach", n_far > 0, str(n_far))
Cf = np.asarray(far.vertices)[len(Vf):]
check("and only within reach", np.linalg.norm(Cf - [0.5, 0.5, 1.0], axis=1).max() < 1.8,
      f"{np.linalg.norm(Cf - [0.5, 0.5, 1.0], axis=1).max():.2f}")

print("\nT6: the Poisson remesh and the gap fill")
Vp, Fp = grid_mesh(0, 1, 0, 1, 81)
Vp[:, 2] = 0.05 * np.sin(4 * Vp[:, 0])                     # a gentle wave, not a flat sheet
plane = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(Vp), o3d.utility.Vector3iVector(Fp))
pm, pinfo = pd.poisson_remesh(plane, 0.0125, depth=7, faces=4000)
Vq = np.asarray(pm.vertices)
from scipy.spatial import cKDTree  # noqa: E402

dq = cKDTree(Vp).query(Vq)[0]
check("Poisson keeps a surface", len(pm.triangles) > 500, str(pinfo))
check("nothing past the trim distance", dq.max() <= 3 * 0.0125 + 1e-9, f"{dq.max():.4f}")
check("decimated to the face budget", len(pm.triangles) <= 4000, str(len(pm.triangles)))
filled, n_gap = pd.gap_fill(fused, Vm, Fm, up, 0.025)
Cg = Vm[Fm].mean(1)
Ca = np.asarray(filled.vertices)[np.asarray(filled.triangles)[len(Ff):]].mean(1)
check("the gap fill fills the hole", ((abs(Ca[:, 0] - 0.5) < 0.05) & (abs(Ca[:, 1] - 0.5) < 0.05)).any())
check("and the ground past the edge", (Ca[:, 0] > 1.5).any() and (Ca[:, 1] < -0.5).any())
core = (Cg[:, 0] > 0.1) & (Cg[:, 0] < 0.3) & (Cg[:, 1] > 0.1) & (Cg[:, 1] < 0.3)
covered = ((Ca[:, 0] > 0.1) & (Ca[:, 0] < 0.3) & (Ca[:, 1] > 0.1) & (Ca[:, 1] < 0.3)).sum()
check("but nothing where the prior has faces", covered == 0 and core.sum() > 0, str(covered))
check("the count matches the faces added", n_gap == len(filled.triangles) - len(Ff))

print()
if FAILED:
    print(f"{len(FAILED)} TEST(S) FAILED: {FAILED}")
    sys.exit(1)
print("ALL PASS")
