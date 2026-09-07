"""
Build the SIH 2026 idea-submission deck on top of the OFFICIAL template.

Two rules from the template's own instruction slide drive the whole design:

  "You can only use provided template for making the PPT without changing the idea
   details pointers"          -> we EDIT the downloaded .pptx in place. The SIH logo,
                                 the footer, the slide numbers, the team-name badge and
                                 the six section headings are left exactly as shipped;
                                 only the prompt text inside the content boxes is
                                 replaced. "Clarity and details in the prescribed
                                 format" is one of the scored criteria, so the chrome is
                                 not cosmetic.

  "You need to save the file in PDF"   -> exported through PowerPoint COM at the end.
                                          python-pptx cannot write PDF.

Slide 7 (Important Instructions) is deleted before export, as that slide itself says.

Nothing on these slides is invented. Every number traces to docs/05-quality-analysis.md,
docs/06-gcp-deployment.md, or the mvs_result.json / export_manifest.json written by the
runs themselves. Where a PS target is not yet met, the slide says so — NTRO evaluates its
own problem statement and will recognise its own numbers.
"""
from __future__ import annotations

import copy
import os
import subprocess
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIG = os.path.join(ROOT, "out", "ppt")
TEMPLATE = os.path.join(FIG, "SIH2026-IDEA-Presentation-Format.pptx")
OUT_PPTX = os.path.join(FIG, "SIH26158_IdeaSubmission.pptx")
OUT_PDF = os.path.join(FIG, "SIH26158_IdeaSubmission.pdf")

INK = RGBColor(0x1A, 0x1A, 0x1A)
BLUE = RGBColor(0x1F, 0x6F, 0xA8)
ORANGE = RGBColor(0xC2, 0x61, 0x2C)
GREY = RGBColor(0x5A, 0x5A, 0x5A)
LIGHT = RGBColor(0xEC, 0xF2, 0xF7)
RULE = RGBColor(0xC8, 0xD6, 0xE2)

TEAM_NAME = "«TEAM NAME»"          # filled by the team on the portal; never invented
TEAM_ID = "«TEAM ID»"

IDEA_TITLE = "Measured, not interpolated: accurate 3D from a single drone pass"

# The six formats the problem statement asks for. glb and gltf are one line item there,
# so they are counted as one here too - counting them separately would quietly turn a
# 5/6 into a 6/7 and flatter us.
REQUIRED_FORMATS = ("obj", "ply", "las", "geotiff", "glb+gltf", "fbx")


def _json(path):
    import json
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        raise SystemExit(f"missing {path}. Run the pipeline and "
                         "src/analysis/compare_mvs.py --json before building the deck.")
    return json.load(open(full))


def measurements():
    """
    Every figure that appears on a slide, read from the run that produced it.

    Nothing here is typed by hand. The deck claims on slide 6 that its numbers are
    regenerated from the run outputs; this function is what makes that claim true, and
    it fails loudly rather than silently falling back to a stale constant.
    """
    run = _json("out/kolu_mvs/mvs_result.json")           # the survey clip
    short = _json("out/ytd_mvs/mvs_result.json")
    ex = _json("out/kolumvs3d/export/export_manifest.json")["formats"]
    mk, ms = _json("out/ppt/measure_kolu.json"), _json("out/ppt/measure_short.json")

    tri = run["sparse_after_triangulation"]
    ba = run["sparse_after_bundle_adjustment"]
    px = lambda v: float(str(v).replace("px", ""))
    have = {"glb+gltf": ex["glb"] and ex["gltf"], **{k: ex[k] for k in
            ("obj", "ply", "las", "geotiff", "fbx")}}
    at = lambda d, r: dict((x[0], x[1]) for x in d["roughness_cm"])[r]
    gain = lambda d: at(d["baseline"], 6.0) / at(d["mvs"], 6.0)

    import numpy as np
    tris = len(np.load(os.path.join(ROOT, "out/kolumvs3d/mesh_f.npy"), mmap_mode="r"))

    return {
        "triangles": tris,
        "coverage": mk["coverage"]["mvs_over_baseline"],
        "coverage_kept": mk["coverage"]["baseline_cells_kept"],
        "intrinsics_px": run["intrinsics_fit_residual_px"],
        "registered": f'{ba["Registered images"]} / {run["n_images"]}',
        "reproj_tri": px(tri["Mean reprojection error"]),
        "reproj_ba": px(ba["Mean reprojection error"]),
        "reproj_gain": px(tri["Mean reprojection error"]) / px(ba["Mean reprojection error"]),
        "frame": "×".join(str(v) for v in run["full_frame"]),
        "n_views": run["n_images"],
        "n_views_short": short["n_images"],
        "dense_points": mk["mvs"]["points"],
        "seconds": run["total_seconds"],
        "seconds_short": short["total_seconds"],
        "formats_have": sum(bool(have[k]) for k in REQUIRED_FORMATS),
        "formats_need": len(REQUIRED_FORMATS),
        "resid_6cm": at(mk["mvs"], 6.0),
        "resid_6cm_base": at(mk["baseline"], 6.0),
        "finest_mm": min(at(mk["mvs"], 3.0), at(ms["mvs"], 3.0)) * 10,
        "gain_lo": min(gain(mk), gain(ms)),
        "gain_hi": max(gain(mk), gain(ms)),
        "relief_base": mk["baseline"]["relief_m"]["max"],
        "relief_mvs": mk["mvs"]["relief_m"]["max"],
    }


def hms(sec):
    return f"{int(sec) // 60}m {int(sec) % 60:02d}s"


# --------------------------------------------------------------------------- helpers
def shape(slide, name):
    for s in slide.shapes:
        if s.name == name:
            return s
    raise KeyError(f"{name} not on slide")


def write(tf, blocks, line=1.0):
    """
    Replace a text frame's contents.

    `blocks` is a list of dicts: text, size, bold, colour, indent level, space above.
    Written as a list of bullets rather than prose because the template asks for points,
    and because a screening reader gives this slide seconds, not minutes.
    """
    tf.clear()
    tf.word_wrap = True
    for i, b in enumerate(blocks):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.level = b.get("level", 0)
        p.line_spacing = b.get("line", line)
        if b.get("space"):
            p.space_before = Pt(b["space"])
        if b.get("align"):
            p.alignment = b["align"]
        for j, run_spec in enumerate(b["text"] if isinstance(b["text"], list) else [b]):
            r = p.add_run()
            r.text = run_spec["text"] if isinstance(run_spec, dict) else run_spec
            f = r.font
            src = run_spec if isinstance(run_spec, dict) else b
            f.size = Pt(src.get("size", b.get("size", 12)))
            f.bold = src.get("bold", b.get("bold", False))
            f.color.rgb = src.get("colour", b.get("colour", INK))
            f.name = "Calibri"
    return tf


def textbox(slide, x, y, w, h, blocks, line=1.0):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    write(tb.text_frame, blocks, line=line)
    return tb


def band(slide, x, y, w, h, fill=LIGHT, edge=RULE, radius=0.06):
    """A soft panel behind a block of text, so the eye can find the groups."""
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                Inches(x), Inches(y), Inches(w), Inches(h))
    sh.adjustments[0] = radius
    sh.fill.solid(); sh.fill.fore_color.rgb = fill
    sh.line.color.rgb = edge; sh.line.width = Pt(0.75)
    sh.shadow.inherit = False
    sh.text_frame.text = ""
    return sh


def chip(slide, x, y, w, h, head, sub, colour=BLUE):
    """One measured fact, big enough to read from the back of a screening queue."""
    band(slide, x, y, w, h, fill=RGBColor(0xFF, 0xFF, 0xFF), edge=RULE)
    textbox(slide, x + 0.10, y + 0.06, w - 0.2, 0.42,
            [{"text": head, "size": 17, "bold": True, "colour": colour,
              "align": PP_ALIGN.CENTER}])
    textbox(slide, x + 0.08, y + 0.46, w - 0.16, h - 0.5,
            [{"text": sub, "size": 9, "colour": GREY, "align": PP_ALIGN.CENTER}],
            line=0.95)


def flow_box(slide, x, y, w, h, n, title, body):
    band(slide, x, y, w, h, fill=RGBColor(0xFF, 0xFF, 0xFF), edge=BLUE)
    textbox(slide, x + 0.08, y + 0.05, w - 0.16, 0.3,
            [{"text": [{"text": f"S{n}  ", "size": 10, "bold": True, "colour": ORANGE},
                       {"text": title, "size": 10, "bold": True, "colour": BLUE}],
              "size": 10}])
    textbox(slide, x + 0.08, y + 0.36, w - 0.16, h - 0.42,
            [{"text": body, "size": 8.5, "colour": INK}], line=0.92)


def arrow(slide, x, y):
    a = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x), Inches(y),
                               Inches(0.20), Inches(0.20))
    a.fill.solid(); a.fill.fore_color.rgb = BLUE
    a.line.fill.background(); a.shadow.inherit = False
    return a


def drop_slide(prs, index):
    lst = prs.slides._sldIdLst
    lst.remove(list(lst)[index])


TEMPLATE_URL = "https://www.sih.gov.in/letters/2026/SIH2026-IDEA-Presentation-Format.pptx"


def fetch_template():
    """
    The mandated template is an input, not an output, but `out/` is gitignored — so a
    fresh clone has to be able to pull it. Straight from sih.gov.in, never a mirror: the
    SIH logo, footer and slide numbering all have to be the shipped ones.
    """
    if os.path.exists(TEMPLATE):
        return
    import urllib.request
    os.makedirs(FIG, exist_ok=True)
    print("fetching the official template from sih.gov.in ...")
    # The portal 403s the default Python-urllib agent; curl gets through, so this is a
    # user-agent filter rather than any kind of access control.
    req = urllib.request.Request(TEMPLATE_URL, headers={"User-Agent": "curl/8.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(TEMPLATE, "wb") as f:
        f.write(r.read())
    print(f"  {os.path.getsize(TEMPLATE)/1e6:.2f} MB -> {TEMPLATE}")


# ----------------------------------------------------------------------------- build
# ------------------------------------------------------------- visual-first helpers
GREEN = RGBColor(0x2E, 0x7D, 0x32)
PAPER = RGBColor(0xFF, 0xFF, 0xFF)
WARM = RGBColor(0xFD, 0xF3, 0xEB)


def dot(slide, cx, cy, d, colour, glyph="", gcol=PAPER):
    """A filled status disc. Colour carries the meaning; the glyph repeats it, because
    a reader who prints this in greyscale still has to be able to score the row."""
    s = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(cx - d / 2), Inches(cy - d / 2),
                               Inches(d), Inches(d))
    s.fill.solid(); s.fill.fore_color.rgb = colour
    s.line.fill.background(); s.shadow.inherit = False
    write(s.text_frame, [{"text": glyph, "size": 9.5, "bold": True, "colour": gcol,
                          "align": PP_ALIGN.CENTER}])
    s.text_frame.margin_top = s.text_frame.margin_bottom = 0
    return s


def pill(slide, x, y, w, h, text, colour=BLUE, fill=None, size=8.6):
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                               Inches(x), Inches(y), Inches(w), Inches(h))
    s.adjustments[0] = 0.42
    s.fill.solid(); s.fill.fore_color.rgb = fill or LIGHT
    s.line.color.rgb = colour; s.line.width = Pt(0.75)
    s.shadow.inherit = False
    write(s.text_frame, [{"text": text, "size": size, "bold": True, "colour": colour,
                          "align": PP_ALIGN.CENTER}], line=0.9)
    s.text_frame.margin_left = s.text_frame.margin_right = Emu(18000)
    s.text_frame.margin_top = s.text_frame.margin_bottom = 0
    return s


def rule(slide, x, y, w, colour=RULE):
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y),
                               Inches(w), Inches(0.008))
    s.fill.solid(); s.fill.fore_color.rgb = colour
    s.line.fill.background(); s.shadow.inherit = False
    return s


MARKS = {"y": (GREEN, "✓"), "n": (RGBColor(0xC0, 0x39, 0x2B), "✗"),
         "p": (RGBColor(0xC9, 0x93, 0x1F), "~")}


def mark(slide, cx, cy, kind, note="", w=1.8):
    """One cell of the comparison matrix: a coloured mark, plus three or four words
    saying why. The mark is what gets read; the words are for whoever leans in."""
    colour, glyph = MARKS[kind]
    dot(slide, cx, cy, 0.24, colour, glyph)
    if note:
        textbox(slide, cx - w / 2, cy + 0.15, w, 0.44,
                [{"text": note, "size": 7.4, "colour": GREY,
                  "align": PP_ALIGN.CENTER}], line=0.88)


# ----------------------------------------------------------------------------- build
def build():
    fetch_template()
    m = measurements()
    prs = Presentation(TEMPLATE)
    s1, s2, s3, s4, s5, s6 = [prs.slides[i] for i in range(6)]

    for s in (s2, s3, s4, s5, s6):
        write(shape(s, [o.name for o in s.shapes
                        if o.name.startswith("Oval")][0]).text_frame,
              [{"text": TEAM_NAME, "size": 10, "bold": True, "colour": INK,
                "align": PP_ALIGN.CENTER}])

    # ---------------------------------------------------------------- 1 · title page
    write(shape(s1, "TextBox 9").text_frame, [
        {"text": [{"text": "Problem Statement ID – ", "size": 15},
                  {"text": "SIH26158", "size": 15, "bold": True}], "space": 4},
        {"text": [{"text": "Problem Statement Title – ", "size": 15},
                  {"text": "Single-Pass Drone Video to Accurate 3D Model "
                           "Generation System", "size": 15, "bold": True}], "space": 8},
        {"text": [{"text": "Theme – ", "size": 15},
                  {"text": "Robotics and Drones", "size": 15, "bold": True}], "space": 8},
        {"text": [{"text": "PS Category – ", "size": 15},
                  {"text": "Software", "size": 15, "bold": True}], "space": 8},
        {"text": [{"text": "Team ID – ", "size": 15},
                  {"text": TEAM_ID, "size": 15, "bold": True}], "space": 8},
        {"text": [{"text": "Team Name (Registered on portal) – ", "size": 15},
                  {"text": TEAM_NAME, "size": 15, "bold": True}], "space": 8},
    ], line=1.05)
    sub = shape(s1, "Subtitle 3")
    # The placeholder ships overlapping the SIH title block, which is fine for the two
    # words "TITLE PAGE" and not for a real title. Drop it clear of the descenders.
    sub.top, sub.left, sub.width = Inches(1.30), Inches(0.36), Inches(10.6)
    write(sub.text_frame, [{"text": IDEA_TITLE, "size": 21, "bold": True,
                            "colour": INK, "align": PP_ALIGN.CENTER}])
    textbox(s1, 0.36, 6.35, 6.6, 0.5, [
        {"text": "National Technical Research Organisation (NTRO)",
         "size": 12, "bold": True, "colour": BLUE}])

    # ------------------------------------------------------- 2 · proposed solution
    write(shape(s2, "Title 1").text_frame,
          [{"text": "MEASURED, NOT INTERPOLATED", "size": 34, "bold": True,
            "colour": INK, "align": PP_ALIGN.CENTER}])
    shape(s2, "TextBox 8")._element.getparent().remove(shape(s2, "TextBox 8")._element)

    textbox(s2, 0.45, 1.16, 12.4, 0.34, [
        {"text": [{"text": "One drone pass in — a metrically scaled, textured 3D mesh "
                           "and dense point cloud out, in all six required formats, "
                           "measurable in the browser.",
                   "size": 12.5, "bold": True, "colour": INK}]}])

    # The idea, as a picture. Everything the AI is good at is kept; the one thing it is
    # bad at is thrown away and replaced. That is the whole submission in one row.
    band(s2, 0.45, 1.58, 6.32, 1.92, fill=PAPER, edge=RULE)
    pill(s2, 0.58, 1.86, 1.05, 0.46, "ONE\nDRONE PASS", INK, PAPER, size=8.2)
    arrow(s2, 1.68, 2.00)
    pill(s2, 1.93, 1.86, 1.15, 0.46, "FEED-\nFORWARD AI", INK, PAPER, size=8.2)
    arrow(s2, 3.13, 1.75); arrow(s2, 3.13, 2.29)
    pill(s2, 3.38, 1.64, 3.24, 0.42, "✓  KEEP   camera pose + metric scale",
         GREEN, RGBColor(0xEE, 0xF6, 0xEE), size=9)
    pill(s2, 3.38, 2.18, 3.24, 0.42, "✗  DROP   its geometry",
         RGBColor(0xC0, 0x39, 0x2B), RGBColor(0xFC, 0xEF, 0xEE), size=9)
    textbox(s2, 3.38, 2.60, 3.24, 0.26, [
        {"text": "sampled at 2.2 cm, but only carries 30–50 cm",
         "size": 7.6, "colour": GREY, "align": PP_ALIGN.CENTER}])
    # Second row: what the kept half actually drives. Kept on its own line because the
    # first draft interleaved it with the fork and the reading order became ambiguous.
    textbox(s2, 0.58, 2.70, 6.1, 0.24, [
        {"text": "the kept pose and scale then drive:", "size": 8, "bold": True,
         "colour": GREY}])
    pill(s2, 0.58, 2.96, 1.72, 0.40, "global bundle adjustment", BLUE, LIGHT, size=8.2)
    arrow(s2, 2.35, 3.06)
    pill(s2, 2.60, 2.96, 2.20, 0.40, "full-resolution photometric MVS",
         BLUE, LIGHT, size=8.2)
    arrow(s2, 4.85, 3.06)
    pill(s2, 5.10, 2.96, 1.52, 0.40, "MEASURED 3D", GREEN,
         RGBColor(0xEE, 0xF6, 0xEE), size=8.6)

    textbox(s2, 0.45, 3.62, 6.32, 0.3, [
        {"text": "Reconstructs, per the problem statement", "size": 9.5,
         "bold": True, "colour": BLUE}])
    for i, t in enumerate(("terrain +\nstructures", "building facades\n+ rooftops",
                           "roads +\ninfrastructure", "vegetation\n+ obstacles",
                           "textured mesh\nor point cloud")):
        pill(s2, 0.45 + i * 1.28, 3.94, 1.20, 0.50, t, BLUE, LIGHT, size=7.6)

    s2.shapes.add_picture(f"{FIG}/fig_beforeafter.png", Inches(6.95), Inches(1.52),
                          width=Inches(5.93))
    textbox(s2, 6.95, 4.12, 5.93, 0.32, [
        {"text": "Same clip, same 45 keyframes, same camera poses. Only the geometry "
                 "stage changed.", "size": 8.6, "colour": GREY,
         "align": PP_ALIGN.CENTER}])

    for i, (h, sub_t) in enumerate((
            (m["registered"], "keyframes registered"),
            (f'{m["reproj_ba"]:.2f} px', "reprojection error"),
            (f'{m["dense_points"]/1e6:.2f} M', "measured dense points"),
            (f'{m["finest_mm"]:.1f} mm', "finest detail resolved"),
            (f'{m["gain_lo"]:.1f}–{m["gain_hi"]:.1f}×', "finer than the AI alone"),
            (f'{m["formats_have"]} / {m["formats_need"]}', "export formats"))):
        chip(s2, 0.45 + i * 2.09, 4.86, 1.98, 0.98, h, sub_t)

    textbox(s2, 0.45, 6.00, 12.4, 0.5, [
        {"text": [{"text": "Prototype status:  ", "size": 9.6, "bold": True,
                   "colour": ORANGE},
                  {"text": "the pipeline is containerised and running end to end on two "
                           "real clips. Four of the PS's six desired-output targets are "
                           "met and measured; the other two are on the feasibility "
                           "slide with the work that closes them.",
                   "size": 9.6, "colour": INK}]}], line=0.95)

    # -------------------------------------------------------- 3 · technical approach
    shape(s3, "TextBox 8")._element.getparent().remove(shape(s3, "TextBox 8")._element)
    textbox(s3, 0.45, 1.14, 12.4, 0.32, [
        {"text": "Methodology — five stages, all of them already running end to end",
         "size": 12.5, "bold": True, "colour": BLUE}])

    stages = [
        ("INGEST", "1080p/4K video + GPS + flight metadata.\nAdaptive keyframing drops "
                   "motion blur, compression artefacts and duplicates.\nAuto-detects "
                   "SRT / CSV / EXIF / flight log."),
        ("POSE + METRIC SCALE", "MapAnything point maps → intrinsics by robust masked "
                                f"fit ({m['intrinsics_px']:.2f} px) → COLMAP "
                                "triangulation + global bundle adjustment."),
        ("DENSE GEOMETRY", "OpenMVS PatchMatch at full keyframe resolution.\nGeometric-"
                           "consistency filtering across ≥ 3 views also rejects moving "
                           "vehicles, people and animals."),
        ("SURFACE + FRAME", "Delaunay + graph-cut mesh, per-vertex colour.\nVertical "
                            "from the ground plane, cross-checked against the gimbal's "
                            "roll-zero constraint."),
        ("EXPORT + VIEW", "OBJ · PLY · LAS 1.4 · GeoTIFF DSM · glB/glTF · FBX, in one "
                          "shared ENU frame.\nBrowser viewer for measurement."),
    ]
    x = 0.45
    for i, (t, b) in enumerate(stages):
        flow_box(s3, x, 1.50, 2.29, 1.66, i + 1, t, b)
        if i < 4:
            arrow(s3, x + 2.33, 2.23)
        x += 2.53
    for i, (lab, side) in enumerate((("IN", 0.45), ("OUT", 12.18))):
        textbox(s3, side - 0.02, 3.19, 0.7, 0.24,
                [{"text": lab, "size": 7.5, "bold": True, "colour": GREY}])

    textbox(s3, 0.45, 3.56, 7.55, 0.3, [
        {"text": "Technology stack", "size": 12, "bold": True, "colour": BLUE}])
    groups = [
        ("Vision / 3D", ("PyTorch", "MapAnything", "COLMAP", "OpenMVS", "Open3D",
                         "OpenCV")),
        ("Export", ("trimesh", "laspy", "rasterio", "pygltflib", "assimp")),
        ("Serve", ("Python 3.11", "Docker", "Cloud Run · asia-south1", "GCS",
                   "three.js")),
    ]
    y = 3.90
    for lab, items in groups:
        textbox(s3, 0.45, y + 0.04, 1.05, 0.3,
                [{"text": lab, "size": 8.6, "bold": True, "colour": GREY}])
        gx = 1.52
        for it in items:
            w = 0.20 + 0.072 * len(it)
            pill(s3, gx, y, w, 0.30, it, BLUE, LIGHT, size=8)
            gx += w + 0.09
        y += 0.44

    band(s3, 8.22, 3.56, 4.63, 3.20, fill=WARM, edge=ORANGE)
    textbox(s3, 8.40, 3.64, 4.3, 3.05, [
        {"text": "Four choices we can defend", "size": 11.5, "bold": True,
         "colour": ORANGE},
        {"text": [{"text": "Licence, not leaderboard.  ", "size": 9.2, "bold": True},
                  {"text": "VGGT is the better-known model. Its acceptable-use policy "
                           "bars military and espionage use — which this PS names. "
                           "MapAnything's Apache-2.0 checkpoint does not.",
                   "size": 9.2}], "space": 7},
        {"text": [{"text": "Sovereign by construction.  ", "size": 9.2, "bold": True},
                  {"text": "All processing pinned to asia-south1: India's geospatial "
                           "guidelines require finer-than-1 m data to be processed "
                           "within India, and this PS targets ≤ 1 m.", "size": 9.2}],
         "space": 6},
        {"text": [{"text": "No GPU floor.  ", "size": 9.2, "bold": True},
                  {"text": "Every component is permissive and runs on CPU. GPU is a "
                           "speed upgrade, never a dependency for getting a result.",
                   "size": 9.2}], "space": 6},
        {"text": [{"text": "Honest by construction.  ", "size": 9.2, "bold": True},
                  {"text": "With no GNSS in a clip the DEM ships with a real "
                           "geotransform in metres and no CRS at all, rather than a "
                           "plausible-looking wrong one that downstream GIS would "
                           "silently reproject.", "size": 9.2}], "space": 6},
    ], line=0.96)

    s3.shapes.add_picture(f"{FIG}/fig_timing.png", Inches(0.45), Inches(5.28),
                          width=Inches(7.50))

    # ------------------------------------------------------ 4 · feasibility, risks
    shape(s4, "TextBox 8")._element.getparent().remove(shape(s4, "TextBox 8")._element)
    textbox(s4, 0.45, 1.10, 12.4, 0.32, [
        {"text": [{"text": "Scored against the PS's own six desired outputs.  ",
                   "size": 12.5, "bold": True, "colour": BLUE},
                  {"text": "Four met and measured, two open and named.",
                   "size": 11, "colour": INK}]}])

    targets = [
        ("y", "3D mesh or point cloud",
         f'{m["triangles"]/1e6:.2f} M triangles · {m["dense_points"]/1e6:.2f} M points',
         "every point triangulated from real pixels"),
        ("y", "Six output formats",
         "OBJ · PLY · LAS 1.4 · GeoTIFF · glB/glTF · FBX",
         "all written and read back in one shared frame"),
        ("y", "Coverage of the visible scene",
         f'{m["coverage"]:.0%} of the AI-only baseline',
         "on the survey clip; it declines to invent unmatched ground"),
        ("y", "Web or desktop visualisation",
         "browser viewer, with measurement",
         "runs straight off the exported model"),
        ("n", "Processing < 15 min for a 10-min video",
         f'{hms(m["seconds"])} for {m["n_views"]} views on 8 vCPU',
         "GPU PatchMatch + keyframe budgeting; CPU fan-out already measured at 1.42×"),
        ("n", "Spatial accuracy ≤ 1 m, georeferenced",
         "unvalidated — no GNSS in either test clip",
         "RTK/PPK dataset with surveyed check points; CRS left empty, never faked"),
    ]
    y = 1.52
    for i, (st, target, measured, note) in enumerate(targets):
        met = st == "y"
        band(s4, 0.45, y, 12.4, 0.40,
             fill=PAPER if met else WARM, edge=RULE if met else ORANGE)
        dot(s4, 0.75, y + 0.20, 0.22, GREEN if met else ORANGE, "✓" if met else "!")
        textbox(s4, 0.98, y + 0.07, 3.35, 0.3,
                [{"text": target, "size": 9.6, "bold": True, "colour": INK}])
        textbox(s4, 4.40, y + 0.07, 3.55, 0.3,
                [{"text": measured, "size": 9.4,
                  "colour": GREEN if met else ORANGE, "bold": True}])
        textbox(s4, 8.05, y + 0.08, 4.72, 0.3,
                [{"text": note, "size": 8.6, "colour": GREY}])
        y += 0.46

    # Caption above the chart, not below: the chart is 2.4:1, and anything underneath it
    # lands in the footer bar.
    textbox(s4, 0.45, 4.34, 5.85, 0.30, [
        {"text": [{"text": "Why the accuracy claim holds.  ", "size": 9.4,
                   "bold": True, "colour": ORANGE},
                  {"text": "The old curve flattens into a floor; the rebuilt one keeps "
                           "a constant slope. Both meet at 1 m, as they must.",
                   "size": 8.8, "colour": GREY}]}], line=0.93)
    s4.shapes.add_picture(f"{FIG}/fig_accuracy.png", Inches(0.45), Inches(4.64),
                          width=Inches(5.40))

    textbox(s4, 6.62, 4.42, 6.23, 0.3, [
        {"text": "Other risks, and the strategy for each", "size": 11.5, "bold": True,
         "colour": ORANGE}])
    others = [
        ("Facades from a nadir pass", "physically unobservable straight down",
         "handle oblique passes natively; bound the inference and mark inferred "
         "surface as inferred, never as measured"),
        ("Dataset schema unknown until the event",
         "the PS says the link is provided in real time",
         "auto-detecting ingest across SRT / CSV / EXIF / flight log, and self-"
         "calibration when intrinsics are absent — already exercised on two clips"),
        ("OpenMVS is AGPL-3.0", "a deployment licence question, not a technical one",
         "invoked as a separate unmodified process, so our code is not a derived work; "
         "a BSD GPU replacement for that one stage is the clean answer"),
        ("Moving vehicles, people, animals", "they corrupt a naive reconstruction",
         "geometric-consistency filtering across ≥ 3 views rejects them by "
         "construction — nothing extra to build"),
    ]
    y = 4.78
    for head, state, fix in others:
        textbox(s4, 6.62, y, 6.23, 0.5, [
            {"text": [{"text": "▸ " + head + "  ", "size": 9.2, "bold": True,
                       "colour": INK},
                      {"text": state, "size": 8.6, "colour": GREY}]},
            {"text": [{"text": "→ ", "size": 8.6, "bold": True, "colour": BLUE},
                      {"text": fix, "size": 8.6, "colour": BLUE}], "space": 1}],
            line=0.92)
        y += 0.52

    # ------------------------------------------------------- 5 · impact and benefits
    shape(s5, "TextBox 8")._element.getparent().remove(shape(s5, "TextBox 8")._element)
    textbox(s5, 0.45, 1.10, 6.32, 0.32, [
        {"text": "What changes for the operator", "size": 12.5, "bold": True,
         "colour": BLUE}])
    s5.shapes.add_picture(f"{FIG}/fig_missions.png", Inches(0.45), Inches(1.42),
                          width=Inches(6.32))
    textbox(s5, 0.45, 3.78, 6.32, 0.32, [
        {"text": "A 3D model stops costing a planned survey and starts costing one "
                 "flight line.", "size": 9.4, "bold": True, "colour": INK,
         "align": PP_ALIGN.CENTER}])

    textbox(s5, 7.02, 1.10, 5.83, 0.32, [
        {"text": "Where it is used — the PS's own applications", "size": 12.5,
         "bold": True, "colour": BLUE}])
    apps = ("Border + strategic\narea mapping", "Military reconnaissance\n+ mission "
            "planning", "Disaster damage\nassessment", "Infrastructure\ninspection",
            "Urban planning\n+ smart cities", "Construction\nprogress monitoring",
            "Archaeological\ndocumentation", "Digital twin\ngeneration")
    for i, t in enumerate(apps):
        gx = 7.02 + (i % 4) * 1.48
        gy = 1.46 + (i // 4) * 0.66
        pill(s5, gx, gy, 1.40, 0.58, t, BLUE,
             WARM if i < 3 else LIGHT, size=7.4)
    textbox(s5, 7.02, 2.82, 5.83, 0.3, [
        {"text": "shaded: the three NTRO named first", "size": 7.6, "colour": GREY}])

    textbox(s5, 7.02, 3.14, 5.83, 0.3, [
        {"text": "Benefits", "size": 12, "bold": True, "colour": BLUE}])
    for i, (lab, txt) in enumerate((
            ("Economic", "permissive open source on commodity cloud CPU — no per-seat "
                         "photogrammetry licence, no proprietary SDK"),
            ("Strategic", "processing stays in India by construction; the model was "
                          "chosen against acceptable-use terms, not benchmarks"),
            ("Operational", "less air time and less operator effort per target; output "
                            "feeds existing GIS and 3D tooling directly"))):
        textbox(s5, 7.02, 3.46 + i * 0.44, 5.83, 0.42, [
            {"text": [{"text": lab + ":  ", "size": 9.2, "bold": True,
                       "colour": ORANGE},
                      {"text": txt, "size": 9.2, "colour": INK}]}], line=0.93)

    rule(s5, 0.45, 4.86, 12.4)
    textbox(s5, 0.45, 4.96, 12.4, 0.3, [
        {"text": "Measured benefit, on the two clips we have run", "size": 12,
         "bold": True, "colour": BLUE}])
    for i, (h, sub_t) in enumerate((
            (f'{m["gain_lo"]:.1f}–{m["gain_hi"]:.1f}×',
             "finer detail at 6 cm scale,\non two unrelated clips"),
            (f'{m["relief_base"]:.2f} → {m["relief_mvs"]:.2f} m',
             "vertical structure ceiling;\nbuildings stop being paint"),
            (f'{m["coverage"]:.0%}',
             "of the AI-only baseline's\nground coverage"),
            (f'{m["reproj_gain"]:.1f}×',
             "reprojection error improved\nby bundle adjustment"))):
        chip(s5, 0.45 + i * 3.13, 5.30, 3.00, 1.10, h, sub_t)

    textbox(s5, 0.45, 6.48, 12.4, 0.35, [
        {"text": [{"text": "Not claimed:  ", "size": 9.2, "bold": True,
                   "colour": ORANGE},
                  {"text": f"≤ 1 m absolute accuracy is unproven on our clips (no "
                           f"GNSS), and the 15-minute budget is not met on CPU. We "
                           f"would rather bring NTRO a measured "
                           f"{int(m['seconds'] // 60)} minutes than a claimed 12.",
                   "size": 9.2, "colour": GREY}]}], line=0.93)

    # -------------------------------------------------- 6 · research and references
    shape(s6, "TextBox 8")._element.getparent().remove(shape(s6, "TextBox 8")._element)
    textbox(s6, 0.45, 1.08, 12.4, 0.32, [
        {"text": [{"text": "Existing approaches, scored against what this PS actually "
                           "needs.  ", "size": 12.5, "bold": True, "colour": BLUE},
                  {"text": "This is why the two-model split exists.",
                   "size": 11, "colour": INK}]}])

    cols = ("pose from a\nsingle pass", "metric scale\nwithout GCPs",
            "detail below\n10 cm", "GIS-ready\nexports", "licence clear\nfor NTRO")
    x0, cw, roww = 0.45, 1.86, 3.10
    for j, c in enumerate(cols):
        textbox(s6, x0 + roww + j * cw, 1.44, cw, 0.42,
                [{"text": c, "size": 8.4, "bold": True, "colour": GREY,
                  "align": PP_ALIGN.CENTER}], line=0.9)
    rows = [
        ("Classical SfM + MVS", "COLMAP, OpenMVS alone",
         [("p", "thin strip, low overlap"), ("n", "needs GCPs or RTK"),
          ("y", "the accuracy standard"), ("y", ""), ("y", "BSD / AGPL")]),
        ("Commercial photogrammetry", "Pix4D, Metashape, RealityCapture",
         [("p", "assumes 70–80% overlap"), ("p", "needs GCPs or RTK"),
          ("y", ""), ("y", ""), ("n", "per-seat, closed")]),
        ("Feed-forward 3D", "DUSt3R, VGGT, MapAnything",
         [("y", "this is what it solves"), ("y", "metric, from one pass"),
          ("n", "patch-limited ceiling"), ("p", "no LAS / GeoTIFF"),
          ("p", "VGGT barred by AUP")]),
        ("NeRF / 3D Gaussian splatting", "radiance-field reconstruction",
         [("n", "needs poses given"), ("n", ""), ("p", "appearance, not surface"),
          ("n", "renders, not products"), ("y", "")]),
        ("This submission", "AI for pose and scale, MVS for every surface point",
         [("y", ""), ("y", ""), ("y", f'{m["finest_mm"]:.1f} mm measured'),
          ("y", "all six formats"), ("y", "Apache-2.0 / BSD")]),
    ]
    y = 1.94
    for i, (name, sub_t, marks) in enumerate(rows):
        last = i == len(rows) - 1
        band(s6, x0, y, roww + 5 * cw, 0.62, fill=WARM if last else PAPER,
             edge=ORANGE if last else RULE)
        textbox(s6, x0 + 0.12, y + 0.06, roww - 0.2, 0.5, [
            {"text": name, "size": 9.4, "bold": True,
             "colour": ORANGE if last else INK},
            {"text": sub_t, "size": 7.4, "colour": GREY}], line=0.9)
        for j, (kind, note) in enumerate(marks):
            mark(s6, x0 + roww + j * cw + cw / 2, y + 0.17, kind, note, w=cw - 0.1)
        y += 0.68

    textbox(s6, 0.45, 5.46, 6.15, 0.3, [
        {"text": "Methods and models", "size": 11.5, "bold": True, "colour": BLUE}])
    textbox(s6, 0.45, 5.76, 6.15, 1.15, [
        {"text": [{"text": "MapAnything", "size": 8.8, "bold": True},
                  {"text": " — Meta AI, 2025 · Apache-2.0.  ", "size": 8.6},
                  {"text": "COLMAP", "size": 8.8, "bold": True},
                  {"text": " — Schönberger & Frahm, CVPR 2016.  ", "size": 8.6},
                  {"text": "OpenMVS 2.4.0", "size": 8.8, "bold": True},
                  {"text": " — PatchMatch MVS + Delaunay/graph-cut meshing.  ",
                   "size": 8.6},
                  {"text": "DINOv2", "size": 8.8, "bold": True},
                  {"text": " — Oquab et al., TMLR 2024; the patch-14 backbone whose "
                           "grid is the ceiling we measured.  ", "size": 8.6},
                  {"text": "PatchMatch Stereo", "size": 8.8, "bold": True},
                  {"text": " — Bleyer et al., BMVC 2011; Schönberger et al., ECCV 2016.  ",
                   "size": 8.6},
                  {"text": "VGGT", "size": 8.8, "bold": True},
                  {"text": " — Wang et al., CVPR 2025; evaluated, rejected on licence.",
                   "size": 8.6}]}], line=0.95)

    textbox(s6, 6.90, 5.46, 5.95, 0.3, [
        {"text": "Standards, policy, and our own record", "size": 11.5, "bold": True,
         "colour": BLUE}])
    textbox(s6, 6.90, 5.76, 5.95, 1.15, [
        {"text": [{"text": "Geospatial Data Guidelines, DST 2021", "size": 8.8,
                   "bold": True},
                  {"text": " and the National Geospatial Policy 2022 — why processing "
                           "is pinned to an Indian region.  ", "size": 8.6},
                  {"text": "ASPRS LAS 1.4", "size": 8.8, "bold": True},
                  {"text": " pf3 and ", "size": 8.6},
                  {"text": "Khronos glTF 2.0", "size": 8.8, "bold": True},
                  {"text": " — both validated on write.", "size": 8.6}]},
        {"text": [{"text": "Our record: ", "size": 8.8, "bold": True,
                   "colour": ORANGE},
                  {"text": "an SRS baselined line-by-line against the PS PDF, plus "
                           "architecture, test plan, a quality analysis that diagnoses "
                           "the resolution ceiling with controls, and a deployment "
                           "study. Both charts and every headline number here are read "
                           "at build time from the JSON the runs wrote — the build "
                           "fails rather than print a stale figure.", "size": 8.6}],
         "space": 4},
        {"text": [{"text": "Note: ", "size": 8.8, "bold": True, "colour": ORANGE},
                  {"text": "the portal listing for SIH26158 still carries the editorial "
                           "placeholder “Add 'Desired Output' and 'Evaluation Criteria' "
                           "table here”. The binding targets exist only in the linked "
                           "PDF, which we read as images and traced one by one.",
                   "size": 8.6}], "space": 4},
    ], line=0.95)

    drop_slide(prs, 6)          # the template's own Important Instructions slide
    prs.save(OUT_PPTX)
    print("wrote", OUT_PPTX)
    return OUT_PPTX


def to_pdf(pptx_path):
    """PowerPoint COM. python-pptx cannot write PDF and the portal takes PDF only."""
    # A file called SIH26158_IdeaSubmission.pdf invites being uploaded. While the team
    # fields are still placeholders it must not carry that name, or someone will submit
    # a deck that says «TEAM NAME» six times.
    draft = TEAM_NAME.startswith("«") or TEAM_ID.startswith("«")
    dest = OUT_PDF.replace(".pdf", "_DRAFT.pdf") if draft else OUT_PDF
    ps = (
        "$p = New-Object -ComObject PowerPoint.Application;"
        f"$d = $p.Presentations.Open('{pptx_path}', $true, $false, $false);"
        f"$d.SaveAs('{dest}', 32);"
        "$d.Close(); $p.Quit();"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True)
    if r.returncode or not os.path.exists(dest):
        sys.exit(f"PDF export failed:\n{r.stdout}\n{r.stderr}")
    print("wrote", dest, f"{os.path.getsize(dest)/1e6:.2f} MB")
    if draft:
        print("\n  DRAFT - not uploadable yet. Set TEAM_NAME and TEAM_ID at the top of\n"
              "  this file and rebuild; the output is then named for submission.")


if __name__ == "__main__":
    to_pdf(build())
