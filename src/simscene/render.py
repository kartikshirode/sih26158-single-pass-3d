"""
CPU rasteriser: turn the synthetic scene into actual drone-camera IMAGES.

Why this exists. Until now the pipeline "sensed" geometry directly from the known
mesh, which is fine for testing georeferencing and export but cannot exercise a real
vision model - a learned reconstructor needs pixels. This renders the scene from each
camera pose so MapAnything (or any image-based model) has something to consume, and so
the demo can honestly say "video frames in, 3D out".

No GPU and no OpenGL: trimesh's ray caster runs at ~1 ms/ray without embree, which is
hopeless for images, so this uses the same z-buffer projection as visibility.py -
splat dense surface samples, keep the nearest per pixel, shade, then fill the few
remaining gaps. At 640x360 that is a fraction of a second per frame.

Shading is deliberately simple but not flat: a lambertian sun term plus per-class
albedo and a little per-point noise, which gives the texture gradient a feature
matcher or a learned model needs. A uniformly-coloured render would be degenerate
input and would flatter any model tested on it.
"""

from __future__ import annotations

import numpy as np

# Per-class base albedo (terrain, building, road, vegetation) - see Scene.LABELS
CLASS_RGB = np.array([
    [0.55, 0.50, 0.38],    # terrain - dry earth
    [0.72, 0.70, 0.67],    # building - concrete
    [0.28, 0.28, 0.30],    # road - asphalt
    [0.22, 0.38, 0.18],    # vegetation
])

SUN = np.array([-0.35, 0.25, 0.90])
SUN = SUN / np.linalg.norm(SUN)


def render_view(points, normals, labels, cam_pos, cam_R, K, width, height, *,
                bin_scale=1.0, rng=None, exposure=1.0):
    """
    Render one camera view.

    Returns (rgb uint8 [H,W,3], depth float32 [H,W] with NaN where nothing was hit).

    `points` should be a DENSE surface sampling - roughly 3-5x the pixel count, or
    holes appear. `bin_scale` renders at reduced resolution then upsamples, which is
    the cheap way to trade quality for speed.
    """
    rng = rng or np.random.default_rng(0)
    W = max(int(width * bin_scale), 1)
    H = max(int(height * bin_scale), 1)

    rel = np.asarray(points, dtype=np.float64) - cam_pos[None, :]
    cam = rel @ cam_R                       # cam_R is cam->world, so this is R^T @ rel
    z = cam[:, 2]

    ok = z > 1e-6
    with np.errstate(invalid="ignore", divide="ignore"):
        u = (K[0, 0] * cam[:, 0] / z + K[0, 2]) * bin_scale
        v = (K[1, 1] * cam[:, 1] / z + K[1, 2]) * bin_scale
    ok &= (u >= 0) & (u < W) & (v >= 0) & (v < H)
    if not ok.any():
        return np.zeros((height, width, 3), np.uint8), np.full((height, width), np.nan, np.float32)

    ui = u[ok].astype(np.int64)
    vi = v[ok].astype(np.int64)
    zi = z[ok]
    idx = np.flatnonzero(ok)

    # z-buffer: nearest sample wins each pixel
    flat = vi * W + ui
    order = np.lexsort((zi, flat))
    flat_s, idx_s, z_s = flat[order], idx[order], zi[order]
    first = np.ones(len(flat_s), bool)
    first[1:] = flat_s[1:] != flat_s[:-1]

    pix = flat_s[first]
    src = idx_s[first]
    dep = z_s[first]

    # Lambertian shading with per-class albedo
    n = np.asarray(normals)[src]
    lam = np.clip(np.abs(n @ SUN), 0.0, 1.0)
    base = CLASS_RGB[np.asarray(labels)[src]]
    shade = (0.30 + 0.70 * lam)[:, None]
    col = base * shade * exposure
    # fine grain so the image has matchable texture rather than flat fills
    col *= (1.0 + rng.normal(0, 0.045, col.shape))
    col = np.clip(col, 0, 1)

    img = np.zeros((H * W, 3), np.float32)
    depth = np.full(H * W, np.nan, np.float32)
    img[pix] = col
    depth[pix] = dep

    img = img.reshape(H, W, 3)
    depth = depth.reshape(H, W)

    # Fill unsplattered pixels from their neighbours so the render is not speckled
    holes = ~np.isfinite(depth)
    if holes.any() and (~holes).any():
        img, depth = _fill_holes(img, depth, holes)

    if bin_scale != 1.0:
        img = _upsample(img, height, width)
        depth = _upsample(depth[..., None], height, width)[..., 0]

    return (np.clip(img, 0, 1) * 255).astype(np.uint8), depth.astype(np.float32)


def _fill_holes(img, depth, holes, iters=3):
    """Dilate known pixels into holes - a couple of passes closes splat gaps."""
    for _ in range(iters):
        if not holes.any():
            break
        acc = np.zeros_like(img)
        accd = np.zeros_like(depth)
        cnt = np.zeros(depth.shape, np.float32)
        known = (~holes).astype(np.float32)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            k = np.roll(known, (dy, dx), (0, 1))
            acc += np.roll(img * known[..., None], (dy, dx), (0, 1))
            accd += np.roll(np.nan_to_num(depth) * known, (dy, dx), (0, 1))
            cnt += k
        fill = holes & (cnt > 0)
        with np.errstate(invalid="ignore", divide="ignore"):
            img[fill] = acc[fill] / cnt[fill][:, None]
            depth[fill] = accd[fill] / cnt[fill]
        holes = holes & ~fill
    return img, depth


def _upsample(a, height, width):
    ys = (np.arange(height) * a.shape[0] / height).astype(int).clip(0, a.shape[0] - 1)
    xs = (np.arange(width) * a.shape[1] / width).astype(int).clip(0, a.shape[1] - 1)
    return a[ys][:, xs]


def apply_motion_blur(img, px=2):
    """Horizontal box blur - a crude stand-in for along-track motion blur (R-C2)."""
    if px < 2:
        return img
    f = np.asarray(img, np.float32)
    acc = np.zeros_like(f)
    for k in range(px):
        acc += np.roll(f, k - px // 2, axis=1)
    return (acc / px).astype(np.uint8)


def render_flight(scene, positions, rotations, K, width, height, *,
                  dense=None, n_dense=1_200_000, bin_scale=0.5,
                  blur_px=0, rng=None, progress=False):
    """Render every camera in a flight. Returns (frames uint8 [N,H,W,3], depths)."""
    import trimesh
    rng = rng or np.random.default_rng(0)
    if dense is None:
        pts, fidx = trimesh.sample.sample_surface(scene.mesh, n_dense, seed=3)
        dense = (np.asarray(pts), scene.mesh.face_normals[fidx], scene.labels[fidx])
    pts, nrm, lab = dense

    frames, depths = [], []
    for i in range(len(positions)):
        img, d = render_view(pts, nrm, lab, positions[i], rotations[i], K,
                             width, height, bin_scale=bin_scale, rng=rng)
        if blur_px:
            img = apply_motion_blur(img, blur_px)
        frames.append(img)
        depths.append(d)
        if progress and i % 20 == 0:
            print(f"    rendered {i + 1}/{len(positions)}", end="\r", flush=True)
    return np.stack(frames), np.stack(depths)
