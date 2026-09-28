"""
Image figures for the research paper, rendered from the demo runs on this machine.

Reads out/runs/night-b1-final (the demo model) and out/runs/demo-prior (the same clip
with the depth prior), plus a few saved evidence images, and writes paper/fig/.
The demo clip is third-party footage, so fig/ is gitignored like web/data/.

    python paper/figures.py
"""
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "src"))
from view_check import project_points, rasterize, read_camera  # noqa: E402
from build_run_page import read_obj  # noqa: E402
from pipeline.local_gpu import read_images_txt  # noqa: E402

OUT = os.path.join(HERE, "fig")
B1 = os.path.join(ROOT, "out", "runs", "night-b1-final")
PRIOR = os.path.join(ROOT, "out", "runs", "demo-prior")
EVIDENCE = os.path.join(ROOT, "out", "evidence", "quality-2026-09-25")
JPG = [cv2.IMWRITE_JPEG_QUALITY, 88]


def load(run):
    V, T, F, FU, tex = read_obj(os.path.join(run, "geometry", "scene_tex.obj"))
    return V, T, F, FU, cv2.imread(tex)


def render(mesh, c2w, K, w, h, up, shade=False):
    """Textured render, or a grey Lambert shading through a one-row atlas."""
    V, T, F, FU, atlas = mesh
    uv, d = project_points(V, c2w, K)
    if shade:
        n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        light = 0.55 * up + 0.75 * c2w[:3, 0] - 0.35 * c2w[:3, 2]
        light /= np.linalg.norm(light)
        level = (35 + 215 * np.clip(np.abs(n @ light), 0, 1)).astype(np.int64)
        atlas = np.repeat(np.arange(256, dtype=np.uint8)[None, :, None], 3, axis=2)
        atlas = np.ascontiguousarray(np.repeat(atlas, 2, axis=0))
        T = np.column_stack((np.arange(256) / 255.0, np.full(256, 0.5)))
        FU = np.repeat(level[:, None], 3, axis=1)
    img, mask = rasterize(uv, d, F, FU, T, atlas, w, h)
    img[~mask] = (245, 245, 245)
    return img


def rotation(axis, angle):
    axis = axis / np.linalg.norm(axis)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(angle) * k + (1 - np.cos(angle)) * k @ k


def novel(c2w, up, back, lift, pitch_deg):
    """A keyframe camera moved back along its view and up, then pitched further down."""
    R = c2w[:3, :3]
    out = np.eye(4)
    out[:3, :3] = rotation(R[:, 0], -np.radians(pitch_deg)) @ R
    out[:3, 3] = c2w[:3, 3] - back * R[:, 2] + lift * up
    return out


def label(img, text):
    img = img.copy()
    cv2.rectangle(img, (0, 0), (60 + 22 * len(text), 58), (255, 255, 255), -1)
    cv2.putText(img, text, (14, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (20, 20, 20), 3, cv2.LINE_AA)
    return img


def white(h, w):
    return np.full((h, w, 3), 255, np.uint8)


def half(img, f=0.5):
    return cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)


def main():
    os.makedirs(OUT, exist_ok=True)
    W, H, K = read_camera(os.path.join(B1, "geometry", "sparse_txt", "cameras.txt"))
    poses = read_images_txt(os.path.join(B1, "geometry", "sparse_txt", "images.txt"))
    names = sorted(poses)
    up = np.array(json.load(open(os.path.join(B1, "level.json")))["basis_rows"][1])
    base, prior = load(B1), load(PRIOR)
    wn, hn = 1600, 1000
    Kn = (900.0, 900.0, wn / 2, hn / 2)

    # Four keyframes, 2 x 2
    kd = os.path.join(B1, "keyframes")
    ks = [label(cv2.imread(os.path.join(kd, names[i])), t)
          for i, t in zip((0, 60, 120, 176), ("(a) kf 0", "(b) kf 60", "(c) kf 120", "(d) kf 176"))]
    g = white(ks[0].shape[0], 16)
    grid = np.vstack([np.hstack([ks[0], g, ks[1]]), white(16, 2 * W + 16), np.hstack([ks[2], g, ks[3]])])
    cv2.imwrite(os.path.join(OUT, "fig_keyframes.jpg"), half(grid), JPG)

    # Photo against render from the same camera, keyframes 40 and 100
    cols = []
    for i in (40, 100):
        photo = cv2.imread(os.path.join(kd, names[i]))
        cols.append(np.vstack([photo, white(12, W), render(base, poses[names[i]], K, W, H, up)]))
    pairs = np.hstack([cols[0], white(cols[0].shape[0], 24), cols[1]])
    cv2.imwrite(os.path.join(OUT, "fig_pairs.jpg"), half(pairs, 0.45), JPG)

    # A viewpoint no photo was taken from
    cam = novel(poses[names[60]], up, 1.5, 1.0, 15)
    cv2.imwrite(os.path.join(OUT, "fig_novel.jpg"), render(base, cam, Kn, wn, hn, up), [cv2.IMWRITE_JPEG_QUALITY, 90])

    # The houses: textured, OpenMVS mesh shaded, prior mesh shaded
    cam = novel(poses[names[160]], up, -2.8, 1.0, 28)
    panels = [render(base, cam, Kn, wn, hn, up)[:620], render(base, cam, Kn, wn, hn, up, True)[:620],
              render(prior, cam, Kn, wn, hn, up, True)[:620]]
    panels = [label(p, t) for p, t in zip(panels, ("(a) textured", "(b) OpenMVS mesh", "(c) with depth prior"))]
    stack = np.vstack([panels[0], white(16, wn), panels[1], white(16, wn), panels[2]])
    cv2.imwrite(os.path.join(OUT, "fig_prior.jpg"), half(stack), JPG)

    # Saved evidence: the pose fix, the map sheet, Kolu
    a = cv2.imread(os.path.join(EVIDENCE, "demo_gpu_side.jpg"))
    b = cv2.imread(os.path.join(EVIDENCE, "demo_gpu2_side.jpg"))
    b = cv2.resize(b, (a.shape[1], int(b.shape[0] * a.shape[1] / b.shape[1])))
    cv2.imwrite(os.path.join(OUT, "fig_posefix.jpg"),
                np.vstack([label(a, "(a) before"), white(16, a.shape[1]), label(b, "(b) after")]), JPG)
    cv2.imwrite(os.path.join(OUT, "fig_sheet.jpg"), half(cv2.imread(os.path.join(ROOT, "web", "data", "sheet.jpg")), 0.6), JPG)
    cv2.imwrite(os.path.join(OUT, "fig_kolu.jpg"),
                half(cv2.imread(os.path.join(ROOT, "research", "run-evidence", "kolu-reconstruction.png")), 0.6), JPG)
    print(sorted(f for f in os.listdir(OUT) if f.startswith("fig_")))


if __name__ == "__main__":
    main()
