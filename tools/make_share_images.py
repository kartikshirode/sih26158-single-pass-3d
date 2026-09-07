"""
Render the findings as standalone shareable images.

Each one has to survive being pasted into a chat with no caption, so the numbers and
the labels are burned in rather than left to whoever posts it.
"""
from __future__ import annotations

import os

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out", "share")
BG, FG, DIM = "#FAFAF8", "#1A1A1A", "#5A5A5A"
BASE, MVS = "#C2612C", "#1F6FA8"          # baseline / rebuild, consistent everywhere

SHORT_B = [(6, 1.288), (12, 1.944), (25, 2.344), (50, 2.634), (100, 3.340)]
SHORT_M = [(3, 0.187), (6, 0.353), (12, 0.624), (25, 1.121), (50, 2.031), (100, 3.217)]
KOLU_B = [(6, 1.382), (12, 2.762), (25, 4.756), (50, 5.852), (100, 7.219)]
KOLU_M = [(3, 0.349), (6, 0.756), (12, 1.487), (25, 2.787), (50, 4.707), (100, 7.359)]


def cell(path, row, col, w=1000):
    """One panel out of a 3x3 render sheet, trimmed to its content."""
    im = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB)
    H, W = im.shape[:2]
    ch, cw = H // 3, W // 3
    c = im[row * ch + int(ch * 0.06):(row + 1) * ch, col * cw:(col + 1) * cw]
    bg = np.median(np.concatenate([c[:4].reshape(-1, 3), c[-4:].reshape(-1, 3)]), 0)
    ys, xs = np.where(np.abs(c.astype(np.int16) - bg).max(2) > 22)
    if len(xs):
        c = c[max(ys.min() - 8, 0):ys.max() + 8, max(xs.min() - 8, 0):xs.max() + 8]
    s = w / c.shape[1]
    return cv2.resize(c, (w, int(c.shape[0] * s)), interpolation=cv2.INTER_AREA)


def ab(name, base_png, mvs_png, title, sub, lines):
    a, b = cell(base_png, 1, 1), cell(mvs_png, 1, 1)
    h = max(a.shape[0], b.shape[0])
    a = cv2.copyMakeBorder(a, 0, h - a.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(241, 241, 236))
    b = cv2.copyMakeBorder(b, 0, h - b.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(241, 241, 236))

    fig = plt.figure(figsize=(16, 9.6), facecolor=BG)
    gs = GridSpec(3, 2, height_ratios=[1.25, 5.4, 1.5], hspace=0.10, wspace=0.03,
                  left=0.035, right=0.965, top=0.97, bottom=0.03)
    ax = fig.add_subplot(gs[0, :]); ax.axis("off")
    ax.text(0, .74, title, color=FG, fontsize=27, fontweight="bold", va="center")
    ax.text(0, .30, sub, color=DIM, fontsize=14, va="center")
    ax.text(1, .74, "SIH26158 · NTRO", color=DIM, fontsize=12,
            va="center", ha="right", family="monospace")

    for i, (img, lab, colr) in enumerate(((a, "BEFORE  ·  feed-forward point maps", BASE),
                                          (b, "AFTER  ·  per-pixel photometric MVS", MVS))):
        axi = fig.add_subplot(gs[1, i])
        axi.imshow(img); axi.axis("off")
        axi.set_title(lab, color=colr, fontsize=15, fontweight="bold", pad=9,
                      family="monospace")

    axf = fig.add_subplot(gs[2, :]); axf.axis("off")
    for j, (lab, lo, hi) in enumerate(lines):
        x = j / len(lines)
        axf.text(x, .78, lab, color=DIM, fontsize=12, family="monospace")
        axf.text(x, .40, lo, color=BASE, fontsize=17, fontweight="bold", family="monospace")
        axf.text(x, .05, hi, color=MVS, fontsize=17, fontweight="bold", family="monospace")
    p = f"{OUT}/{name}"
    fig.savefig(p, dpi=125, facecolor=BG)
    plt.close(fig)
    print("wrote", p)


def chart():
    fig, axes = plt.subplots(1, 2, figsize=(16, 7.6), facecolor=BG)
    fig.subplots_adjust(left=.07, right=.975, top=.80, bottom=.13, wspace=.18)
    fig.text(.07, .935, "Where the detail actually is", color=FG, fontsize=27,
             fontweight="bold", va="center")
    fig.text(.07, .875, "Plane fitted in a ball of radius r; median |residual|. "
             "Lower is finer detail resolved.", color=DIM, fontsize=14, va="center")
    fig.text(.975, .935, "SIH26158 · NTRO", color=DIM, fontsize=12,
             va="center", ha="right", family="monospace")
    for ax, (t, bs, ms, note) in zip(axes, (
            ("Short — 42 views", SHORT_B, SHORT_M,
             "3.6x tighter at 6 cm; identical at 1 m"),
            ("Kolu — 45 views", KOLU_B, KOLU_M,
             "1.8x tighter at 6 cm; identical at 1 m"))):
        ax.set_facecolor("#F1F1EC")
        for s in ax.spines.values():
            s.set_color("#D8D8D2")
        ax.grid(True, which="both", color="#E2E2DC", lw=.8)
        ax.set_axisbelow(True)
        ax.plot(*zip(*bs), "-o", color=BASE, lw=2.4, ms=7,
                label="MapAnything — feed-forward")
        ax.plot(*zip(*ms), "-o", color=MVS, lw=2.4, ms=7,
                label="OpenMVS — per-pixel MVS")
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlim(2.5, 130); ax.set_ylim(.12, 10)
        ax.set_xticks([3, 10, 30, 100]); ax.set_xticklabels(["3", "10", "30", "100"])
        ax.set_yticks([.2, .5, 1, 2, 5, 10])
        ax.set_yticklabels([".2", ".5", "1", "2", "5", "10"])
        ax.tick_params(colors=DIM, labelsize=12, which="both")
        ax.set_xlabel("ball radius (cm)", color=DIM, fontsize=12)
        ax.set_ylabel("plane residual (cm)", color=DIM, fontsize=12)
        ax.set_title(t, color=FG, fontsize=17, fontweight="bold", pad=10, loc="left")
        ax.text(.03, .04, note, transform=ax.transAxes, color=DIM, fontsize=11.5,
                family="monospace")
        lg = ax.legend(loc="upper left", fontsize=12, facecolor="#F1F1EC",
                       edgecolor="#D8D8D2", labelcolor=FG)
        lg.get_frame().set_linewidth(.8)
    p = f"{OUT}/03_resolution_vs_scale.png"
    fig.savefig(p, dpi=125, facecolor=BG)
    plt.close(fig)
    print("wrote", p)


def summary():
    fig = plt.figure(figsize=(16, 9), facecolor=BG)
    fig.text(.055, .93, "The 14-pixel floor", color=FG, fontsize=34, fontweight="bold")
    fig.text(.055, .875, "Our reconstructions sampled the ground at 2.2 cm and carried "
             "information at 30–50 cm.", color=DIM, fontsize=15)
    fig.text(.945, .93, "SIH26158 · NTRO", color=DIM, fontsize=12, ha="right",
             family="monospace")

    # Two columns: the story on the left, the numbers on the right. A single stacked
    # column left the top-right third empty and ran the table into the prose.
    fig.text(.055, .765, "CAUSE", color=DIM, fontsize=12, family="monospace")
    fig.text(.055, .700, "DINOv2 patch 14 + DPT head", color=FG, fontsize=22,
             fontweight="bold")
    fig.text(.055, .645, "Geometry is predicted per patch and interpolated\n"
             "below it. Every output grid is patch-aligned:\n"
             "518/14, 392/14, 294/14 — not the 518 px input\n"
             "cap the literature blames.",
             color=DIM, fontsize=13, va="top", linespacing=1.75)

    fig.text(.055, .410, "FIX", color=DIM, fontsize=12, family="monospace")
    fig.text(.055, .345, "Keep the poses, replace\nthe geometry", color=FG, fontsize=22,
             fontweight="bold", va="top", linespacing=1.35)
    fig.text(.055, .215, "MapAnything → COLMAP bundle adjustment →\n"
             "OpenMVS PatchMatch at full resolution. CPU only,\n"
             "18–33 min per clip. Bundle adjustment runs\nBEFORE densification.",
             color=DIM, fontsize=13, va="top", linespacing=1.75)

    rows = [("plane residual @ 6 cm", "1.29 / 1.38 cm", "0.35 / 0.76 cm"),
            ("finest detail resolved", "~30–50 cm", "1.9 / 3.5 mm"),
            ("relief above ground, max", "1.32 / 2.33 m", "3.01 / 3.58 m"),
            ("points above 1.5 m (Short)", "0.000 %", "0.902 %"),
            ("reprojection error", "—", "0.41 / 0.37 px"),
            ("ground covered (Kolu)", "241 m²", "327 m²")]
    X0, X1, X2 = .50, .755, .885
    fig.text(X0, .765, "MEASURED  ·  Short / Kolu", color=DIM, fontsize=12,
             family="monospace")
    fig.text(X1, .765, "before", color=BASE, fontsize=12, family="monospace")
    fig.text(X2, .765, "after", color=MVS, fontsize=12, family="monospace")
    y = .690
    for lab, lo, hi in rows:
        fig.text(X0, y, lab, color=FG, fontsize=13, family="monospace")
        fig.text(X1, y, lo, color=BASE, fontsize=13, family="monospace")
        fig.text(X2, y, hi, color=MVS, fontsize=13, fontweight="bold",
                 family="monospace")
        y -= .052
    fig.text(X0, y - .015, "Two clips, 42 and 45 keyframes.\nIdentical poses and "
             "renderer either side —\nonly the geometry stage changed.",
             color=DIM, fontsize=12.5, va="top", linespacing=1.75)
    fig.text(.055, .045, "No GNSS in either clip — absolute accuracy is not yet "
             "measurable; metre labels come from the model's own metric scale.",
             color="#7A7A74", fontsize=11.5, family="monospace")
    p = f"{OUT}/00_summary.png"
    fig.savefig(p, dpi=125, facecolor=BG)
    plt.close(fig)
    print("wrote", p)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    summary()
    ab("01_short_before_after.png", f"{ROOT}/out/ytd3d/render.png",
       f"{ROOT}/out/ytdmvs3d/render.png",
       "Buildings stop being paint on a sheet",
       "Short clip · 42 keyframes at 1080×1250 · identical poses, "
       "identical renderer — only the geometry stage changed",
       [("points above 1.5 m", "0.000 %", "0.902 %"),
        ("tallest structure", "1.32 m", "3.01 m"),
        ("detail at 6 cm", "1.29 cm", "0.35 cm"),
        ("dense points", "570 k", "1.34 M")])
    ab("02_kolu_before_after.png", f"{ROOT}/out/kolu3d/render.png",
       f"{ROOT}/out/kolumvs3d/render.png",
       "Fewer holes, not more",
       "Kolu survey pass · 45 keyframes at 1920×1080 · here the rebuild "
       "wins on coverage as well as accuracy",
       [("ground covered", "241 m²", "327 m²"),
        ("tallest structure", "2.33 m", "3.58 m"),
        ("detail at 6 cm", "1.38 cm", "0.76 cm"),
        ("dense points", "951 k", "3.45 M")])
    chart()
    print("\nall images in", OUT)
