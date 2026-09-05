"""
Render the reconstruction so it can be judged as a surface, not as a scatter plot.

A point cloud plotted with matplotlib's scatter looks like noise whether it is noise
or not, which is exactly how a bad result gets shipped with confident statistics
attached. These are flat-shaded triangle renders with a real light direction and a
painter's depth sort, so a wrong surface looks wrong.
"""
from __future__ import annotations
import argparse, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def rot(az_deg: float, el_deg: float) -> np.ndarray:
    a, e = np.radians(az_deg), np.radians(el_deg)
    Ry = np.array([[np.cos(a), 0, -np.sin(a)], [0, 1, 0], [np.sin(a), 0, np.cos(a)]])
    Rx = np.array([[1, 0, 0], [0, np.cos(e), -np.sin(e)], [0, np.sin(e), np.cos(e)]])
    return Rx @ Ry


def shade_mesh(ax, V, F, VC, az, el, title, radius=None, light=(0.35, -0.75, 0.56)):
    Vr = V @ rot(az, el).T
    tri = Vr[F]                                            # (T, 3, 3)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    # Ambient + diffuse. Pure lambert drives back-facing geometry to black, which
    # hides exactly the detail a reviewer needs to see.
    lam = 0.42 + 0.58 * np.clip(np.abs(n @ np.asarray(light)), 0.0, 1.0)
    fc = np.clip(VC[F].mean(1) * lam[:, None], 0, 1)

    order = np.argsort(tri[:, :, 2].mean(1))               # painter's algorithm
    from matplotlib.collections import PolyCollection
    ax.add_collection(PolyCollection(tri[order][:, :, :2], facecolors=fc[order],
                                     edgecolors="none", linewidths=0))
    _frame(ax, Vr, title, radius)


def shade_points(ax, P, C, az, el, title, radius=None, s=0.6):
    Pr = P @ rot(az, el).T
    o = np.argsort(Pr[:, 2])
    ax.scatter(Pr[o, 0], Pr[o, 1], c=np.clip(C[o] / 255.0, 0, 1), s=s,
               linewidths=0, marker=".")
    _frame(ax, Pr, title, radius)


def _frame(ax, Vr, title, radius=None):
    # One radius for every panel, so the views are comparable at a glance and each
    # one fills its axes. Per-panel autoscaling makes a plan view and an elevation
    # of the same model look like different objects.
    cx, cy = Vr[:, 0].mean(), Vr[:, 1].mean()
    r = radius if radius is not None else 0.52 * max(np.ptp(Vr[:, 0]), np.ptp(Vr[:, 1]))
    ax.set_xlim(cx - r, cx + r); ax.set_ylim(cy - r, cy + r)
    ax.set_aspect("equal"); ax.axis("off")
    ax.set_title(title, fontsize=11, color="#e8e8e8")


def section(ax, P, C, title, frac=0.02):
    """
    A thin vertical slab through the scene, cut perpendicular to its long axis.

    This is the view that settles whether an arch or a tunnel is really there. A
    shaded mesh cannot answer it, because screened Poisson closes over unobserved
    space by construction: the drone never saw through the underpass, so the mesher
    will happily fill it and the surface will look correct from every outside angle.
    The POINT CLOUD either has the void or it does not, and a section shows that
    directly.
    """
    q = P - P.mean(0)
    horiz = q[:, [0, 2]]
    axis = np.linalg.svd(horiz[::13], full_matrices=False)[2][0]      # long axis
    t = horiz @ axis
    perp = horiz @ np.array([-axis[1], axis[0]])
    lo, hi = np.percentile(t, [50 - frac * 50, 50 + frac * 50])
    m = (t >= lo) & (t <= hi)
    # Coloured by HEIGHT, not by photo colour. A section of real footage in shadow
    # is almost black, and a black profile on a black ground shows nothing - which
    # defeats the only view that can tell an open underpass from a filled one.
    ax.scatter(perp[m], q[m, 1], c=q[m, 1], cmap="turbo", s=3.2,
               linewidths=0, marker=".")
    _frame(ax, np.stack([perp[m], q[m, 1], np.zeros(m.sum())], 1), title)


def upright_frame(P: np.ndarray, centres=None):
    """
    Rotate the reconstruction so its terrain plane is horizontal.

    The model's own frame is NOT gravity-aligned: its Y is the camera's down, and
    the camera here is a steep oblique, so a naive "height" colouring grades along
    the viewing direction rather than along the vertical. That makes a plan view not
    a plan and a section not a section.

    Without IMU or GPS the only gravity proxy available is the scene itself: for a
    survey pass over terrain, the smallest principal axis of the cloud is the ground
    plane's normal. Its SIGN is arbitrary, so the cameras fix it - they were above
    the ground, which is the one thing known for certain about a drone.
    """
    c = P.mean(0)
    q = (P[::17] - c).astype(np.float64)
    up = np.linalg.svd(q, full_matrices=False)[2][-1]
    if centres is not None and len(centres):
        if np.dot(np.asarray(centres, float).mean(0) - c, up) < 0:
            up = -up
    a = up / np.linalg.norm(up)
    # Any orthonormal basis with `a` as the vertical.
    t = np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = np.cross(a, t); e1 /= np.linalg.norm(e1)
    e2 = np.cross(a, e1)
    return np.stack([e1, a, e2])          # rows: right, up, forward


def main(d: str, out: str):
    P = np.load(f"{d}/points_fused.npy").astype(np.float64)
    C = np.load(f"{d}/colors_fused.npy")
    centres = (np.load(f"{d}/cam_centres.npy")
               if os.path.exists(f"{d}/cam_centres.npy") else None)
    B = upright_frame(P, centres)
    c0 = P.mean(0)
    P = (P - c0) @ B.T

    have_mesh = os.path.exists(f"{d}/mesh_v.npy")
    if have_mesh:
        V = (np.load(f"{d}/mesh_v.npy") - c0) @ B.T
        F = np.load(f"{d}/mesh_f.npy")
        VC = np.load(f"{d}/mesh_c.npy") / 255.0

    views = [(0, 90, "plan"), (30, 55, "oblique"), (75, 25, "low angle")]
    rows = 3 if have_mesh else 2
    fig, ax = plt.subplots(rows, 3, figsize=(19, 5.6 * rows),
                           facecolor="#101010", squeeze=False)
    # One radius for the rendered views, sized to the footprint rather than the
    # diagonal, so the model fills the frame instead of floating in black.
    R = 0.52 * float(max(np.ptp(P[:, 0]), np.ptp(P[:, 2])))
    for j, (az, el, name) in enumerate(views):
        shade_points(ax[0][j], P, C, az, el, f"fused point cloud - {name}", radius=R)
        if have_mesh:
            shade_mesh(ax[1][j], V, F, VC, az, el, f"mesh - {name}", radius=R)

    # Bottom row: vertical sections through the CLOUD at three stations along the
    # pass. The mesh cannot answer whether the underpass is open, because screened
    # Poisson closes unobserved space by construction.
    q = P - P.mean(0)
    horiz = q[:, [0, 2]]
    axis = np.linalg.svd(horiz[::13], full_matrices=False)[2][0]
    t = horiz @ axis
    w = 0.015 * float(np.ptp(t))
    # Panel 1 of the bottom row is a height-coloured plan; a photo-coloured plan
    # cannot show whether two surfaces sit at plausible relative heights.
    a0 = ax[rows - 1][0]
    sub = np.random.default_rng(0).choice(len(P), min(200_000, len(P)), replace=False)
    a0.scatter(P[sub, 0], P[sub, 2], c=P[sub, 1], cmap="turbo", s=0.8,
               linewidths=0, marker=".")
    _frame(a0, P[sub][:, [0, 2, 1]], "plan, coloured by height", radius=R)
    for j, pct in enumerate((40, 60)):
        c = float(np.percentile(t, pct))
        m = np.abs(t - c) <= w
        section(ax[rows - 1][j + 1], P[m], C[m], f"section - {pct}% along track")

    for a in ax.ravel():
        a.set_facecolor("#101010")
    plt.tight_layout()
    plt.savefig(out, dpi=110, facecolor="#101010")
    print("wrote", out, f"| {len(P):,} points" +
          (f", {len(F):,} triangles" if have_mesh else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("indir"); ap.add_argument("--out", default="out/kolu3d/render.png")
    a = ap.parse_args()
    main(a.indir, a.out)
