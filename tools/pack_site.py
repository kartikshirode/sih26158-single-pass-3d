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

THUMB_W = 480


def frame_transform(run: str):
    """F4 to the export frame (Z up), and the factor that makes it metres, if any."""
    man = json.load(open(os.path.join(run, "run_manifest.json"), encoding="utf-8"))
    geo = bool(man.get("georeferenced"))
    tf = json.load(open(os.path.join(run, "georef.json" if geo else "level.json"),
                        encoding="utf-8"))
    return man, tf, (lambda X: _apply_frame_json(np.asarray(X, np.float64), tf))


def cameras(run: str, to5, fps: float, f_px: float, w: int, h: int) -> list:
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
                    "file": f"data/frames/{os.path.splitext(name)[0]}.jpg",
                    "p": [round(float(x), 4) for x in P[0]],
                    "f": [round(float(x), 5) for x in f],
                    "u": [round(float(x), 5) for x in u],
                    "fovy": round(fovy, 3), "aspect": round(w / h, 4)})
    return out


def glb_bounds(glb_path: str) -> dict:
    import trimesh
    m = trimesh.load(glb_path, process=False)
    lo, hi = m.bounds
    return {"min": [round(float(x), 4) for x in lo], "max": [round(float(x), 4) for x in hi]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run")
    ap.add_argument("--mesh", help="textured OBJ in the geometry frame to pack instead")
    ap.add_argument("--out", default=os.path.join(ROOT, "web", "data"))
    ap.add_argument("--id", default=None)
    ap.add_argument("--title", default=None)
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

    os.makedirs(os.path.join(a.out, "frames"), exist_ok=True)
    cams = cameras(run, to5, fps, float(cam["f"]), int(cam["w"]), int(cam["h"]))
    for c in cams:
        img = cv2.imread(os.path.join(run, "keyframes", c.pop("name")))
        s = THUMB_W / img.shape[1]
        img = cv2.resize(img, (THUMB_W, max(1, round(img.shape[0] * s))),
                         interpolation=cv2.INTER_AREA)
        cv2.imwrite(os.path.join(a.out, os.path.relpath(c["file"], "data")), img,
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
    with open(glb, "rb") as f:
        data["glb"] = base64.b64encode(f.read()).decode("ascii")
    with open(os.path.join(a.out, "model.js"), "w", encoding="utf-8", newline="\n") as f:
        f.write("window.TESSERACT = ")
        json.dump(data, f, separators=(",", ":"))
        f.write(";\n")
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    size = os.path.getsize(os.path.join(a.out, "model.js")) / 1e6
    print(f"{data['id']}: {len(cams)} cameras, {tri} triangles, {size:.1f} MB -> {a.out}")


if __name__ == "__main__":
    main()
