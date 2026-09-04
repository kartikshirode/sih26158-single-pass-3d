"""
CPU rasteriser: turn the synthetic scene into actual drone-camera IMAGES.

Why this exists. The pipeline otherwise "senses" geometry directly from the known
mesh, which is fine for testing georeferencing and export but cannot exercise a real
vision model - a learned reconstructor needs pixels.

THE FIRST VERSION WAS WRONG, AND THE FAILURE IS WORTH RECORDING. It splatted dense
surface SAMPLES into a z-buffer. Point splatting cannot fill an image: only samples
that happen to land in a pixel contribute, so coverage came out at 19% and the frames
were black speckle. MapAnything was then fed essentially noise and returned a
reconstruction whose camera baselines were an irregular ~1.95 m where the truth was a
uniform 61.4 m. The model was fine; the renderer was broken. Diagnosing that from the
model's output alone would have been very hard - looking at the actual frames took
seconds.

This version rasterises TRIANGLES with barycentric coverage and a proper z-buffer, so
every pixel a surface covers gets filled. No GPU, no OpenGL: trimesh's ray caster runs
at ~1 ms/ray without embree, which is hopeless for images.

Shading is lambertian with per-class albedo plus per-face grain, so frames carry
matchable texture. A flat render would be degenerate input and would flatter any model
tested on it.
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


def _hash01(ix, iy, iz, seed=0):
    """Integer hash -> pseudo-random float in [0,1). Deterministic, aperiodic."""
    h = (ix.astype(np.int64) * np.int64(73856093)
         ^ iy.astype(np.int64) * np.int64(19349663)
         ^ iz.astype(np.int64) * np.int64(83492791)
         ^ np.int64(seed) * np.int64(2654435761))
    h = (h ^ (h >> 13)) * np.int64(1274126177)
    h = h ^ (h >> 16)
    return (h & np.int64(0xFFFFFF)).astype(np.float32) / float(0x1000000)


def _value_noise(P, cell, seed):
    """Trilinearly-interpolated value noise on a lattice of the given cell size."""
    q = P / cell
    i = np.floor(q).astype(np.int64)
    f = (q - i).astype(np.float32)
    f = f * f * (3.0 - 2.0 * f)                      # smoothstep
    ix, iy, iz = i[..., 0], i[..., 1], i[..., 2]
    fx, fy, fz = f[..., 0], f[..., 1], f[..., 2]

    def c(dx, dy, dz):
        return _hash01(ix + dx, iy + dy, iz + dz, seed)

    x00 = c(0, 0, 0) * (1 - fx) + c(1, 0, 0) * fx
    x10 = c(0, 1, 0) * (1 - fx) + c(1, 1, 0) * fx
    x01 = c(0, 0, 1) * (1 - fx) + c(1, 0, 1) * fx
    x11 = c(0, 1, 1) * (1 - fx) + c(1, 1, 1) * fx
    y0 = x00 * (1 - fy) + x10 * fy
    y1 = x01 * (1 - fy) + x11 * fy
    return y0 * (1 - fz) + y1 * fz


def world_texture(P, octaves=5, base=0.45):
    """
    Aperiodic multi-octave value noise evaluated at WORLD coordinates.

    Two properties matter, and the first version had only one of them:

    1. VIEW-CONSISTENT. Because the texture is a function of world position, a surface
       point looks the same from every camera. That is what multi-view matching needs;
       a screen-space or per-face texture would look fine to a human and be useless to
       a reconstructor.

    2. APERIODIC. The first version summed sines, which are exactly periodic - the
       ground repeated every few metres, so correspondence was ambiguous and
       MapAnything collapsed most cameras onto nearly the same position (baselines of
       0.02-1.45 where the truth was a uniform 24.6 m). Hash-based value noise has no
       repeat, so every patch is locally unique.

    Octaves span metres down to ~10 cm, which is the band an aerial matcher works in.
    """
    P = np.asarray(P, np.float32)
    acc = np.zeros(P.shape[:-1], np.float32)
    amp, cell, total = 1.0, 12.0, 0.0
    for o in range(octaves):
        acc += amp * _value_noise(P, cell, seed=o * 7919 + 13)
        total += amp
        amp *= 0.55
        cell *= 0.42
    acc /= total
    return np.clip(base + (1.0 - base) * (0.35 + 1.3 * acc), 0.25, 1.5).astype(np.float32)


def shade_faces(mesh, labels, rng=None, texture_strength=0.20):
    """Per-face colour: class albedo x lambertian sun term x per-face grain."""
    rng = rng or np.random.default_rng(0)
    lam = np.clip(np.abs(mesh.face_normals @ SUN), 0.0, 1.0)
    col = CLASS_RGB[np.asarray(labels)] * (0.32 + 0.68 * lam)[:, None]
    col = col * (1.0 + rng.normal(0, texture_strength, (len(col), 1)))
    return np.clip(col, 0, 1).astype(np.float32)


def _rasterise(verts_px, depth_v, tri, shade, W, H, world_v=None):
    """Barycentric triangle rasteriser with a z-buffer. Returns (colour, zbuf)."""
    colour = np.zeros((H, W, 3), np.float32)
    zbuf = np.full((H, W), np.inf, np.float32)

    a_all = verts_px[tri[:, 0]]
    b_all = verts_px[tri[:, 1]]
    c_all = verts_px[tri[:, 2]]
    za = depth_v[tri[:, 0]]
    zb = depth_v[tri[:, 1]]
    zc = depth_v[tri[:, 2]]

    area = ((b_all[:, 0] - a_all[:, 0]) * (c_all[:, 1] - a_all[:, 1])
            - (c_all[:, 0] - a_all[:, 0]) * (b_all[:, 1] - a_all[:, 1]))
    keep = np.abs(area) > 1e-9
    if not keep.any():
        return colour, zbuf

    for t in np.flatnonzero(keep):
        a, b, c = a_all[t], b_all[t], c_all[t]
        xlo = max(int(np.floor(min(a[0], b[0], c[0]))), 0)
        xhi = min(int(np.ceil(max(a[0], b[0], c[0]))) + 1, W)
        ylo = max(int(np.floor(min(a[1], b[1], c[1]))), 0)
        yhi = min(int(np.ceil(max(a[1], b[1], c[1]))) + 1, H)
        if xhi <= xlo or yhi <= ylo:
            continue

        px, py = np.meshgrid(np.arange(xlo, xhi) + 0.5, np.arange(ylo, yhi) + 0.5)
        ar = area[t]
        # barycentric weights: wa belongs to vertex a, etc.
        wc = ((b[0] - a[0]) * (py - a[1]) - (px - a[0]) * (b[1] - a[1])) / ar
        wa = ((c[0] - b[0]) * (py - b[1]) - (px - b[0]) * (c[1] - b[1])) / ar
        wb = 1.0 - wa - wc
        inside = (wa >= 0) & (wb >= 0) & (wc >= 0)
        if not inside.any():
            continue

        z = wa * za[t] + wb * zb[t] + wc * zc[t]
        sub = zbuf[ylo:yhi, xlo:xhi]
        win = inside & (z < sub)
        if not win.any():
            continue
        sub[win] = z[win]

        px_col = np.broadcast_to(shade[t], win.shape + (3,))
        if world_v is not None:
            # Interpolate the world position of every covered pixel, then modulate by
            # world-space noise so the texture is identical from every viewpoint.
            wp = (wa[win][:, None] * world_v[tri[t, 0]]
                  + wb[win][:, None] * world_v[tri[t, 1]]
                  + wc[win][:, None] * world_v[tri[t, 2]])
            px_col = shade[t][None, :] * world_texture(wp)[:, None]
            colour[ylo:yhi, xlo:xhi][win] = np.clip(px_col, 0, 1)
        else:
            colour[ylo:yhi, xlo:xhi][win] = px_col[win] if px_col.ndim == 3 else shade[t]

    return colour, zbuf


def render_view(scene_verts, scene_faces, face_rgb, cam_pos, cam_R, K,
                width, height, *, rng=None, exposure=1.0):
    """
    Render one camera view by triangle rasterisation.

    Returns (rgb uint8 [H,W,3], depth float32 [H,W], NaN where nothing was hit).
    """
    V = np.asarray(scene_verts, np.float64)
    rel = V - cam_pos[None, :]
    cam = rel @ cam_R                      # cam_R is cam->world, so this is R^T @ rel
    z = cam[:, 2]

    with np.errstate(invalid="ignore", divide="ignore"):
        u = K[0, 0] * cam[:, 0] / z + K[0, 2]
        v = K[1, 1] * cam[:, 1] / z + K[1, 2]
    verts_px = np.stack([u, v], 1)

    F = np.asarray(scene_faces)
    front = (z[F] > 0.1).all(1)            # whole triangle in front of the camera
    xs, ys = verts_px[F][..., 0], verts_px[F][..., 1]
    onscreen = ((xs.max(1) >= 0) & (xs.min(1) < width)
                & (ys.max(1) >= 0) & (ys.min(1) < height))
    vis = front & onscreen
    if not vis.any():
        return (np.zeros((height, width, 3), np.uint8),
                np.full((height, width), np.nan, np.float32))

    colour, zbuf = _rasterise(verts_px, z, F[vis], face_rgb[vis], width, height,
                              world_v=V)
    depth = np.where(np.isfinite(zbuf), zbuf, np.nan).astype(np.float32)

    img = np.clip(colour * exposure, 0, 1)
    if rng is not None:                     # sensor noise, keeps frames non-identical
        img = np.clip(img * (1.0 + rng.normal(0, 0.02, img.shape)), 0, 1)
    return (img * 255).astype(np.uint8), depth


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
                  blur_px=0, rng=None, progress=False):
    """Render every camera in a flight. Returns (frames uint8 [N,H,W,3], depths)."""
    rng = rng or np.random.default_rng(0)
    face_rgb = shade_faces(scene.mesh, scene.labels, rng=np.random.default_rng(11))
    V = np.asarray(scene.mesh.vertices)
    F = np.asarray(scene.mesh.faces)

    frames, depths = [], []
    for i in range(len(positions)):
        img, d = render_view(V, F, face_rgb, positions[i], rotations[i], K,
                             width, height, rng=rng)
        if blur_px:
            img = apply_motion_blur(img, blur_px)
        frames.append(img)
        depths.append(d)
        if progress and i % 5 == 0:
            print(f"    rendered {i + 1}/{len(positions)}", end="\r", flush=True)
    return np.stack(frames), np.stack(depths)
