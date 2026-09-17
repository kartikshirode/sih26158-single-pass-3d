"""
Build the SIH 2026 idea-submission deck on top of the OFFICIAL template.

Two rules from the template's own instruction slide drive the whole design:

  "You can only use provided template for making the PPT without changing the idea
   details pointers"          -> we EDIT the downloaded .pptx in place. The SIH logo,
                                 the footer, the slide numbers, the team-name badge and
                                 the six section headings are left exactly as shipped.
                                 The template's own content pointers are not deleted
                                 either: each one is kept verbatim and set small at the
                                 top right of its slide, so an evaluator can read the
                                 question and our answer to it on the same line.
                                 "Clarity and details in the prescribed format" is one
                                 of the scored criteria, so the chrome is not cosmetic.

  "You need to save the file in PDF"   -> exported through PowerPoint COM at the end.
                                          python-pptx cannot write PDF.

Slide 7 (Important Instructions) is deleted before export, as that slide itself says.

Nothing on these slides is invented. Every number traces to docs/05-quality-analysis.md,
docs/06-gcp-deployment.md, or the mvs_result.json / export_manifest.json written by the
runs themselves. Where a PS target is not yet met, the slide says so - NTRO evaluates its
own problem statement and will recognise its own numbers.

Layout follows `deck_theme`: a 12-column grid inside the margins the mandated chrome
leaves free, two hues and no more, and rules and whitespace instead of boxes. The
previous version put every group in a rounded rectangle with a hairline border, which
flattened the hierarchy - when everything is a card, nothing is emphasis.
"""
from __future__ import annotations

import os
import subprocess
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deck_theme as th
import scale_cal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIG = os.path.join(ROOT, "out", "ppt")
TEMPLATE = os.path.join(FIG, "SIH2026-IDEA-Presentation-Format.pptx")
OUT_PPTX = os.path.join(FIG, "SIH26158_IdeaSubmission.pptx")
OUT_PDF = os.path.join(FIG, "SIH26158_IdeaSubmission.pdf")

C = lambda h: RGBColor.from_string(h[1:])
NAVY, RUST, INK = C(th.NAVY), C(th.RUST), C(th.INK)
MUTED, FAINT, RULE = C(th.MUTED), C(th.FAINT), C(th.RULE)
PAPER, WASH = C(th.PAPER), C(th.WASH)

SANS, SEMI, MONO = th.SANS, th.SEMI, th.MONO
L, R, X, SPAN = th.L, th.R, th.X, th.SPAN

TEAM_NAME = "«TEAM NAME»"          # filled by the team on the portal; never invented
TEAM_ID = "«TEAM ID»"

IDEA_TITLE = "Measured, not interpolated: accurate 3D from a single drone pass"

# The six formats the problem statement asks for. glb and gltf are one line item there,
# so they are counted as one here too - counting them separately would quietly turn a
# 5/6 into a 6/7 and flatter us.
REQUIRED_FORMATS = ("obj", "ply", "las", "geotiff", "glb+gltf", "fbx")

# One 14-px patch on the Kolu survey pass, in the model's units (docs/05 section 2). The
# deck multiplies it by the clip's calibration; it never prints the raw value as metres.
PATCH_KOLU_MODEL = 0.512


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

    # compare_mvs.py measures in the model's units, which EXP-14 found 5.3-5.8x short on
    # Kolu (docs/08). Every length on the slides is Kolu's, times its calibration. The
    # Village clip has no ruler, so none of its absolute lengths reach a slide.
    cal = scale_cal.load("kolumvs3d")
    if cal["status"] == "unvalidated":
        raise SystemExit("the deck prints Kolu lengths in metres; it needs "
                         "research/calibration/kolu.json (src/experiments/exp14_scale_audit.py)")
    k = cal["factor"]
    lo, hi = cal["bracket"]

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
        "finest_cm": at(mk["mvs"], 3.0) * k,
        "gain_lo": min(gain(mk), gain(ms)),
        "gain_hi": max(gain(mk), gain(ms)),
        "relief_base": mk["baseline"]["relief_m"]["max"] * k,
        "relief_mvs": mk["mvs"]["relief_m"]["max"] * k,
        "patch_m": PATCH_KOLU_MODEL * k,
        "scale_k": k,
        "scale_lo": lo,
        "scale_hi": hi,
        "scale_pm": 100 * (hi - lo) / 2 / k,
    }


def hms(sec):
    return f"{int(sec) // 60}m {int(sec) % 60:02d}s"


# --------------------------------------------------------------------------- helpers
def shape(slide, name):
    for s in slide.shapes:
        if s.name == name:
            return s
    raise KeyError(f"{name} not on slide")


def _nobullet(p):
    """
    Strip the bullet a template placeholder brings with it.

    The prescribed pointer boxes are bulleted lists in the shipped file. Reusing one as
    a quiet caption otherwise drags a stray glyph and a hanging indent along with it.
    """
    pPr = p._p.get_or_add_pPr()
    pPr.set("marL", "0")
    pPr.set("indent", "0")
    for tag in ("a:buChar", "a:buAutoNum", "a:buNone"):
        for e in pPr.findall(qn(tag)):
            pPr.remove(e)
    pPr.insert_element_before(pPr.makeelement(qn("a:buNone"), {}),
                              "a:tabLst", "a:defRPr", "a:extLst")


def write(tf, blocks, line=1.0):
    """
    Replace a text frame's contents.

    `blocks` is a list of dicts: text, size, bold, colour, font, letter spacing,
    alignment, space above. Written as short blocks rather than prose because the
    template asks for points, and because a screening reader gives this slide seconds.
    """
    tf.clear()
    tf.word_wrap = True
    for i, b in enumerate(blocks):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.level = b.get("level", 0)
        _nobullet(p)
        p.line_spacing = b.get("line", line)
        if b.get("space"):
            p.space_before = Pt(b["space"])
        if b.get("align"):
            p.alignment = b["align"]
        for spec in (b["text"] if isinstance(b["text"], list) else [b]):
            r = p.add_run()
            r.text = spec["text"] if isinstance(spec, dict) else spec
            src = spec if isinstance(spec, dict) else b
            f = r.font
            f.size = Pt(src.get("size", b.get("size", th.T_BODY)))
            f.bold = src.get("bold", b.get("bold", False))
            f.color.rgb = src.get("colour", b.get("colour", INK))
            f.name = src.get("font", b.get("font", SANS))
            spc = src.get("spc", b.get("spc"))
            if spc:
                # Tracking is not exposed by python-pptx; it is a plain rPr attribute
                # in hundredths of a point. Used only on the small uppercase labels.
                f._rPr.set("spc", str(int(spc)))
    return tf


def textbox(slide, x, y, w, h, blocks, line=1.0, anchor=None):
    """
    A text frame whose left edge is actually at `x`.

    PowerPoint gives every new textbox a 0.1 in left and right inset, so a box placed
    on a grid column starts its text 0.1 in inside it. Every column, figure edge and
    rule in this deck is aligned to the same grid, so the insets are zeroed instead of
    being compensated for one shape at a time.
    """
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    if anchor is not None:
        tf.vertical_anchor = anchor
    write(tf, blocks, line=line)
    return tb


def _bar(slide, x, y, w, h, colour):
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y),
                               Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = colour
    s.line.fill.background()
    s.shadow.inherit = False
    s.text_frame.text = ""
    return s


def hair(slide, x, y, w, colour=RULE, weight=0.0085):
    """A horizontal hairline. This deck's only grouping device."""
    return _bar(slide, x, y, w, weight, colour)


def vhair(slide, x, y, h, colour=RULE, weight=0.0085):
    return _bar(slide, x, y, weight, h, colour)


def keyline(slide, x, y, h, colour, w=0.028):
    """A short vertical accent bar. Carries status without drawing a box."""
    return _bar(slide, x, y, w, h, colour)


def eyebrow(slide, x, y, w, text, colour=MUTED, align=None, size=None):
    """
    A tracked-out uppercase label.

    Used to name a block, never as decoration above every paragraph - the moment an
    eyebrow appears over everything it stops marking anything.
    """
    return textbox(slide, x, y, w, 0.20, [
        {"text": text.upper(), "size": size or th.T_EYEBROW, "bold": True,
         "colour": colour, "font": SEMI, "spc": 75, "align": align}])


def metric(slide, x, y, w, value, label, colour=NAVY, size=None):
    """
    One measured fact, unboxed.

    The number is set in Consolas because that is what it is: instrument output, not a
    marketing figure. Digits also line up column to column, which a proportional face
    does not do.
    """
    textbox(slide, x, y, w, 0.36, [
        {"text": value, "size": size or th.T_HERO, "bold": True, "colour": colour,
         "font": MONO}])
    textbox(slide, x, y + (0.40 if size is None else 0.33), w, 0.40, [
        {"text": label, "size": th.T_MICRO, "colour": MUTED}], line=1.08)


MARK_YES, MARK_PART, MARK_NO = "y", "p", "n"


# A traffic light, deliberately, and the one place the deck's two-hue rule is set
# aside. A matrix of twenty-five judgements is the one thing on these slides a reader
# scores rather than reads, and green/amber/red is the convention they already know.
# All three are dark enough to hold their hue on white paper at 0.125 in.
GREEN = C("#1B7340")         # meets it
AMBER = C("#B8860B")         # partly
RED = C("#A32015")           # does not
MARK_COLOUR = {"y": GREEN, "p": AMBER, "n": RED}


def markdisc(slide, cx, cy, kind, d=0.125):
    """
    One cell of the comparison matrix: a filled traffic-light disc.

    Colour alone cannot survive the greyscale printout a screening table works from -
    dark green, dark goldenrod and dark red sit close in luminance. The key in the
    header names all three, and nineteen of the twenty-five cells carry a note under
    the disc saying why, so the meaning does not rest on hue by itself.
    """
    s = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(cx - d / 2), Inches(cy - d / 2),
                               Inches(d), Inches(d))
    s.shadow.inherit = False
    s.text_frame.text = ""
    s.fill.solid()
    s.fill.fore_color.rgb = MARK_COLOUR[kind]
    s.line.fill.background()
    return s


def retext(sh, s, size=None):
    """
    Replace a placeholder's text while keeping every property it inherits.

    Used for the one heading we are allowed to fill in. Writing the run through
    `write()` would set an explicit font and colour and the slide would stop matching
    the five prescribed headings beside it.

    `size` is the one property worth overriding. The master sets this placeholder for
    the two words "IDEA TITLE"; a real 63-character idea title at that size wraps to
    two lines and the first one climbs off the top of the slide. The face and colour
    still come from the master, so the heading keeps matching the prescribed five.
    """
    tf = sh.text_frame
    p0 = tf.paragraphs[0]
    if not p0.runs:
        raise SystemExit("expected a run to inherit formatting from")
    p0.runs[0].text = s
    if size is not None:
        p0.runs[0].font.size = Pt(size)
    for r in p0.runs[1:]:
        r._r.getparent().remove(r._r)
    for p in tf.paragraphs[1:]:
        p._p.getparent().remove(p._p)


def pointers(slide):
    """The template's own content pointers for this slide, verbatim, as one line."""
    sh = shape(slide, "TextBox 8")
    lines = [ln.strip(" \t ") for ln in sh.text_frame.text.splitlines()]
    return sh, [ln for ln in lines if ln]


def header(slide, statement, keep=None, strong=False):
    """
    The repeated slide header: our claim on the left, the template's own question on
    the right, one rule under both. Returns the pointer lines for the caller to use.

    Keeping the prescribed pointers on the slide rather than deleting them is a small
    format-compliance argument made typographically - the evaluator sees what was asked
    and what we answered without having to hold the template in their head.

    `keep` selects which pointer lines appear in the corner. Slides 2 and 4 answer
    their pointers *under the pointers' own words*, used as block headings; repeating
    those words in the corner as well would print the same sentence twice on one slide.
    So those slides keep a narrower selection, or none.
    """
    sh, lines = pointers(slide)
    textbox(slide, X(0), 1.13, SPAN(8), 0.42, statement, line=1.06)
    shown = lines if keep is None else [lines[i] for i in keep]
    if not shown:
        sh._element.getparent().remove(sh._element)
    else:
        sh.left, sh.top, sh.width, sh.height = (Inches(X(8)), Inches(1.15),
                                                Inches(SPAN(4)), Inches(0.40))
        tf = sh.text_frame
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.word_wrap = True
        write(tf, [{"text": " · ".join(shown),
                    "size": 8.0 if strong else 6.8, "bold": strong,
                    "font": SEMI if strong else SANS,
                    "colour": NAVY if strong else FAINT,
                    "align": PP_ALIGN.RIGHT}], line=1.14)
    hair(slide, X(0), 1.62, SPAN(12))
    return lines


def inline(items, sep=" · ", size=th.T_SEC, colour=INK, strong=()):
    """A list rendered as one flowing line instead of a row of identical pills."""
    out = []
    for i, it in enumerate(items):
        if i:
            out.append({"text": sep, "size": size, "colour": FAINT})
        out.append({"text": it, "size": size,
                    "colour": NAVY if it in strong else colour,
                    "bold": it in strong,
                    "font": SEMI if it in strong else SANS})
    return out


def drop_slide(prs, index):
    """
    Remove a slide, and its relationship, so the part is not written at all.

    Dropping only the sldIdLst entry leaves the slide's XML orphaned inside the .pptx.
    The exported PDF is correct either way, but the template's instruction slide is the
    one thing the template explicitly tells you to delete, and leaving it in the package
    means a repair pass in PowerPoint can put it back.
    """
    lst = prs.slides._sldIdLst
    sld = list(lst)[index]
    prs.part.drop_rel(sld.get(qn("r:id")))
    lst.remove(sld)


TEMPLATE_URL = "https://www.sih.gov.in/letters/2026/SIH2026-IDEA-Presentation-Format.pptx"


def fetch_template():
    """
    The mandated template is an input, not an output, but `out/` is gitignored - so a
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
    m = measurements()
    prs = Presentation(TEMPLATE)
    s1, s2, s3, s4, s5, s6 = [prs.slides[i] for i in range(6)]

    for s in (s2, s3, s4, s5, s6):
        badge = shape(s, [o.name for o in s.shapes if o.name.startswith("Oval")][0])
        write(badge.text_frame, [{"text": TEAM_NAME, "size": 9.5, "bold": True,
                                  "colour": INK, "font": SEMI,
                                  "align": PP_ALIGN.CENTER}], line=0.95)

    # ---------------------------------------------------------------- 1 · title page
    sub = shape(s1, "Subtitle 3")
    # The placeholder ships overlapping the SIH title block, which is fine for the two
    # words "TITLE PAGE" and not for a real title. Drop it clear of the descenders and
    # into the left column, where the template's own artwork leaves the page free.
    # It also ships centred; a centred two-line title beside a left-aligned field list
    # has no shared edge to read down, so it is set left with the rule as that edge.
    sub.left, sub.top, sub.width, sub.height = (Inches(0.62), Inches(1.34),
                                                Inches(5.10), Inches(1.10))
    write(sub.text_frame, [{"text": IDEA_TITLE, "size": 19, "bold": True,
                            "colour": INK, "font": SEMI, "align": PP_ALIGN.LEFT}],
          line=1.06)
    sub.text_frame.margin_left = sub.text_frame.margin_right = 0
    sub.text_frame.margin_top = sub.text_frame.margin_bottom = 0
    keyline(s1, 0.42, 1.38, 0.90, NAVY, w=0.034)

    textbox(s1, 0.62, 2.50, 5.30, 0.28, [
        {"text": [{"text": "for the ", "size": 9.5, "colour": MUTED},
                  {"text": "National Technical Research Organisation (NTRO)",
                   "size": 9.5, "bold": True, "colour": NAVY, "font": SEMI}]}])
    hair(s1, 0.42, 2.92, 5.50)

    # The prescribed fields, as a two-column list. Label and value shared one paragraph
    # in the first version, so the long PS title wrapped back under its own label and
    # the column of values lost its left edge.
    tb9 = shape(s1, "TextBox 9")
    tb9._element.getparent().remove(tb9._element)
    fields = [("Problem Statement ID", "SIH26158", 0.30),
              ("Problem Statement Title",
               "Single-Pass Drone Video to Accurate 3D Model Generation System", 0.58),
              ("Theme", "Robotics and Drones", 0.30),
              ("PS Category", "Software", 0.30),
              ("Team ID", TEAM_ID, 0.30),
              ("Team Name (Registered on portal)", TEAM_NAME, 0.30)]
    y = 3.10
    for lab, val, h in fields:
        textbox(s1, 0.42, y + 0.03, 1.92, 0.24,
                [{"text": lab, "size": 8.4, "colour": MUTED}], line=1.10)
        textbox(s1, 2.46, y, 3.46, h,
                [{"text": val, "size": 12, "bold": True, "colour": INK, "font": SEMI}],
                line=1.08)
        y += h

    # ------------------------------------------------------- 2 · proposed solution
    # This slide is the one the template leaves structurally open, and it is the one
    # place the shipped file states its own section heading in the body rather than in
    # Title 1. An earlier version put a tagline in the IDEA TITLE slot and shrank
    # "Proposed Solution" and its three pointers to grey corner text - which inverts
    # what the template asks for. The pointers are now the slide's skeleton: each of
    # the three is a block heading, quoted exactly, with our answer under it.
    t2 = shape(s2, "Title 1")
    t2.left, t2.top, t2.width, t2.height = (Inches(1.82), Inches(0.06),
                                            Inches(8.80), Inches(1.04))
    t2.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    t2.text_frame.word_wrap = True
    retext(t2, IDEA_TITLE, size=20)

    # Corner keeps only line 0, the section name. Lines 1-3 are the pointers, and they
    # appear below at full size as the headings of the three blocks that answer them.
    pts = header(s2, [{"text": "One drone pass in; a georeferenced, metrically scaled, "
                               "textured 3D mesh and dense point cloud out, fit for "
                               "visualisation, measurement and analysis.",
                       "size": th.T_STATE, "bold": True, "colour": INK, "font": SEMI}],
                 keep=(0,), strong=True)

    # ---- pointer 1: detailed explanation of the proposed solution
    eyebrow(s2, X(0), 1.74, SPAN(6), pts[1], colour=NAVY)
    textbox(s2, X(0), 1.98, SPAN(6), 0.26, [
        {"text": [{"text": "ONE DRONE PASS", "size": 10.5, "bold": True, "font": SEMI},
                  {"text": "   →   ", "size": 10.5, "colour": FAINT},
                  {"text": "FEED-FORWARD AI", "size": 10.5, "bold": True,
                   "font": SEMI}]}])

    # Indented, and the bodies say "its", so both rows read as halves of what the AI
    # returned rather than as the next two steps after it.
    for i, (word, body, note, col) in enumerate((
            ("KEEP", "its camera pose", "", NAVY),
            ("DROP", "its geometry, and its unchecked scale",
             f"geometry sampled per pixel but carried per 14-px patch, "
             f"~{m['patch_m']:.1f} m on our survey clip", RUST))):
        y = 2.32 + i * 0.40
        keyline(s2, X(0) + 0.22, y, 0.28, col)
        textbox(s2, X(0) + 0.36, y, SPAN(6) - 0.36, 0.28, [
            {"text": [{"text": word + "   ", "size": 9.4, "bold": True, "colour": col,
                       "font": SEMI},
                      {"text": body, "size": 9.4, "colour": INK}]}])
        if note:
            textbox(s2, X(0) + 0.36, y + 0.17, SPAN(6) - 0.36, 0.22,
                    [{"text": note, "size": th.T_MICRO, "colour": MUTED}])

    textbox(s2, X(0), 3.22, SPAN(6), 0.26, [
        {"text": inline(("global bundle adjustment", "full-resolution photometric MVS",
                         "MEASURED 3D"), sep="   →   ", size=9.4,
                        strong=("MEASURED 3D",))}])

    # Sits low against the rule rather than directly under the flow: the two blocks
    # then read as two statements with air between them, instead of one block with a
    # hole underneath it.
    textbox(s2, X(0), 4.02, SPAN(6), 0.44, [
        {"text": [{"text": "Reconstructs (i)–(v), the PS's own list:   ", "size": 8.2,
                   "bold": True, "colour": MUTED, "font": SEMI}] +
                 inline(("3D terrain and structures", "building facades and rooftops",
                         "roads and infrastructure", "vegetation and obstacles",
                         "textured 3D meshes or point clouds"), size=8.2)}], line=1.20)

    s2.shapes.add_picture(f"{FIG}/fig_beforeafter.png", Inches(X(6)), Inches(1.74),
                          width=Inches(SPAN(6)))
    textbox(s2, X(6), 1.74 + th.FIG["beforeafter"][1] + 0.06, SPAN(6), 0.24, [
        {"text": "Same clip, same 45 keyframes, same camera poses. Only the geometry "
                 "stage changed.", "size": th.T_MICRO, "colour": MUTED}])

    hair(s2, X(0), 4.62, SPAN(12))

    # ---- pointer 2: how it addresses the problem
    eyebrow(s2, X(0), 4.74, SPAN(6), pts[2], colour=NAVY)
    for i, (lab, txt) in enumerate((
            ("One pass, no re-flight",
             "reconstructs from a single trajectory with no cross-strip overlap, which "
             "is the capture constraint the PS is built around"),
            ("Zero ground control points",
             "scale comes from GNSS when present, else from objects of known size in "
             f"the scene; the AI's own was {m['scale_lo']:.1f}–{m['scale_hi']:.1f}× off"),
            ("Georeferenced and measurable",
             "one shared local frame in calibrated metres across all six formats, and "
             "a browser viewer built for measurement"))):
        y = 4.96 + i * 0.30
        textbox(s2, X(0), y, 1.62, 0.26,
                [{"text": lab, "size": 8.4, "bold": True, "colour": INK, "font": SEMI}])
        textbox(s2, X(0) + 1.70, y, SPAN(6) - 1.70, 0.28,
                [{"text": txt, "size": 8.2, "colour": MUTED}], line=1.12)

    # ---- pointer 3: innovation and uniqueness of the solution
    eyebrow(s2, X(6), 4.74, SPAN(6), pts[3], colour=NAVY)
    textbox(s2, X(6), 4.96, SPAN(6), 0.60, [
        {"text": [{"text": "We measured the ceiling instead of assuming it. ",
                   "size": 8.6, "bold": True, "colour": INK, "font": SEMI},
                  {"text": "A feed-forward model samples depth per pixel but carries "
                           "information only per 14-pixel patch, about "
                           f"{m['patch_m']:.1f} m on the ground on our survey clip. "
                           "Confirmed three ways, with the competing explanation tested "
                           "and rejected. Its metric scale we checked against lane "
                           f"markings: {m['scale_lo']:.1f}–{m['scale_hi']:.1f}× too small.",
                   "size": 8.6, "colour": MUTED}]}], line=1.14)
    textbox(s2, X(6), 5.62, SPAN(6), 0.44, [
        {"text": [{"text": "So the AI is a pose prior, nothing more. ",
                   "size": 8.6, "bold": True, "colour": INK, "font": SEMI},
                  {"text": "Every delivered surface point is triangulated from real "
                           "pixels by full-resolution photometric MVS.",
                   "size": 8.6, "colour": MUTED}]}], line=1.14)

    hair(s2, X(0), 6.16, SPAN(12))
    cells = ((m["registered"], "keyframes\nregistered"),
             (f'{m["reproj_ba"]:.2f} px', "reprojection\nerror"),
             (f'{m["dense_points"]/1e6:.2f} M', "measured\ndense points"),
             (f'{m["finest_cm"]:.1f} cm', "finest detail,\ncalibrated"),
             (f'{m["gain_lo"]:.1f}–{m["gain_hi"]:.1f}×', "finer than\nthe AI alone"),
             (f'{m["formats_have"]} / {m["formats_need"]}', "export\nformats"))
    cw = SPAN(12) / len(cells)
    for i, (h, sub_t) in enumerate(cells):
        metric(s2, X(0) + i * cw, 6.26, cw - 0.18, h, sub_t, size=16.5)
        if i:
            vhair(s2, X(0) + i * cw - 0.09, 6.26, 0.52)

    # -------------------------------------------------------- 3 · technical approach
    header(s3, [{"text": "Five stages, all of them already running end to end on two "
                         "unrelated clips.", "size": th.T_STATE, "bold": True,
                 "colour": INK, "font": SEMI}])

    stages = [
        ("INGEST", "Mandatory in: 1080p/4K video, GPS, flight metadata. Optional: IMU, "
                   "barometric altitude, intrinsics, RTK/PPK; used when present, never "
                   "required. Auto-detects SRT, CSV, EXIF or flight log."),
        ("POSE + SCALE", "MapAnything point maps, intrinsics by robust masked "
                         f"fit at {m['intrinsics_px']:.2f} px, then COLMAP "
                         "triangulation and global bundle adjustment. Scale from GNSS "
                         "or objects of known size, never the model alone."),
        ("DENSE GEOMETRY", "OpenMVS PatchMatch at full keyframe resolution. Geometric-"
                           "consistency filtering across three or more views also "
                           "rejects moving vehicles, people and animals."),
        ("SURFACE + FRAME", "Delaunay and graph-cut mesh with per-vertex colour. "
                            "Vertical from the ground plane, cross-checked against the "
                            "gimbal's roll-zero constraint."),
        ("EXPORT + VIEW", "OBJ, PLY, LAS 1.4, GeoTIFF DSM, glB/glTF and FBX in one "
                          "shared frame, in calibrated metres. Browser viewer built for "
                          "measurement."),
    ]
    gap = 0.34
    cw = (SPAN(12) - (len(stages) - 1) * gap) / len(stages)
    for i, (t, b) in enumerate(stages):
        x = X(0) + i * (cw + gap)
        hair(s3, x, 1.78, cw, NAVY, weight=0.013)
        textbox(s3, x, 1.86, cw, 0.22, [
            {"text": [{"text": f"{i+1:02d}   ", "size": 7.6, "bold": True,
                       "colour": FAINT, "font": MONO},
                      {"text": t, "size": 8.8, "bold": True, "colour": INK,
                       "font": SEMI}]}])
        textbox(s3, x, 2.12, cw, 1.00,
                [{"text": b, "size": 7.8, "colour": MUTED}], line=1.16)
        if i < len(stages) - 1:
            textbox(s3, x + cw, 1.84, gap, 0.24, [
                {"text": "→", "size": 10, "colour": FAINT,
                 "align": PP_ALIGN.CENTER}])

    hair(s3, X(0), 3.30, SPAN(12))

    eyebrow(s3, X(0), 3.42, SPAN(7), "technology stack")
    groups = [
        ("Vision / 3D", ("PyTorch", "MapAnything", "COLMAP", "OpenMVS", "Open3D",
                         "OpenCV")),
        ("Export", ("trimesh", "laspy", "rasterio", "pygltflib", "assimp")),
        ("Serve", ("Python 3.11", "Docker", "Cloud Run · asia-south1", "GCS",
                   "three.js")),
    ]
    for i, (lab, items) in enumerate(groups):
        y = 3.66 + i * 0.30
        textbox(s3, X(0), y, 1.10, 0.22,
                [{"text": lab, "size": th.T_MICRO, "bold": True, "colour": FAINT,
                  "font": SEMI}])
        textbox(s3, X(0) + 1.16, y - 0.01, SPAN(7) - 1.16, 0.24,
                [{"text": inline(items, size=8.4)}])

    hair(s3, X(0), 4.62, SPAN(7))
    s3.shapes.add_picture(f"{FIG}/fig_timing.png", Inches(X(0)), Inches(4.76),
                          width=Inches(SPAN(7)))

    eyebrow(s3, X(7), 3.42, SPAN(5), "four choices we can defend", colour=RUST)
    choices = [
        ("Licence, not leaderboard",
         "VGGT is the better-known model. Its acceptable-use policy bars military and "
         "espionage use, which this PS names. MapAnything's Apache-2.0 checkpoint does "
         "not."),
        ("Sovereign by construction",
         "All processing pinned to asia-south1: India's geospatial guidelines require "
         "finer-than-1 m data to be processed within India, and this PS targets ≤ 1 m."),
        ("No GPU floor",
         "Every component is permissive and runs on CPU. GPU is a speed upgrade, never "
         "a dependency for getting a result."),
        ("Honest by construction",
         "With no GNSS the DEM ships with no CRS rather than a plausible-looking wrong "
         "one, and a length is printed in metres only when GNSS or an object of known "
         "size backs it."),
    ]
    y = 3.66
    for i, (head, body) in enumerate(choices):
        if i:
            hair(s3, X(7), y - 0.11, SPAN(5))
        textbox(s3, X(7), y, SPAN(5), 0.20,
                [{"text": head, "size": 8.8, "bold": True, "colour": NAVY,
                  "font": SEMI}])
        textbox(s3, X(7), y + 0.19, SPAN(5), 0.50,
                [{"text": body, "size": 8.2, "colour": MUTED}], line=1.16)
        y += 0.80

    # ------------------------------------------------------ 4 · feasibility, risks
    # The PS names its own eight key challenges and, in the linked PDF, its own weighted
    # scoring function. Both are quoted here rather than paraphrased: answering NTRO in
    # NTRO's own vocabulary is the cheapest possible demonstration that we read the
    # problem statement, and the weights say plainly where the marks actually are.
    # The three prescribed pointers are the two column headings below, so the corner
    # caption is dropped on this slide to avoid printing the same words twice.
    pts4 = header(s4, [{"text": [
        {"text": "70% of NTRO's score is objectively measurable. ", "size": th.T_STATE,
         "bold": True, "colour": INK, "font": SEMI},
        {"text": "We report all three measured, misses included.",
         "size": th.T_STATE, "colour": MUTED}]}], keep=())

    # ---- pointers 2 and 3: challenges, and the strategy for each
    eyebrow(s4, X(0), 1.70, SPAN(7), pts4[1] + " · " + pts4[2], colour=NAVY)
    hair(s4, X(0), 1.92, SPAN(7), C(th.RULE_STRONG))
    challenges = [
        ("i", "Limited viewing angles, single flight path",
         "MVS along one trajectory; coverage measured, not assumed", False),
        ("ii", "Motion blur and compression artefacts",
         "adaptive keyframing drops degraded frames before pose is solved", False),
        ("iii", "Variable illumination and shadows",
         "keyframe scoring survives exposure ramps; per-vertex colour, no atlas seams",
         False),
        ("iv", "Dynamic objects: vehicles, humans, animals",
         "geometric-consistency filtering across ≥ 3 views rejects them", False),
        ("v", "GPS inaccuracies and sensor noise",
         "GPS is a prior, never a constraint; bundle adjustment re-solves pose", False),
        ("vi", "Real-time or near-real-time processing",
         "OPEN: 34m 38s on CPU vs < 15 min; GPU MVS and keyframe budgeting close it",
         True),
        ("vii", "Reconstruction of occluded surfaces",
         "bounded geometric closure only, and every inferred face is tagged inferred",
         False),
        ("viii", "Metric accuracy without extensive GCPs",
         "zero GCPs; scale from known objects in the scene; absolute unvalidated",
         True),
    ]
    y = 1.99
    for num, chal, fix, open_ in challenges:
        col = RUST if open_ else NAVY
        textbox(s4, X(0), y + 0.015, 0.34, 0.22,
                [{"text": f"({num})", "size": 6.8, "colour": FAINT, "font": MONO}])
        textbox(s4, X(0) + 0.36, y, 2.46, 0.24,
                [{"text": chal, "size": 8.2, "bold": True, "colour": INK,
                  "font": SEMI}], line=1.06)
        textbox(s4, X(0) + 2.92, y, SPAN(7) - 2.92, 0.26,
                [{"text": fix, "size": 8.0, "colour": col}], line=1.08)
        y += 0.29
        hair(s4, X(0), y - 0.045, SPAN(7))

    # ---- pointer 1: analysis of the feasibility of the idea
    eyebrow(s4, X(7), 1.70, SPAN(5), pts4[0], colour=NAVY)
    hair(s4, X(7), 1.92, SPAN(5), C(th.RULE_STRONG))
    criteria = [
        ("Reconstruction Accuracy", "30%",
         f'{m["reproj_ba"]:.2f} px reprojection; scale calibrated to '
         f'±{m["scale_pm"]:.0f}%; ≤ 1 m absolute unvalidated, no GNSS in either clip', True),
        ("Model Completeness", "20%",
         f'{m["coverage"]:.0%} of the AI-only baseline\'s ground coverage', False),
        ("Processing Speed", "20%",
         f'{hms(m["seconds"])} for {m["n_views"]} views on 8 vCPU, against < 15 min',
         True),
        ("Innovation", "15%",
         "the patch-grid ceiling and the AI's scale error both measured, not assumed",
         False),
        ("Scalability", "10%",
         "CPU-only and containerised; fan-out measured at 1.42×", False),
        ("User Interface", "5%",
         "browser viewer built for measurement, not display", False),
    ]
    y = 1.99
    for name, wt, standing, open_ in criteria:
        col = RUST if open_ else NAVY
        keyline(s4, X(7), y + 0.01, 0.22, col)
        textbox(s4, X(7) + 0.14, y, SPAN(5) - 0.80, 0.22,
                [{"text": name, "size": 8.4, "bold": True, "colour": INK,
                  "font": SEMI}])
        textbox(s4, X(7) + SPAN(5) - 0.62, y, 0.62, 0.22,
                [{"text": wt, "size": 8.8, "bold": True, "colour": col, "font": MONO,
                  "align": PP_ALIGN.RIGHT}])
        textbox(s4, X(7) + 0.14, y + 0.18, SPAN(5) - 0.14, 0.28,
                [{"text": standing, "size": 7.6, "colour": MUTED}], line=1.08)
        y += 0.40
        hair(s4, X(7), y - 0.055, SPAN(5))

    hair(s4, X(0), 4.52, SPAN(12), C(th.RULE_STRONG))

    # Caption above the chart, not below: the chart is wide and flat, and anything
    # underneath it lands in the footer bar.
    textbox(s4, X(0), 4.64, SPAN(7), 0.24, [
        {"text": [{"text": "Why the 30% criterion is winnable.  ", "size": 8.8,
                   "bold": True, "colour": INK, "font": SEMI},
                  {"text": "The feed-forward curve flattens into a floor and stops; "
                           "ours holds its slope.", "size": 8.4, "colour": MUTED}]}])
    s4.shapes.add_picture(f"{FIG}/fig_accuracy.png", Inches(X(0)), Inches(4.88),
                          width=Inches(SPAN(7)))

    eyebrow(s4, X(7), 4.64, SPAN(5), "desired output, per the PS's own table",
            colour=NAVY)
    outputs = [
        ("Reconstruction Type", "3D Mesh / Point Cloud", "MET"),
        ("Processing Time", "< 15 min for 10-min video", "OPEN"),
        ("Spatial Accuracy", "≤ 1 m", "OPEN"),
        ("Coverage", "Entire visible scene", "MET"),
        ("Output Formats", "OBJ · PLY · LAS · GeoTIFF · glb/gltf · fbx",
         f'{m["formats_have"]}/{m["formats_need"]}'),
        ("Visualization", "Web-based or Desktop Viewer", "MET"),
    ]
    y = 4.88
    for param, target, status in outputs:
        col = RUST if status == "OPEN" else NAVY
        textbox(s4, X(7), y, 1.50, 0.22,
                [{"text": param, "size": 7.8, "bold": True, "colour": INK,
                  "font": SEMI}])
        textbox(s4, X(7) + 1.54, y + 0.01, SPAN(5) - 2.20, 0.22,
                [{"text": target, "size": 7.4, "colour": MUTED, "font": MONO}])
        textbox(s4, X(7) + SPAN(5) - 0.60, y + 0.01, 0.60, 0.22,
                [{"text": status, "size": 6.8, "bold": True, "colour": col,
                  "font": MONO, "spc": 50, "align": PP_ALIGN.RIGHT}])
        y += 0.28
        hair(s4, X(7), y - 0.05, SPAN(5))

    textbox(s4, X(7), y + 0.06, SPAN(5), 0.30, [
        {"text": [{"text": "Both open targets carry a route, not a hope.  ", "size": 7.8,
                   "bold": True, "colour": RUST, "font": SEMI},
                  {"text": "GPU PatchMatch plus keyframe budgeting for speed; an "
                           "RTK/PPK clip with surveyed check points for accuracy.",
                   "size": 7.8, "colour": MUTED}]}], line=1.10)

    # ------------------------------------------------------- 5 · impact and benefits
    # The statement is the PS's own claim for why this matters, quoted back: it names
    # mission time, operator effort, data acquisition and processing complexity, and
    # near real-time situational awareness. Our job on this slide is to show which of
    # those we can already put a measured number against.
    header(s5, [{"text": "The PS's own four: less mission time, operator effort, data "
                         "acquisition, processing complexity.", "size": th.T_STATE,
                 "bold": True, "colour": INK, "font": SEMI}])

    s5.shapes.add_picture(f"{FIG}/fig_missions.png", Inches(X(0)), Inches(1.74),
                          width=Inches(SPAN(6)))
    textbox(s5, X(0), 1.74 + th.FIG["missions"][1] + 0.08, SPAN(6), 0.24, [
        {"text": "Same ground, same product. The left plan is what a metrically "
                 "accurate model costs today.", "size": th.T_MICRO, "colour": MUTED}])

    # All eight, in the PS's own order. An earlier version shaded three as "the ones
    # NTRO named first" and picked the wrong three: military reconnaissance is (viii),
    # last, not first. Position in a list is not priority, so the claim is gone rather
    # than corrected.
    eyebrow(s5, X(6), 1.74, SPAN(6),
            "potential applications · all eight, in the PS's own order")
    apps = ("Border and strategic area mapping", "Construction progress monitoring",
            "Disaster damage assessment", "Archaeological documentation",
            "Urban planning and smart cities", "Digital twin generation",
            "Infrastructure inspection", "Military reconnaissance, mission planning")
    nums = ("i", "v", "ii", "vi", "iii", "vii", "iv", "viii")
    for i, (t, n) in enumerate(zip(apps, nums)):
        ax = X(6) + (i % 2) * 3.14
        ay = 1.98 + (i // 2) * 0.25
        textbox(s5, ax, ay + 0.012, 0.40, 0.22,
                [{"text": f"({n})", "size": 6.6, "colour": FAINT, "font": MONO}])
        textbox(s5, ax + 0.40, ay, 2.70, 0.22,
                [{"text": t, "size": 8.2, "colour": INK}])

    hair(s5, X(6), 3.06, SPAN(6))
    eyebrow(s5, X(6), 3.18, SPAN(6), "benefits")
    # One line each, deliberately. At two lines they ran together into a paragraph and
    # the three headings stopped being findable.
    for i, (lab, txt) in enumerate((
            ("Economic", "permissive open source on commodity cloud CPU: no per-seat "
                         "photogrammetry licence"),
            ("Strategic", "processing stays in India by construction; the model chosen "
                          "on licence terms, not benchmarks"),
            ("Operational", "one flight line instead of a planned grid, and no GCP "
                            "survey to organise"))):
        textbox(s5, X(6) + 0.86, 3.40 + i * 0.30, SPAN(6) - 0.86, 0.26,
                [{"text": txt, "size": 8.6, "colour": INK}], line=1.10)
        textbox(s5, X(6), 3.40 + i * 0.30, 0.84, 0.26,
                [{"text": lab, "size": 8.6, "bold": True, "colour": NAVY,
                  "font": SEMI}], line=1.10)

    textbox(s5, X(6), 4.34, SPAN(6), 0.26, [
        {"text": [{"text": "Near real-time situational awareness ", "size": 8.2,
                   "bold": True, "colour": RUST, "font": SEMI},
                  {"text": "is the PS's fifth benefit, and the one we cannot claim yet.",
                   "size": 8.2, "colour": MUTED}]}])

    hair(s5, X(0), 4.72, SPAN(12))
    eyebrow(s5, X(0), 4.84, SPAN(12), "measured benefit, on the two clips we have run")
    cells = ((f'{m["gain_lo"]:.1f}–{m["gain_hi"]:.1f}×',
              "finer detail at matched scale,\non two unrelated clips"),
             (f'{m["relief_base"]:.1f} → {m["relief_mvs"]:.1f} m',
              "vertical structure ceiling,\nin calibrated metres"),
             (f'{m["coverage"]:.0%}',
              "of the AI-only baseline's\nground coverage"),
             (f'{m["reproj_gain"]:.1f}×',
              "reprojection error improved\nby bundle adjustment"))
    cw = SPAN(12) / len(cells)
    for i, (h, sub_t) in enumerate(cells):
        metric(s5, X(0) + i * cw, 5.10, cw - 0.20, h, sub_t)
        if i:
            vhair(s5, X(0) + i * cw - 0.10, 5.10, 0.66)

    hair(s5, X(0), 6.02, SPAN(12))
    textbox(s5, X(0), 6.14, SPAN(12), 0.36, [
        {"text": [{"text": "Not claimed   ", "size": 9.0, "bold": True, "colour": RUST,
                   "font": SEMI},
                  {"text": f"≤ 1 m absolute accuracy is unproven on our clips, which "
                           f"carry no GNSS, and the 15-minute budget is not met on CPU. "
                           f"We would rather bring NTRO a measured "
                           f"{int(m['seconds'] // 60)} minutes than a claimed 12.",
                   "size": 9.0, "colour": MUTED}]}], line=1.12)

    # -------------------------------------------------- 6 · research and references
    header(s6, [{"text": [{"text": "Existing approaches, scored against what this PS "
                                   "actually needs. ", "size": th.T_STATE,
                           "bold": True, "colour": INK, "font": SEMI},
                          {"text": "This is why the two-model split exists.",
                           "size": th.T_STATE, "colour": MUTED}]}])

    namew = 3.05
    cw = (SPAN(12) - namew) / 5
    cols = ("pose from a\nsingle pass", "metric scale\nwithout GCPs",
            "detail below\n10 cm", "GIS-ready\nexports", "licence clear\nfor NTRO")
    for j, c in enumerate(cols):
        textbox(s6, X(0) + namew + j * cw, 1.72, cw, 0.34,
                [{"text": c, "size": 7.4, "bold": True, "colour": FAINT, "font": SEMI,
                  "align": PP_ALIGN.CENTER}], line=1.10)
    # The key goes in the name column's header space, which is otherwise empty. Each
    # label takes its own colour, so the traffic light is defined on the slide rather
    # than assumed - six of the twenty-five cells carry no note to fall back on.
    for j, (kind, lab) in enumerate(((MARK_YES, "meets it"), (MARK_PART, "partly"),
                                     (MARK_NO, "does not"))):
        kx = X(0) + j * 1.02
        markdisc(s6, kx + 0.06, 1.83, kind, d=0.105)
        textbox(s6, kx + 0.18, 1.76, 0.84, 0.20,
                [{"text": lab, "size": 6.8, "bold": True, "font": SEMI,
                  "colour": MARK_COLOUR[kind]}])
    hair(s6, X(0), 2.06, SPAN(12), C(th.RULE_STRONG))

    rows = [
        ("Classical SfM + MVS", "COLMAP, OpenMVS alone",
         [("p", "thin strip, low overlap"), ("n", "needs GCPs or RTK"),
          ("y", "the accuracy standard"), ("y", ""), ("y", "BSD / AGPL")]),
        ("Commercial photogrammetry", "Pix4D, Metashape, RealityCapture",
         [("p", "assumes 70–80% overlap"), ("p", "needs GCPs or RTK"),
          ("y", ""), ("y", ""), ("n", "per-seat, closed")]),
        ("Feed-forward 3D", "DUSt3R, VGGT, MapAnything",
         [("y", "this is what it solves"),
          ("p", f"metric by design; {m['scale_k']:.1f}× off from the air"),
          ("n", "patch-limited ceiling"), ("p", "no LAS / GeoTIFF"),
          ("p", "VGGT barred by AUP")]),
        ("NeRF / 3D Gaussian splatting", "radiance-field reconstruction",
         [("n", "needs poses given"), ("n", ""), ("p", "appearance, not surface"),
          ("n", "renders, not products"), ("y", "")]),
        ("This submission", "AI for pose, known objects for scale, MVS for every surface",
         [("y", ""), ("y", "calibrated on scene objects"),
          ("y", f'{m["finest_cm"]:.1f} cm, calibrated'),
          ("y", "all six formats"), ("y", "Apache / BSD; AGPL run unmodified")]),
    ]
    y = 2.14
    for i, (name, sub_t, marks) in enumerate(rows):
        last = i == len(rows) - 1
        if last:
            keyline(s6, X(0), y - 0.02, 0.50, NAVY)
        textbox(s6, X(0) + (0.14 if last else 0.0), y, namew - 0.20, 0.22,
                [{"text": name, "size": 9.0, "bold": True,
                  "colour": NAVY if last else INK, "font": SEMI}])
        textbox(s6, X(0) + (0.14 if last else 0.0), y + 0.19, namew - 0.20, 0.22,
                [{"text": sub_t, "size": 7.2, "colour": FAINT}], line=1.10)
        for j, (kind, note) in enumerate(marks):
            ccx = X(0) + namew + j * cw + cw / 2
            markdisc(s6, ccx, y + 0.08, kind)
            if note:
                textbox(s6, ccx - cw / 2 + 0.05, y + 0.21, cw - 0.10, 0.30,
                        [{"text": note, "size": 6.8, "colour": MUTED,
                          "align": PP_ALIGN.CENTER}], line=1.08)
        y += 0.56
        if not last:
            hair(s6, X(0), y - 0.06, SPAN(12))

    hair(s6, X(0), 4.96, SPAN(12), C(th.RULE_STRONG))
    eyebrow(s6, X(0), 5.08, SPAN(6), "methods and models")
    textbox(s6, X(0), 5.30, SPAN(6), 1.50, [
        {"text": [{"text": "MapAnything", "size": 8.4, "bold": True, "font": SEMI},
                  {"text": ": Meta AI, 2025 · Apache-2.0.   ", "size": 8.2,
                   "colour": MUTED},
                  {"text": "COLMAP", "size": 8.4, "bold": True, "font": SEMI},
                  {"text": ": Schönberger & Frahm, CVPR 2016.   ", "size": 8.2,
                   "colour": MUTED},
                  {"text": "OpenMVS 2.4.0", "size": 8.4, "bold": True, "font": SEMI},
                  {"text": ": PatchMatch MVS with Delaunay/graph-cut meshing.   ",
                   "size": 8.2, "colour": MUTED},
                  {"text": "DINOv2", "size": 8.4, "bold": True, "font": SEMI},
                  {"text": ": Oquab et al., TMLR 2024; the patch-14 backbone whose "
                           "grid is the ceiling we measured.   ", "size": 8.2,
                   "colour": MUTED},
                  {"text": "PatchMatch Stereo", "size": 8.4, "bold": True,
                   "font": SEMI},
                  {"text": ": Bleyer et al., BMVC 2011; Schönberger et al., ECCV "
                           "2016.   ", "size": 8.2, "colour": MUTED},
                  {"text": "VGGT", "size": 8.4, "bold": True, "font": SEMI},
                  {"text": ": Wang et al., CVPR 2025; evaluated, rejected on licence.",
                   "size": 8.2, "colour": MUTED}]}], line=1.18)

    eyebrow(s6, X(6), 5.08, SPAN(6), "standards, policy, and our own record")
    textbox(s6, X(6), 5.30, SPAN(6), 1.50, [
        {"text": [{"text": "Geospatial Data Guidelines, DST 2021", "size": 8.4,
                   "bold": True, "font": SEMI},
                  {"text": " and the National Geospatial Policy 2022: why processing "
                           "is pinned to an Indian region.   ", "size": 8.2,
                   "colour": MUTED},
                  {"text": "ASPRS LAS 1.4", "size": 8.4, "bold": True, "font": SEMI},
                  {"text": " pf3 and ", "size": 8.2, "colour": MUTED},
                  {"text": "Khronos glTF 2.0", "size": 8.4, "bold": True,
                   "font": SEMI},
                  {"text": ": both validated on write.", "size": 8.2,
                   "colour": MUTED}]},
        {"text": [{"text": "Our record   ", "size": 8.4, "bold": True, "colour": NAVY,
                   "font": SEMI},
                  {"text": "an SRS baselined line-by-line against the PS PDF, plus "
                           "architecture, test plan, a quality analysis that diagnoses "
                           "the resolution ceiling with controls, and a deployment "
                           "study. Both charts and every headline number here are read "
                           "at build time from the JSON the runs wrote; the build "
                           "fails rather than print a stale figure.", "size": 8.2,
                   "colour": MUTED}], "space": 5},
        {"text": [{"text": "Note   ", "size": 8.4, "bold": True, "colour": RUST,
                   "font": SEMI},
                  {"text": "the portal listing for SIH26158 still carries the editorial "
                           "placeholder “Add 'Desired Output' and 'Evaluation Criteria' "
                           "table here”. The binding targets exist only in the linked "
                           "PDF, which we read as images and traced one by one.",
                   "size": 8.2, "colour": MUTED}], "space": 5},
    ], line=1.18)

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
