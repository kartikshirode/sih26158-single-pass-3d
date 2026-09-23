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

# Footage provenance, from docs/16 section 4.1. This page republishes two things per
# example: the source clip, copied into assets/, and a 3D model derived from it. A
# derived model carries the source's licence, which is why the credit sits with the
# example and not in a page footer.
#
# CC0 waives attribution, so Kolu needs none and the page said nothing for a long time.
# Anything else does need it, by name, with the licence and a link back. Adding a clip
# here without filling this in is the F-4 mistake again (docs/16 T11).
FOOTAGE = {
    "kolu": {
        "title": "Kolu overpass", "author": None, "licence": "CC0",
        "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "source_url": None,
    },
    "toolse": {
        "title": "Toolse castle in Estonia (Fall 2021)", "author": "Sillerkiil",
        "licence": "CC BY-SA 4.0",
        "licence_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "source_url": "https://commons.wikimedia.org/wiki/File:Toolse_castle_in_Estonia_(Fall_2021).webm",
    },
    "bahai": {
        "title": "Baha'i Temple -- Wilmette, IL -- Drone Video (DJI Spark)",
        "author": "Kurt Elster", "licence": "CC BY 3.0",
        "licence_url": "https://creativecommons.org/licenses/by/3.0/",
        "source_url": "https://commons.wikimedia.org/wiki/File:Baha%27i_Temple_--_Wilmette_,_IL_--_Drone_Video_(DJI_Spark).webm",
    },
}


def credit(key):
    """The attribution line for one example. Refuses rather than ships a clip whose
    rights are not recorded, because the failure mode is silent republication."""
    if key not in FOOTAGE:
        sys.exit(f"no footage rights recorded for '{key}' - add it to FOOTAGE "
                 f"(docs/16 section 4.1) before it goes on a public page")
    f = FOOTAGE[key]
    lic = f'<a href="{f["licence_url"]}" rel="license noopener" target="_blank">{f["licence"]}</a>'
    if f["author"] is None:
        return f'Source clip: {f["title"]}, {lic}. No attribution required.'
    src = f['title']
    if f["source_url"]:
        src = f'<a href="{f["source_url"]}" rel="noopener" target="_blank">{src}</a>'
    return f'Source clip: {src} by {f["author"]}, {lic}. This model is derived from it.'


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

    at = lambda d, r: dict((x[0], x[1]) for x in d["roughness_cm"]).get(r)

    # ---- geometry: one file per model, loaded on demand by the page
    # Only Kolu. The Village runs came from a third-party clip whose rights are not
    # cleared, and a reconstruction is derived work, so neither the footage nor its
    # geometry may be published (`docs/16` L-8, finding F-4).
    # kolu_tex is packed for the console (the gallery page keeps its two-way A/B);
    # its atlas travels beside the .js under the name the pack recorded.
    RUNS = {"kolu_base": "kolu3d", "kolu_mvs": "kolumvs3d", "kolu_tex": "kolutex3d"}
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

    sk, kk = ing_k["stats"], ing_k["keyframes"]

    cal_k = scale_cal.load("kolumvs3d")
    if scale_cal.load("kolu3d") != cal_k:
        sys.exit("the two Kolu models must share one calibration - they share a frame")
    kk_ = cal_k["factor"]
    STAR_NOTE = (" <b>*</b> Lengths marked * are in the model's own units: this clip has "
                 "no external ruler yet, and on the Kolu clip those units turned out to "
                 "be 5.3-5.8x too small (docs/08).")

    gain_k = at(mk["baseline"], 6.0) / at(mk["mvs"], 6.0)

    EX = [
        {
            "key": "kolu", "tab": "Kolu overpass", "aspect": kw / kh,
            "video": "assets/kolu.mp4", "poster": poster("assets/kolu.mp4"),
            "credit": credit("kolu"),
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
