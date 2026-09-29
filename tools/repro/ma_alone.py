"""MapAnything-alone baseline on the demo keyframes: its own stitched poses, its own
per-view intrinsics and its point maps, fused in a TSDF (same fusion settings as the
depth prior: voxel median depth / 240, truncation 8, depth upsampled 2x, lowest 15%
confidence and an 8 px border dropped, weight 3), textured by OpenMVS TextureMesh with
Tesseract's texture settings, fill and levelling, and scored on the same held-out views.
Nothing from COLMAP or OpenMVS's geometry is used.

python tools/repro/ma_alone.py <tag> [window]
"""
import json
import os
import shutil
import subprocess
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import EXP, ROOT, RUN, demo_keyframes, tool  # noqa: E402
from pipeline.local_gpu import frame_order, mapanything_poses  # noqa: E402

COLMAP = tool("SIH_COLMAP")
MVS = tool("SIH_OPENMVS")
KF = demo_keyframes()
tag = sys.argv[1]
window = int(sys.argv[2]) if len(sys.argv) > 2 else 0
work = os.path.join(EXP, f"bl-{tag}")
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
names = sorted((x for x in os.listdir(KF) if x.endswith(".jpg")), key=frame_order)
held = set(names[9::10])
H0, W0 = cv2.imread(os.path.join(KF, names[0])).shape[:2]
T = {}
t = time.perf_counter()
ma = mapanything_poses([os.path.join(KF, n) for n in names], window=window, overlap=8)
T["mapanything"] = time.perf_counter() - t
gh, gw = ma["grid"]
P, C, M, cams = ma["points"], ma["conf"], ma["mask"], ma["cams"]

# Per-view pinhole intrinsics from the point map: u = fx X/Z + cx, v = fy Y/Z + cy.
vs, us = np.mgrid[0:gh, 0:gw]
us, vs = us.ravel() + 0.5, vs.ravel() + 0.5
Ks, depths = [], []
for i in range(len(names)):
    c2w = cams[i]
    Xc = (P[i] - c2w[:3, 3]) @ c2w[:3, :3]
    ok = M[i] & np.isfinite(Xc).all(1) & (Xc[:, 2] > 1e-6)
    x, y = Xc[ok, 0] / Xc[ok, 2], Xc[ok, 1] / Xc[ok, 2]
    fx, cx = np.linalg.lstsq(np.column_stack([x, np.ones_like(x)]), us[ok], rcond=None)[0]
    fy, cy = np.linalg.lstsq(np.column_stack([y, np.ones_like(y)]), vs[ok], rcond=None)[0]
    Ks.append((fx, fy, cx, cy))
    d = np.where(ok, Xc[:, 2], 0).reshape(gh, gw).astype(np.float32)
    c = C[i].reshape(gh, gw)
    d[c < np.percentile(c[d > 0], 15)] = 0
    depths.append(d)
Ks = np.array(Ks)
med = float(np.median([np.median(d[d > 0]) for d in depths]))

# TSDF over the views that are not held out.
import open3d as o3d  # noqa: E402

t = time.perf_counter()
voxel, up, border = med / 240, 2, 8
dev = o3d.core.Device("CPU:0")
vbg = o3d.t.geometry.VoxelBlockGrid(attr_names=("tsdf", "weight", "color"),
                                    attr_dtypes=(o3d.core.float32,) * 3, attr_channels=((1), (1), (3)),
                                    voxel_size=voxel, block_resolution=8, block_count=400_000, device=dev)
for i, n in enumerate(names):
    if n in held:
        continue
    d = depths[i].copy()
    d[:border] = d[-border:] = 0
    d[:, :border] = d[:, -border:] = 0
    fx, fy, cx, cy = Ks[i]
    K = np.array([[fx * up, 0, cx * up], [0, fy * up, cy * up], [0, 0, 1]])
    valid = cv2.resize((d > 0).astype(np.float32), (gw * up, gh * up))
    D = np.where(valid > 0.999, cv2.resize(d, (gw * up, gh * up)), 0).astype(np.float32)
    img = cv2.cvtColor(cv2.resize(cv2.imread(os.path.join(KF, n)), (gw * up, gh * up), interpolation=cv2.INTER_AREA),
                       cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    dimg = o3d.t.geometry.Image(o3d.core.Tensor(np.ascontiguousarray(D[..., None]), device=dev))
    cimg = o3d.t.geometry.Image(o3d.core.Tensor(np.ascontiguousarray(img), device=dev))
    intr, extr = o3d.core.Tensor(K), o3d.core.Tensor(np.linalg.inv(cams[i]))
    far = 3.0 * med
    blocks = vbg.compute_unique_block_coordinates(dimg, intr, extr, depth_scale=1.0, depth_max=far,
                                                  trunc_voxel_multiplier=8.0)
    vbg.integrate(blocks, dimg, cimg, intr, intr, extr, depth_scale=1.0, depth_max=far, trunc_voxel_multiplier=8.0)
mesh = vbg.extract_triangle_mesh(weight_threshold=3.0).to_legacy()
tri, cnt, _ = mesh.cluster_connected_triangles()
tri, cnt = np.asarray(tri), np.asarray(cnt)
mesh.remove_triangles_by_mask(cnt[tri] < max(500, 0.002 * len(tri)))
mesh.remove_unreferenced_vertices()
if len(mesh.triangles) > 900_000:
    mesh = mesh.simplify_quadric_decimation(900_000)
    mesh.remove_unreferenced_vertices()
o3d.io.write_triangle_mesh(os.path.join(work, "ma_mesh.ply"), mesh)
T["fusion"] = time.perf_counter() - t

# A COLMAP text model with MapAnything's cameras, one PINHOLE camera per view at keyframe size.
txt = os.path.join(work, "sparse_txt")
os.makedirs(txt)
sx, sy = W0 / gw, H0 / gh
with open(os.path.join(txt, "cameras.txt"), "w") as f:
    for i in range(len(names)):
        fx, fy, cx, cy = Ks[i]
        f.write(f"{i + 1} PINHOLE {W0} {H0} {fx * sx} {fy * sy} {cx * sx} {cy * sy}\n")


def rot_to_quat(R):
    from scipy.spatial.transform import Rotation
    x, y, z, w = Rotation.from_matrix(R).as_quat()
    return w, x, y, z


# InterfaceCOLMAP crashes on a model without points, so each non-held view contributes
# 300 of its own MapAnything points, observed in it and in the next view.
def proj(i, X):
    Xc = (X - cams[i][:3, 3]) @ cams[i][:3, :3]
    fx, fy, cx, cy = Ks[i]
    return np.column_stack([(fx * Xc[:, 0] / Xc[:, 2] + cx) * sx, (fy * Xc[:, 1] / Xc[:, 2] + cy) * sy]), Xc[:, 2]


obs = {i: [] for i in range(len(names))}
pts3d = []
rng = np.random.default_rng(0)
keep_idx = [i for i, n in enumerate(names) if n not in held]
for a, i in enumerate(keep_idx[:-1]):
    j = keep_idx[a + 1]
    cand = np.flatnonzero(M[i] & np.isfinite(P[i]).all(1))
    if len(cand) == 0:
        continue
    X = P[i][rng.choice(cand, min(300, len(cand)), replace=False)].astype(np.float64)
    ui, zi = proj(i, X)
    uj, zj = proj(j, X)
    ok = (zi > 0) & (zj > 0) & (uj[:, 0] >= 0) & (uj[:, 0] < W0) & (uj[:, 1] >= 0) & (uj[:, 1] < H0)
    for x, pi_, pj_ in zip(X[ok], ui[ok], uj[ok]):
        pid = len(pts3d) + 1
        ki, kj = len(obs[i]), len(obs[j])
        obs[i].append((pi_, pid)); obs[j].append((pj_, pid))
        pts3d.append((pid, x, [(i + 1, ki), (j + 1, kj)]))
with open(os.path.join(txt, "images.txt"), "w") as f:
    for i, n in enumerate(names):
        w2c = np.linalg.inv(cams[i])
        q = rot_to_quat(w2c[:3, :3])
        tt = w2c[:3, 3]
        f.write(f"{i + 1} {q[0]} {q[1]} {q[2]} {q[3]} {tt[0]} {tt[1]} {tt[2]} {i + 1} {n}\n")
        f.write(" ".join(f"{u:.2f} {v:.2f} {pid}" for (u, v), pid in obs[i]) + "\n")
with open(os.path.join(txt, "points3D.txt"), "w") as f:
    for pid, x, tr in pts3d:
        f.write(f"{pid} {x[0]} {x[1]} {x[2]} 128 128 128 0.5 " + " ".join(f"{a} {b}" for a, b in tr) + "\n")
# view_check reads one camera; it gets the median one, scored per view below instead.
t = time.perf_counter()
dense_txt = os.path.join(work, "dense_txt")
sys.path.insert(0, os.path.join(ROOT, "mvs_job"))
from run_mvs_sharded import filter_model  # noqa: E402

filter_model(txt, dense_txt, set(n for n in names if n not in held))
und = os.path.join(work, "dense")
subprocess.run([COLMAP, "image_undistorter", "--image_path", KF, "--input_path", dense_txt,
                "--output_path", und, "--output_type", "COLMAP"], check=True, capture_output=True)
subprocess.run([os.path.join(MVS, "InterfaceCOLMAP.exe"), "-i", und, "-o", "scene.mvs", "-w", work],
               check=True, capture_output=True)
subprocess.run([os.path.join(MVS, "TextureMesh.exe"), "scene.mvs", "-m", "ma_mesh.ply", "-w", work,
                "--decimate", "1", "--global-seam-leveling", "0", "--local-seam-leveling", "0",
                "--sharpness-weight", "0", "--cost-smoothness-ratio", "0.5", "--export-type", "obj",
                "-o", "scene_tex.mvs", "--cuda-device", "0"], check=True, capture_output=True)
T["texture"] = time.perf_counter() - t
# texture_fill wants the cloud: MapAnything's own points, not held out.
keep = [i for i, n in enumerate(names) if n not in held]
pts = np.concatenate([P[i][M[i]] for i in keep])[::4]
cols = []
for i in keep:
    im = cv2.resize(cv2.imread(os.path.join(KF, names[i])), (gw, gh), interpolation=cv2.INTER_AREA)
    cols.append(cv2.cvtColor(im, cv2.COLOR_BGR2RGB).reshape(-1, 3)[M[i]])
cols = np.concatenate(cols)[::4]
np.save(os.path.join(work, "points_fused.npy"), pts.astype(np.float32))
np.save(os.path.join(work, "colors_fused.npy"), cols.astype(np.uint8))
from texture_fill import fill_in_place  # noqa: E402
from texture_level import level_in_place  # noqa: E402

fr = fill_in_place(work)
level_in_place(work)

# Score each held-out view with its own intrinsics (view_check reads one camera per model).
import view_check as vc  # noqa: E402

views = []
for i, n in enumerate(names):
    if n not in held:
        continue
    one = os.path.join(work, "one")
    os.makedirs(os.path.join(one, "sparse_txt"), exist_ok=True)
    fx, fy, cx, cy = Ks[i]
    open(os.path.join(one, "sparse_txt", "cameras.txt"), "w").write(
        f"1 PINHOLE {W0} {H0} {fx * sx} {fy * sy} {cx * sx} {cy * sy}\n")
    w2c = np.linalg.inv(cams[i])
    q = rot_to_quat(w2c[:3, :3])
    tt = w2c[:3, 3]
    open(os.path.join(one, "sparse_txt", "images.txt"), "w").write(
        f"1 {q[0]} {q[1]} {q[2]} {q[3]} {tt[0]} {tt[1]} {tt[2]} 1 {n}\n\n")
    for f in os.listdir(work):
        if f.startswith("scene_tex") and not f.endswith(".mvs") and not f.endswith(".log"):
            if not os.path.exists(os.path.join(one, f)):
                shutil.copyfile(os.path.join(work, f), os.path.join(one, f))
    try:
        views += vc.score(RUN, one, [n], scale=1)["views"]
    except ValueError:                      # covers under 100 px: counts as empty
        views.append({"name": n, "coverage": 0.0, "psnr_db": float("nan"), "ssim": float("nan")})
out = {"tag": tag, "seconds": {k: round(v, 1) for k, v in T.items()}, "faces": len(mesh.triangles),
       "median_depth": med, "unseen_faces": fr["unseen_faces"], "windows": ma["windows"],
       "focal_px_median": float(np.median(Ks[:, 0] * sx)),
       "mean_coverage": round(float(np.mean([v["coverage"] for v in views])), 5),
       "mean_psnr_db": round(float(np.nanmean([v["psnr_db"] for v in views])), 3),
       "mean_ssim": round(float(np.nanmean([v["ssim"] for v in views])), 5), "views": views}
json.dump(out, open(os.path.join(work, "baseline.json"), "w"), indent=1)
print({k: v for k, v in out.items() if k != "views"})
