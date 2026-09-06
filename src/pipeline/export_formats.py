"""
S5 - write the reconstruction in every format the PS asks for.

Required: OBJ, PLY, LAS, GeoTIFF, glb/gltf, fbx. All six have permissive routes, so
none of this needs a proprietary SDK.

The one that needs thought is GeoTIFF, because a GeoTIFF is a *georeferenced* raster and
neither test clip has GNSS. Writing one anyway with a fabricated CRS would be the worst
option: it would look georeferenced and be wrong, and downstream GIS would silently
reproject nonsense. So the DEM is written in a local ENU frame with a real, honest
geotransform in metres and **no CRS**, plus a sidecar recording exactly that. When GNSS
or ground control arrives, `crs=` and `origin=` are the only two things that change.

The vertical comes from `gravity.estimate`, which validates the terrain normal against
the gimbal's roll-zero constraint - without a trustworthy vertical a DEM is meaningless,
which is why that had to be settled first.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import numpy as np

FORMATS = ("ply", "obj", "glb", "gltf", "las", "tif", "fbx")


def _o3d_mesh(V, F, C):
    import open3d as o3d
    m = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(np.asarray(V, float)),
                                  o3d.utility.Vector3iVector(np.asarray(F, np.int32)))
    if C is not None and len(C):
        m.vertex_colors = o3d.utility.Vector3dVector(np.asarray(C, float)[:, :3] / 255.0)
    m.compute_vertex_normals()
    return m


def write_mesh_formats(out, V, F, C, log=print):
    """PLY, OBJ, GLB and glTF. `V` must already be in the shared export frame."""
    import open3d as o3d
    m = _o3d_mesh(V, F, C)
    o3d.io.write_triangle_mesh(f"{out}/model.ply", m)
    # OBJ carries vertex colours only as a non-standard extension; write an MTL-less
    # OBJ and keep the colours in the PLY/GLB, which express them properly.
    o3d.io.write_triangle_mesh(f"{out}/model.obj", m, write_vertex_colors=False)
    log(f"  model.ply / model.obj  {len(V):,} v, {len(F):,} f")

    import trimesh
    # glTF's spec is Y-up, the geospatial outputs are Z-up ENU. Swap here rather than
    # shipping two files that disagree about which way is up.
    Vg = np.asarray(V, float)[:, [0, 2, 1]].copy()
    Vg[:, 2] *= -1.0
    tm = trimesh.Trimesh(vertices=Vg, faces=np.asarray(F, np.int64), process=False)
    if C is not None and len(C):
        rgba = np.hstack([np.asarray(C, np.uint8)[:, :3],
                          np.full((len(C), 1), 255, np.uint8)])
        tm.visual = trimesh.visual.ColorVisuals(mesh=tm, vertex_colors=rgba)
    tm.export(f"{out}/model.glb")
    tm.export(f"{out}/model.gltf")
    log(f"  model.glb / model.gltf  {os.path.getsize(out+'/model.glb')/1e6:.1f} MB")


def write_fbx(out, log=print):
    """FBX via the assimp CLI (BSD-3). No SDK, no licence question.

    Deliberately not a hand-rolled FBX writer: the ASCII flavour is easy to emit and
    Blender will not read it, so it would be a format we can claim and nobody can open.
    """
    exe = shutil.which("assimp")
    if not exe:
        log("  model.fbx  SKIPPED - assimp CLI not on PATH "
            "(apt install assimp-utils; it is in the container)")
        return False
    r = subprocess.run([exe, "export", f"{out}/model.ply", f"{out}/model.fbx", "-ffbx"],
                       capture_output=True, text=True)
    if r.returncode or not os.path.exists(f"{out}/model.fbx"):
        log(f"  model.fbx  FAILED rc={r.returncode} {(r.stderr or r.stdout)[:160]}")
        return False
    log(f"  model.fbx  {os.path.getsize(out+'/model.fbx')/1e6:.1f} MB")
    return True


def write_las(out, xyz, C, log=print):
    """LAS 1.4 point format 3 (RGB). `xyz` is already east/north/up in metres."""
    import laspy
    xyz = np.asarray(xyz, float)

    hdr = laspy.LasHeader(point_format=3, version="1.4")
    hdr.offsets = xyz.min(0)
    hdr.scales = np.array([0.001, 0.001, 0.001])            # 1 mm, below our precision
    las = laspy.LasData(hdr)
    las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    if C is not None and len(C):
        c = np.asarray(C)
        c = (c * 255 if c.max() <= 1.0 else c).astype(np.uint16) * 257   # LAS is 16-bit
        las.red, las.green, las.blue = c[:, 0], c[:, 1], c[:, 2]
    las.write(f"{out}/cloud.las")
    log(f"  cloud.las  {len(xyz):,} points, {os.path.getsize(out+'/cloud.las')/1e6:.1f} MB")


def write_dem(out, xyz, gsd=0.10, log=print):
    """
    Digital surface model as a GeoTIFF: max height per cell, in local metres.

    NO CRS is attached, on purpose - see the module docstring. The geotransform is real
    (north-up, `gsd` metres per pixel, origin at the cloud's own corner), so the raster
    is internally consistent and measurable; it simply is not on the Earth yet.
    """
    import rasterio
    from rasterio.transform import from_origin
    xyz = np.asarray(xyz, float)
    e, n, h = xyz[:, 0], xyz[:, 1], xyz[:, 2]

    w = int(np.ceil(np.ptp(e) / gsd)) + 1
    ht = int(np.ceil(np.ptp(n) / gsd)) + 1
    ix = np.clip(((e - e.min()) / gsd).astype(int), 0, w - 1)
    iy = np.clip(((n.max() - n) / gsd).astype(int), 0, ht - 1)   # north-up raster
    dem = np.full(ht * w, np.nan, np.float32)
    flat = iy * w + ix
    order = np.argsort(h)                    # ascending, so the last write is the max
    np.put(dem, flat[order], h[order].astype(np.float32))
    dem = dem.reshape(ht, w)
    filled = np.isfinite(dem).mean()

    with rasterio.open(f"{out}/dem.tif", "w", driver="GTiff", height=ht, width=w,
                       count=1, dtype="float32", nodata=np.nan, crs=None,
                       transform=from_origin(0.0, ht * gsd, gsd, gsd),
                       compress="deflate") as ds:
        ds.write(dem, 1)
        ds.update_tags(VERTICAL="local gravity-aligned, metres above cloud centroid",
                       CRS_STATUS="NONE - not georeferenced, no GNSS in source clip",
                       GSD_M=str(gsd))
    log(f"  dem.tif  {w}x{ht} at {gsd*100:.0f} cm/px, {filled:.0%} of cells filled, "
        f"relief {np.nanmax(dem)-np.nanmin(dem):.2f} m  [NO CRS - not georeferenced]")
    return {"width": w, "height": ht, "gsd_m": gsd, "filled_fraction": round(float(filled), 4),
            "crs": None, "reason_no_crs": "source clip has no GNSS"}


def export_all(out, points, colors, V, F, C, cams=None, gsd=0.10, log=print):
    os.makedirs(out, exist_ok=True)
    from gravity import estimate, frame
    g = estimate(cams, points, log=log) if cams is not None else None
    up = g["up"] if g else np.array([0.0, 1.0, 0.0])

    # ONE frame for every output. The first version rotated only the point-derived
    # products, so model.obj and cloud.las came out in different orientations - a file
    # set that looks complete and does not overlay.
    B = frame(up)
    origin = np.asarray(points, float).mean(0)
    to_enu = lambda A: ((np.asarray(A, float) - origin) @ B.T)[:, [0, 2, 1]]
    P_enu = to_enu(points)
    V_enu = to_enu(V)

    write_mesh_formats(out, V_enu, F, C, log=log)
    fbx = write_fbx(out, log=log)
    write_las(out, P_enu, colors, log=log)
    dem = write_dem(out, P_enu, gsd=gsd, log=log)

    manifest = {
        "formats": {f: os.path.exists(f"{out}/{n}") for f, n in
                    (("ply", "model.ply"), ("obj", "model.obj"), ("glb", "model.glb"),
                     ("gltf", "model.gltf"), ("las", "cloud.las"),
                     ("geotiff", "dem.tif"), ("fbx", "model.fbx"))},
        "dem": dem,
        "gravity": {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                    for k, v in (g or {}).items()},
        "georeferenced": False,
        "note": ("Coordinates are a local gravity-aligned ENU frame in metres, origin at "
                 "the cloud centroid. No CRS is attached because the source clip carries "
                 "no GNSS; attaching one would make the output look georeferenced and be "
                 "wrong."),
    }
    json.dump(manifest, open(f"{out}/export_manifest.json", "w"), indent=2)
    have = [k for k, v in manifest["formats"].items() if v]
    log(f"\n  wrote {len(have)}/7: {', '.join(have)}")
    return manifest


if __name__ == "__main__":
    import argparse
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser()
    ap.add_argument("indir", help="dir with points_fused.npy / mesh_*.npy")
    ap.add_argument("--cameras", default=None, help="cameras.npy for the gravity check")
    ap.add_argument("--out", default=None)
    ap.add_argument("--gsd", type=float, default=0.10)
    a = ap.parse_args()
    out = a.out or os.path.join(a.indir, "export")
    P = np.load(f"{a.indir}/points_fused.npy").astype(np.float64)
    C0 = np.load(f"{a.indir}/colors_fused.npy")
    V = np.load(f"{a.indir}/mesh_v.npy")
    F = np.load(f"{a.indir}/mesh_f.npy")
    Cv = np.load(f"{a.indir}/mesh_c.npy")
    cams = np.load(a.cameras) if a.cameras and os.path.exists(a.cameras) else None
    export_all(out, P, C0, V, F, Cv, cams=cams, gsd=a.gsd)
