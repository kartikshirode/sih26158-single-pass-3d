"""
S3/S4 - turn raw per-view point maps into a surface.

Concatenating per-view point maps is not a reconstruction. MapAnything emits one
depth map per view in a shared frame; overlapping views therefore print the same
surface two or three times, each copy offset by its own error, and the result reads
as a smear even when every individual view is correct. The stages here are what turn
that into geometry, in the order that matters:

  conf     the model's own per-point confidence. The first attempt discarded this
           channel entirely, which left nothing to filter on.
  valid    the non-ambiguous mask - sky, and regions the model declines to commit to.
  range    only where the depth distribution actually HAS a far-field tail. On
           bounded survey footage it does not, and a blanket percentile cut throws
           away a third of the scene for nothing.
  sor      statistical outlier removal against local neighbour distance.
  fuse     voxel averaging, so overlapping views average instead of triple-printing.
  mesh     screened Poisson. Normals must be oriented toward the camera side or the
           surface comes out inside-out and renders black.
"""
from __future__ import annotations
import argparse, json, os
import numpy as np
from scipy.spatial import cKDTree


def load(d: str):
    P = np.load(f"{d}/points.npy").astype(np.float64)
    C = np.load(f"{d}/colors.npy")
    F = np.load(f"{d}/conf.npy") if os.path.exists(f"{d}/conf.npy") else np.ones(len(P), np.float32)
    M = np.load(f"{d}/mask.npy") if os.path.exists(f"{d}/mask.npy") else np.ones(len(P), bool)
    n = min(len(P), len(C), len(F), len(M))
    return P[:n], C[:n], F[:n], M[:n]


def filter_fuse(P, C, F, M, *, conf_pct=30.0, sor_sigma=1.2, log=print):
    log(f"raw              {len(P):>10,}")
    ok = np.isfinite(P).all(1) & M
    P, C, F = P[ok], C[ok], F[ok]
    log(f"finite + valid   {len(P):>10,}")

    thr = np.percentile(F, conf_pct)
    g = F >= thr
    P, C = P[g], C[g]
    log(f"confidence       {len(P):>10,}   (conf >= {thr:.3f}, dropped {conf_pct:.0f}%)")

    cen = np.median(P, axis=0)
    r = np.linalg.norm(P - cen, axis=1)
    p50, p99 = np.percentile(r, [50, 99])
    tail = p99 / max(p50, 1e-9)
    if tail > 6.0:
        g = r <= np.percentile(r, 90)
        P, C = P[g], C[g]
        log(f"range gate       {len(P):>10,}   (tail ratio {tail:.1f} - far field cut)")
    else:
        log(f"range gate       {'skipped':>10}   (tail ratio {tail:.1f}, scene is bounded)")

    rng = np.random.default_rng(0)
    sub = P[rng.choice(len(P), min(200_000, len(P)), replace=False)]
    dd, _ = cKDTree(sub).query(P, k=9, workers=-1)
    md = dd[:, 1:].mean(1)
    g = md < md.mean() + sor_sigma * md.std()
    P, C, dd = P[g], C[g], dd[g]
    log(f"outlier removal  {len(P):>10,}")

    vox = float(np.percentile(dd[:, 1], 55) * 1.4)
    key = np.floor(P / vox).astype(np.int64)
    _, idx, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    Pf = np.zeros((len(idx), 3)); Cf = np.zeros((len(idx), 3))
    cnt = np.bincount(inv, minlength=len(idx)).astype(float)[:, None]
    np.add.at(Pf, inv, P); np.add.at(Cf, inv, C.astype(float))
    P, C = Pf / cnt, np.clip(Cf / cnt, 0, 255).astype(np.uint8)
    log(f"voxel fusion     {len(P):>10,}   (voxel {vox:.4f}, mean {cnt.mean():.1f} views/cell)")
    log(f"extent           {np.round(P.max(0) - P.min(0), 2)}")

    s = np.linalg.svd(P[::7] - P[::7].mean(0), full_matrices=False)[1]
    log(f"PCA singular     {np.round(s/s[0], 3)}   flatness {s[2]/s[0]:.3f}")
    return P, C, vox


def mesh(P, C, vox, cam=None, depth=10, trim=0.06, log=print):
    import open3d as o3d
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(P)
    pcd.colors = o3d.utility.Vector3dVector(C / 255.0)
    pcd.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=vox * 4, max_nn=30))
    if cam is None:
        # Thinnest principal axis of a near-planar survey scene is the up direction.
        up = np.linalg.svd(P[::37] - P.mean(0), full_matrices=False)[2][-1]
        cam = P.mean(0) + up * float(np.ptp(P, axis=0).max())
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
    ap.add_argument("--no-mesh", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    P, C, F, M = load(a.indir)
    P, C, vox = filter_fuse(P, C, F, M, conf_pct=a.conf_pct)
    np.save(f"{a.out}/points_fused.npy", P.astype(np.float32))
    np.save(f"{a.out}/colors_fused.npy", C)
    if not a.no_mesh:
        import open3d as o3d
        pcd, m = mesh(P, C, vox)
        o3d.io.write_point_cloud(f"{a.out}/cloud.ply", pcd)
        o3d.io.write_triangle_mesh(f"{a.out}/model.ply", m)
        np.save(f"{a.out}/mesh_v.npy", np.asarray(m.vertices))
        np.save(f"{a.out}/mesh_f.npy", np.asarray(m.triangles))
        np.save(f"{a.out}/mesh_c.npy", (np.asarray(m.vertex_colors)*255).astype(np.uint8))
    print("wrote", a.out)
