"""Score a textured mesh against keyframes withheld from its dense reconstruction.

Run: python tools/view_check.py out/runs/<run> --build

The sparse mapper still sees every view. Every tenth view, starting at index 9,
is excluded from OpenMVS densification and texturing. The mesh is rendered at a
quarter of the keyframe width. Scores use only pixels hit by the mesh; coverage
is reported over the whole keyframe so missing surfaces cannot help the score.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import cv2
import numpy as np
from numba import njit
from skimage.metrics import structural_similarity

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
from pipeline.local_gpu import frame_order, read_images_txt, run as run_geometry  # noqa: E402
from build_run_page import read_obj  # noqa: E402


def project_points(points: np.ndarray, camera_to_world: np.ndarray,
                   intrinsics: tuple[float, float, float, float]):
    """Project F4 world points into an OpenCV image; depth is in model units."""
    fx, fy, cx, cy = intrinsics
    camera = (points - camera_to_world[:3, 3]) @ camera_to_world[:3, :3]
    depth = camera[:, 2]
    safe = np.where(np.abs(depth) < 1e-12, np.nan, depth)
    uv = np.column_stack((fx * camera[:, 0] / safe + cx,
                          fy * camera[:, 1] / safe + cy))
    return uv, depth


def read_camera(path: str):
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        if parts[1] == "SIMPLE_PINHOLE":        # one focal length, refined by the mapper
            f, cx, cy = map(float, parts[4:7])
            return int(parts[2]), int(parts[3]), (f, f, cx, cy)
        if parts[1] != "PINHOLE":
            raise ValueError(f"Expected a pinhole camera, got {parts[1]}")
        return int(parts[2]), int(parts[3]), tuple(map(float, parts[4:8]))
    raise ValueError(f"No camera in {path}")


@njit(cache=True)
def rasterize(uv, depth, faces, face_uv, tex_uv, atlas, width, height):
    """Z-buffered triangle raster with perspective-correct atlas coordinates."""
    img = np.zeros((height, width, 3), np.uint8)
    zbuf = np.full((height, width), np.inf)
    th, tw = atlas.shape[:2]
    for fi in range(len(faces)):
        a, b, c = faces[fi]
        z0, z1, z2 = depth[a], depth[b], depth[c]
        if min(z0, z1, z2) <= 1e-6:
            continue
        x0, y0 = uv[a]
        x1, y1 = uv[b]
        x2, y2 = uv[c]
        if not (np.isfinite(x0) and np.isfinite(x1) and np.isfinite(x2)
                and np.isfinite(y0) and np.isfinite(y1) and np.isfinite(y2)):
            continue
        xmin = max(0, int(np.floor(min(x0, x1, x2))))
        xmax = min(width - 1, int(np.ceil(max(x0, x1, x2))))
        ymin = max(0, int(np.floor(min(y0, y1, y2))))
        ymax = min(height - 1, int(np.ceil(max(y0, y1, y2))))
        if xmin > xmax or ymin > ymax:
            continue
        den = (y1-y2)*(x0-x2) + (x2-x1)*(y0-y2)
        if abs(den) < 1e-9:
            continue
        t0, t1, t2 = face_uv[fi]
        for y in range(ymin, ymax + 1):
            for x in range(xmin, xmax + 1):
                px, py = x + 0.5, y + 0.5
                w0 = ((y1-y2)*(px-x2) + (x2-x1)*(py-y2)) / den
                w1 = ((y2-y0)*(px-x2) + (x0-x2)*(py-y2)) / den
                w2 = 1.0 - w0 - w1
                if min(w0, w1, w2) < -1e-8:
                    continue
                invz = w0/z0 + w1/z1 + w2/z2
                z = 1.0 / invz
                if z >= zbuf[y, x]:
                    continue
                u = (w0*tex_uv[t0, 0]/z0 + w1*tex_uv[t1, 0]/z1
                     + w2*tex_uv[t2, 0]/z2) * z
                v = (w0*tex_uv[t0, 1]/z0 + w1*tex_uv[t1, 1]/z1
                     + w2*tex_uv[t2, 1]/z2) * z
                tx = min(tw-1, max(0, int(u * (tw-1) + 0.5)))
                ty = min(th-1, max(0, int((1.0-v) * (th-1) + 0.5)))
                img[y, x] = atlas[ty, tx]
                zbuf[y, x] = z
    return img, np.isfinite(zbuf)


def score(run_dir: str, geometry_dir: str, holdout_names: list[str], scale: int = 4):
    keyframes = os.path.join(run_dir, "keyframes")
    geo = os.path.join(geometry_dir, "sparse_txt")
    width, height, intrinsics = read_camera(os.path.join(geo, "cameras.txt"))
    poses = read_images_txt(os.path.join(geo, "images.txt"))
    vertices, tex_uv, faces, face_uv, texture = read_obj(
        os.path.join(geometry_dir, "scene_tex.obj"))
    atlas = cv2.imread(texture) if texture else None
    if atlas is None:
        raise ValueError("Textured mesh has no readable atlas")
    target = (max(1, width // scale), max(1, height // scale))
    K = tuple(x / scale for x in intrinsics)
    views = []
    for name in holdout_names:
        if name not in poses:
            raise ValueError(f"Held-out view has no registered pose: {name}")
        truth = cv2.imread(os.path.join(keyframes, name))
        if truth is None or truth.shape[:2] != (height, width):
            raise ValueError(f"Held-out image has wrong size: {name}")
        truth = cv2.resize(truth, target, interpolation=cv2.INTER_AREA)
        uv, depth = project_points(vertices, poses[name], K)
        render, mask = rasterize(uv, depth, faces, face_uv, tex_uv, atlas,
                                 target[0], target[1])
        coverage = float(mask.mean())
        if mask.sum() < 100:
            raise ValueError(f"Held-out render covers too few pixels: {name}")
        error = (truth.astype(np.float32) - render.astype(np.float32)) ** 2
        mse = float(error[mask].mean())
        psnr = float(10 * np.log10(255.0 ** 2 / max(mse, 1e-12)))
        _, ssim_map = structural_similarity(truth, render, data_range=255,
                                             channel_axis=2, full=True)
        ssim = float(ssim_map[mask].mean())
        views.append({"name": name, "coverage": round(coverage, 5),
                      "psnr_db": round(psnr, 3), "ssim": round(ssim, 5)})
    return {"render_scale": scale, "held_out": holdout_names, "views": views,
            "mean_coverage": round(float(np.mean([v["coverage"] for v in views])), 5),
            "mean_psnr_db": round(float(np.mean([v["psnr_db"] for v in views])), 3),
            "mean_ssim": round(float(np.mean([v["ssim"] for v in views])), 5)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run", help="Run folder with keyframes/")
    ap.add_argument("--geometry", help="Held-out geometry folder")
    ap.add_argument("--build", action="store_true", help="Build held-out geometry")
    ap.add_argument("--every", type=int, default=10)
    ap.add_argument("--scale", type=int, default=4)
    ap.add_argument("--out", help="JSON output; default under run folder")
    args = ap.parse_args()
    if args.every < 2 or args.scale < 1:
        ap.error("--every must be at least 2 and --scale at least 1")
    names = sorted((x for x in os.listdir(os.path.join(args.run, "keyframes"))
                    if x.lower().endswith((".jpg", ".jpeg", ".png"))),
                   key=frame_order)
    held = names[args.every-1::args.every]
    if not held:
        raise ValueError("No held-out view; need at least --every keyframes")
    geometry = args.geometry or os.path.join(args.run, "geometry_heldout")
    if args.build:
        ingest_path = os.path.join(args.run, "ingest.json")
        ingest = json.load(open(ingest_path, encoding="utf-8"))
        crop = ingest["stats"].get("overlay_crop_trbl")
        run_geometry(os.path.join(args.run, "keyframes"), geometry,
                     crop_trbl=crop, dense_names=[x for x in names if x not in set(held)])
    result = score(args.run, geometry, held, scale=args.scale)
    out = args.out or os.path.join(args.run, "view_check.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(json.dumps({k: result[k] for k in ("mean_coverage", "mean_psnr_db",
                                              "mean_ssim")}, indent=2))


if __name__ == "__main__":
    main()
