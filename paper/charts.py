"""
Charts and the pipeline diagram for the research paper, written to paper/fig/.

Every number is copied from the recorded runs: research/exp05 and exp09 results,
docs/05 section 9 (Kolu) and the run manifests behind research/11 and 12.

    python paper/charts.py
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = os.path.join(os.path.dirname(__file__), "fig")
os.makedirs(OUT, exist_ok=True)
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": INK2,
                     "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "figure.dpi": 220, "savefig.dpi": 300, "savefig.bbox": "tight", "savefig.facecolor": "white"})


def grid(ax, axis="y"):
    ax.grid(axis=axis, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


# 1. EXP-09: scene error, full Sim(3) against yaw-only
def degeneracy():
    cls = ["Consumer", "SBAS", "RTK"]
    full = [310.955, 273.421, 267.062]
    yaw = [3.707, 1.692, 0.041]
    x = np.arange(3)
    fig, ax = plt.subplots(figsize=(5.6, 2.8))
    b1 = ax.bar(x - 0.19, full, 0.34, color=C[1], label="Full Sim(3), 7-DOF")
    b2 = ax.bar(x + 0.19, yaw, 0.34, color=C[0], label="Yaw-only with gravity, 5-DOF")
    ax.set_yscale("log")
    ax.set_ylim(0.02, 2000)
    ax.axhline(1.0, color=INK2, linewidth=0.8, linestyle="--")
    ax.text(2.55, 1.15, "1 m target", color=INK2, fontsize=8, ha="right")
    for bars in (b1, b2):
        for r in bars:
            v = r.get_height()
            ax.text(r.get_x() + r.get_width() / 2, v * 1.25, f"{v:.3g} m", ha="center",
                    fontsize=7.5, color=INK)
    ax.set_xticks(x, cls)
    ax.set_ylabel("Scene RMSE (m, log scale)")
    ax.legend(frameon=False, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.16))
    grid(ax)
    fig.savefig(os.path.join(OUT, "chart_degeneracy.png"))


# 2. EXP-05: consumer GNSS error does not average away
def gnss_flat():
    n = [50, 150, 300, 600, 1200, 2400]
    meas = [3.856, 4.683, 4.034, 4.419, 4.132, 4.581]
    pred = [3.856, 2.226, 1.574, 1.113, 0.787, 0.557]
    fig, ax = plt.subplots(figsize=(5.6, 2.6))
    ax.plot(n, meas, color=C[0], linewidth=2, marker="o", markersize=5, label="Measured")
    ax.plot(n, pred, color=C[1], linewidth=2, marker="s", markersize=5, label="If error fell as 1/sqrt(N)")
    ax.set_xscale("log")
    ax.set_xticks(n, [str(v) for v in n])
    ax.minorticks_off()
    ax.set_ylim(0, 5.3)
    ax.axhline(1.0, color=INK2, linewidth=0.8, linestyle="--")
    ax.text(2400, 1.12, "1 m target", color=INK2, fontsize=8, ha="right")
    ax.set_xlabel("Keyframes used in the fit")
    ax.set_ylabel("3D RMSE (m)")
    ax.legend(frameon=False, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.16))
    grid(ax)
    fig.savefig(os.path.join(OUT, "chart_gnss.png"))


# 3. Stage time per benchmark run (manifest and local_gpu_result.json)
def runtime():
    runs = ["B1 demo clip\n(18.9 s)", "B1 with the\ndepth prior", "B2 Nicosia\n(40 s)",
            "B3 test flight\n(20 s)", "B5v ten-minute\n(600 s)"]
    ingest = [3.307 + 4.074, 3.274 + 4.055, 1.711 + 6.522, 1.672 + 3.593, 1.787 + 6.656]
    poses = [41.85 + .76 + 5.37 + 7.13 + 56.44 + .5 + .28 + 1.67,
             41.72 + .75 + 5.68 + 7.11 + 58.77 + .49 + .29 + 1.67,
             28.69 + .71 + 3.81 + 13.09 + 181.56 + .54 + .29 + 1.81,
             58.38 + 1.69 + 6.09 + 16.17 + 22.89 + .29 + .19 + 1.0,
             40.94 + 1.71 + 11.91 + 30.8 + 43.58 + .42 + .24 + 1.44]
    dense = [2.11 + .38 + 51.37, 2.16 + .27 + 51.62, 2.31 + .29 + 16.02, 1.23 + .16 + 77.82,
             .39 + 1.71 + .22 + 140.03]
    # With the prior, its tiles, fusion, Poisson and RefineMesh count as mesh time.
    mesh = [38.34, 37.54 + 123.61 + 38.07 + 15.17 + 237.8, 6.95, 50.45, 78.94]
    tex = [52.78, 62.56, 15.03, 63.11, 116.38]
    total = [293.4, 752.7, 282.6, 349.0, 548.2]
    rest = [t - a - b - c - d - e for t, a, b, c, d, e in zip(total, ingest, poses, dense, mesh, tex)]
    parts = [("Screen and ingest", ingest), ("Camera and poses", poses), ("Dense", dense),
             ("Mesh, or depth prior", mesh), ("Texture", tex), ("Fill, level, georef, export", rest)]
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    y = np.arange(len(runs))[::-1]
    left = np.zeros(len(runs))
    for i, (lab, vals) in enumerate(parts):
        ax.barh(y, vals, 0.55, left=left, color=C[i], label=lab, edgecolor="white", linewidth=1)
        left += np.array(vals)
    for yi, t in zip(y, total):
        ax.text(t + 8, yi, f"{t:.1f} s", va="center", fontsize=8, color=INK)
    ax.axvline(900, color=INK2, linestyle="--", linewidth=0.8)
    ax.text(893, y[0] + 0.45, "900 s budget", fontsize=8, color=INK2, ha="right")
    ax.set_yticks(y, runs)
    ax.set_xlim(0, 960)
    ax.set_xlabel("Wall-clock seconds, one laptop (RTX 4060 8 GB)")
    ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.45, 1.25), fontsize=8)
    grid(ax, "x")
    fig.savefig(os.path.join(OUT, "chart_runtime.png"))


# 4. Kolu: plane-fit residual against radius, feed-forward vs MVS
def kolu_detail():
    r = [6, 12, 25, 50, 100]
    ma = [1.382, 2.762, 4.756, 5.852, 7.219]
    mvs = [0.756, 1.487, 2.787, 4.707, 7.359]
    fig, ax = plt.subplots(figsize=(5.0, 2.7))
    ax.plot(r, ma, color=C[1], linewidth=2, marker="s", markersize=5, label="MapAnything point map")
    ax.plot([3] + r, [0.349] + mvs, color=C[0], linewidth=2, marker="o", markersize=5,
            label="COLMAP + OpenMVS")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xticks([3, 6, 12, 25, 50, 100], ["3", "6", "12", "25", "50", "100"])
    ax.minorticks_off()
    ax.set_yticks([0.5, 1, 2, 5], ["0.5", "1", "2", "5"])
    ax.set_xlabel("Neighbourhood radius (model cm)")
    ax.set_ylabel("Median plane residual (cm)")
    ax.legend(frameon=False, loc="upper left")
    grid(ax)
    fig.savefig(os.path.join(OUT, "chart_kolu.png"))


# 5. The pipeline
def pipeline():
    fig, ax = plt.subplots(figsize=(7.2, 3.9))
    ax.set_xlim(0, 100); ax.set_ylim(0, 58); ax.axis("off")

    def box(x, y, w, h, title, sub, fc="#eef4fc", ec=C[0]):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2",
                                    fc=fc, ec=ec, lw=1))
        ax.text(x + w / 2, y + h - 2.6, title, ha="center", va="top", fontsize=8, weight="bold", color=INK)
        ax.text(x + w / 2, y + h - 6.4, sub, ha="center", va="top", fontsize=6.6, color=INK2, linespacing=1.25)

    def arrow(x0, y0, x1, y1):
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                    arrowprops=dict(arrowstyle="-|>", color=INK2, lw=0.9, shrinkA=0, shrinkB=0))

    # inputs
    box(0.5, 40, 13, 13, "Inputs", "one video\n+ DJI SRT\n(optional)", fc="#f6f6f4", ec=INK2)
    row1 = [("S0 Screen", "admissibility:\nsky, horizon,\nshots, overlay"),
            ("S1 Ingest", "decode, crop,\nshot cut, blur and\nflow keyframes"),
            ("S2 Plan", "keyframe set for\nthe ladder level"),
            ("S3a Poses","MapAnything focal,\nCOLMAP SIFT and\nglobal mapper")]
    xs = [17.5, 38, 58.5, 79]
    for (t, s), x in zip(row1, xs):
        box(x, 40, 18, 13, t, s)
    arrow(14.3, 46.5, 17.1, 46.5)
    for a, b in zip(xs[:-1], xs[1:]):
        arrow(a + 18.4, 46.5, b - 0.4, 46.5)
    row2 = [("S3b Dense", "OpenMVS densify,\nfusion filter 1"),
            ("S3c Mesh", "ReconstructMesh;\noptional depth\nprior (TSDF)"),
            ("S3d Texture", "TextureMesh, fill\nunseen faces,\nseam levelling"),
            ("S4 Scale", "GNSS, known\nlength, or model\nunits (labelled)")]
    xs2 = [79, 58.5, 38, 17.5]
    for (t, s), x in zip(row2, xs2):
        box(x, 22, 18, 13, t, s)
    arrow(88, 39.6, 88, 35.4)
    for a, b in zip(xs2[:-1], xs2[1:]):
        arrow(a - 0.4, 28.5, b + 18.4, 28.5)
    row3 = [("S5 Georef", "SRT fit, 5-DOF,\ngimbal-pitch\nstretch, ENU"),
            ("S5b Level", "gravity from\nthe camera\ntrack"),
            ("S6 Export", "OBJ GLB FBX\nPLY LAS\nGeoTIFF"),
            ("S7-S8", "score and\nthree-valued\nverdicts")]
    xs3 = [17.5, 34.5, 51.5, 68.5]
    for (t, s), x in zip(row3, xs3):
        box(x, 4, 14, 13, t, s)
    arrow(24.5, 21.6, 24.5, 17.4)
    for a, b in zip(xs3[:-1], xs3[1:]):
        arrow(a + 14.4, 10.5, b - 0.4, 10.5)
    arrow(82.9, 10.5, 85.1, 10.5)
    box(85.5, 4, 14, 13, "Outputs", "mesh, cloud,\nDSM, QA report,\nweb workspace", fc="#f6f6f4", ec=INK2)
    ax.text(50, 56.2, "Orchestrator: content-addressed resume, 900 s budget, degradation ladder L0-L5, run manifest",
            ha="center", fontsize=7, color=INK2, style="italic")
    fig.savefig(os.path.join(OUT, "fig_pipeline.png"))


if __name__ == "__main__":
    degeneracy(); gnss_flat(); runtime(); kolu_detail(); pipeline()
    print(sorted(os.listdir(OUT)))
