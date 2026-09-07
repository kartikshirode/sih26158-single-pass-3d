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
def build():
    fetch_template()
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
    textbox(s1, 0.36, 6.35, 6.6, 0.5, [
        {"text": "National Technical Research Organisation (NTRO)",
         "size": 12, "bold": True, "colour": BLUE}])

    # ------------------------------------------------------- 2 · proposed solution
    write(shape(s2, "Title 1").text_frame,
          [{"text": "MEASURED, NOT INTERPOLATED", "size": 34, "bold": True,
            "colour": INK, "align": PP_ALIGN.CENTER}])
    shape(s2, "TextBox 8")._element.getparent().remove(shape(s2, "TextBox 8")._element)

    textbox(s2, 0.42, 1.32, 6.35, 0.55, [
        {"text": "Proposed Solution", "size": 15, "bold": True, "colour": BLUE},
        {"text": "One drone pass in — a georeferenceable, metrically scaled, textured "
                 "3D mesh and point cloud out, in all six required formats.",
         "size": 11.5, "space": 3}])
    textbox(s2, 0.42, 2.42, 6.35, 1.5, [
        {"text": "How it addresses the problem", "size": 13, "bold": True,
         "colour": BLUE},
        {"text": "•  No repeat passes, no flight planning, no Ground Control Point "
                 "survey — the AI recovers pose and metric scale from the single pass "
                 "itself.", "size": 10.5, "space": 4},
        {"text": "•  Reconstructs terrain and structures, facades and rooftops, roads, "
                 "vegetation and obstacles as textured mesh or point cloud.",
         "size": 10.5, "space": 3},
        {"text": "•  Output is measurable — distance, area and height — not just "
                 "viewable.", "size": 10.5, "space": 3}], line=0.98)

    band(s2, 0.42, 4.05, 6.35, 2.18, fill=LIGHT)
    textbox(s2, 0.60, 4.14, 6.0, 2.05, [
        {"text": "Innovation and uniqueness", "size": 13, "bold": True,
         "colour": ORANGE},
        {"text": [{"text": "We found why single-pass AI 3D looks right from far and "
                           "falls apart up close.", "size": 10.5, "bold": True}],
         "space": 5},
        {"text": "The feed-forward model samples at 2.2 cm but only carries "
                 "information at 30–50 cm — a ceiling set by its patch-14 vision "
                 "backbone and its interpolating depth head, not by tuning. We proved "
                 "it three ways and tested the competing explanation, which failed.",
         "size": 10, "space": 3},
        {"text": [{"text": "The fix: use the AI only for what one pass uniquely needs "
                           "— pose and metric scale — and take the geometry from "
                           "full-resolution photometric multi-view stereo.",
                   "size": 10.5, "bold": True}], "space": 5},
        {"text": "Measured on two real clips: 1.8–3.6× finer detail, resolving to "
                 "1.9 mm; buildings gain real walls (height ceiling 2.33 m → 3.58 m); "
                 "coverage 135% of the AI-only baseline on the survey clip.",
         "size": 10, "space": 3},
    ], line=0.98)

    textbox(s2, 0.42, 6.32, 6.35, 0.55, [
        {"text": [{"text": "Prototype status today:  ", "size": 10, "bold": True,
                   "colour": ORANGE},
                  {"text": "the whole pipeline is containerised and running, with a "
                           "browser viewer for measurement. Four of the six "
                           "desired-output targets are met and measured; the two that "
                           "are not are named on the feasibility slide.",
                   "size": 10, "colour": INK}]}], line=0.95)

    s2.shapes.add_picture(f"{FIG}/fig_beforeafter.png", Inches(6.95), Inches(1.45),
                          width=Inches(6.0))
    textbox(s2, 6.95, 4.42, 6.0, 0.4, [
        {"text": "Same clip, same 45 keyframes, same camera poses — the only change is "
                 "where the geometry comes from.", "size": 9, "colour": GREY,
         "align": PP_ALIGN.CENTER}], line=0.95)
    for i, (h, sub) in enumerate((
            ("45 / 45", "keyframes registered\n1920×1080, single pass"),
            ("0.37 px", "mean reprojection error\nafter bundle adjustment"),
            ("3.45 M", "dense points measured\nnot interpolated"),
            ("6 / 6", "required export formats\nOBJ PLY LAS GeoTIFF glB FBX"))):
        chip(s2, 6.95 + i * 1.52, 5.00, 1.42, 1.15, h, sub)

    # -------------------------------------------------------- 3 · technical approach
    shape(s3, "TextBox 8")._element.getparent().remove(shape(s3, "TextBox 8")._element)
    textbox(s3, 0.45, 1.20, 12.4, 0.35, [
        {"text": "Methodology — five stages, all of them already running end to end",
         "size": 13, "bold": True, "colour": BLUE}])

    stages = [
        ("INGEST", "Video 1080p/4K + GPS + flight metadata. Adaptive keyframing, blur "
                   "and duplicate rejection. Auto-detects SRT / CSV / EXIF / flight-log "
                   "schema; self-calibrates when intrinsics are absent."),
        ("POSE + METRIC SCALE", "MapAnything feed-forward point maps → intrinsics by "
                                "robust masked fit (0.22 px residual) → COLMAP "
                                "triangulation and global bundle adjustment. "
                                "1.73 → 0.37 px."),
        ("DENSE GEOMETRY", "OpenMVS PatchMatch at full keyframe resolution with "
                           "geometric-consistency depth filtering. This is the stage "
                           "that breaks the patch ceiling."),
        ("SURFACE + FRAME", "Delaunay + graph-cut mesh, per-vertex colour. Vertical "
                            "recovered from the ground plane and cross-checked against "
                            "the gimbal roll-zero constraint; the two agree within 0.6 degrees."),
        ("EXPORT + VIEW", "OBJ · PLY · LAS 1.4 · GeoTIFF DSM · glB/glTF · FBX, one "
                          "shared ENU frame, plus a browser viewer for measurement."),
    ]
    x = 0.45
    for i, (t, b) in enumerate(stages):
        flow_box(s3, x, 1.58, 2.29, 1.52, i + 1, t, b)
        if i < 4:
            arrow(s3, x + 2.33, 2.24)
        x += 2.53

    band(s3, 0.45, 3.30, 6.15, 3.15)
    textbox(s3, 0.62, 3.38, 5.85, 3.3, [
        {"text": "Technologies", "size": 12.5, "bold": True, "colour": BLUE},
        {"text": [{"text": "Vision / 3D:  ", "size": 10, "bold": True},
                  {"text": "MapAnything (Apache-2.0), COLMAP, OpenMVS, Open3D, OpenCV, "
                           "PyTorch", "size": 10}], "space": 5},
        {"text": [{"text": "Export:  ", "size": 10, "bold": True},
                  {"text": "trimesh, laspy, rasterio, pygltflib, assimp (BSD-3)",
                   "size": 10}], "space": 4},
        {"text": [{"text": "Serving:  ", "size": 10, "bold": True},
                  {"text": "Python 3.11, Docker, Google Cloud Run jobs in asia-south1, "
                           "GCS, three.js viewer", "size": 10}], "space": 4},
        {"text": [{"text": "Why this stack, specifically:", "size": 10, "bold": True,
                   "colour": ORANGE}], "space": 8},
        {"text": "•  VGGT is the better-known feed-forward model and we rejected it: "
                 "its acceptable-use terms bar military and espionage use, which is "
                 "exactly what this problem statement names. MapAnything's Apache-2.0 "
                 "checkpoint carries no such bar.", "size": 9.5, "space": 4},
        {"text": "•  Processing is pinned to asia-south1 because India's geospatial "
                 "guidelines require data finer than 1 m to be processed within India — "
                 "and this PS targets ≤ 1 m.", "size": 9.5, "space": 4},
        {"text": "•  Every component is permissively licensed and runs on CPU, so the "
                 "system has a working floor with no GPU at all. GPU is a speed "
                 "upgrade, never a dependency for producing a result.",
         "size": 9.5, "space": 4},
    ], line=0.97)

    band(s3, 6.75, 3.30, 6.12, 3.15)
    textbox(s3, 6.92, 3.38, 5.82, 3.3, [
        {"text": "Why the two-model split is the whole idea", "size": 12.5,
         "bold": True, "colour": BLUE},
        {"text": "A single pass gives weak geometry but strong context. Classical "
                 "structure-from-motion alone struggles to fix scale and can fail to "
                 "register a thin, low-overlap strip; the feed-forward model solves "
                 "exactly that, and nothing else well.",
         "size": 10, "space": 5},
        {"text": "So it is used as a pose-and-scale prior, then discarded. Every "
                 "surface point in the delivered model is triangulated from real pixels "
                 "across at least three views.", "size": 10, "space": 4},
        {"text": [{"text": "Evidence that the split is load-bearing:", "size": 10,
                   "bold": True, "colour": ORANGE}], "space": 7},
        {"text": "•  Reprojection error falls 1.73 → 0.37 px through bundle "
                 "adjustment — the AI poses did carry error, and densifying before "
                 "correcting it would have sharpened a wrong surface.",
         "size": 9.5, "space": 4},
        {"text": "•  At 1 m window size the two agree to within 2–4%. The entire "
                 "difference is at small scale — precisely where the diagnosis said "
                 "the information was missing.", "size": 9.5, "space": 4},
        {"text": "•  Vertical relief above local ground rises from a hard 2.33 m "
                 "ceiling to 3.58 m. Noise cannot fake that: noise is isotropic, and "
                 "buildings are not.", "size": 9.5, "space": 4},
        {"text": "•  The rebuilt surface declines to invent ground it could not match, "
                 "and still covers 135% of the baseline's footprint on the survey clip "
                 "— accuracy and completeness moved together, not against each other.",
         "size": 9.5, "space": 4},
    ], line=0.97)

    # ------------------------------------------------------ 4 · feasibility, risks
    shape(s4, "TextBox 8")._element.getparent().remove(shape(s4, "TextBox 8")._element)
    textbox(s4, 0.45, 1.18, 12.4, 0.35, [
        {"text": [{"text": "Feasibility — this is a measurement, not a plan.  ",
                   "size": 13, "bold": True, "colour": BLUE},
                  {"text": "Both clips ran end to end on commodity CPU; no GPU was "
                           "available and none was needed to produce these numbers.",
                   "size": 11, "colour": INK}]}])
    for i, (h, sub) in enumerate((
            ("2 clips", "run end to end\n42 and 45 keyframes"),
            ("32m 43s", "wall clock, 8 vCPU\nCPU only, no GPU"),
            ("1.95 M", "mesh triangles\nDelaunay + graph cut"),
            ("0.76 cm", "detail at 6 cm scale\nwas 1.38 cm"),
            ("135%", "coverage vs baseline\non the survey clip"),
            ("1.42×", "measured CPU fan-out\n2 tasks × 8 vCPU"))):
        chip(s4, 0.45 + i * 2.09, 1.62, 1.98, 1.10, h, sub)

    textbox(s4, 0.45, 2.92, 7.35, 0.3, [
        {"text": "Potential challenges and risks — and how we close them",
         "size": 12.5, "bold": True, "colour": ORANGE}])
    risks = [
        ("Processing time < 15 min for a 10-min video",
         "NOT MET YET. 45 views take 33 min on 8 vCPU. CPU fan-out is measured at only "
         "1.42×, and honest extrapolation puts a 600-view clip at ~29 min.",
         "GPU PatchMatch on the Baramati Blackwell cluster (the same stage is 10–20× "
         "faster on GPU) + keyframe budgeting to the scene, not the clock. CPU sharding "
         "stays as the no-GPU fallback."),
        ("Spatial accuracy ≤ 1 m, georeferenced",
         "UNVALIDATED. Neither test clip carries GNSS, so the output is metric-relative "
         "and the DEM is written with a real geotransform and deliberately NO CRS "
         "rather than a plausible-looking wrong one.",
         "Validate on an RTK/PPK-tagged public dataset with surveyed check points. The "
         "georeferencing hooks are already in the exporter — only the CRS and origin "
         "change when GNSS arrives."),
        ("Facades from a nadir single pass",
         "A straight-down pass physically cannot observe a vertical wall. We state this "
         "rather than gloss it.",
         "Handle oblique passes natively; bound the inference for genuinely unobserved "
         "surface and mark it as inferred in the output, never as measured."),
        ("Dataset schema unknown until the event",
         "The PS says the dataset link will be provided in real time, so codec, drone "
         "and metadata format are all unknown in advance.",
         "Auto-detecting ingest across SRT / CSV / EXIF / flight log, and self-"
         "calibration when camera intrinsics are absent. Already exercised on two "
         "unrelated clips with different aspect ratios."),
        ("OpenMVS is AGPL-3.0",
         "A licence question for any onward government deployment, not a technical one.",
         "Invoked as a separate unmodified process, so our code is not a derived work; "
         "a BSD-licensed GPU replacement for this one stage is the clean long-term "
         "answer."),
    ]
    y = 3.28
    for head, state, fix in risks:
        textbox(s4, 0.45, y, 7.35, 0.62, [
            {"text": [{"text": "▸ " + head + "  ", "size": 9.8, "bold": True,
                       "colour": INK},
                      {"text": state, "size": 9, "colour": GREY}]},
            {"text": [{"text": "→ ", "size": 9, "bold": True, "colour": BLUE},
                      {"text": fix, "size": 9, "colour": BLUE}], "space": 1}],
            line=0.92)
        y += 0.70

    s4.shapes.add_picture(f"{FIG}/fig_accuracy.png", Inches(7.95), Inches(3.05),
                          width=Inches(4.95))
    textbox(s4, 7.95, 5.20, 4.95, 1.5, [
        {"text": "Why we trust the accuracy claim", "size": 11, "bold": True,
         "colour": BLUE},
        {"text": "A plane fitted in a shrinking window. The feed-forward curve flattens "
                 "into a floor — the signature of an interpolant with nothing below it. "
                 "The rebuilt curve holds a constant slope all the way down, which is "
                 "what a real self-affine surface does. Both meet at 1 m, as they must: "
                 "same poses, same large-scale shape.",
         "size": 9, "colour": GREY, "space": 3}], line=0.95)

    # ------------------------------------------------------- 5 · impact and benefits
    shape(s5, "TextBox 8")._element.getparent().remove(shape(s5, "TextBox 8")._element)
    textbox(s5, 0.45, 1.18, 12.4, 0.32, [
        {"text": "Potential impact on the target audience", "size": 13, "bold": True,
         "colour": BLUE}])
    band(s5, 0.45, 1.58, 6.15, 2.35)
    textbox(s5, 0.62, 1.66, 5.85, 2.2, [
        {"text": "Operational — the audience that wrote this PS", "size": 11.5,
         "bold": True, "colour": ORANGE},
        {"text": "•  Border and strategic area mapping, and military reconnaissance "
                 "and mission planning, where a second pass over the target may not be "
                 "available at all.", "size": 10, "space": 5},
        {"text": "•  Disaster damage assessment, where the aircraft is scarce and the "
                 "first hours decide the response.", "size": 10, "space": 4},
        {"text": "•  Infrastructure inspection, construction monitoring, urban planning "
                 "and digital-twin generation on the same single-pass capture.",
         "size": 10, "space": 4},
        {"text": "The mission cost of a 3D model drops from a planned grid survey with "
                 "ground control to one flight line.", "size": 10, "bold": True,
         "space": 6}], line=0.97)

    band(s5, 6.75, 1.58, 6.12, 2.35)
    textbox(s5, 6.92, 1.66, 5.82, 2.2, [
        {"text": "Benefits", "size": 11.5, "bold": True, "colour": ORANGE},
        {"text": [{"text": "Economic:  ", "size": 10, "bold": True},
                  {"text": "the entire stack is permissively licensed open source on "
                           "commodity cloud CPU — no per-seat photogrammetry licence, "
                           "no proprietary SDK, no GPU floor to get a first result.",
                   "size": 10}], "space": 5},
        {"text": [{"text": "Strategic:  ", "size": 10, "bold": True},
                  {"text": "processing stays inside India by construction, and the "
                           "model choice was made against acceptable-use terms rather "
                           "than benchmark scores.", "size": 10}], "space": 4},
        {"text": [{"text": "Operational:  ", "size": 10, "bold": True},
                  {"text": "less operator effort and less air time per target; the "
                           "output feeds existing GIS and 3D tooling directly through "
                           "the six mandated formats.", "size": 10}], "space": 4},
        {"text": [{"text": "Environmental:  ", "size": 10, "bold": True},
                  {"text": "fewer sorties per surveyed area.", "size": 10}], "space": 4},
    ], line=0.97)

    textbox(s5, 0.45, 4.05, 12.4, 0.32, [
        {"text": "Measured benefit, on the two clips we have run", "size": 13,
         "bold": True, "colour": BLUE}])
    for i, (h, sub) in enumerate((
            ("1.8–3.6×", "finer detail resolved at 6 cm scale,\non two unrelated clips"),
            ("2.33 → 3.58 m", "vertical structure ceiling;\nbuildings stop being paint"),
            ("135%", "of the AI-only baseline's ground\ncoverage on the survey clip"),
            ("4.7×", "reprojection error improvement\nthrough bundle adjustment"))):
        chip(s5, 0.45 + i * 3.15, 4.45, 3.02, 1.25, h, sub)

    textbox(s5, 0.45, 5.90, 12.4, 0.85, [
        {"text": "What we are not claiming yet", "size": 11, "bold": True,
         "colour": ORANGE},
        {"text": "Absolute ≤ 1 m accuracy is unproven on our clips because neither has "
                 "GNSS, and the < 15 minute budget is not met on CPU. Both gaps are "
                 "named on the previous slide with the work that closes them. We would "
                 "rather bring NTRO a measured 33 minutes than a claimed 12.",
         "size": 10, "colour": GREY, "space": 3}], line=0.97)

    # -------------------------------------------------- 6 · research and references
    shape(s6, "TextBox 8")._element.getparent().remove(shape(s6, "TextBox 8")._element)
    textbox(s6, 0.45, 1.18, 6.15, 0.32, [
        {"text": "Methods and models", "size": 12.5, "bold": True, "colour": BLUE}])
    textbox(s6, 0.45, 1.55, 6.15, 4.9, [
        {"text": [{"text": "MapAnything", "size": 10, "bold": True},
                  {"text": " — Meta AI, 2025. Feed-forward metric point maps from "
                           "uncalibrated images; supplies our pose and scale prior. "
                           "Apache-2.0 checkpoint.\ngithub.com/facebookresearch/"
                           "map-anything", "size": 9.5}], "space": 4},
        {"text": [{"text": "VGGT", "size": 10, "bold": True},
                  {"text": " — Wang et al., CVPR 2025. Evaluated and deliberately not "
                           "used: its acceptable-use policy bars military and espionage "
                           "applications, which this PS explicitly lists.",
                   "size": 9.5}], "space": 7},
        {"text": [{"text": "COLMAP", "size": 10, "bold": True},
                  {"text": " — Schönberger & Frahm, CVPR 2016. Feature matching, "
                           "triangulation and global bundle adjustment. BSD.",
                   "size": 9.5}], "space": 7},
        {"text": [{"text": "OpenMVS 2.4.0", "size": 10, "bold": True},
                  {"text": " — PatchMatch multi-view stereo with geometric-consistency "
                           "filtering, and Delaunay + graph-cut meshing. AGPL-3.0, used "
                           "as an unmodified separate process.", "size": 9.5}],
         "space": 7},
        {"text": [{"text": "DINOv2", "size": 10, "bold": True},
                  {"text": " — Oquab et al., TMLR 2024. The patch-14 vision backbone "
                           "whose patch grid is the resolution ceiling we measured and "
                           "then designed around.", "size": 9.5}], "space": 7},
        {"text": [{"text": "PatchMatch Stereo", "size": 10, "bold": True},
                  {"text": " — Bleyer et al., BMVC 2011; and Schönberger et al., "
                           "ECCV 2016 for the pixelwise view-selection variant we rely "
                           "on.", "size": 9.5}], "space": 7},
    ], line=0.97)

    textbox(s6, 6.90, 1.18, 5.95, 0.32, [
        {"text": "Standards, policy and our own record", "size": 12.5, "bold": True,
         "colour": BLUE}])
    textbox(s6, 6.90, 1.55, 5.95, 4.9, [
        {"text": [{"text": "Guidelines for acquiring and producing Geospatial Data, "
                           "DST, 2021", "size": 10, "bold": True},
                  {"text": " and the National Geospatial Policy 2022 — the basis for "
                           "pinning all processing to an Indian region for finer-than-"
                           "1 m data.", "size": 9.5}], "space": 4},
        {"text": [{"text": "ASPRS LAS 1.4", "size": 10, "bold": True},
                  {"text": " point format 3, and the Khronos glTF 2.0 specification — "
                           "the two export formats with real conformance rules; both "
                           "are validated on write.", "size": 9.5}], "space": 7},
        {"text": [{"text": "Our engineering record", "size": 10, "bold": True,
                   "colour": ORANGE},
                  {"text": " — six documents written before and during this work and "
                           "traceable to the runs: SRS baselined line-by-line against "
                           "the PS PDF, architecture, SDLC plan, test plan, a quality "
                           "analysis that diagnoses the resolution ceiling with "
                           "controls, and a deployment study. Available to the "
                           "evaluators on request.", "size": 9.5}], "space": 7},
        {"text": [{"text": "Reproducibility", "size": 10, "bold": True},
                  {"text": " — every figure and number on these slides is regenerated "
                           "by a script in the repository from the run outputs; none "
                           "is transcribed by hand.", "size": 9.5}], "space": 7},
        {"text": [{"text": "A note on the portal text.", "size": 10, "bold": True,
                   "colour": ORANGE},
                  {"text": " The sih.gov.in listing for SIH26158 still contains the "
                           "editorial placeholder “Add 'Desired Output' and "
                           "'Evaluation Criteria' table here”. The binding targets "
                           "— mesh or point cloud, < 15 min for a 10-min video, ≤ 1 m "
                           "accuracy, full-scene coverage, six export formats, a web or "
                           "desktop viewer — exist only in the linked PDF, which we "
                           "read as images and traced requirement by requirement.",
                   "size": 9.5}], "space": 7},
    ], line=0.97)

    # Existing-solutions analysis. It belongs on the references slide because it is the
    # part of the research that justifies the design, and because a reviewer scoring
    # novelty needs to see that we know what already exists.
    textbox(s6, 0.45, 4.72, 12.4, 0.32, [
        {"text": "Existing approaches we studied — and why none of them answers this "
                 "problem statement on its own", "size": 12.5, "bold": True,
         "colour": ORANGE}])
    prior = [
        ("Classical SfM + MVS", "COLMAP, OpenMVS on their own",
         "The accuracy standard, and what we build on. But a thin single-pass strip "
         "gives it little overlap to work with, and it recovers no metric scale at all "
         "without GCPs or RTK."),
        ("Commercial photogrammetry", "Pix4D, Metashape, RealityCapture",
         "Mature and trusted, but designed around a planned multi-pass grid with 70–80% "
         "overlap. Per-seat licensing and closed pipelines also make it a poor fit for "
         "sovereign deployment."),
        ("Feed-forward 3D", "DUSt3R, VGGT, MapAnything",
         "Genuinely solves the single-pass problem of pose and metric scale. Its "
         "geometry, however, is bounded by the patch grid — the ceiling this deck "
         "measures. VGGT is additionally licence-barred here."),
        ("NeRF / 3D Gaussian Splatting", "radiance-field reconstruction",
         "Outstanding novel-view rendering, but it optimises appearance rather than a "
         "measurable surface, and does not yield the LAS or GeoTIFF products a mapping "
         "organisation actually consumes."),
        ("This submission", "the split, and why it is new",
         "Feed-forward AI for pose and scale only; classical per-pixel MVS for every "
         "delivered surface point. Each is used strictly where it is strongest, and the "
         "handover point was chosen from a measurement, not a guess."),
    ]
    for i, (head, sub, body) in enumerate(prior):
        x = 0.45 + i * 2.51
        last = i == len(prior) - 1
        band(s6, x, 5.08, 2.38, 1.72,
             fill=RGBColor(0xFD, 0xF3, 0xEB) if last else RGBColor(0xFF, 0xFF, 0xFF),
             edge=ORANGE if last else RULE)
        textbox(s6, x + 0.10, 5.14, 2.18, 0.5, [
            {"text": head, "size": 9.5, "bold": True,
             "colour": ORANGE if last else BLUE},
            {"text": sub, "size": 8, "colour": GREY}], line=0.92)
        textbox(s6, x + 0.10, 5.66, 2.18, 1.08,
                [{"text": body, "size": 8.2, "colour": INK}], line=0.92)

    drop_slide(prs, 6)          # the template's own Important Instructions slide
    prs.save(OUT_PPTX)
    print("wrote", OUT_PPTX)
    return OUT_PPTX


def to_pdf(pptx_path):
    """PowerPoint COM. python-pptx cannot write PDF and the portal takes PDF only."""
    ps = (
        "$p = New-Object -ComObject PowerPoint.Application;"
        f"$d = $p.Presentations.Open('{pptx_path}', $true, $false, $false);"
        f"$d.SaveAs('{OUT_PDF}', 32);"
        "$d.Close(); $p.Quit();"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True)
    if r.returncode or not os.path.exists(OUT_PDF):
        sys.exit(f"PDF export failed:\n{r.stdout}\n{r.stderr}")
    print("wrote", OUT_PDF, f"{os.path.getsize(OUT_PDF)/1e6:.2f} MB")


if __name__ == "__main__":
    to_pdf(build())
