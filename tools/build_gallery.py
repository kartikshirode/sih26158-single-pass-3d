"""
Build the gallery: every clip we actually reconstructed, source video beside the
interactive 3D, with the feed-forward baseline and the MVS rebuild on one toggle.

Two things this file is careful about, because both are easy to get wrong:

1. ONE METRIC FRAME PER EXAMPLE. Each viewer was packed independently, normalised
   by its own extent, so a naive A/B toggle would compare normalisations rather than
   geometry. Every model is emitted with its metres-per-unit and its own median
   centroid, and the page divides both by a view scale shared across the example. The
   two models are NOT re-registered - measured as-packed their footprints overlap at
   IoU 0.69 (kolu) and 0.64 (village), and a best-fit yaw search moved that by under
   0.05, so there is no rotation worth correcting and inventing one would be fiction.

2. THE NUMBERS COME FROM THE SHARED-FRAME ANALYSIS, NOT FROM THE PACKED MESHES.
   `src/analysis/compare_mvs.py` measures relief with ONE vertical taken from the
   baseline, deliberately, so the two clouds stay comparable. Bounding-box extents off
   the packed meshes use each model's own `upright_frame` and would quietly be a
   different quantity. Relief here is that script's, via out/ppt/measure_*.json.

    python tools/build_gallery.py
"""
from __future__ import annotations
import base64, glob, io, json, os, re, subprocess, sys

from design_system import css as ds_css
import scale_cal

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.join(ROOT, "tools")
# The gallery lives inside the deployed folder rather than beside it: one copy,
# nothing to drift, and it ships on the existing URL at /gallery/.
OUT = os.path.join(ROOT, "demo", "gallery")
SITE_URL = "https://tesseract-demo.vercel.app"


def jload(p):
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def packed(run):
    """Lift the already-shipped geometry out of a built viewer. Byte-for-byte what
    that run delivered, and it avoids needing open3d to re-pack."""
    with io.open(os.path.join(ROOT, "out", run, "viewer.html"), encoding="utf-8") as f:
        h = f.read()
    m = re.search(r"const D = (\{.*?\}), S = \{", h, re.S)
    if not m:
        sys.exit(f"no packed mesh in out/{run}/viewer.html")
    D = json.loads(m.group(1))
    pts = np.frombuffer(base64.b64decode(D["ppos"]), dtype=np.int16).reshape(-1, 3)
    mpu = D["scale"] * 32767 / 32000                     # metres per shader unit
    metres = pts.astype(np.float64) / 32767.0 * mpu
    # median, not mean: the centroid only has to make the A/B toggle sit still, and a
    # handful of MVS outliers would drag a mean by a metre or more
    centre = np.median(metres, axis=0)
    half = float(np.abs(metres - centre).max())
    D["centroid"] = [round(float(c), 6) for c in centre]
    return D, half


def probe(path):
    q = ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-show_entries", "format=duration",
         "-of", "json", path]
    d = json.loads(subprocess.run(q, capture_output=True, text=True).stdout)
    s = d["streams"][0]
    return s["width"], s["height"], float(d["format"]["duration"])


def poster(clip_rel, width=520, quality=80):
    """Pull frame 0 out of the clip itself. Taking it from the keyframe folder looked
    right on Kolu but was wrong on the portrait clip: ingest crops the horizon and the
    watermark away (1080x1920 -> 1080x1250), so the keyframe is a different shape from
    the video and the pane would jump aspect the moment playback started."""
    from PIL import Image
    src = os.path.join(OUT, clip_rel.replace("/", os.sep))
    tmp = os.path.join(OUT, "assets", "_poster.jpg")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-frames:v", "1",
                    "-q:v", "2", tmp], check=True)
    im = Image.open(tmp).convert("RGB")
    im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=quality, optimize=True)
    os.remove(tmp)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


def og_card(kf_dir, out_path, size=(1200, 630)):
    from PIL import Image
    src = sorted(glob.glob(os.path.join(ROOT, "out", kf_dir, "*.jpg")))[0]
    im = Image.open(src).convert("RGB")
    tw, th = size
    sc = max(tw / im.width, th / im.height)
    im = im.resize((round(im.width * sc), round(im.height * sc)), Image.LANCZOS)
    l, t = (im.width - tw) // 2, (im.height - th) // 2
    im.crop((l, t, l + tw, t + th)).save(out_path, "JPEG", quality=86, optimize=True)


def pct(x):
    return f"{100 * x:.2f}%"


def main():
    os.makedirs(os.path.join(OUT, "mesh"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "assets"), exist_ok=True)

    mk = jload(os.path.join(ROOT, "out/ppt/measure_kolu.json"))
    ms = jload(os.path.join(ROOT, "out/ppt/measure_short.json"))
    ing_k = jload(os.path.join(ROOT, "out/kf_kolu/ingest.json"))
    ing_v = jload(os.path.join(ROOT, "out/kf_yt_dense/ingest.json"))
    ing_w = jload(os.path.join(ROOT, "out/kf_yt/ingest.json"))
    mvs_k = jload(os.path.join(ROOT, "out/kolu_mvs/mvs_result.json"))
    mvs_v = jload(os.path.join(ROOT, "out/ytd_mvs/mvs_result.json"))
    vs_wide = jload(os.path.join(ROOT, "out/yt3d/viewer_stats.json"))

    at = lambda d, r: dict((x[0], x[1]) for x in d["roughness_cm"]).get(r)

    # ---- geometry: one file per model, loaded on demand by the page
    RUNS = {
        "kolu_base":  "kolu3d",   "kolu_mvs":    "kolumvs3d",
        "vill_base":  "ytd3d",    "vill_mvs":    "ytdmvs3d",
        "wide_base":  "yt3d",
    }
    halves, written = {}, 0
    for key, run in RUNS.items():
        D, half = packed(run)
        halves[key] = half
        js = (f"window.__MESH=window.__MESH||{{}};\n"
              f"window.__MESH[{json.dumps(key)}]={json.dumps(D)};\n")
        p = os.path.join(OUT, "mesh", f"{key}.js")
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(js)
        written += os.path.getsize(p)
        print(f"  {key:11} <- out/{run:10} {D['nt']:>7,} tri  {D['np']:>7,} pts  "
              f"half-extent {half:6.2f} m  ({os.path.getsize(p)/1e6:.1f} MB)")

    # compare_mvs.py measures in the model's units. A calibrated clip prints metres
    # (every length, and every length-valued threshold, times the factor); an
    # unvalidated one prints the raw numbers with an asterisk and says why.
    def units(cal):
        star = "" if cal["status"] != "unvalidated" else "*"
        return cal["factor"], star

    def rows_pair(d, cal, cov_note=True):
        b, m = d["baseline"], d["mvs"]
        k, star = units(cal)
        r = [
            ["points in the cloud", f'{b["points"]:,}', f'{m["points"]:,}', "", "win"],
            ["footprint",
             f'{b["footprint_m"][0]*k:.1f} x {b["footprint_m"][1]*k:.1f} m{star}',
             f'{m["footprint_m"][0]*k:.1f} x {m["footprint_m"][1]*k:.1f} m{star}', "", ""],
            ["relief above local ground, max",
             f'{b["relief_m"]["max"]*k:.2f} m{star}',
             f'{m["relief_m"]["max"]*k:.2f} m{star}', "lose", "win"],
            [f"points more than {1.5*k:.1f} m{star} up",
             pct(b["fraction_above_m"]["1.5"]), pct(m["fraction_above_m"]["1.5"]), "", ""],
            [f"points more than {2.5*k:.1f} m{star} up",
             pct(b["fraction_above_m"]["2.5"]), pct(m["fraction_above_m"]["2.5"]),
             "lose", "win"],
            [f"surface residual, {6*k:.0f} cm{star} neighbourhood",
             f'{at(b, 6.0)*k:.2f} cm{star}', f'{at(m, 6.0)*k:.2f} cm{star}',
             "lose", "win"],
        ]
        if cov_note:
            c = d["coverage"]["mvs_over_baseline"]
            r.append(["ground cells covered, vs baseline", "100%",
                      f'{100*c:.0f}%', "", "win" if c >= 1 else "lose"])
        return r

    kw, kh, kdur = probe(os.path.join(OUT, "assets", "kolu.mp4"))
    vw, vh, vdur = probe(os.path.join(OUT, "assets", "village.mp4"))
    ww, wh, wdur = probe(os.path.join(OUT, "assets", "village_full.mp4"))

    sk, sv, sw = ing_k["stats"], ing_v["stats"], ing_w["stats"]
    kk, kv, kwf = ing_k["keyframes"], ing_v["keyframes"], ing_w["keyframes"]

    cal_k = scale_cal.load("kolumvs3d")
    if scale_cal.load("kolu3d") != cal_k:
        sys.exit("the two Kolu models must share one calibration - they share a frame")
    cal_v = scale_cal.load("ytdmvs3d")
    cal_w = scale_cal.load("yt3d")
    kk_ = cal_k["factor"]
    STAR_NOTE = (" <b>*</b> Lengths marked * are in the model's own units: this clip has "
                 "no external ruler yet, and on the Kolu clip those units turned out to "
                 "be 5.3-5.8x too small (docs/08).")

    gain_k = at(mk["baseline"], 6.0) / at(mk["mvs"], 6.0)
    gain_v = at(ms["baseline"], 6.0) / at(ms["mvs"], 6.0)

    EX = [
        {
            "key": "kolu", "tab": "Kolu overpass", "aspect": kw / kh,
            "video": "assets/kolu.mp4", "poster": poster("assets/kolu.mp4"),
            "clipName": sk["video"],
            "clipMeta": f'{sk["resolution"]} &middot; {sk["fps"]} fps &middot; '
                        f'{sk["keyframes_selected"]} keyframes',
            "span": f'frames {kk[0]} to {kk[-1]}  ({kdur:.1f} s)',
            "viewScale": round(max(halves["kolu_base"], halves["kolu_mvs"]), 4),
            "models": [
                {"key": "kolu_base", "file": "mesh/kolu_base.js",
                 "label": "baseline", "sub": "feed-forward"},
                {"key": "kolu_mvs", "file": "mesh/kolu_mvs.js",
                 "label": "MVS rebuild", "sub": "per-pixel"},
            ],
            "tableHead": ["Kolu overpass, 45 keyframes",
                          "MapAnything, feed-forward", "OpenMVS rebuild"],
            "scale": scale_cal.for_page(cal_k),
            "rows": rows_pair(mk, cal_k),
            "note": (
                f'The feed-forward model put <b>{pct(mk["baseline"]["fraction_above_m"]["2.5"])}</b> '
                f'of its points more than {2.5*kk_:.0f} m above local ground, on an '
                f'overpass whose deck stands several metres over the road. That is the '
                f'"buildings are paint on a sheet" result, and it is why the rebuilt '
                f'pipeline takes every delivered surface point from photometric MVS '
                f'instead. At a {6*kk_:.0f} cm neighbourhood the rebuilt surface sits '
                f'<b>{gain_k:.1f}x</b> tighter to a fitted plane; its finest resolved '
                f'residual is {10*at(mk["mvs"], 3.0)*kk_:.0f} mm at {3*kk_:.0f} cm. '
                f"Lengths are in metres calibrated against lane width and the ecoduct's "
                f"published waist (x{kk_:.2f}; the model's own units were 5.3-5.8x short). "
                f'Relief is measured in one shared vertical taken from the baseline by '
                f'<code>src/analysis/compare_mvs.py</code>, so both columns are on the same '
                f'axis. Wall clock for the rebuild: {mvs_k["total_seconds"]/60:.0f} min on '
                f'8 vCPU, no GPU.'),
        },
        {
            "key": "village", "tab": "Village pass", "aspect": vw / vh,
            "video": "assets/village.mp4", "poster": poster("assets/village.mp4"),
            "clipName": sv["video"],
            "clipMeta": f'{sv["resolution"]} &middot; {sv["fps"]} fps &middot; '
                        f'{sv["keyframes_selected"]} keyframes',
            "span": f'frames {kv[0]} to {kv[-1]}  ({vdur:.1f} s)',
            "viewScale": round(max(halves["vill_base"], halves["vill_mvs"]), 4),
            "models": [
                {"key": "vill_base", "file": "mesh/vill_base.js",
                 "label": "baseline", "sub": "feed-forward"},
                {"key": "vill_mvs", "file": "mesh/vill_mvs.js",
                 "label": "MVS rebuild", "sub": "per-pixel"},
            ],
            "tableHead": ["Village pass, 42 keyframes",
                          "MapAnything, feed-forward", "OpenMVS rebuild"],
            "scale": scale_cal.for_page(cal_v),
            "rows": rows_pair(ms, cal_v),
            "note": (
                f'A portrait phone clip, and the second scene the pipeline was run on '
                f'end to end. The detail gain is larger here than on Kolu '
                f'(<b>{gain_v:.1f}x</b> tighter at 6 cm*, finest residual '
                f'{10*at(ms["mvs"], 3.0):.1f} mm* at 3 cm*) but <b>coverage goes the other '
                f'way</b>: the rebuild holds only '
                f'{100*ms["coverage"]["mvs_over_baseline"]:.0f}% of the baseline\'s ground '
                f'cells, because photometric MVS refuses surfaces it cannot match across '
                f'three views while the feed-forward model will happily invent them. '
                f'Both behaviours are the same trade, and only one of them is reported as '
                f'a win on the deck. Wall clock: {mvs_v["total_seconds"]/60:.0f} min on '
                f'8 vCPU.' + STAR_NOTE),
        },
        {
            "key": "wide", "tab": "Village pass, whole clip", "aspect": ww / wh,
            "failed": True,
            "video": "assets/village_full.mp4", "poster": poster("assets/village_full.mp4"),
            "clipName": sw["video"],
            "clipMeta": f'{sw["resolution"]} &middot; {sw["fps"]} fps &middot; '
                        f'{sw["keyframes_selected"]} keyframes',
            "span": f'the whole {wdur:.0f} s, {sw["shots_detected"]} shots',
            "viewScale": round(halves["wide_base"], 4),
            "scale": scale_cal.for_page(cal_w),
            "models": [
                {"key": "wide_base", "file": "mesh/wide_base.js",
                 "label": "baseline", "sub": "feed-forward"},
            ],
            "tableHead": ["Same clip, wrong span", "MapAnything, feed-forward", None],
            "rows": [
                ["frames analysed", f'{sw["frames_decoded"]:,}', None, "", ""],
                ["shots detected", f'{sw["shots_detected"]}  (the other runs saw 1)',
                 None, "lose", ""],
                ["keyframes kept", f'{sw["keyframes_selected"]}', None, "", ""],
                ["footprint",
                 dict(vs_wide["geom"]).get("footprint", "—").replace("&times;", "x")
                 .removesuffix(" m") + " m*",
                 None, "", ""],
                ["relief / footprint",
                 dict(vs_wide["geom"]).get("relief / footprint", "—"), None, "lose", ""],
                ["points above local ground",
                 dict(vs_wide["geom"]).get("above local ground", "—"), None, "lose", ""],
            ],
            "note": (
                'The same source video as the Village pass, but ingested whole instead of '
                'over the single moving pass. Keyframing detected <b>2 shots</b> here '
                'against 1 in the run beside it, and spread 45 keyframes across a 115 x 58 m* '
                'footprint. The result has a relief-to-footprint ratio of 0.037 and puts '
                '1.34% of its points above local ground: a flat sheet with the scene '
                'painted on it. It is kept here because it is the failure that motivates '
                'adaptive keyframing, and because the fix was choosing the span, not '
                'changing the model. There is no MVS column because this run was never '
                'carried through the rebuild.' + STAR_NOTE),
        },
    ]

    og_card("kf_kolu", os.path.join(OUT, "assets", "og.jpg"))
    title = "SIH26158 - every clip we reconstructed"
    desc = ("Source drone video beside the interactive 3D model, for every clip the "
            "pipeline was run on. Feed-forward baseline against the MVS rebuild, in one "
            "shared frame per clip.")
    note = ("Two further clips sit in <code>data/cand/</code> (bahai, toolse) that were "
            "shortlisted but never ingested, and a fourth (nicosia, 20 keyframes) was "
            "ingested but never reconstructed. Everything that reached a 3D model is on "
            "this page.")

    with io.open(os.path.join(HERE, "gallery_template.html"), encoding="utf-8") as f:
        tpl = f.read()
    html = (tpl.replace("__DS_CSS__", ds_css("viewer"))
               .replace("__EXAMPLES__", json.dumps(EX))
               .replace("__NOTE__", json.dumps(note))
               .replace("__OGIMG__", f"{SITE_URL}/gallery/assets/og.jpg")
               .replace("__DESC__", desc)
               .replace("__TITLE__", title))
    out = os.path.join(OUT, "index.html")
    with io.open(out, "w", encoding="utf-8") as f:
        f.write(html)

    vids = sum(os.path.getsize(os.path.join(OUT, "assets", v))
               for v in os.listdir(os.path.join(OUT, "assets")))
    print(f"\n  examples  {len(EX)}  ({sum(len(e['models']) for e in EX)} models)")
    print(f"  geometry  {written/1e6:.1f} MB across {len(RUNS)} lazy-loaded files")
    print(f"  video     {vids/1e6:.1f} MB")
    print(f"  -> {out}  {os.path.getsize(out)/1e3:.0f} KB")


if __name__ == "__main__":
    main()
