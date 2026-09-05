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


def shade_mesh(ax, V, F, VC, az, el, title, light=(0.35, -0.75, 0.56)):
    Vr = V @ rot(az, el).T
    tri = Vr[F]                                            # (T, 3, 3)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    lam = np.clip(np.abs(n @ np.asarray(light)), 0.18, 1.0)
    fc = np.clip(VC[F].mean(1) * lam[:, None], 0, 1)

    order = np.argsort(tri[:, :, 2].mean(1))               # painter's algorithm
    from matplotlib.collections import PolyCollection
    ax.add_collection(PolyCollection(tri[order][:, :, :2], facecolors=fc[order],
                                     edgecolors="none", linewidths=0))
    _frame(ax, Vr, title)


def shade_points(ax, P, C, az, el, title, s=0.35):
    Pr = P @ rot(az, el).T
    o = np.argsort(Pr[:, 2])
    ax.scatter(Pr[o, 0], Pr[o, 1], c=np.clip(C[o] / 255.0, 0, 1), s=s,
               linewidths=0, marker=".")
    _frame(ax, Pr, title)


def _frame(ax, Vr, title):
    pad = 0.03 * max(np.ptp(Vr[:, 0]), np.ptp(Vr[:, 1]))
    ax.set_xlim(Vr[:, 0].min() - pad, Vr[:, 0].max() + pad)
    ax.set_ylim(Vr[:, 1].min() - pad, Vr[:, 1].max() + pad)
    ax.set_aspect("equal"); ax.axis("off")
    ax.set_title(title, fontsize=11, color="#e8e8e8")


def main(d: str, out: str):
    P = np.load(f"{d}/points_fused.npy").astype(np.float64)
    C = np.load(f"{d}/colors_fused.npy")
    # Model Y points down; flip so renders read the right way up.
    P = P * np.array([1.0, -1.0, 1.0])
    P -= P.mean(0)

    have_mesh = os.path.exists(f"{d}/mesh_v.npy")
    if have_mesh:
        V = np.load(f"{d}/mesh_v.npy") * np.array([1.0, -1.0, 1.0])
        F = np.load(f"{d}/mesh_f.npy")
        VC = np.load(f"{d}/mesh_c.npy") / 255.0
        V = V - V.mean(0)

    views = [(0, 90, "plan"), (30, 55, "oblique"), (75, 25, "low angle")]
    rows = 2 if have_mesh else 1
    fig, ax = plt.subplots(rows, 3, figsize=(19, 6.4 * rows),
                           facecolor="#101010", squeeze=False)
    for j, (az, el, name) in enumerate(views):
        shade_points(ax[0][j], P, C, az, el, f"fused point cloud - {name}")
        if have_mesh:
            shade_mesh(ax[1][j], V, F, VC, az, el, f"mesh - {name}")
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
