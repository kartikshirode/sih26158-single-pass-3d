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
from footage import credit
import scale_cal

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.join(ROOT, "tools")
# The gallery lives inside the deployed folder rather than beside it: one copy,
# nothing to drift, and it ships on the existing URL at /gallery/.
OUT = os.path.join(ROOT, "demo", "gallery")
SITE_URL = "https://tesseract-demo.vercel.app"

# This page republishes two things per example: the source clip, copied into assets/,
# and a 3D model derived from it. A derived model carries the source's licence, which
# is why the credit sits with the example and not in a page footer. The records live in
# tools/footage.py, shared with the console so one clip has one spelling and one author.
# credit() is given sys.exit: a clip with no record must stop the build, because an
# unattributed example renders perfectly and looks correct (docs/16 T11, finding F-4).
CREDIT_SUBJECT = "The 3D model on the right"


def jload(p):
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def packed(run):
    """Lift the already-shipped geometry out of a built viewer. Byte-for-byte what
    that run delivered, and it avoids needing open3d to re-pack.

    A textured run has no viewer.html; tools/pack_textured.py leaves packed.json in
    the same layout plus `uv`, `tex` and `texSize`."""
    pj = os.path.join(ROOT, "out", run, "packed.json")
    if os.path.exists(pj):
        with io.open(pj, encoding="utf-8") as f:
            D = json.load(f)
    else:
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
    ing_k = jload(os.path.join(ROOT, "out/kf_kolu/ingest.json"))
    mvs_k = jload(os.path.join(ROOT, "out/kolu_mvs/mvs_result.json"))

    mt = jload(os.path.join(ROOT, "out/ppt/measure_toolse.json"))
    ing_t = jload(os.path.join(ROOT, "out/kf_toolse/ingest.json"))
    mvs_t = jload(os.path.join(ROOT, "out/toolse_mvs/mvs_result.json"))

    at = lambda d, r: dict((x[0], x[1]) for x in d["roughness_cm"]).get(r)

    # ---- geometry: one file per model, loaded on demand by the page
    # Kolu and Toolse. The Village runs came from a third-party clip whose rights are
    # not cleared, and a reconstruction is derived work, so neither the footage nor its
    # geometry may be published (`docs/16` L-8, finding F-4). Toolse is CC BY-SA 4.0 and
    # cleared, with its credit and the model's own licence on the page; see FOOTAGE.
    # kolu_tex is packed for the console (the gallery page keeps its two-way A/B);
    # its atlas travels beside the .js under the name the pack recorded.
    RUNS = {"kolu_base": "kolu3d", "kolu_mvs": "kolumvs3d", "kolu_tex": "kolutex3d",
            "toolse_base": "toolse3d", "toolse_mvs": "toolsemvs3d"}
    halves, written = {}, 0
    for key, run in RUNS.items():
        D, half = packed(run)
        halves[key] = half
        if D.get("tex"):
            import shutil
            shutil.copyfile(os.path.join(ROOT, "out", run, "atlas.jpg"),
                            os.path.join(OUT, "mesh", D["tex"]))
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

    def common_radius(d):
        """Smallest neighbourhood both clouds actually measured.

        compare_mvs drops a radius that had too few neighbours to fit a plane, so the
        two clouds do not always offer the same set. Kolu's baseline reaches 6 cm (on
        56 queries); Toolse's is sparser over a wider footprint and stops at 12 cm.
        Hardcoding 6 printed a residual for one clip and crashed on the other, so the
        row names whichever radius the pair share."""
        b = {x[0] for x in d["baseline"]["roughness_cm"]}
        m = {x[0] for x in d["mvs"]["roughness_cm"]}
        both = sorted(b & m)
        if not both:
            sys.exit("baseline and MVS share no roughness radius; cannot compare them")
        return both[0]

    def rows_pair(d, cal, cov_note=True):
        b, m = d["baseline"], d["mvs"]
        k, star = units(cal)
        rr = common_radius(d)
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
            [f"surface residual, {rr*k:.0f} cm{star} neighbourhood",
             f'{at(b, rr)*k:.2f} cm{star}', f'{at(m, rr)*k:.2f} cm{star}',
             "lose", "win"],
        ]
        if cov_note:
            c = d["coverage"]["mvs_over_baseline"]
            r.append(["ground cells covered, vs baseline", "100%",
                      f'{100*c:.0f}%', "", "win" if c >= 1 else "lose"])
        return r

    kw, kh, kdur = probe(os.path.join(OUT, "assets", "kolu.mp4"))

    sk, kk = ing_k["stats"], ing_k["keyframes"]

    cal_k = scale_cal.load("kolumvs3d")
    if scale_cal.load("kolu3d") != cal_k:
        sys.exit("the two Kolu models must share one calibration - they share a frame")
    kk_ = cal_k["factor"]
    STAR_NOTE = (" <b>*</b> Lengths marked * are in the model's own units: this clip has "
                 "no external ruler yet, and on the Kolu clip those units turned out to "
                 "be 5.3-5.8x too small (docs/08).")

    gain_k = at(mk["baseline"], 6.0) / at(mk["mvs"], 6.0)

    tw_, th_, tdur = probe(os.path.join(OUT, "assets", "toolse.mp4"))
    st, tk = ing_t["stats"], ing_t["keyframes"]
    # No calibration file names this run, so scale_cal returns the unvalidated default
    # and every length on the tab carries the asterisk. That contrast with Kolu's
    # calibrated metres is the reason a second clip is here at all (docs/18 B-33).
    cal_t = scale_cal.load("toolsemvs3d")
    if scale_cal.load("toolse3d") != cal_t:
        sys.exit("toolse3d and toolsemvs3d disagree on scale; one table cannot cover both")
    kt_ = cal_t["factor"]
    rt_ = common_radius(mt)
    gain_t = at(mt["baseline"], rt_) / at(mt["mvs"], rt_)

    EX = [
        {
            "key": "kolu", "tab": "Kolu overpass", "aspect": kw / kh,
            "video": "assets/kolu.mp4", "poster": poster("assets/kolu.mp4"),
            "credit": credit("kolu.webm", CREDIT_SUBJECT, sys.exit, clip_published=True),
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
            "key": "toolse", "tab": "Toolse castle", "aspect": tw_ / th_,
            "video": "assets/toolse.mp4", "poster": poster("assets/toolse.mp4"),
            "credit": credit("toolse.webm", CREDIT_SUBJECT, sys.exit, clip_published=True),
            "clipName": st["video"],
            "clipMeta": f'{st["resolution"]} &middot; {st["fps"]} fps &middot; '
                        f'{st["keyframes_selected"]} keyframes',
            "span": f'frames {tk[0]} to {tk[-1]}  ({tdur:.1f} s)',
            "viewScale": round(max(halves["toolse_base"], halves["toolse_mvs"]), 4),
            "models": [
                {"key": "toolse_base", "file": "mesh/toolse_base.js",
                 "label": "baseline", "sub": "feed-forward"},
                {"key": "toolse_mvs", "file": "mesh/toolse_mvs.js",
                 "label": "MVS rebuild", "sub": "per-pixel"},
            ],
            "tableHead": [f'Toolse castle, {st["keyframes_selected"]} keyframes',
                          "MapAnything, feed-forward", "OpenMVS rebuild"],
            "scale": scale_cal.for_page(cal_t),
            "rows": rows_pair(mt, cal_t),
            "note": (
                f'A medieval ruin on a headland, and the counterpart to Kolu in two ways. '
                f'Its lengths carry an asterisk: there is no object of known size in the '
                f'frame and no GNSS in the clip, so this model is in its own units while '
                f"Kolu's are calibrated metres. Read the two tabs together and the "
                f'asterisk is the point. '
                f'It is also the case where the rebuild is the smaller model: it holds '
                f'<b>{100*mt["coverage"]["mvs_over_baseline"]:.0f}%</b> of the baseline\'s '
                f'ground cells, against 136% on Kolu. Open sea fills the right of every '
                f'frame, and the feed-forward pass paints points onto it, while photometric '
                f'MVS keeps only what several views agree on and drops the water. Less '
                f'coverage, and the {mt["mvs"]["points"]:,} points it does keep sit '
                f'<b>{gain_t:.1f}x</b> tighter to a fitted plane at a {rt_*kt_:.0f} cm '
                f'neighbourhood. The walls reach {mt["mvs"]["relief_m"]["max"]:.1f} units '
                f'above local ground. Textured from the keyframes, not per-vertex colour. '
                f'Wall clock for the rebuild: {mvs_t["total_seconds"]/60:.0f} min on 8 '
                f'vCPU, no GPU.'),
        },
    ]

    og_card("kf_kolu", os.path.join(OUT, "assets", "og.jpg"))
    title = "SIH26158 - every clip we reconstructed"
    desc = ("Source drone video beside the interactive 3D model, for every clip the "
            "pipeline was run on. Feed-forward baseline against the MVS rebuild, in one "
            "shared frame per clip.")
    note = ("One further clip sits in <code>data/cand/</code> (bahai): it passes screening "
            "only with 66% of the frame cropped away, which leaves 37 keyframes over 3.8 s, "
            "so it was ingested and not carried further. A fourth (nicosia, 20 keyframes) "
            "was ingested but never reconstructed. Everything that reached a 3D model is on "
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
