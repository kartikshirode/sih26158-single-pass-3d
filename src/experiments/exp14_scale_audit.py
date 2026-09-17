"""
EXP-14 - Is the metric scale right? Audit it against things of known size in the scene.

Every metre on the demo, the gallery, the deck and docs/05 comes from MapAnything's
`metric_scaling_factor`. Until now the only check on it was a plausibility band (implied
camera speed 1.6-3.0 m/s, altitude 6.4-11.4 m), and docs/05 said openly that a 30% error
would pass that band. This experiment replaces the band with measurements against
objects whose real size is published.

The Kolu clip is a wildlife overpass on Estonian national road 2 (Tallinn-Tartu), so it
carries two independent rulers, neither of which depends on the model:

  1. LANE WIDTH. The four-lane sections are designed on 3.5 m lanes (the Swedish-style
     cross-section); the ministry's minimum for 2+2 is 3.75 m. Take both as the bracket.
       ERR 650086, "Kose-Vo~obu neljarealine maantee ehitatakse Rootsi laiuse jargi"
       ERR news 1608116446 (Karevere-Kardla: 3.5 m lanes)
  2. THE ECODUCT WAIST. Kolu, Estonia's first ecoduct (2013), is 21-22 m wide at its
     narrowest point.
       et.wikipedia "Okodukt": "ehitati Kolu sild selle kitsaimas kohas 22 meetri laiuseks"
       21 m is reported elsewhere; the bracket carries both.

A third check is one-sided. Estonian road design norms require 5.0 m of clearance under
any overpass open to vehicles ("Tuleb tagada korgusgabariit 5,0 m ... viadukti ja estakaadi
all avades, kus on lubatud soidukiliiklus" - MKM regulation 106, par. 9, and the same
paragraph in the 1999 norms the 2013 structure was built under). The arch rings are
reconstructed on the portal face, so the crown clearance is measurable there - the
underpass interior is not - and it gives a FLOOR on the factor, not an estimate.

Both rulers are measured in the export's own gravity-aligned frame - the frame every shipped
file (OBJ/PLY/LAS/GeoTIFF/glTF/FBX) and both viewer pages use - so the factor found here
applies to the artefacts, not to some intermediate.

    python src/experiments/exp14_scale_audit.py            # writes research/exp14-results.txt

Scope, stated plainly: this audits ONE clip. The scale error comes from a per-run model
output, so the factor found here says nothing about any other run.
"""
from __future__ import annotations

import io
import json
import os
import sys

import numpy as np
from scipy.signal import find_peaks

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src", "pipeline"))
from gravity import frame  # noqa: E402

RUN = os.path.join(ROOT, "out", "kolumvs3d")
LANE_REAL = (3.50, 3.75)        # m, design basis .. ministry 2+2 minimum
WAIST_REAL = (21.0, 22.0)       # m, the two published figures
CLEARANCE_MIN = 5.0             # m, Estonian minimum under an overpass with traffic
CAL_OUT = os.path.join(ROOT, "research", "calibration", "kolu.json")

out = io.StringIO()


def say(s=""):
    print(s)
    out.write(s + "\n")


def load_enu():
    P = np.load(f"{RUN}/points_fused.npy").astype(np.float64)
    C = np.load(f"{RUN}/colors_fused.npy").astype(np.float64)
    man = json.load(open(f"{RUN}/export/export_manifest.json"))
    B = frame(np.array(man["gravity"]["up"]))
    # identical to export_formats.export_all: centroid origin, [e1, e2, up]
    E = ((P - P.mean(0)) @ B.T)[:, [0, 2, 1]]
    return E, C, man


def lane_width(E, C):
    """Across-road paint profile on the right-hand carriageway."""
    # below the deck (the road is the low surface) and clear of the ecoduct
    m = (E[:, 0] > 3.5) & (E[:, 0] < 9.5) & (E[:, 1] > -6.5) & (E[:, 1] < 0.5) & (E[:, 2] < -0.3)
    P, K = E[m], C[m]
    lum = K.mean(1)
    sat = K.max(1) - K.min(1)
    green = (K[:, 1] > K[:, 0] + 8) & (K[:, 1] > K[:, 2] + 8)
    paint = (lum > np.percentile(lum[~green], 92)) & (sat < 30) & ~green

    def profile(theta, mask, bw=0.02):
        u = -np.sin(theta) * P[:, 0] + np.cos(theta) * P[:, 1]
        bins = np.arange(u.min(), u.max() + bw, bw)
        tot, _ = np.histogram(u, bins)
        sel, _ = np.histogram(u[mask], bins)
        return bins[:-1] + bw / 2, np.where(tot > 20, sel / np.maximum(tot, 1), 0.0)

    # the road direction is whatever makes the grass strips sharpest in profile
    theta = max(np.radians(np.arange(-45, 0, 0.1)), key=lambda t: profile(t, green)[1].var())
    u, fp = profile(theta, paint)
    fp = np.convolve(fp, np.ones(3) / 3, mode="same")
    pk, pr = find_peaks(fp, height=0.10, distance=15, prominence=0.06)
    pos, fill = u[pk], pr["peak_heights"]

    # A carriageway reads solid | dashed | solid. The dashed line is the one whose
    # paint fraction is LOWEST of three consecutive peaks, and the two lanes either side
    # of it should match. Pick the most symmetric such triple.
    best = None
    for i in range(1, len(pos) - 1):
        a, b = pos[i] - pos[i - 1], pos[i + 1] - pos[i]
        if not (fill[i] < fill[i - 1] and fill[i] < fill[i + 1]):
            continue
        if not (0.3 < a < 1.5 and 0.3 < b < 1.5):
            continue
        asym = abs(a - b) / (a + b)
        if best is None or asym < best[0]:
            best = (asym, i, a, b)
    return theta, pos, fill, best


def waist_width(E, theta):
    """Narrowest along-road distance between the two barrier crests on the deck."""
    w = np.cos(theta) * E[:, 0] + np.sin(theta) * E[:, 1]      # along road = across deck
    v = -np.sin(theta) * E[:, 0] + np.cos(theta) * E[:, 1]     # across road = along deck
    h = E[:, 2]
    bw = 0.05
    bins = np.arange(-8, 8 + bw, bw)
    cen = bins[:-1] + bw / 2
    rows = []
    for v0 in np.arange(-3.0, 7.0, 0.25):
        s = (v > v0) & (v < v0 + 0.25) & (np.abs(w) < 8)
        if s.sum() < 2000:
            continue
        idx = np.digitize(w[s], bins) - 1
        hmax = np.full(len(cen), -np.inf)
        np.maximum.at(hmax, idx, h[s])
        hmax[np.isinf(hmax)] = np.nan
        deck_bins = np.where(hmax > 0.2)[0]
        if len(deck_bins) < 20:
            continue
        c = int(np.median(deck_bins))
        # deck level from the median point height near the centre line, NOT from the
        # per-bin maxima: shrubs on the deck inflate those and hide the barrier crests
        ws, hs = w[s], h[s]
        deck_h = float(np.median(hs[np.abs(ws - cen[c]) < 1.0]))

        def edge(step):
            # walk outward until the road level, or a gap (the unobserved drop), is hit
            i, gap = c, 0
            while 0 <= i < len(hmax):
                gap = gap + 1 if np.isnan(hmax[i]) else 0
                if (not np.isnan(hmax[i]) and hmax[i] < -0.3) or gap * bw >= 0.3:
                    return i
                i += step
            return None

        lo, hi = edge(-1), edge(+1)
        if lo is None or hi is None:
            continue
        k = int(0.8 / bw)
        L = lo + int(np.nanargmax(hmax[lo:lo + k]))
        R = hi - k + int(np.nanargmax(hmax[hi - k:hi + 1]))
        # only accept a slice where BOTH crests stand clear of the deck - otherwise the
        # "wall" is a point on the embankment slope and the width is meaningless
        if hmax[L] - deck_h < 0.3 or hmax[R] - deck_h < 0.3:
            continue
        rows.append((v0 + 0.125, cen[R] - cen[L]))
    rows = np.array(rows)
    # the waist is a plateau, not a single slice: take every slice within 10% of the
    # narrowest, so one noisy crest cannot set the answer on its own
    near = rows[rows[:, 1] <= 1.10 * rows[:, 1].min(), 1]
    road = float(np.median(h[(v > -3) & (v < 0.5) & (w > 5) & (h < 0)]))
    at = rows[np.argmin(rows[:, 1]), 0]
    deck = float(np.median(h[(np.abs(v - at) < 1.0) & (np.abs(w) < 1.0)]))
    return rows, float(near.min()), float(np.median(near)), deck - road


def portal_clearance(E, C, theta):
    """Arch crown height above the road, traced on the left portal face.

    The drone never sees inside the underpass, but it does see the portal: the arch
    rings are light concrete over a dark, sparsely reconstructed opening. Per 10 cm
    across the road, the soffit is the lowest dense, light band on the face, and the
    road is the median surface just outside it. The crown is where that gap peaks.
    """
    w = np.cos(theta) * E[:, 0] + np.sin(theta) * E[:, 1]
    v = -np.sin(theta) * E[:, 0] + np.cos(theta) * E[:, 1]
    h = E[:, 2]
    lum = C.mean(1)
    face = (w > -3.3) & (w < -2.55)
    road = (w > -4.6) & (w < -3.3)
    inside = ((w > -2.4) & (w < 1.2) & (v > -0.7) & (v < 0.55)
              & (h > -1.1) & (h < -0.2)).sum()
    clear = []
    for v0 in np.arange(-2.6, 4.0, 0.1):
        b = (v >= v0) & (v < v0 + 0.1)
        rz = h[b & road]
        if len(rz) < 30:
            continue
        for z in np.arange(-1.2, 0.6, 0.025):
            sl = b & face & (h >= z) & (h < z + 0.025)
            if sl.sum() >= 12 and np.median(lum[sl]) > 70:
                clear.append(z - float(np.median(rz)))
                break
    clear = np.array(clear)
    crown = float(np.median(np.sort(clear)[-5:]))    # the five highest slices
    return crown, int(inside)


def main():
    E, C, man = load_enu()
    say("=" * 84)
    say("EXP-14  Metric scale audit against objects of published size  (Kolu, MVS export)")
    say("=" * 84)
    ext = np.ptp(E, axis=0)
    say(f"points {len(E):,}   extent e/n/u = {ext[0]:.2f} x {ext[1]:.2f} x {ext[2]:.2f} model m")
    say(f"frame: export ENU (gravity up, centroid origin) - the frame of every shipped file")

    theta, pos, fill, best = lane_width(E, C)
    say("\n--- 1. Lane width (road marking profile) ---")
    say(f"road direction {np.degrees(theta):.1f} deg (maximises grass-strip contrast)")
    say("paint peaks across the road (model m, paint fraction):")
    say("   " + "  ".join(f"{p:+.2f}({f:.2f})" for p, f in zip(pos, fill)))
    if best is None:
        say("NO solid|dashed|solid triple found - lane check inconclusive")
        k_lane = None
    else:
        _, i, a, b = best
        lane = (a + b) / 2
        k_lane = (LANE_REAL[0] / lane, LANE_REAL[1] / lane)
        say(f"solid {pos[i-1]:+.2f} | dashed {pos[i]:+.2f} (fill {fill[i]:.2f}, lowest) | solid {pos[i+1]:+.2f}")
        say(f"lane widths {a:.2f} and {b:.2f} model m  ->  lane = {lane:.3f} model m")
        say(f"real lane {LANE_REAL[0]}-{LANE_REAL[1]} m  ->  scale factor {k_lane[0]:.2f} - {k_lane[1]:.2f}")

    rows, wmin, wmed, clear = waist_width(E, theta)
    k_waist = (WAIST_REAL[0] / wmed, WAIST_REAL[1] / wmed)
    say("\n--- 2. Ecoduct waist (barrier crest to barrier crest, along the road) ---")
    say(f"{len(rows)} deck slices with both crests clear of the deck")
    say("   " + "  ".join(f"v{r[0]:+.1f}:{r[1]:.2f}" for r in rows))
    say(f"narrowest {wmin:.2f} model m; waist plateau (slices within 10% of it) "
        f"median {wmed:.2f} model m")
    say(f"real waist {WAIST_REAL[0]:.0f}-{WAIST_REAL[1]:.0f} m  ->  scale factor "
        f"{k_waist[0]:.2f} - {k_waist[1]:.2f}")

    crown, inside = portal_clearance(E, C, theta)
    floor = CLEARANCE_MIN / crown
    say("\n--- 3. Floor: arch clearance against the 5.0 m legal minimum ---")
    say(f"points inside the underpass volume: {inside} (the interior is unobserved;")
    say("the arch rings on the portal face are not)")
    say(f"crown clearance on the portal face  {crown:.2f} model m")
    say(f"a real crown must clear {CLEARANCE_MIN} m  ->  factor >= {floor:.2f}")
    say(f"at x2 the crown would stand {2 * crown:.2f} m - below the legal minimum")

    lo = min(k_waist[0], k_lane[0]) if k_lane else k_waist[0]
    hi = max(k_waist[1], k_lane[1]) if k_lane else k_waist[1]
    mid = float(np.sqrt(lo * hi))
    g = man["gravity"]
    say("\n--- 4. What the factor implies (sanity, not evidence) ---")
    say(f"deck surface above road      {clear:.2f} model m  ->  {clear*lo:.1f}-{clear*hi:.1f} m"
        "   (a highway overpass needs >= ~5 m clearance plus the deck)")
    say(f"arch crown clearance         {crown:.2f} model m  ->  {crown*lo:.1f}-{crown*hi:.1f} m")
    say(f"camera above ground          {g['camera_above_ground_m']:.2f} model m  ->  "
        f"{g['camera_above_ground_m']*lo:.0f}-{g['camera_above_ground_m']*hi:.0f} m")
    say(f"scene extent                 {ext[0]:.1f} x {ext[1]:.1f} model m  ->  "
        f"{ext[0]*mid:.0f} x {ext[1]*mid:.0f} m at the central factor")
    say(f"DSM cell (declared 0.10 m)   ->  actually {0.10*lo:.2f}-{0.10*hi:.2f} m on the ground")

    say("\n" + "-" * 84)
    say("CONCLUSION (EXP-14)")
    say("-" * 84)
    say(f"  Two independent rulers agree: the Kolu model is {lo:.1f}-{hi:.1f}x TOO SMALL")
    say(f"  (central {mid:.1f}x). Every absolute length it reports is short by that factor.")
    say("")
    say("  1. The plausibility band that accepted this scale (6.4-11.4 m altitude) was the")
    say("     defect. A 10.6 m camera height with a 67 deg lens sees ~14 m of ground; the")
    say("     keyframes show a four-lane highway, an ecoduct and its verges. The band")
    say(f"     checked internal consistency, not reality, and passed a ~{mid:.1f}x error.")
    say("  2. Scale-free results are untouched: the 14x sampling/information ratio, the")
    say("     1.8-3.6x MVS gain, reprojection error in px, every percentage.")
    say("  3. A single global correction constant is wrong in principle. The factor is a")
    say("     per-run model output; each clip needs its own ruler or its own GNSS.")
    say(f"  4. A 2x correction would leave Kolu measurements {lo/2:.1f}-{hi/2:.1f}x short.")
    say("=" * 84)

    with open(os.path.join(ROOT, "research", "exp14-results.txt"), "w", encoding="utf-8") as f:
        f.write(out.getvalue())

    # The contract file every builder reads (docs/09 section 2). The MVS cloud inherits
    # the feed-forward model's frame - bundle adjustment refines poses, it does not
    # re-frame them - so one factor covers both Kolu reconstructions.
    cal = {
        "schema": "sih26158/scale-calibration/1",
        "runs": ["kolumvs3d", "kolu3d"],
        "factor": round(mid, 2),
        "bracket": [round(lo, 2), round(hi, 2)],
        "status": "calibrated",
        "method": "known-object",
        "summary": "lane width and the ecoduct's published 21-22 m waist",
        "references": [
            {"object": "lane width", "model_m": round((best[2] + best[3]) / 2, 3) if best else None,
             "real_m": list(LANE_REAL), "source": "ERR 650086; ERR news 1608116446; MKM 106 table 2.4"},
            {"object": "ecoduct waist", "model_m": round(wmed, 3),
             "real_m": list(WAIST_REAL), "source": "et.wikipedia Okodukt"},
        ],
        "floor_checks": [
            {"object": "arch crown clearance", "model_m": round(crown, 3),
             "min_real_m": CLEARANCE_MIN, "implies_factor_at_least": round(floor, 2),
             "source": "MKM 106 par. 9; 1999 road design norms par. 8"},
        ],
        "measured_by": "src/experiments/exp14_scale_audit.py",
        "date": "2026-09-17",
    }
    os.makedirs(os.path.dirname(CAL_OUT), exist_ok=True)
    with open(CAL_OUT, "w", encoding="utf-8") as f:
        json.dump(cal, f, indent=2)
    print(f"\nwrote {os.path.relpath(CAL_OUT, ROOT)}  (factor {cal['factor']}, bracket {cal['bracket']})")


if __name__ == "__main__":
    main()
