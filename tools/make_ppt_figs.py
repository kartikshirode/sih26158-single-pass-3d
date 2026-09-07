"""
Figures for the SIH idea-submission deck.

Separate from `make_share_images.py` because that one targets a dark chat window and
this one has to sit on the mandated SIH template, which is white. Same numbers, same
colour roles, different ground.
"""
from __future__ import annotations

import os

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out", "ppt")
BASE, MVS, INK, DIM = "#C2612C", "#1F6FA8", "#1A1A1A", "#6B6B6B"

# docs/05-quality-analysis.md sections 8 and 9. Plane fitted in a ball of radius r,
# median |residual|, in cm.
KOLU_B = [(6, 1.382), (12, 2.762), (25, 4.756), (50, 5.852), (100, 7.219)]
KOLU_M = [(3, 0.349), (6, 0.756), (12, 1.487), (25, 2.787), (50, 4.707), (100, 7.359)]
SHORT_B = [(6, 1.288), (12, 1.944), (25, 2.344), (50, 2.634), (100, 3.340)]
SHORT_M = [(3, 0.187), (6, 0.353), (12, 0.624), (25, 1.121), (50, 2.031), (100, 3.217)]


def cell(path, row, col, w=1000):
    """One panel out of a 3x3 render sheet, trimmed to its content."""
    im = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB)
    H, W = im.shape[:2]
    ch, cw = H // 3, W // 3
    c = im[row * ch + int(ch * 0.06):(row + 1) * ch, col * cw:(col + 1) * cw]
    g = cv2.cvtColor(c, cv2.COLOR_RGB2GRAY)
    ys, xs = np.where(g > 18)
    if len(xs):
        c = c[max(ys.min() - 8, 0):ys.max() + 8, max(xs.min() - 8, 0):xs.max() + 8]
    s = w / c.shape[1]
    return cv2.resize(c, (w, int(c.shape[0] * s)), interpolation=cv2.INTER_AREA)


def before_after():
    """The evidence panel: same clip, same poses, only the geometry stage changed."""
    a = cell(f"{ROOT}/out/kolu3d/render.png", 1, 1)
    b = cell(f"{ROOT}/out/kolumvs3d/render.png", 1, 1)
    h = max(a.shape[0], b.shape[0])
    pad = lambda im: cv2.copyMakeBorder(im, 0, h - im.shape[0], 0, 0,
                                        cv2.BORDER_CONSTANT, value=(255, 255, 255))
    fig, ax = plt.subplots(1, 2, figsize=(9.2, 4.5), facecolor="white")
    for axi, img, lab, c in ((ax[0], pad(a), "BEFORE  ·  feed-forward point maps", BASE),
                             (ax[1], pad(b), "AFTER  ·  full-res photometric MVS", MVS)):
        axi.imshow(img); axi.axis("off")
        axi.set_title(lab, color=c, fontsize=11.5, fontweight="bold", pad=7)
        for s in ("top", "bottom", "left", "right"):
            axi.spines[s].set_visible(False)
    fig.subplots_adjust(left=.01, right=.99, top=.90, bottom=.01, wspace=.03)
    p = f"{OUT}/fig_beforeafter.png"
    fig.savefig(p, dpi=190, facecolor="white"); plt.close(fig)
    print("wrote", p)


def accuracy():
    """
    Detail vs scale. The baseline stalls at a floor; MVS keeps a constant slope, which
    is what a real surface looks like. This chart carries the novelty claim.
    """
    from matplotlib.ticker import FixedLocator, FuncFormatter
    fmt = FuncFormatter(lambda v, _: ("%g" % v))
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.0), facecolor="white")
    for ax, (bl, mv, name) in zip(axes, ((KOLU_B, KOLU_M, "Kolu survey pass  ·  45 views"),
                                         (SHORT_B, SHORT_M, "Village pass  ·  42 views"))):
        for data, c, lab, m in ((bl, BASE, "feed-forward point maps", "o"),
                                (mv, MVS, "full-resolution photometric MVS", "s")):
            x = [d[0] for d in data]; y = [d[1] for d in data]
            ax.plot(x, y, m + "-", color=c, lw=2.2, ms=6, label=lab)
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlabel("window radius (cm)", fontsize=9.5, color=DIM)
        ax.set_title(name, fontsize=10.5, color=INK, fontweight="bold", pad=8)
        ax.grid(alpha=.22, which="major", lw=.6)
        ax.xaxis.set_major_locator(FixedLocator([3, 6, 12, 25, 50, 100]))
        ax.xaxis.set_minor_locator(FixedLocator([]))
        ax.yaxis.set_major_locator(FixedLocator([0.2, 0.5, 1, 2, 5, 10]))
        ax.yaxis.set_minor_locator(FixedLocator([]))
        ax.xaxis.set_major_formatter(fmt); ax.yaxis.set_major_formatter(fmt)
        ax.tick_params(labelsize=8.8, colors=DIM)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    axes[0].set_ylabel("finest detail resolved\nmedian |residual|, cm", fontsize=9.5, color=DIM)
    axes[0].legend(fontsize=8.8, frameon=False, loc="upper left")
    # The two annotations are the whole point: where the old curve stops, and how far
    # past it the new one goes.
    axes[0].annotate("stalls at a 1.4 cm floor\n(no structure below it)",
                     xy=(6, 1.382), xytext=(9.5, 0.52), fontsize=8.4, color=BASE,
                     arrowprops=dict(arrowstyle="->", color=BASE, lw=1.1))
    axes[0].annotate("3.5 mm", xy=(3, 0.349), xytext=(3.55, 0.315), fontsize=9,
                     color=MVS, fontweight="bold")
    axes[1].annotate("1.9 mm", xy=(3, 0.187), xytext=(3.55, 0.170), fontsize=9,
                     color=MVS, fontweight="bold")
    fig.subplots_adjust(left=.115, right=.985, top=.86, bottom=.155, wspace=.16)
    p = f"{OUT}/fig_accuracy.png"
    fig.savefig(p, dpi=190, facecolor="white"); plt.close(fig)
    print("wrote", p)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    before_after()
    accuracy()
