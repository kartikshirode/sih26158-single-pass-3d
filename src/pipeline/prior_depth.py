"""
A mesh from MapAnything's depth, for what photo matching alone cannot shape.

On the demo clip the drone sees the houses and trees from long range with little change
of angle, and OpenMVS's depth maps there are noise: its mesh made lumps of the houses and
a crumpled sheet of the tree. MapAnything, given the solved poses and intrinsics, predicts
a depth map with flat roofs, upright walls and trees that stand. This module:

1. cuts every keyframe into overlapping tiles of the network's grid shape (near full
   resolution; a whole 1920x595 keyframe would be squeezed to 518x161) and runs
   MapAnything on short windows of consecutive views of each tile, with the poses and
   intrinsics as inputs (tile_depths);
2. corrects each depth map's low frequencies to the MVS surface: a coarse, robust field
   of MVS depth over MapAnything depth, so the metric shape comes from the photos and the
   detail from the network (ratio_field);
3. fuses every corrected tile in a TSDF (Open3D's voxel block grid), with MVS depth
   standing in where MapAnything has nothing it trusts and grazing rays dropped (fuse);
4. closes the holes the fused mesh surrounds with the MVS mesh's faces (close_holes);
5. remeshes it with screened Poisson, trimmed back to it, which closes the thin ribbons
   the TSDF leaves at grazing range (poisson_remesh).

local_gpu then refines the result photometrically (OpenMVS RefineMesh), adds the MVS
mesh's faces wherever the refined mesh left plan-view ground empty (gap_fill) and
textures it.
research/13 has the measurements. Sizes are relative to the median MVS depth of the views,
so the same settings serve any scale of model.
"""
from __future__ import annotations

import os
import time

import numpy as np

GRID = (518, 434)          # network input, width x height: 37 x 31 patches of 14 px


def zbuffer(uv, depth, faces, width, height):
    """Nearest depth per pixel of a projected triangle mesh (numba, compiled on first use)."""
    return _zbuffer()(uv, depth, faces, width, height)


_ZB = None


def _zbuffer():
    global _ZB
    if _ZB is None:
        from numba import njit

        @njit(cache=True)
        def zb_(uv, depth, faces, width, height):
            zb = np.full((height, width), np.inf)
            for fi in range(len(faces)):
                a, b, c = faces[fi]
                z0, z1, z2 = depth[a], depth[b], depth[c]
                if min(z0, z1, z2) <= 1e-6:
                    continue
                x0, y0 = uv[a]
                x1, y1 = uv[b]
                x2, y2 = uv[c]
                if not (np.isfinite(x0) and np.isfinite(x1) and np.isfinite(x2)):
                    continue
                xmin = max(0, int(np.floor(min(x0, x1, x2))))
                xmax = min(width - 1, int(np.ceil(max(x0, x1, x2))))
                ymin = max(0, int(np.floor(min(y0, y1, y2))))
                ymax = min(height - 1, int(np.ceil(max(y0, y1, y2))))
                if xmin > xmax or ymin > ymax:
                    continue
                den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
                if abs(den) < 1e-12:
                    continue
                for y in range(ymin, ymax + 1):
                    for x in range(xmin, xmax + 1):
                        px, py = x + 0.5, y + 0.5
                        w0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / den
                        w1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / den
                        w2 = 1.0 - w0 - w1
                        if min(w0, w1, w2) < -1e-8:
                            continue
                        z = 1.0 / (w0 / z0 + w1 / z1 + w2 / z2)
                        if z < zb[y, x]:
                            zb[y, x] = z
            return zb
        _ZB = zb_
    return _ZB


def project(points: np.ndarray, c2w: np.ndarray, K: np.ndarray):
    """OpenCV projection of world points: pixel coordinates and z depth."""
    cam = (points - c2w[:3, 3]) @ c2w[:3, :3]
    z = cam[:, 2]
    safe = np.where(np.abs(z) < 1e-12, np.nan, z)
    uv = np.column_stack((K[0, 0] * cam[:, 0] / safe + K[0, 2],
                          K[1, 1] * cam[:, 1] / safe + K[1, 2]))
    return uv, z


def tile_columns(width: int, height: int, tiles: int, grid=GRID) -> tuple[list[int], int]:
    """Left edges of `tiles` full-height tiles with the grid's aspect, spread over the width."""
    tw = int(round(height * grid[0] / grid[1]))
    if tw >= width or tiles < 2:
        return [0], min(tw, width)
    return np.linspace(0, width - tw, tiles).round().astype(int).tolist(), tw


def windows(n: int, size: int, overlap: int = 2) -> list[tuple[int, int]]:
    """Consecutive windows over n views, `overlap` shared, the last one ending at n."""
    if n <= size:
        return [(0, n)]
    step = max(1, size - overlap)
    starts = list(range(0, n - overlap, step))
    return [(s, min(n, s + size)) for s in starts if min(n, s + size) - s >= 2]


def ratio_field(D: np.ndarray, M: np.ndarray, ok: np.ndarray, cell: int = 48):
    """
    MVS depth over MapAnything depth, as a smooth field: the robust median in cells of
    `cell` pixels, holes filled from neighbours, blurred, resized to the tile. None when
    no cell has enough MVS support.
    """
    import cv2
    th, tw = D.shape
    gh, gw = int(np.ceil(th / cell)), int(np.ceil(tw / cell))
    R = np.full((gh, gw), np.nan)
    r = np.where(ok, M / np.maximum(D, 1e-9), np.nan)
    for i in range(gh):
        for j in range(gw):
            blk = r[i * cell:(i + 1) * cell, j * cell:(j + 1) * cell]
            v = blk[np.isfinite(blk)]
            if v.size > 0.25 * blk.size:
                R[i, j] = np.median(v)
    if not np.isfinite(R).any():
        return None
    med = np.nanmedian(R)
    for _ in range(gh + gw):
        if np.isfinite(R).all():
            break
        P = np.pad(R, 1, constant_values=np.nan)
        nb = np.stack([P[:-2, 1:-1], P[2:, 1:-1], P[1:-1, :-2], P[1:-1, 2:]])
        cnt = np.isfinite(nb).sum(0)
        fill = np.where(cnt > 0, np.nansum(nb, 0) / np.maximum(cnt, 1), np.nan)
        R = np.where(np.isfinite(R), R, fill)
    R = np.where(np.isfinite(R), R, med).astype(np.float32)
    R = cv2.GaussianBlur(R, (0, 0), 1.0)
    return cv2.resize(R, (tw, th), interpolation=cv2.INTER_CUBIC)


def tile_depths(img_dir: str, names: list, poses: dict, K: np.ndarray, mesh_V: np.ndarray,
                mesh_F: np.ndarray, out_dir: str, *, tiles: int = 3, window: int = 8,
                checkpoint: str, log=print) -> dict:
    """
    MapAnything depth for every tile of every named keyframe, beside the MVS mesh's own
    depth in the same tile. One .npz per (tile, view) in out_dir.
    """
    import tempfile

    import cv2
    import torch
    from mapanything.models import MapAnything
    from mapanything.utils.image import load_images

    first = cv2.imread(os.path.join(img_dir, names[0]))
    H, W = first.shape[:2]
    xs, tw = tile_columns(W, H, tiles)
    sx, sy = GRID[0] / tw, GRID[1] / H
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.perf_counter()
    model = MapAnything.from_pretrained(checkpoint).to("cuda").eval()
    t_load = time.perf_counter() - t0
    tmp = tempfile.mkdtemp(prefix="prior-")
    wins = windows(len(names), window)
    done, ratios = set(), []
    t0 = time.perf_counter()
    try:
        for j, x0 in enumerate(xs):
            Kt = np.array([[K[0, 0] * sx, 0, (K[0, 2] - x0) * sx],
                           [0, K[1, 1] * sy, K[1, 2] * sy], [0, 0, 1]], np.float32)
            for lo, hi in wins:
                win = names[lo:hi]
                paths = []
                for n in win:
                    p = os.path.join(tmp, f"t{j}_{n}")
                    if not os.path.exists(p):
                        cv2.imwrite(p, cv2.imread(os.path.join(img_dir, n))[:, x0:x0 + tw],
                                    [cv2.IMWRITE_JPEG_QUALITY, 97])
                    paths.append(p)
                views = load_images(paths, resize_mode="fixed_size", size=GRID)
                for v, n in zip(views, win):
                    v["intrinsics"] = torch.from_numpy(Kt)[None]
                    v["camera_poses"] = torch.from_numpy(poses[n].astype(np.float32))[None]
                    v["is_metric_scale"] = torch.tensor([False])
                with torch.no_grad():
                    preds = model.infer([dict(v) for v in views], memory_efficient_inference=True,
                                        use_amp=True, amp_dtype="bf16", apply_mask=True,
                                        mask_edges=True)
                for n, pr in zip(win, preds):
                    if (j, n) in done:
                        continue
                    done.add((j, n))
                    d = pr["depth_z"].squeeze().float().cpu().numpy()
                    conf = pr["conf"].squeeze().float().cpu().numpy()
                    m = pr["mask"].squeeze().cpu().numpy().astype(bool)
                    uv, z = project(mesh_V, poses[n], Kt.astype(np.float64))
                    zb = zbuffer(uv, z, mesh_F, GRID[0], GRID[1])
                    ok = m & np.isfinite(zb) & (d > 0)
                    if ok.sum() > 500:
                        ratios.append(float(np.median(zb[ok] / d[ok])))
                    np.savez_compressed(
                        os.path.join(out_dir, f"t{j}_{os.path.splitext(n)[0]}.npz"),
                        depth=d.astype(np.float32), conf=conf.astype(np.float16), mask=m,
                        mvs=np.where(np.isfinite(zb), zb, 0).astype(np.float32), K=Kt, x0=x0)
            log(f"  prior depth: tile {j + 1} of {len(xs)}, {len(done)} views, "
                f"{time.perf_counter() - t0:.0f} s")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        del model
        torch.cuda.empty_cache()
    return {"tiles": len(xs), "tile_width": tw, "views": len(done), "load_s": round(t_load, 1),
            "infer_s": round(time.perf_counter() - t0, 1),
            "mvs_over_prior_median": round(float(np.median(ratios)), 4) if ratios else None}


def fuse(depth_dir: str, img_dir: str, names: list, poses: dict, *, voxel: float,
         max_depth: float, trunc: float = 8.0, up: int = 2, graze: float = 0.05,
         conf_pct: float = 15.0, border: int = 8, cell: int = 48, fill_mvs: bool = True,
         min_weight: float = 3.0, faces: int = 900_000, skip: set | None = None,
         fill_depth: float | None = None, log=print):
    """
    TSDF of every corrected tile; returns an Open3D triangle mesh in the pose frame.
    MapAnything depth is used out to max_depth; the MVS stand-in may reach fill_depth
    (default the same), so the far field keeps the photos' surface without the network's
    guesses about it.
    """
    import cv2
    import open3d as o3d

    dev = o3d.core.Device("CPU:0")
    # Blocks of 8^3 voxels; enough for the demo's extent at 1/240 of its median depth.
    vbg = o3d.t.geometry.VoxelBlockGrid(
        attr_names=("tsdf", "weight", "color"),
        attr_dtypes=(o3d.core.float32, o3d.core.float32, o3d.core.float32),
        attr_channels=((1), (1), (3)), voxel_size=voxel, block_resolution=8,
        block_count=400_000, device=dev)
    th, tw_grid = GRID[1], GRID[0]
    used, dev_from_mvs = 0, []
    order = {n: i for i, n in enumerate(names)}
    files = sorted(f for f in os.listdir(depth_dir) if f.endswith(".npz"))
    for f in files:
        j = f[1:f.index("_")]
        name = f[f.index("_") + 1:-4] + ".jpg"
        if name not in order or (skip and name in skip):
            continue
        z = np.load(os.path.join(depth_dir, f))
        D, M, mask, K = z["depth"], z["mvs"], z["mask"], z["K"].astype(np.float64)
        conf = z["conf"].astype(np.float32)
        x0 = int(z["x0"])
        ok_ref = mask & (M > 0) & (D > 0)
        if ok_ref.sum() < 2000:
            continue
        R = ratio_field(D, M, ok_ref, cell)
        if R is None:
            continue
        Df = D * R
        far = max(max_depth, fill_depth or max_depth)
        keep = mask & (D > 0) & (conf >= np.percentile(conf[mask], conf_pct)) & (Df < max_depth)
        if fill_mvs:
            mv = ~keep & (M > 0) & (M < far)
            Df = np.where(mv, M, Df)
            keep |= mv
        if graze > 0:
            ys, xs = np.mgrid[0:th, 0:tw_grid].astype(np.float32)
            X = np.stack([(xs - K[0, 2]) / K[0, 0] * Df, (ys - K[1, 2]) / K[1, 1] * Df, Df], -1)
            nrm = np.cross(np.gradient(X, axis=1), np.gradient(X, axis=0))
            cos = np.abs((nrm * X).sum(-1)) / (np.linalg.norm(nrm, axis=2)
                                               * np.linalg.norm(X, axis=2) + 1e-12)
            keep &= cos > graze
        keep[:border] = keep[-border:] = False
        keep[:, :border] = keep[:, -border:] = False
        both = ok_ref & keep
        if both.any():
            dev_from_mvs.append(float(np.median(np.abs(Df[both] / M[both] - 1))))
        Df = np.where(keep, Df, 0).astype(np.float32)
        img = cv2.imread(os.path.join(img_dir, name))
        tw = int(round(img.shape[0] * GRID[0] / GRID[1]))
        img = cv2.cvtColor(cv2.resize(img[:, x0:x0 + tw], GRID, interpolation=cv2.INTER_AREA),
                           cv2.COLOR_BGR2RGB)
        Ku = K.copy()
        if up > 1:
            # An oblique tile's rows land far apart on the ground; denser rays keep the
            # voxels between them from being skipped.
            valid = cv2.resize((Df > 0).astype(np.float32), (tw_grid * up, th * up))
            Df = np.where(valid > 0.999, cv2.resize(Df, (tw_grid * up, th * up)), 0).astype(np.float32)
            img = cv2.resize(img, (tw_grid * up, th * up))
            Ku[:2] *= up
            Ku[0, 2] += (up - 1) / 2.0
            Ku[1, 2] += (up - 1) / 2.0
        dimg = o3d.t.geometry.Image(o3d.core.Tensor(np.ascontiguousarray(Df[..., None]), device=dev))
        cimg = o3d.t.geometry.Image(o3d.core.Tensor(
            np.ascontiguousarray(img.astype(np.float32) / 255.0), device=dev))
        intr = o3d.core.Tensor(Ku)
        extr = o3d.core.Tensor(np.linalg.inv(poses[name]))
        blocks = vbg.compute_unique_block_coordinates(dimg, intr, extr, depth_scale=1.0,
                                                      depth_max=far,
                                                      trunc_voxel_multiplier=trunc)
        vbg.integrate(blocks, dimg, cimg, intr, intr, extr, depth_scale=1.0,
                      depth_max=far, trunc_voxel_multiplier=trunc)
        used += 1
    mesh = vbg.extract_triangle_mesh(weight_threshold=min_weight).to_legacy()
    n_raw = len(mesh.triangles)
    tri, cnt, _ = mesh.cluster_connected_triangles()
    tri, cnt = np.asarray(tri), np.asarray(cnt)
    mesh.remove_triangles_by_mask(cnt[tri] < max(500, 0.002 * len(tri)))
    mesh.remove_unreferenced_vertices()
    if faces and len(mesh.triangles) > faces:
        mesh = mesh.simplify_quadric_decimation(faces)
        mesh.remove_unreferenced_vertices()
    log(f"  prior fusion: {used} tiles, {n_raw:,} faces, {len(mesh.triangles):,} kept")
    return mesh, {"tiles_fused": used, "raw_faces": n_raw, "faces": len(mesh.triangles),
                  "median_deviation_from_mvs": round(float(np.median(dev_from_mvs)), 4)
                  if dev_from_mvs else None}


def ground_up(points: np.ndarray, cams: np.ndarray) -> np.ndarray:
    """The cloud's least-spread axis, pointing toward the cameras: up, near enough."""
    o = points.mean(0)
    S = points[::max(1, len(points) // 200_000)] - o
    _, V = np.linalg.eigh(S.T @ S)
    n = V[:, 0]
    if ((cams - o) @ n).mean() < 0:
        n = -n
    return n


def close_holes(mesh, mvs_V: np.ndarray, mvs_F: np.ndarray, up: np.ndarray, cell: float,
                grow: int = 1, min_hole: int = 4):
    """
    Add the MVS mesh's faces where, seen from above, the fused mesh surrounds a hole it
    has nothing in: ground no view saw past a house or a tree. Open ground past the fused
    mesh's edge is left open; that is the far field it dropped on purpose.
    """
    import open3d as o3d
    from scipy import ndimage

    Vf, Ff = np.asarray(mesh.vertices), np.asarray(mesh.triangles)
    e1 = np.cross(up, [1.0, 0, 0] if abs(up[0]) < 0.9 else [0, 1.0, 0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(up, e1)

    def plan(X):
        return np.column_stack([X @ e1, X @ e2])
    # Coverage from face centres: a vertex left behind by a removed face covers nothing.
    pf, pm = plan(Vf[Ff].mean(1)), plan(mvs_V)
    lo = np.minimum(pf.min(0), pm.min(0))
    shape = tuple(np.floor((np.maximum(pf.max(0), pm.max(0)) - lo) / cell).astype(int) + 2)
    cov = np.zeros(shape, bool)
    ij = np.floor((pf - lo) / cell).astype(int)
    cov[ij[:, 0], ij[:, 1]] = True
    cov = ndimage.binary_closing(cov, iterations=1)
    if grow:
        cov = ndimage.binary_dilation(cov, iterations=grow)
    holes = ndimage.binary_fill_holes(cov) & ~cov
    lab, n = ndimage.label(holes)
    if n:
        sizes = ndimage.sum(holes, lab, range(1, n + 1))
        holes &= ~np.isin(lab, 1 + np.flatnonzero(sizes < min_hole))
    k = np.floor((plan(mvs_V[mvs_F].mean(1)) - lo) / cell).astype(int)
    inside = (k >= 0).all(1) & (k[:, 0] < shape[0]) & (k[:, 1] < shape[1])
    take = np.zeros(len(mvs_F), bool)
    take[inside] = holes[k[inside, 0], k[inside, 1]]
    F2 = mvs_F[take]
    used = np.unique(F2)
    remap = -np.ones(len(mvs_V), np.int64)
    remap[used] = np.arange(len(used)) + len(Vf)
    out = o3d.geometry.TriangleMesh(
        o3d.utility.Vector3dVector(np.vstack([Vf, mvs_V[used]])),
        o3d.utility.Vector3iVector(np.vstack([Ff, remap[F2]])))
    out.remove_duplicated_vertices()
    return out, int(take.sum())


def add_far_field(mesh, mvs_V: np.ndarray, mvs_F: np.ndarray, up: np.ndarray, cell: float,
                  cams: np.ndarray, reach: float, grow: int = 2):
    """
    The MVS mesh's faces outside the fused mesh's plan footprint and within `reach` of a
    camera: the far field the prior leaves out, kept at the photos' own (coarse) surface
    so every view still has ground to the top of its crop. Added after refinement, which
    would otherwise spend its face budget on it.
    """
    import open3d as o3d
    from scipy import ndimage
    from scipy.spatial import cKDTree

    Vf, Ff = np.asarray(mesh.vertices), np.asarray(mesh.triangles)
    e1 = np.cross(up, [1.0, 0, 0] if abs(up[0]) < 0.9 else [0, 1.0, 0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(up, e1)

    def plan(X):
        return np.column_stack([X @ e1, X @ e2])
    # Coverage from face centres: a vertex left behind by a removed face covers nothing.
    pf, pm = plan(Vf[Ff].mean(1)), plan(mvs_V)
    lo = np.minimum(pf.min(0), pm.min(0))
    shape = tuple(np.floor((np.maximum(pf.max(0), pm.max(0)) - lo) / cell).astype(int) + 2)
    cov = np.zeros(shape, bool)
    ij = np.floor((pf - lo) / cell).astype(int)
    cov[ij[:, 0], ij[:, 1]] = True
    cov = ndimage.binary_dilation(ndimage.binary_closing(cov, iterations=1), iterations=grow)
    cen = mvs_V[mvs_F].mean(1)
    k = np.floor((plan(cen) - lo) / cell).astype(int)
    near = cKDTree(cams).query(cen)[0] < reach
    take = near & ~cov[k[:, 0], k[:, 1]]
    F2 = mvs_F[take]
    used = np.unique(F2)
    remap = -np.ones(len(mvs_V), np.int64)
    remap[used] = np.arange(len(used)) + len(Vf)
    out = o3d.geometry.TriangleMesh(
        o3d.utility.Vector3dVector(np.vstack([Vf, mvs_V[used]])),
        o3d.utility.Vector3iVector(np.vstack([Ff, remap[F2]])))
    return out, int(take.sum())


def poisson_remesh(mesh, voxel: float, *, depth: int = 11, trim: float = 3.0,
                   faces: int = 900_000):
    """
    Screened Poisson over the fused mesh's vertices and normals. At grazing range the TSDF
    breaks into thin parallel ribbons that RefineMesh keeps (research/13 section 6a); the
    Poisson surface is one sheet there. Its vertices more than `trim` voxels from the
    fused mesh go, so it adds no surface the fusion had no evidence for.
    """
    import open3d as o3d
    from scipy.spatial import cKDTree

    mesh.compute_vertex_normals()
    pc = o3d.geometry.PointCloud(mesh.vertices)
    pc.normals = mesh.vertex_normals
    p, _ = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
        pc, depth=depth, scale=1.05, n_threads=-1)
    n_raw = len(p.triangles)
    d, _ = cKDTree(np.asarray(mesh.vertices)).query(np.asarray(p.vertices))
    p.remove_vertices_by_mask(d > trim * voxel)
    if faces and len(p.triangles) > faces:
        p = p.simplify_quadric_decimation(faces)
    p.remove_unreferenced_vertices()
    return p, {"poisson_depth": depth, "poisson_raw_faces": n_raw,
               "poisson_faces": len(p.triangles)}


def gap_fill(mesh, mvs_V: np.ndarray, mvs_F: np.ndarray, up: np.ndarray, cell: float,
             below: float = 0.0, ring: int = 0):
    """
    Add the MVS mesh's faces whose centre falls in a plan-view cell of `cell` with no face
    of `mesh`: ground the prior dropped or RefineMesh thinned out, past the edges as well
    as inside. A prior face covers the cells of its centre and its three corners. With
    `below` > 0, a face lower than every prior face in its cell by more than `below` is
    added too: ground under a tree whose crown the prior kept and whose floor it lost.
    `ring` grows every added patch by that many rings of neighbouring MVS faces.
    """
    import open3d as o3d

    Vf, Ff = np.asarray(mesh.vertices), np.asarray(mesh.triangles)
    e1 = np.cross(up, [1.0, 0, 0] if abs(up[0]) < 0.9 else [0, 1.0, 0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(up, e1)

    def plan(X):
        return np.column_stack([X @ e1, X @ e2])
    T = Vf[Ff]
    pf = plan(np.vstack([T.mean(1), T[:, 0], T[:, 1], T[:, 2]]))
    pm = plan(mvs_V)
    lo = np.minimum(pf.min(0), pm.min(0))
    shape = tuple(np.floor((np.maximum(pf.max(0), pm.max(0)) - lo) / cell).astype(int) + 2)
    cov = np.zeros(shape, bool)
    ij = np.floor((pf - lo) / cell).astype(int)
    cov[ij[:, 0], ij[:, 1]] = True
    cen = mvs_V[mvs_F].mean(1)
    k = np.floor((plan(cen) - lo) / cell).astype(int)
    take = ~cov[k[:, 0], k[:, 1]]
    if below > 0:
        low = np.full(shape, np.inf)
        h = np.concatenate([T.mean(1), T[:, 0], T[:, 1], T[:, 2]]) @ up
        np.minimum.at(low, (ij[:, 0], ij[:, 1]), h)
        take |= cen @ up < low[k[:, 0], k[:, 1]] - below
    if ring:
        # Faces sharing a vertex with an added one, so a patch overlaps the prior's
        # edge instead of leaving a sliver between them. Long faces are the sails
        # ReconstructMesh spans unseen gaps with, so they are not grown into.
        E = mvs_V[mvs_F]
        edge = np.linalg.norm(E - np.roll(E, 1, axis=1), axis=2).max(1)
        small = edge < 4 * np.median(edge)
    for _ in range(ring):
        v = np.zeros(len(mvs_V), bool)
        v[mvs_F[take].ravel()] = True
        take |= v[mvs_F].any(1) & small
    F2 = mvs_F[take]
    used = np.unique(F2)
    remap = -np.ones(len(mvs_V), np.int64)
    remap[used] = np.arange(len(used)) + len(Vf)
    out = o3d.geometry.TriangleMesh(
        o3d.utility.Vector3dVector(np.vstack([Vf, mvs_V[used]])),
        o3d.utility.Vector3iVector(np.vstack([Ff, remap[F2]])))
    return out, int(take.sum())


def median_mvs_depth(tiles_dir: str) -> float:
    """Median of every tile's MVS depth: the scale the fusion's sizes are measured in."""
    meds = []
    for f in sorted(os.listdir(tiles_dir)):
        if f.endswith(".npz"):
            m = np.load(os.path.join(tiles_dir, f))["mvs"]
            if (m > 0).any():
                meds.append(float(np.median(m[m > 0])))
    if not meds:
        raise RuntimeError("no tile has MVS depth to scale the fusion by")
    return float(np.median(meds))
