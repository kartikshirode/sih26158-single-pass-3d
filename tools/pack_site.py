"""
Pack one tesseract run for the web workspace: the textured mesh, the flight and the
keyframe thumbnails, in the form web/SPEC.md describes ("The packed model").

Run:  python tools/pack_site.py out/runs/<run> [--mesh <scene_tex.obj>] [--out web/data]

The page opens from disk, where a browser won't fetch local files, so the mesh travels
inside data/model.js as base64 and the page loads it with a plain script tag. The frame
is the run's export frame turned Y-up, the same as export/model.glb. `--mesh` swaps in
another textured OBJ from the geometry frame (F4), carried through the run's own
level.json or georef.json exactly as S6 carries the mesh.

web/data/ is gitignored: a model of the demo clip is a render of it and stays local.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import shutil
import sys
import tempfile

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from pipeline.local_gpu import frame_order  # noqa: E402
from pipeline.mesh_export import export_textured, z_up_to_y_up  # noqa: E402
from tesseract.stages import _apply_frame_json  # noqa: E402

THUMB_W = 1280


def frame_transform(run: str):
    """F4 to the export frame (Z up), and the factor that makes it metres, if any."""
    man = json.load(open(os.path.join(run, "run_manifest.json"), encoding="utf-8"))
    geo = bool(man.get("georeferenced"))
    tf = json.load(open(os.path.join(run, "georef.json" if geo else "level.json"),
                        encoding="utf-8"))
    return man, tf, (lambda X: _apply_frame_json(np.asarray(X, np.float64), tf))


def cameras(run: str, to5, fps: float, f_px: float, w: int, h: int, prefix: str = "data") -> list:
    """Each registered keyframe camera: time, thumbnail, position, forward and up, Y up."""
    names = sorted((x for x in os.listdir(os.path.join(run, "keyframes"))
                    if x.lower().endswith((".jpg", ".jpeg", ".png"))), key=frame_order)
    M = np.load(os.path.join(run, "cameras.npy"))
    if len(M) != len(names):
        raise ValueError(f"{len(M)} cameras for {len(names)} keyframes")
    fovy = math.degrees(2 * math.atan(h / (2 * f_px)))
    out = []
    for name, c2w in zip(names, M):
        if not np.isfinite(c2w).all():
            continue                                    # a view the mapper did not place
        C = c2w[:3, 3]
        # OpenCV camera axes: z looks forward, y points down the image. Directions go
        # through the same (affine) transform as points, by differences, so the depth
        # stretch and the axis swap act on them as they act on the mesh.
        step = 0.01
        P = to5(np.stack([C, C + step * c2w[:3, 2], C - step * c2w[:3, 1]]))
        P = z_up_to_y_up(P)
        f = P[1] - P[0]
        u = P[2] - P[0]
        f /= np.linalg.norm(f)
        u -= f * float(u @ f)
        u /= np.linalg.norm(u)
        frame = int(re.search(r"_f(\d+)", name).group(1)) if "_f" in name else len(out)
        out.append({"t": round(frame / fps, 3), "name": name,
                    "file": f"{prefix}/frames/{os.path.splitext(name)[0]}.jpg",
                    "p": [round(float(x), 4) for x in P[0]],
                    "f": [round(float(x), 5) for x in f],
                    "u": [round(float(x), 5) for x in u],
                    "fovy": round(fovy, 3), "aspect": round(w / h, 4)})
    return out


def render_sheet(obj_dir: str, run: str, cams: list, out_path: str, width: int = 2400,
                 f_px: float | None = None, prefix: str = "data") -> dict:
    """
    The site drawn as a map sheet, straight down: the textured mesh rendered
    orthographically, contours from the levelled dense cloud, the flight path on top.
    Z-up export frame; the camera list is Y-up, so its (x, -z) is the plan position.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy.ndimage import gaussian_filter, distance_transform_edt
    sys.path.insert(0, HERE)
    from view_check import rasterize
    from build_run_page import read_obj

    V, TU, F, FU, tex = read_obj(os.path.join(obj_dir, "model.obj"))
    atlas = cv2.imread(tex)
    lo, hi = np.percentile(V[:, :2], 0.5, 0), np.percentile(V[:, :2], 99.5, 0)
    pad = 0.03 * (hi - lo)
    lo, hi = lo - pad, hi + pad
    res = (hi[0] - lo[0]) / width
    height = int(np.ceil((hi[1] - lo[1]) / res))
    uv = np.column_stack([(V[:, 0] - lo[0]) / res, (hi[1] - V[:, 1]) / res])
    zr = float(np.ptp(V[:, 2])) or 1.0
    depth = (V[:, 2].max() - V[:, 2]) + 200.0 * zr      # near-orthographic
    img, mask = rasterize(uv, depth, F, FU, TU, atlas, width, height)

    # Where the photos are coarse: rasterise each vertex's pixel footprint through a
    # one-row grey ramp used as the atlas, then read the value back per pixel.
    hatch = None
    if f_px:
        import trimesh
        m = trimesh.Trimesh(V, F, process=False)
        fp = pixel_footprint(z_up_to_y_up(V), z_up_to_y_up(np.asarray(m.vertex_normals)),
                             cams, f_px)
        seen = np.isfinite(fp)
        if seen.any():
            coarse = 4.0 * np.median(fp[seen])
            q = np.where(seen, np.clip(fp / coarse, 0, 2) / 2, 1.0)
            ramp = np.repeat(np.linspace(0, 255, 256, dtype=np.uint8)[None, :, None], 3, 2)
            vt = np.column_stack([q * 255 / 256 + 0.5 / 256, np.full(len(q), 0.5)])
            val, _ = rasterize(uv, depth, F, F, vt, ramp, width, height)
            hatch = (val[..., 0] >= 128) & mask            # footprint over 4x the median

    # Heights for contours: the dense cloud's highest point per cell, holes filled from
    # the nearest cell, smoothed so the lines follow the ground rather than the noise.
    pts_path = os.path.join(run, "points_llf.npy")
    if not os.path.exists(pts_path):
        pts_path = os.path.join(run, "points_geo.npy")
    P = np.load(pts_path, mmap_mode="r")
    step = max(1, len(P) // 3_000_000)
    P = np.asarray(P[::step])
    cell = 4
    gw, gh = width // cell, height // cell
    gx = ((P[:, 0] - lo[0]) / (res * cell)).astype(int)
    gy = ((hi[1] - P[:, 1]) / (res * cell)).astype(int)
    ok = (gx >= 0) & (gx < gw) & (gy >= 0) & (gy < gh)
    Z = np.full((gh, gw), -np.inf)
    np.maximum.at(Z, (gy[ok], gx[ok]), P[ok, 2])
    empty = ~np.isfinite(Z)
    if empty.any() and (~empty).any():
        _, (iy, ix) = distance_transform_edt(empty, return_indices=True)
        Z = Z[iy, ix]
    Z = gaussian_filter(Z, 5.0)
    covered = cv2.resize(mask.astype(np.uint8), (gw, gh), interpolation=cv2.INTER_NEAREST) > 0
    Zm = np.where(covered, Z, np.nan)
    zlo, zhi = np.nanpercentile(Zm, 1), np.nanpercentile(Zm, 99)
    raw = (zhi - zlo) / 14
    mag = 10 ** np.floor(np.log10(raw))
    interval = float(min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=raw))

    film = np.array([235, 237, 232], np.float32)
    base = img.astype(np.float32)
    base[~mask] = film
    base = (0.82 * base + 0.18 * film)                  # a little paper under the photo
    dpi = 100
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(cv2.cvtColor(base.astype(np.uint8), cv2.COLOR_BGR2RGB),
              extent=[0, width, height, 0], interpolation="lanczos")
    yy, xx = np.mgrid[0:gh, 0:gw] * cell + cell / 2
    levels = np.arange(np.floor(zlo / interval) * interval, zhi + interval, interval)
    idx = [lv for lv in levels if round(lv / interval) % 5 == 0]
    ax.contour(xx, yy, Zm, levels=levels, colors="#7A4E26", linewidths=0.9, alpha=0.9)
    ax.contour(xx, yy, Zm, levels=idx, colors="#7A4E26", linewidths=2.0)
    if hatch is not None and hatch.any():
        # Hatched, as a map marks an unsurveyed area: the ground here was only ever seen
        # coarsely, at a grazing angle or from far away.
        from matplotlib.colors import ListedColormap
        yy2, xx2 = np.mgrid[0:height, 0:width]
        lines = ((xx2 + yy2) % 18) < 3
        layer = np.where(hatch & lines, 1.0, np.nan)
        ax.imshow(layer, extent=[0, width, height, 0], cmap=ListedColormap(["#1F2629"]),
                  alpha=0.45, interpolation="nearest")
    fx = [(c["p"][0] - lo[0]) / res for c in cams]
    fy = [(hi[1] + c["p"][2]) / res for c in cams]
    ax.plot(fx, fy, color="#1F2629", linewidth=5, solid_capstyle="round")
    for c in cams:
        if abs(c["t"] - round(c["t"])) < 0.06:        # a tick each second
            ax.plot((c["p"][0] - lo[0]) / res, (hi[1] + c["p"][2]) / res, "o",
                    color="#1F2629", markersize=10)
    ax.set_xlim(0, width)
    ax.set_ylim(height, 0)
    ax.axis("off")
    fig.savefig(out_path, dpi=dpi, pil_kwargs={"quality": 88})
    plt.close(fig)
    return {"file": f"{prefix}/" + os.path.basename(out_path), "width": width, "height": height,
            "hatched_fraction": round(float(hatch.sum() / max(1, mask.sum())), 4)
            if hatch is not None else None,
            "units_per_px": round(float(res), 6), "contour_interval": interval,
            "extent": [round(float(x), 3) for x in (*lo, *hi)]}


def pixel_footprint(V: np.ndarray, N: np.ndarray, cams: list, f_px: float) -> np.ndarray:
    """
    For points V with normals N (both Y-up, the cameras' frame): the finest surface size
    one photo pixel covers, over every keyframe whose frame holds the point,
    dist / (f * cos(incidence)); inf where none does.
    """
    P = np.array([c["p"] for c in cams])
    Fw = np.array([c["f"] for c in cams])
    U = np.array([c["u"] for c in cams])
    R = np.cross(Fw, U)
    tan_y = np.tan(np.radians(cams[0]["fovy"]) / 2)
    tan_x = tan_y * cams[0]["aspect"]
    best = np.full(len(V), np.inf)
    for a in range(0, len(V), 20000):
        v, n = V[a:a + 20000], N[a:a + 20000]
        d = v[:, None, :] - P[None, :, :]                    # camera to point
        z = np.einsum("vck,ck->vc", d, Fw)
        x = np.einsum("vck,ck->vc", d, R)
        y = np.einsum("vck,ck->vc", d, U)
        inside = (z > 0) & (np.abs(x) < z * tan_x) & (np.abs(y) < z * tan_y)
        dist = np.linalg.norm(d, axis=2)
        cos = np.abs(np.einsum("vck,vk->vc", d, n)) / np.maximum(dist, 1e-12)
        upp = dist / (f_px * np.maximum(cos, 0.05))
        upp[~inside] = np.inf
        best[a:a + 20000] = upp.min(1)
    return best


def detail_map(glb_path: str, cams: list, f_px: float, w: int, h: int) -> dict:
    """
    Per vertex of the GLB, in its own accessor order: the finest size one photo pixel
    covers on the surface there, over every keyframe that sees it inside its frame,
    dist / (f * cos(incidence)). Small where the drone flew close and square on; large on
    the far field seen at a grazing angle, where no measurement should be trusted.
    Packed as uint8 on a log scale between lo and hi (model units per pixel).
    """
    import trimesh
    scene = trimesh.load(glb_path, process=False)
    meshes = list(scene.geometry.values()) if hasattr(scene, "geometry") else [scene]
    out = [pixel_footprint(np.asarray(m.vertices, np.float64),
                           np.asarray(m.vertex_normals, np.float64), cams, f_px)
           for m in meshes]
    allv = np.concatenate(out)
    seen = np.isfinite(allv)
    lo, hi = np.percentile(allv[seen], [2, 98]) if seen.any() else (1e-3, 1.0)
    q = np.where(seen, (np.log(np.clip(allv, lo, hi)) - np.log(lo)) / (np.log(hi) - np.log(lo)), 1)
    b = np.clip(np.round(q * 254), 0, 254).astype(np.uint8)
    b[~seen] = 255                                           # seen by no keyframe frame
    return {"b64": base64.b64encode(b.tobytes()).decode("ascii"),
            "counts": [len(o) for o in out], "lo": float(lo), "hi": float(hi),
            "median": float(np.median(allv[seen])) if seen.any() else None}


def glb_bounds(glb_path: str) -> dict:
    import trimesh
    m = trimesh.load(glb_path, process=False)
    lo, hi = m.bounds
    return {"min": [round(float(x), 4) for x in lo], "max": [round(float(x), 4) for x in hi]}


def register(prefix: str, data: dict):
    """List the packed models in web/data/models.js for the pages' model switcher."""
    path = os.path.join(ROOT, "web", "data", "models.js")
    models = []
    if os.path.exists(path):
        txt = open(path, encoding="utf-8").read()
        models = json.loads(txt[txt.index("=") + 1:].strip().rstrip(";"))
    models = [m for m in models if m["src"] != f"{prefix}/model.js"]
    models.append({"id": data["id"], "title": data["title"], "src": f"{prefix}/model.js",
                   "units": data["units"], "georef": bool(data["georef"])})
    models.sort(key=lambda m: (m["src"] != "data/model.js", m["title"]))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("window.TESSERACT_MODELS = " + json.dumps(models, indent=1) + ";\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run")
    ap.add_argument("--mesh", help="textured OBJ in the geometry frame to pack instead")
    ap.add_argument("--out", default=os.path.join(ROOT, "web", "data"))
    ap.add_argument("--id", default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--no-sheet", action="store_true", help="skip the plan-view map sheet")
    a = ap.parse_args()

    run = os.path.abspath(a.run)
    man, tf, to5 = frame_transform(run)
    ingest = json.load(open(os.path.join(run, "ingest.json"), encoding="utf-8"))
    stats = ingest["stats"]
    fps = float(stats.get("fps") or 30.0)
    geo_res = json.load(open(os.path.join(run, "geometry", "local_gpu_result.json"),
                             encoding="utf-8"))
    cam = geo_res["camera"]

    tmp = None
    glb = os.path.join(run, "export", "model.glb")
    if a.mesh:
        tmp = tempfile.mkdtemp(prefix="pack-")
        paths, notes = export_textured(a.mesh, tmp, to5)
        if "glb" not in paths:
            raise SystemExit(f"GLB export failed: {notes}")
        glb = paths["glb"]

    obj_dir = os.path.dirname(glb)
    os.makedirs(os.path.join(a.out, "frames"), exist_ok=True)
    # Paths in the data are relative to web/, where the pages sit.
    prefix = os.path.relpath(os.path.abspath(a.out), os.path.join(ROOT, "web")).replace(os.sep, "/")
    cams = cameras(run, to5, fps, float(cam["f"]), int(cam["w"]), int(cam["h"]), prefix)
    for c in cams:
        img = cv2.imread(os.path.join(run, "keyframes", c.pop("name")))
        s = THUMB_W / img.shape[1]
        img = cv2.resize(img, (THUMB_W, max(1, round(img.shape[0] * s))),
                         interpolation=cv2.INTER_AREA)
        cv2.imwrite(os.path.join(a.out, os.path.relpath(c["file"], prefix)), img,
                    [cv2.IMWRITE_JPEG_QUALITY, 82])

    metres = man.get("units") == "metres"
    scale = man.get("scale") or {}
    georef = None
    if man.get("georeferenced") and "enu_reference" in tf:
        ref = tf["enu_reference"]
        georef = {"lat0": ref["latitude"], "lon0": ref["longitude"],
                  "h0": ref["height"] if isinstance(ref["height"], (int, float)) else 0.0,
                  "height_note": None if isinstance(ref["height"], (int, float))
                  else str(ref["height"])}
    frames_decoded = stats.get("frames_decoded") or 0
    duration = round(frames_decoded / fps, 2) if frames_decoded else cams[-1]["t"]
    tri = None
    try:
        import trimesh
        tri = int(len(trimesh.load(glb, force="mesh", process=False).faces))
    except Exception:
        pass
    data = {
        "id": a.id or os.path.basename(run),
        "title": a.title or stats.get("video") or os.path.basename(run),
        "subtitle": (f"{duration:.1f} s single pass, {stats.get('keyframes_selected')} keyframes, "
                     f"{float(man['seconds']):.0f} s to reconstruct"),
        "units": "metres" if metres else "model units",
        "scale": {"factor": 1.0,
                  "status": "gnss" if metres else scale.get("status", "unvalidated"),
                  "label": scale.get("label") or ""},
        "georef": georef,
        "bounds": glb_bounds(glb),
        "duration": duration,
        "stats": {"wall_s": round(float(man["seconds"]), 1), "keyframes": len(cams),
                  "triangles": tri, "dense_points": geo_res.get("dense_points"),
                  "level": man.get("level"), "frame": man.get("frame")},
        "cameras": cams,
    }
    data["detail"] = detail_map(glb, cams, float(cam["f"]), int(cam["w"]), int(cam["h"]))
    if not a.no_sheet:
        data["sheet"] = render_sheet(obj_dir, run, cams, os.path.join(a.out, "sheet.jpg"),
                                     f_px=float(cam["f"]), prefix=prefix)
    with open(glb, "rb") as f:
        data["glb"] = base64.b64encode(f.read()).decode("ascii")
    with open(os.path.join(a.out, "model.js"), "w", encoding="utf-8", newline="\n") as f:
        f.write("window.TESSERACT = ")
        json.dump(data, f, separators=(",", ":"))
        f.write(";\n")
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    register(prefix, data)
    size = os.path.getsize(os.path.join(a.out, "model.js")) / 1e6
    print(f"{data['id']}: {len(cams)} cameras, {tri} triangles, {size:.1f} MB -> {a.out}")


if __name__ == "__main__":
    main()
