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

def series(clip):
    """
    Plane residual vs window radius, straight out of the measurement.

    Read rather than transcribed, on purpose: a chart with hand-typed numbers goes stale
    the first time a run changes and nobody notices. Regenerate the inputs with
      python src/analysis/compare_mvs.py --baseline ... --mvs ... --json out/ppt/measure_<clip>.json
    """
    import json
    p = f"{ROOT}/out/ppt/measure_{clip}.json"
    if not os.path.exists(p):
        raise SystemExit(f"missing {p} - run src/analysis/compare_mvs.py --json first")
    d = json.load(open(p))
    grab = lambda k: [(r, v) for r, v, _ in d[k]["roughness_cm"]]
    return grab("baseline"), grab("mvs")


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
    (kb, km), (sb, sm) = series("kolu"), series("short")
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.0), facecolor="white")
    for ax, (bl, mv, name) in zip(axes, ((kb, km, "Kolu survey pass  ·  45 views"),
                                         (sb, sm, "Village pass  ·  42 views"))):
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
    # Anchored on the measured end points, not on typed-in coordinates, so the labels
    # follow the data if a re-run moves it.
    bx, by = kb[0]
    axes[0].annotate(f"stalls at a {by:.1f} cm floor\n(no structure below it)",
                     xy=(bx, by), xytext=(bx * 1.6, by * 0.38), fontsize=8.4,
                     color=BASE, arrowprops=dict(arrowstyle="->", color=BASE, lw=1.1))
    for ax, (mx, my) in ((axes[0], km[0]), (axes[1], sm[0])):
        ax.annotate(f"{my * 10:.1f} mm", xy=(mx, my), xytext=(mx * 1.18, my * 0.90),
                    fontsize=9, color=MVS, fontweight="bold")
    fig.subplots_adjust(left=.115, right=.985, top=.86, bottom=.155, wspace=.16)
    p = f"{OUT}/fig_accuracy.png"
    fig.savefig(p, dpi=190, facecolor="white"); plt.close(fig)
    print("wrote", p)


def missions():
    """
    The value proposition as a picture rather than a sentence.

    Two flight plans over the same ground. Nobody needs to read a bullet explaining
    that one line is cheaper than eight lines plus surveyed markers.
    """
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 3.5), facecolor="white")
    for ax, single in zip(axes, (False, True)):
        ax.add_patch(plt.Rectangle((0, 0), 10, 6, fc="#F2F0EA", ec="#DAD5C8", lw=1))
        for x, y in ((1.4, 1.1), (8.4, 1.4), (5.0, 3.1), (1.9, 4.8), (8.0, 4.7)):
            ax.add_patch(plt.Rectangle((x, y), 1.2, 0.75, fc="#CFC8B6", ec="none"))
        col = MVS if single else BASE
        if single:
            ax.annotate("", xy=(9.6, 3.0), xytext=(0.4, 3.0),
                        arrowprops=dict(arrowstyle="-|>", color=col, lw=2.6))
            for x in np.linspace(1.2, 8.8, 6):          # camera stations along the pass
                ax.plot([x], [3.0], "o", color=col, ms=6, zorder=3)
            stats = [("flight legs", "1"), ("ground control points", "0"),
                     ("passes over target", "1")]
        else:
            ys = np.linspace(0.7, 5.3, 7)
            path = []
            for i, y in enumerate(ys):
                path += [(0.5, y), (9.5, y)] if i % 2 == 0 else [(9.5, y), (0.5, y)]
            ax.plot([p[0] for p in path], [p[1] for p in path], "-", color=col, lw=1.9)
            for gx, gy in ((1.0, 0.9), (9.0, 0.9), (5.0, 3.0), (1.0, 5.1), (9.0, 5.1)):
                ax.plot([gx], [gy], "^", color="#2E7D32", ms=9, zorder=4)
            stats = [("flight legs", "7+"), ("ground control points", "5+"),
                     ("passes over target", "3+")]
        ax.set_xlim(-0.3, 10.3); ax.set_ylim(-2.6, 7.2)
        ax.set_aspect("equal"); ax.axis("off")
        ax.text(5, 6.55, "ONE PASS  ·  this system" if single
                else "CONVENTIONAL  ·  planned grid survey",
                ha="center", fontsize=11.5, fontweight="bold", color=col)
        for i, (lab, val) in enumerate(stats):
            ax.text(1.0 + i * 4.0, -0.95, val, fontsize=15, fontweight="bold",
                    color=col, ha="center")
            ax.text(1.0 + i * 4.0, -1.95, lab, fontsize=8, color=DIM, ha="center")
    # Legend sits above the panel, not in the stats row, where it collided with "3+".
    axes[0].plot([0.45], [6.18], "^", color="#2E7D32", ms=8, clip_on=False)
    axes[0].text(0.85, 6.05, "surveyed ground control marker", fontsize=7.5, color=DIM)
    fig.subplots_adjust(left=.01, right=.99, top=.97, bottom=.02, wspace=.05)
    p = f"{OUT}/fig_missions.png"
    fig.savefig(p, dpi=190, facecolor="white"); plt.close(fig)
    print("wrote", p)


def timing():
    """
    Where the wall clock actually goes, straight from the run's own stage timings.

    This is the honest version of the speed story: one stage is three quarters of the
    budget, and it is the stage a GPU changes. A reader gets that from the picture
    without being told, and it makes the 15-minute gap on the next slide legible
    rather than alarming.
    """
    import json
    r = json.load(open(f"{ROOT}/out/kolu_mvs/mvs_result.json"))
    t = {s["stage"]: s["seconds"] for s in r["stages"]}
    groups = [
        ("features + matching", t["feature_extractor"] + t["exhaustive_matcher"], "#9AA7B0"),
        ("pose + bundle adjustment", t["point_triangulator"] + t["bundle_adjuster"], "#7C8B96"),
        ("dense geometry (PatchMatch MVS)", t["DensifyPointCloud"], BASE),
        ("mesh", t["ReconstructMesh"], "#5E6B75"),
    ]
    total = r["total_seconds"]
    fig, ax = plt.subplots(figsize=(7.5, 1.42), facecolor="white")
    left = 0.0
    for name, sec, c in groups:
        ax.barh([0], [sec], left=left, height=0.42, color=c,
                edgecolor="white", linewidth=1.2)
        if sec / total > 0.06:
            ax.text(left + sec / 2, 0, f"{sec/60:.0f}m", ha="center", va="center",
                    color="white", fontsize=9.5, fontweight="bold")
        left += sec
    ax.set_xlim(0, total); ax.set_ylim(-1.35, 0.85); ax.axis("off")
    ax.text(0, 0.62, f"Where the {int(total)//60}m {int(total)%60:02d}s goes",
            fontsize=10.5, fontweight="bold", color=INK)
    x = 0.0
    for name, sec, c in groups:
        if sec / total > 0.06:
            ax.text(x + sec / 2, -0.34, name, ha="center", va="top",
                    fontsize=7.8, color=DIM)
        x += sec
    ax.annotate(f"{groups[2][1]/total:.0%} of the run — and the one stage a GPU changes",
                xy=(groups[0][1] + groups[1][1] + groups[2][1] / 2, -0.84),
                ha="center", fontsize=8.6, color=BASE, fontweight="bold")
    fig.subplots_adjust(left=.005, right=.995, top=.98, bottom=.02)
    p = f"{OUT}/fig_timing.png"
    fig.savefig(p, dpi=190, facecolor="white"); plt.close(fig)
    print("wrote", p)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    before_after()
    accuracy()
    missions()
    timing()
