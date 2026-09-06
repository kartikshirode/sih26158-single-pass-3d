"""
Pull the MVS result off GCS and take it to renders, a viewer, and a verdict.

Converts OpenMVS's PLY output into the same .npy layout the existing render and
viewer stages already consume, so the two reconstructions are drawn by identical
code and any visible difference is a difference in the geometry rather than in the
plotting.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = os.environ.get("RUN", "ytd")
GCS = os.environ.get("GCS_PREFIX", "mvs/ytd_out")
BASE = os.environ.get("BASELINE", "ytd3d")          # the feed-forward result
RAW = os.path.join(ROOT, "out", f"{NAME}_mvs")
OUT = os.path.join(ROOT, "out", f"{NAME}mvs3d")
PY311 = r"C:\Users\Mandar\AppData\Local\Programs\Python\Python311\python.exe"


def sh(*a, check=True):
    print("  $", " ".join(str(x) for x in a[:4]), "...")
    r = subprocess.run([str(x) for x in a], capture_output=True, text=True)
    if r.stdout.strip():
        print("\n".join("    " + l for l in r.stdout.strip().splitlines()))
    if r.returncode and check:
        print(r.stderr[-2500:])
        sys.exit(f"failed: {a[0]}")
    return r.stdout


def main():
    os.makedirs(RAW, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    # Guard on EVERY artefact, not just the cloud. Pulling scene_dense.ply early to
    # look at the numbers used to satisfy this check and silently skip the mesh, so
    # the run finished "successfully" with no mesh and the viewer then died on a
    # missing model.ply.
    need = ("scene_dense.ply", "scene_dense_mesh.ply", "mvs_result.json")
    if not all(os.path.exists(os.path.join(RAW, f)) for f in need):
        subprocess.run(f"gsutil -m cp gs://sih26158-mumbai/{GCS}/* " + RAW,
                       shell=True, check=True)

    rp = os.path.join(RAW, "mvs_result.json")
    if os.path.exists(rp):
        r = json.load(open(rp))
        print("\nMVS run:")
        for k in ("n_images", "full_frame", "model_grid",
                  "intrinsics_fit_residual_px", "resolution_level", "total_seconds"):
            if k in r:
                print(f"  {k:28s} {r[k]}")
        for label in ("sparse_after_triangulation", "sparse_after_bundle_adjustment"):
            if r.get(label):
                print(f"  {label}:")
                for k, v in r[label].items():
                    print(f"      {k:32s} {v}")
        print("\n  stage timings:")
        for s in r.get("stages", []):
            print(f"      {s['stage']:34s} {s['seconds']:>8.1f}s  rc={s['rc']}")

    import open3d as o3d
    dense = os.path.join(RAW, "scene_dense.ply")
    pcd = o3d.io.read_point_cloud(dense)
    P = np.asarray(pcd.points, np.float64)
    C = (np.asarray(pcd.colors) * 255).astype(np.uint8) if pcd.has_colors() \
        else np.full((len(P), 3), 200, np.uint8)
    print(f"\ndense cloud  {len(P):,} points   colours: {pcd.has_colors()}")
    np.save(f"{OUT}/points_fused.npy", P.astype(np.float32))
    np.save(f"{OUT}/colors_fused.npy", C)

    # Reuse the baseline's camera centres to orient the vertical: MVS inherits
    # MapAnything's frame (bundle adjustment refines it but does not reframe it),
    # so the two renders stay directly comparable.
    cc = os.path.join(ROOT, "out", BASE, "cam_centres.npy")
    if os.path.exists(cc):
        np.save(f"{OUT}/cam_centres.npy", np.load(cc))

    # Mesh: prefer the textured one, then the refined, then the plain reconstruction.
    mesh = None
    for cand in ("scene_dense_mesh_refine_texture.ply", "scene_dense_mesh_texture.ply",
                 "scene_dense_mesh_refine.ply", "scene_dense_mesh.ply"):
        if os.path.exists(os.path.join(RAW, cand)):
            mesh = os.path.join(RAW, cand)
            break
    if mesh:
        m = o3d.io.read_triangle_mesh(mesh)
        V = np.asarray(m.vertices)
        F = np.asarray(m.triangles)
        print(f"mesh {os.path.basename(mesh)}  {len(V):,} vertices, {len(F):,} triangles")
        if m.has_vertex_colors():
            VC = (np.asarray(m.vertex_colors) * 255).astype(np.uint8)
        else:
            # ReconstructMesh emits geometry only. Colour each vertex from the
            # nearest dense point rather than shipping a grey mesh, which would make
            # the comparison against the baseline render meaningless.
            from scipy.spatial import cKDTree
            sub = np.random.default_rng(0).choice(
                len(P), min(2_000_000, len(P)), replace=False)
            _, idx = cKDTree(P[sub]).query(V, k=1, workers=-1)
            VC = C[sub][idx]
        np.save(f"{OUT}/mesh_v.npy", V)
        np.save(f"{OUT}/mesh_f.npy", F)
        np.save(f"{OUT}/mesh_c.npy", VC)
        # build_viewer.py reads model.ply, so write the coloured mesh back out under
        # the name the packer expects rather than teaching it a second layout.
        m.vertex_colors = o3d.utility.Vector3dVector(VC.astype(np.float64) / 255.0)
        o3d.io.write_triangle_mesh(f"{OUT}/model.ply", m)
    else:
        print("no mesh in the output - rendering the cloud only")

    print("\nrender:")
    sh(PY311, os.path.join(ROOT, "src", "pipeline", "render_views.py"), OUT,
       "--out", os.path.join(OUT, "render.png"))

    print("\ncompare against the feed-forward baseline:")
    sh(PY311, os.path.join(ROOT, "src", "analysis", "compare_mvs.py"),
       "--baseline", os.path.join(ROOT, "out", BASE, "points_fused.npy"),
       "--mvs", dense)

    stats = {
        "title": os.environ.get("TITLE", "Village pass - MVS"),
        "subtitle": os.environ.get(
            "SUBTITLE",
            "Single-pass drone video to 3D. Geometry from per-pixel photometric MVS "
            "at full keyframe resolution; the feed-forward model supplied only the "
            "camera poses and metric scale."),
        # Read the counts off the run rather than hard-coding them. The first version
        # carried the Short's "42 keyframes, 1080x1250" into the Kolu viewer, which
        # actually used 45 at 1920x1080.
        "ingest": [["keyframes", str(r.get("n_images", "?")) if os.path.exists(rp) else "?"],
                   ["frame", "x".join(str(v) for v in r["full_frame"])
                    if os.path.exists(rp) else "?"],
                   ["poses", "MapAnything, bundle-adjusted"]],
        "funnel": [["dense points", f"{len(P):,}"],
                   ["mesh triangles", f"{len(F):,}" if mesh else "-"]],
        "geom": [["geometry", "OpenMVS PatchMatch (per-pixel)"],
                 ["mesh", "Delaunay + graph cut"],
                 ["reproj, triangulated",
                  (r.get("sparse_after_triangulation") or {}).get(
                      "Mean reprojection error", "-") if os.path.exists(rp) else "-"],
                 ["reproj, after BA",
                  (r.get("sparse_after_bundle_adjustment") or {}).get(
                      "Mean reprojection error", "-") if os.path.exists(rp) else "-"]],
        "caveat": ("Geometry is per-pixel photometric MVS at full keyframe resolution; "
                   "the feed-forward model supplied only the camera poses and metric "
                   "scale. <b>No GPS in this clip</b>, so the result is metric-relative, "
                   "not georeferenced."),
    }
    sp = os.path.join(OUT, "viewer_stats.json")
    json.dump(stats, open(sp, "w"), indent=1)
    print("\nexports:")
    cams_p = os.path.join(ROOT, "out", f"{NAME}_raw", "cameras.npy")
    sh(PY311, os.path.join(ROOT, "src", "pipeline", "export_formats.py"), OUT,
       *(["--cameras", cams_p] if os.path.exists(cams_p) else []),
       "--out", os.path.join(OUT, "export"), check=False)

    print("\npack:")
    sh(PY311, os.path.join(ROOT, "tools", "build_viewer.py"), OUT,
       "--stats", sp, "--out", os.path.join(OUT, "viewer.html"))
    print("\ndone ->", OUT)


if __name__ == "__main__":
    main()
