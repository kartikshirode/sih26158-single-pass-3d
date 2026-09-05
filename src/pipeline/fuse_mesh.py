"""
S3/S4 - turn raw per-view point maps into a surface.

Concatenating per-view point maps is not a reconstruction. The model emits one depth
map per view in a shared frame, so overlapping views print the same surface once per
view, each copy offset by its own error. That reads as a smear even when every
individual view is correct. The stages here are what turn it into geometry:

  conf     the model's own per-point confidence. An earlier run discarded this
           channel entirely, which left nothing to filter on.
  valid    the non-ambiguous mask - sky, and regions the model declines to commit to.
  range    only where the depth distribution actually HAS a far-field tail. On
           bounded survey footage it does not, and a blanket percentile cut throws
           away a third of the scene for nothing.
  sor      statistical outlier removal against local neighbour distance.
  fuse     voxel averaging, sized from ONE VIEW's native point spacing.
  mesh     screened Poisson, with normals oriented by the real camera centres.

Sized for ~7M points on a machine with a few GB free: every neighbour query runs on
a subsample or in slices, never on the whole cloud at once.
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
from scipy.spatial import cKDTree

SUB = 400_000          # subsample used for every density / threshold estimate
SLICE = 1_000_000      # chunk size for full-cloud queries


def load(d: str):
    P = np.load(f"{d}/points.npy").astype(np.float32)
    C = np.load(f"{d}/colors.npy")
    F = (np.load(f"{d}/conf.npy") if os.path.exists(f"{d}/conf.npy")
         else np.ones(len(P), np.float32))
    M = (np.load(f"{d}/mask.npy") if os.path.exists(f"{d}/mask.npy")
         else np.ones(len(P), bool))
    n = min(len(P), len(C), len(F), len(M))
    meta = {}
    rp = f"{d}/mapanything_result.json"
    if os.path.exists(rp):
        meta = json.load(open(rp))
    cams = None
    if os.path.exists(f"{d}/cameras.npy"):
        cams = np.load(f"{d}/cameras.npy")
    return P[:n], C[:n], F[:n], M[:n], cams, meta


def camera_centres(cams) -> np.ndarray | None:
    """
    Extract camera positions from whatever shape the model handed back.

    Worth being explicit about, because the fallback this replaces - the thinnest
    principal axis of the cloud - has an ARBITRARY SIGN. Half the time it points
    normals into the surface, Poisson builds the surface inside out, and a two-sided
    shader hides it: the render looks fine while the geometry is wrong.
    """
    if cams is None:
        return None
    a = np.asarray(cams, float)
    if a.ndim == 3 and a.shape[-2:] in ((4, 4), (3, 4)):
        return a[:, :3, 3]
    if a.ndim == 2 and a.shape[1] >= 3:
        return a[:, :3]
    return None


def view_point_spacing(P: np.ndarray, shapes: list) -> float | None:
    """
    Median distance between horizontally adjacent points WITHIN one view.

    This is the right scale for the fusion voxel, and a constant "points per cell"
    target is not. Occupancy depends on how many views see a patch, which over a 52 s
    pass at 45 keyframes is far more than the three the constant was tuned for -
    so an occupancy target leaves several unmerged copies of the surface standing,
    which is exactly the triple-printing the fusion stage exists to remove.
    """
    if not shapes:
        return None
    H, W = int(shapes[0][0]), int(shapes[0][1])
    if H * W > len(P):
        return None
    g = P[:H * W].reshape(H, W, 3)
    d = np.linalg.norm(g[:, 1:] - g[:, :-1], axis=2)
    d = d[np.isfinite(d) & (d > 0)]
    return float(np.median(d)) if len(d) else None


def filter_fuse(P, C, F, M, *, cams=None, shapes=None, conf_pct=30.0,
                sor_sigma=1.2, log=print):
    rng = np.random.default_rng(0)
    log(f"raw              {len(P):>10,}")

    conf_is_real = float(F.min()) != float(F.max())
    ok = np.isfinite(P).all(1) & M
    P, C, F = P[ok], C[ok], F[ok]
    log(f"finite + valid   {len(P):>10,}   (mask kept {ok.mean():.1%})")

    if conf_is_real:
        thr = float(np.percentile(F, conf_pct))
        g = F >= thr
        P, C = P[g], C[g]
        log(f"confidence       {len(P):>10,}   (conf >= {thr:.3f}, dropped {conf_pct:.0f}%)")
    else:
        # The container writes ones when the model emits no conf key. Reporting a
        # gate that did not fire would be a lie dressed as a number.
        log(f"confidence       {'NOT AVAILABLE':>10}   (channel is constant - gate skipped)")

    cen = np.median(P[rng.choice(len(P), min(SUB, len(P)), replace=False)], axis=0)
    r = np.linalg.norm(P - cen, axis=1)
    p50, p99 = np.percentile(r, [50, 99])
    tail = p99 / max(p50, 1e-9)
    if tail > 6.0:
        g = r <= np.percentile(r, 90)
        P, C = P[g], C[g]
        log(f"range gate       {len(P):>10,}   (tail ratio {tail:.1f} - far field cut)")
    else:
        log(f"range gate       {'skipped':>10}   (tail ratio {tail:.1f}, scene is bounded)")
    del r

    # STATISTICAL OUTLIER REMOVAL. The tree and the threshold come from a subsample;
    # only the final test touches every point, and that runs in slices. Querying k=9
    # against 7M points at once costs ~1 GB of distances and indices alone.
    sub = P[rng.choice(len(P), min(SUB, len(P)), replace=False)]
    tree = cKDTree(sub)
    dd, _ = tree.query(sub, k=9, workers=-1)
    md_sub = dd[:, 1:].mean(1)
    cutoff = float(md_sub.mean() + sor_sigma * md_sub.std())
    nn1 = float(np.median(dd[:, 1]))

    keep = np.empty(len(P), bool)
    for i in range(0, len(P), SLICE):
        d, _ = tree.query(P[i:i + SLICE], k=9, workers=-1)
        keep[i:i + SLICE] = d[:, 1:].mean(1) < cutoff
    P, C = P[keep], C[keep]
    log(f"outlier removal  {len(P):>10,}   (mean-9NN < {cutoff:.4f})")

    # VOXEL FUSION at one view's native spacing, so overlapping views average
    # instead of stacking.
    vs = view_point_spacing(P, shapes) if shapes else None
    vox = float((vs if vs else nn1) * 1.5)
    src = "one view's grid spacing" if vs else "subsample nearest-neighbour"
    key = np.floor(P / vox).astype(np.int64)
    _, idx, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    del key
    Pf = np.zeros((len(idx), 3)); Cf = np.zeros((len(idx), 3))
    cnt = np.bincount(inv, minlength=len(idx)).astype(np.float64)[:, None]
    np.add.at(Pf, inv, P.astype(np.float64))
    np.add.at(Cf, inv, C.astype(np.float64))
    P = (Pf / cnt).astype(np.float32)
    C = np.clip(Cf / cnt, 0, 255).astype(np.uint8)
    log(f"voxel fusion     {len(P):>10,}   (voxel {vox:.4f} from {src}, "
        f"{cnt.mean():.1f} pts/cell)")
    log(f"extent           {np.round(P.max(0) - P.min(0), 3)}  (scene units)")

    q = P[rng.choice(len(P), min(SUB, len(P)), replace=False)].astype(np.float64)
    s = np.linalg.svd(q - q.mean(0), full_matrices=False)[1]
    log(f"PCA singular     {np.round(s/s[0], 3)}   flatness {s[2]/s[0]:.3f}")
    return P, C, vox, {"conf_available": conf_is_real, "voxel": vox,
                       "voxel_source": src, "nn1": nn1}


def mesh(P, C, vox, *, centres=None, depth=10, trim=0.06, log=print):
    import open3d as o3d
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(P.astype(np.float64))
    pcd.colors = o3d.utility.Vector3dVector(C / 255.0)
    pcd.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=vox * 4, max_nn=30))

    if centres is not None and len(centres):
        cam = np.asarray(centres, float).mean(0)
        log(f"normals oriented toward mean camera centre {np.round(cam, 2)}")
    else:
        # No camera poses: fall back to the thin principal axis, but FIX ITS SIGN
        # against the cloud, because an SVD basis vector's direction is arbitrary and
        # the wrong one builds the surface inside out.
        c = P.mean(0)
        up = np.linalg.svd((P[::37] - c).astype(np.float64), full_matrices=False)[2][-1]
        span = float(np.ptp(P, axis=0).max())
        cam = c + up * span
        log("WARNING no camera poses; using thin-axis fallback with sign unverified")
    pcd.orient_normals_towards_camera_location(np.asarray(cam, float))

    m, dens = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
        pcd, depth=depth, width=0, scale=1.1, linear_fit=False)
    # Poisson closes the surface over unobserved space; cut where it had no support.
    m.remove_vertices_by_mask(np.asarray(dens) < np.quantile(np.asarray(dens), trim))
    m.remove_degenerate_triangles(); m.remove_unreferenced_vertices()
    m.compute_vertex_normals()
    log(f"mesh             {len(m.vertices):>10,} vertices, {len(m.triangles):,} triangles")
    return pcd, m


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("indir"); ap.add_argument("--out", default="out/kolu3d")
    ap.add_argument("--conf-pct", type=float, default=30.0)
    ap.add_argument("--depth", type=int, default=10)
    ap.add_argument("--no-mesh", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    P, C, F, M, cams, meta = load(a.indir)
    centres = camera_centres(cams)
    print(f"cameras          {0 if centres is None else len(centres)}")
    P, C, vox, diag = filter_fuse(P, C, F, M, cams=centres,
                                  shapes=meta.get("view_shapes"),
                                  conf_pct=a.conf_pct)
    np.save(f"{a.out}/points_fused.npy", P)
    np.save(f"{a.out}/colors_fused.npy", C)
    if centres is not None:
        np.save(f"{a.out}/cam_centres.npy", centres)
    json.dump(diag, open(f"{a.out}/fuse_diag.json", "w"), indent=1)

    if not a.no_mesh:
        import open3d as o3d
        pcd, m = mesh(P, C, vox, centres=centres, depth=a.depth)
        o3d.io.write_point_cloud(f"{a.out}/cloud.ply", pcd)
        o3d.io.write_triangle_mesh(f"{a.out}/model.ply", m)
        np.save(f"{a.out}/mesh_v.npy", np.asarray(m.vertices))
        np.save(f"{a.out}/mesh_f.npy", np.asarray(m.triangles))
        np.save(f"{a.out}/mesh_c.npy", (np.asarray(m.vertex_colors) * 255).astype(np.uint8))
    print("wrote", a.out)
