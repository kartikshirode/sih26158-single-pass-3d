"""
Figures for the SIH idea-submission deck.

Separate from `make_share_images.py` because that one targets a dark chat window and
this one has to sit on the mandated SIH template, which is white.

Everything visual comes from `deck_theme`: the same navy, the same rust, the same greys
and the same two typefaces the slides use. Each figure is also authored at exactly the
width it is placed at, so its type is in the same point system as the surrounding slide
rather than being silently rescaled.
"""
from __future__ import annotations

import os
import sys

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deck_theme import FAINT, FIG, INK, MONO, MUTED, NAVY, PAPER, RULE, RUST, SANS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out", "ppt")
DPI = 300

# matplotlib registers seguisb.ttf under the family "Segoe UI" at weight semibold
# rather than as a family of its own, so headings ask for the weight, not the name.
SEMI = dict(family=SANS, weight="semibold")
plt.rcParams.update({
    "font.family": SANS,
    "axes.edgecolor": RULE, "axes.linewidth": 0.8, "axes.labelcolor": MUTED,
    "xtick.color": FAINT, "ytick.color": FAINT,
    "xtick.major.width": 0.8, "ytick.major.width": 0.8,
    "grid.color": RULE, "grid.linewidth": 0.7,
    "figure.facecolor": PAPER, "savefig.facecolor": PAPER,
})


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


MAX_TRIS = 400_000
LIGHT_DIR = np.array([0.35, -0.75, 0.56])


def _mesh_in_frame(d, B, c0):
    """Mesh vertices, faces and colours, rotated into a shared upright frame."""
    V = (np.load(f"{ROOT}/out/{d}/mesh_v.npy") - c0) @ B.T
    F = np.load(f"{ROOT}/out/{d}/mesh_f.npy")
    C = np.load(f"{ROOT}/out/{d}/mesh_c.npy") / 255.0
    if len(F) > MAX_TRIS:
        # Decimate, never subsample: dropping random triangles turns the surface into
        # disconnected facets and the shading collapses to speckle.
        import open3d as o3d
        m = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(V),
                                      o3d.utility.Vector3iVector(F))
        m.vertex_colors = o3d.utility.Vector3dVector(C)
        m = m.simplify_quadric_decimation(MAX_TRIS)
        V, F, C = (np.asarray(m.vertices), np.asarray(m.triangles),
                   np.asarray(m.vertex_colors))
    return V, F, C


def _shade(ax, V, F, C, az, el, radius, centre, aspect):
    """
    Flat-shaded triangles on a light ground, painter's-algorithm depth sort.

    Ambient is lifted well above the dark-theme renderer's 0.42: on white, a surface
    lit for a black background reads as a silhouette, and the detail this whole deck
    is arguing about disappears.
    """
    sys.path.insert(0, os.path.join(ROOT, "src", "pipeline"))
    from render_views import rot
    from matplotlib.collections import PolyCollection

    Vr = V @ rot(az, el).T
    tri = Vr[F]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    lam = 0.58 + 0.42 * np.clip(np.abs(n @ LIGHT_DIR), 0.0, 1.0)
    fc = np.clip(C[F].mean(1) * lam[:, None], 0, 1)
    order = np.argsort(tri[:, :, 2].mean(1))
    ax.add_collection(PolyCollection(tri[order][:, :, :2], facecolors=fc[order],
                                     edgecolors="none", linewidths=0))
    # One camera for both panels. Centring each on its own centroid made the smaller,
    # holier reconstruction look merely zoomed out, which hides the actual finding.
    cx, cy = centre
    ax.set_xlim(cx - radius * aspect, cx + radius * aspect)
    ax.set_ylim(cy - radius, cy + radius)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)


def before_after(az=30, el=55):
    """
    The evidence panel, rendered fresh on white rather than cropped out of the
    dark-theme contact sheet.

    Both panels use the BASELINE's upright frame, centre and radius. MVS inherits
    MapAnything's frame, so the two really are in one coordinate system, and sharing
    the framing is what makes this a comparison rather than two pictures.
    """
    sys.path.insert(0, os.path.join(ROOT, "src", "pipeline"))
    from render_views import rot, upright_frame

    base, mvs = "kolu3d", "kolumvs3d"
    P = np.load(f"{ROOT}/out/{base}/points_fused.npy").astype(np.float64)
    cen = np.load(f"{ROOT}/out/{base}/cam_centres.npy")
    B, c0 = upright_frame(P, cen), P.mean(0)

    w, h = FIG["beforeafter"]
    fig, ax = plt.subplots(1, 2, figsize=(w, h))
    fig.subplots_adjust(left=.004, right=.996, top=.845, bottom=.055, wspace=.024)
    # The view window has to match the axes box, or the model floats inside a frame of
    # the wrong shape. Measured off the laid-out figure rather than guessed.
    bb = ax[0].get_position()
    aspect = (bb.width * w) / (bb.height * h)

    # Framing taken from BOTH clouds together, in the view's own screen plane, so the
    # wider reconstruction is not cropped and the narrower one is not re-centred.
    R = rot(az, el)
    scr = np.vstack([((np.load(f"{ROOT}/out/{d}/points_fused.npy").astype(np.float64)
                       - c0) @ B.T @ R.T)[::37, :2] for d in (base, mvs)])
    centre = (float((scr[:, 0].min() + scr[:, 0].max()) / 2),
              float((scr[:, 1].min() + scr[:, 1].max()) / 2))
    radius = 0.52 * float(max(np.ptp(scr[:, 1]), np.ptp(scr[:, 0]) / aspect))

    for axi, d, lab, note, c in (
            (ax[0], base, "BEFORE", "feed-forward point maps", RUST),
            (ax[1], mvs, "AFTER", "full-resolution photometric MVS", NAVY)):
        _shade(axi, *_mesh_in_frame(d, B, c0), az, el, radius, centre, aspect)
        axi.set_title(lab, color=c, fontsize=9.5, pad=9, loc="left", **SEMI)
        axi.text(1.0, 1.028, note, transform=axi.transAxes, ha="right", va="baseline",
                 fontsize=7.4, color=MUTED)
        # A hairline under each caption ties the two panels to the slide's own rules.
        axi.plot([0, 1], [1.005, 1.005], transform=axi.transAxes, color=c,
                 lw=0.9, clip_on=False)

    p = f"{OUT}/fig_beforeafter.png"
    fig.savefig(p, dpi=DPI)
    plt.close(fig)
    print("wrote", p)


def accuracy():
    """
    Detail vs scale. The baseline stalls at a floor; MVS keeps a constant slope, which
    is what a real surface looks like. This chart carries the novelty claim.

    No legend box. The two series are named once, in place, at the left-hand end where
    they are furthest apart and where the baseline simply stops - which is itself the
    finding, so the labelling and the argument become the same gesture.
    """
    from matplotlib.ticker import FixedLocator, FuncFormatter
    fmt = FuncFormatter(lambda v, _: ("%g" % v))
    (kb, km), (sb, sm) = series("kolu"), series("short")
    w, h = FIG["accuracy"]
    fig, axes = plt.subplots(1, 2, figsize=(w, h))
    for ax, (bl, mv, name) in zip(axes, ((kb, km, "Kolu survey pass · 45 views"),
                                         (sb, sm, "Village pass · 42 views"))):
        for data, c in ((bl, RUST), (mv, NAVY)):
            ax.plot([d[0] for d in data], [d[1] for d in data], "o-",
                    color=c, lw=1.9, ms=3.6, mew=0, zorder=3)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(2.4, 130)
        ax.set_ylim(0.13, 12)
        ax.set_xlabel("window radius, cm", fontsize=7.4, labelpad=2)
        ax.set_title(name, fontsize=8.2, color=INK, pad=5, loc="left", **SEMI)
        ax.grid(alpha=.55, which="major")
        ax.set_axisbelow(True)
        ax.xaxis.set_major_locator(FixedLocator([3, 6, 12, 25, 50, 100]))
        ax.yaxis.set_major_locator(FixedLocator([0.2, 0.5, 1, 2, 5, 10]))
        for a in (ax.xaxis, ax.yaxis):
            a.set_minor_locator(FixedLocator([]))
            a.set_major_formatter(fmt)
        ax.tick_params(labelsize=7, pad=1.5)
        for lab in ax.get_xticklabels() + ax.get_yticklabels():
            lab.set_fontfamily(MONO)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    axes[0].set_ylabel("median |residual|, cm", fontsize=7.4, labelpad=2)

    # Named in place, on the panel that establishes the comparison. The right panel
    # inherits the meaning from the colour and stays clean.
    bx, by = kb[0]
    axes[0].plot([bx], [by], "o", color=RUST, ms=6.5, mfc=PAPER, mew=1.6, zorder=4)
    axes[0].annotate("feed-forward point maps stop here:"
                     f"\na {by:.1f} cm floor, nothing below it",
                     xy=(bx, by), xytext=(2.68, 5.2), fontsize=7.2, color=RUST,
                     linespacing=1.35, va="bottom",
                     arrowprops=dict(arrowstyle="-", color=RUST, lw=0.8,
                                     shrinkA=2, shrinkB=5))
    axes[0].text(2.68, 0.152, "full-resolution photometric MVS", fontsize=7.2,
                 color=NAVY, **SEMI)
    for ax, (mx, my) in ((axes[0], km[0]), (axes[1], sm[0])):
        ax.annotate(f"{my * 10:.1f} mm", xy=(mx, my), xytext=(mx * 1.22, my * 0.80),
                    fontsize=8, color=NAVY, family=MONO, weight="bold")
    fig.subplots_adjust(left=.098, right=.995, top=.885, bottom=.155, wspace=.14)
    p = f"{OUT}/fig_accuracy.png"
    fig.savefig(p, dpi=DPI)
    plt.close(fig)
    print("wrote", p)


def missions():
    """
    The value proposition as a picture rather than a sentence.

    Two flight plans over the same ground. Nobody needs to read a bullet explaining
    that one line is cheaper than eight lines plus surveyed markers.
    """
    # Map and stats live in separate axes. Sharing one axes forced the equal-aspect
    # map to reserve vertical room for the title and the stat row, and an equal-aspect
    # box that tall could only fill about two thirds of the width it was given.
    w, h = FIG["missions"]
    fig = plt.figure(figsize=(w, h))
    gs = fig.add_gridspec(2, 2, height_ratios=[2.15, 1], hspace=0.10, wspace=0.07,
                          left=.006, right=.994, top=.875, bottom=.02)
    maps = [fig.add_subplot(gs[0, j]) for j in (0, 1)]
    bars = [fig.add_subplot(gs[1, j]) for j in (0, 1)]
    for ax, sax, single in zip(maps, bars, (False, True)):
        ax.add_patch(plt.Rectangle((0, 0), 10, 4.4, fc="#F4F4F1", ec=RULE, lw=0.8))
        for x, y in ((1.4, 0.8), (8.4, 1.0), (5.0, 2.3), (1.9, 3.5), (8.0, 3.4)):
            ax.add_patch(plt.Rectangle((x, y), 1.2, 0.55, fc="#D9D9D3", ec="none"))
        col = NAVY if single else RUST
        if single:
            ax.annotate("", xy=(9.6, 2.2), xytext=(0.4, 2.2),
                        arrowprops=dict(arrowstyle="-|>", color=col, lw=2.0))
            for x in np.linspace(1.2, 8.8, 6):          # camera stations along the pass
                ax.plot([x], [2.2], "o", color=col, ms=4, zorder=3)
            stats = [("1", "flight\nleg"), ("0", "ground control\npoints"),
                     ("1", "pass over\ntarget")]
        else:
            ys = np.linspace(0.5, 3.9, 7)
            path = []
            for i, y in enumerate(ys):
                path += [(0.5, y), (9.5, y)] if i % 2 == 0 else [(9.5, y), (0.5, y)]
            ax.plot([p[0] for p in path], [p[1] for p in path], "-", color=col, lw=1.3)
            for gx, gy in ((1.0, 0.68), (9.0, 0.68), (5.0, 2.2), (1.0, 3.72),
                           (9.0, 3.72)):
                ax.plot([gx], [gy], "^", color=PAPER, mec=col, mew=1.2, ms=5.5,
                        zorder=4)
            stats = [("7+", "flight\nlegs"), ("5+", "ground control\npoints"),
                     ("3+", "passes over\ntarget")]
        ax.set_xlim(-0.15, 10.15)
        ax.set_ylim(-0.15, 4.55)
        ax.set_aspect("equal")
        ax.axis("off")
        # Titles in axes coordinates: the map's own units now cover only the ground, so
        # anything anchored in data space would move whenever the plot is retuned.
        ax.text(0, 1.10, "ONE PASS" if single else "CONVENTIONAL", fontsize=9,
                color=col, va="bottom", transform=ax.transAxes, **SEMI)
        ax.text(1.0, 1.115, "this system" if single else "planned grid survey",
                fontsize=7.2, color=MUTED, ha="right", va="bottom",
                transform=ax.transAxes)
        ax.plot([0, 1], [1.06, 1.06], color=col, lw=0.9, transform=ax.transAxes,
                clip_on=False)

        sax.set_xlim(0, 10)
        sax.set_ylim(0, 1)
        sax.axis("off")
        sax.plot([0, 10], [0.95, 0.95], color="#E6E9ED", lw=0.8)
        for i, (val, lab) in enumerate(stats):
            sax.text(0.1 + i * 3.5, 0.76, val, fontsize=12.5, color=col, va="top",
                     family=MONO, weight="bold")
            sax.text(0.1 + i * 3.5, 0.30, lab, fontsize=6.6, color=MUTED, va="top",
                     linespacing=1.3)
    # The triangles need a key, but a floating one collided with the panel title, so it
    # sits inside the survey panel where the grid lines leave the corner free.
    maps[0].plot([0.45], [4.18], "^", color=PAPER, mec=RUST, mew=1.1, ms=5, zorder=5)
    maps[0].text(0.78, 4.18, "ground control", fontsize=6.2, color=RUST, va="center")
    p = f"{OUT}/fig_missions.png"
    fig.savefig(p, dpi=DPI)
    plt.close(fig)
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
        ("features + matching", t["feature_extractor"] + t["exhaustive_matcher"],
         "#C3CBD4"),
        ("pose + bundle adjustment", t["point_triangulator"] + t["bundle_adjuster"],
         "#9AA6B3"),
        ("dense geometry · PatchMatch MVS", t["DensifyPointCloud"], RUST),
        ("mesh", t["ReconstructMesh"], "#77828F"),
    ]
    total = r["total_seconds"]
    w, h = FIG["timing"]
    fig, ax = plt.subplots(figsize=(w, h))
    left = 0.0
    for name, sec, c in groups:
        ax.barh([0], [sec], left=left, height=0.34, color=c,
                edgecolor=PAPER, linewidth=1.0)
        if sec / total > 0.06:
            ax.text(left + sec / 2, 0, f"{sec/60:.0f}m", ha="center", va="center",
                    color=PAPER, fontsize=8, family=MONO, weight="bold")
        left += sec
    ax.set_xlim(0, total)
    ax.set_ylim(-1.18, 0.86)
    ax.axis("off")
    ax.text(0, 0.52, f"WHERE THE {int(total)//60}m {int(total)%60:02d}s GOES",
            fontsize=7.6, color=MUTED, va="bottom", **SEMI)
    ax.plot([0, total], [0.42, 0.42], color=RULE, lw=0.8)
    x = 0.0
    for name, sec, c in groups:
        if sec / total > 0.06:
            ax.text(x + sec / 2, -0.28, name, ha="center", va="top",
                    fontsize=6.8, color=MUTED)
        x += sec
    ax.annotate(f"{groups[2][1]/total:.0%} of the run, and the one stage a GPU changes",
                xy=(groups[0][1] + groups[1][1] + groups[2][1] / 2, -0.80),
                ha="center", va="top", fontsize=7.6, color=RUST, **SEMI)
    fig.subplots_adjust(left=.004, right=.996, top=.99, bottom=.02)
    p = f"{OUT}/fig_timing.png"
    fig.savefig(p, dpi=DPI)
    plt.close(fig)
    print("wrote", p)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    before_after()
    accuracy()
    missions()
    timing()
