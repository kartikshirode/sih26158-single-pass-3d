# -*- coding: utf-8 -*-
"""Audit the BUILT demo pages against the design system. Exits 1 on a violation.

A design system that is only a file is a suggestion. This is what makes it a
constraint: it re-reads the shipped HTML and fails the build if a page has
reintroduced an off-scale font size, an unruled padding, a third corner radius,
a colour that is not a token, or a text/background pair below WCAG AA.

Run after the three builders:

    python tools/check_design.py

The "before" column is the audit taken on 2026-09-12, before the system existed.
It is kept here so the reduction is visible rather than asserted.
"""

from __future__ import print_function

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PAGES = [
    ("demo/index.html", os.path.join(ROOT, "demo", "index.html")),
    ("demo/gallery/index.html", os.path.join(ROOT, "demo", "gallery", "index.html")),
    ("demo/qa/index.html", os.path.join(ROOT, "demo", "qa", "index.html")),
]

# The scales, mirrored from design_system.css. If you add a step there, add it
# here and the diff shows up in review as a deliberate widening of the system.
FONT_SIZES = {"11px", "12.5px", "14px", "16px", "19px", "23px", "28px"}
SPACING = {"2px", "4px", "6px", "8px", "12px", "16px", "22px", "32px", "48px"}
RADII = {"3px", "6px", "0"}  # --r-sm, --r-md, and an explicit reset. Nothing else:
                             # a stale exemption here is how the two-value shape
                             # lock quietly loosens again.
TOKEN_HEX = {
    "#06080a", "#151b21", "#202830",
    "#e7ecef", "#b6c1c8", "#909ba3",
    "#252e36", "#36424b",
    "#e8a84a", "#f0b75f", "#57c2a9", "#e0705a",
}

# Measured by THIS script on the pre-rebuild pages (2026-09-12). Taken with the
# same ruler as the "after" column, so the reduction is a real comparison and
# not two different counting methods put side by side.
BEFORE = {"font": 18, "pad": 28, "radius": 4, "hex": 6}

# Values allowed outside the scales, each for a stated structural reason.
PAD_EXEMPT = {
    "0", "0px",           # explicit reset
    "1px",                # hairline borders expressed as padding in insets
    "100%", "50%", "auto",
}


def style_of(html):
    """Every <style> block on the page, concatenated."""
    return "\n".join(re.findall(r"<style>(.*?)</style>", html, re.S))


def root_block(css):
    m = re.search(r":root\{(.*?)\}", css, re.S)
    return m.group(1) if m else ""


def audit(name, path):
    if not os.path.exists(path):
        return None
    with io.open(path, encoding="utf-8") as f:
        html = f.read()
    css = style_of(html)
    root = root_block(css)
    body = css.replace(root, "")  # everything that is not a token declaration

    # The Q&A page prints to WHITE PAPER, so its @media print block is the one
    # place the dark screen tokens are the wrong answer. It is exempt from the
    # colour and scale audit by design, not by oversight - and only it.
    html = re.sub(r"@media print\{.*?\}\s*\}", "", html, flags=re.S)
    body = re.sub(r"@media print\{.*?\}\s*\}", "", body, flags=re.S)

    fonts = set(re.findall(r"font-size:\s*([\d.]+px)", body))
    fonts |= set(re.findall(r"font:[^;{}]*?\s([\d.]+px)\s*/", body))

    pads = set()
    for prop in ("padding", "margin", "gap"):
        for decl in re.findall(r"(?<![-\w])%s(?:-[a-z]+)?:\s*([^;{}]+)" % prop, body):
            for v in decl.split():
                v = v.strip()
                if v.startswith("var(") or v in PAD_EXEMPT or "calc(" in v:
                    continue
                if re.match(r"^[\d.]+px$", v):
                    pads.add(v)

    radii = set()
    for decl in re.findall(r"border-radius:\s*([^;{}]+)", body):
        for v in decl.split():
            v = v.strip()
            if v.startswith("var(") or v == "0":
                continue
            if re.match(r"^[\d.]+px$", v):
                radii.add(v)

    # Whole file, not just <style>: colours also hide in JS-built SVG strings
    # (fill="#e3a13c" in the measurement overlay) and in <meta theme-color>, and
    # a style-only audit silently passes those. :root declarations are the only
    # exemption, because that is where a token is allowed to name a hex.
    hexes = set(h.lower() for h in re.findall(r"#[0-9a-fA-F]{6}\b",
                                              html.replace(root, "")))

    return {
        "name": name,
        "bytes": len(html),
        "css_bytes": len(css),
        "font": sorted(fonts), "pad": sorted(pads),
        "radius": sorted(radii), "hex": sorted(hexes),
    }


# ---- WCAG ------------------------------------------------------------------

def _lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def lum(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


SURFACES = [("bg", "#06080a"), ("s1", "#151b21"), ("s2", "#202830")]
TEXTS = [("fg", "#e7ecef"), ("fg-2", "#b6c1c8"), ("fg-3", "#909ba3"),
         ("accent", "#e8a84a"), ("ok", "#57c2a9"), ("bad", "#e0705a")]


def contrast_report():
    fails = []
    print("  text on surface (AA body needs 4.5)")
    print("    %-8s %-9s %7s %7s %7s" % ("token", "hex", "on bg", "on s1", "on s2"))
    for tn, tv in TEXTS:
        rs = [ratio(tv, sv) for _, sv in SURFACES]
        worst = min(rs)
        flag = "" if worst >= 4.5 else "   <-- FAIL"
        if worst < 4.5:
            fails.append("%s is %.2f:1 on the lightest surface" % (tn, worst))
        print("    %-8s %-9s %7.2f %7.2f %7.2f%s" % (tn, tv, rs[0], rs[1], rs[2], flag))

    print("  surface steps (want >= 1.15 so elevation is visible)")
    for i in range(len(SURFACES) - 1):
        a, b = SURFACES[i], SURFACES[i + 1]
        r = ratio(a[1], b[1])
        flag = "" if r >= 1.15 else "   <-- FLAT"
        if r < 1.15:
            fails.append("%s->%s step is only %.3f" % (a[0], b[0], r))
        print("    %s -> %-4s %.3f%s" % (a[0], b[0], r, flag))

    r = ratio("#06080a", "#e8a84a")
    print("  accent fill button (ground text on accent): %.2f" % r)
    if r < 4.5:
        fails.append("accent button text is %.2f:1" % r)
    return fails


def main():
    print("\n  DESIGN SYSTEM AUDIT\n  " + "-" * 62)
    fails = contrast_report()

    rows = [a for a in (audit(n, p) for n, p in PAGES) if a]
    if not rows:
        print("\n  no built pages found - run the builders first")
        return 1

    print("\n  scale conformance (built pages, excluding :root declarations)")
    print("    %-26s %5s %5s %6s %4s %6s"
          % ("page", "fonts", "pads", "radii", "hex", "cssKB"))
    union = {"font": set(), "pad": set(), "radius": set(), "hex": set()}
    for a in rows:
        for k in union:
            union[k] |= set(a[k])
        print("    %-26s %5d %5d %6d %4d %6.1f"
              % (a["name"], len(a["font"]), len(a["pad"]),
                 len(a["radius"]), len(a["hex"]), a["css_bytes"] / 1024.0))

    print("    %-26s %5d %5d %6d %4d"
          % ("UNION", len(union["font"]), len(union["pad"]),
             len(union["radius"]), len(union["hex"])))

    print("\n  before -> after")
    for k, label in (("font", "distinct font sizes"), ("pad", "distinct spacings"),
                     ("radius", "corner radii"), ("hex", "off-token colours")):
        now = len(union[k])
        print("    %-22s %3d -> %3d" % (label, BEFORE[k], now))

    print("\n  violations")
    bad = False
    off = sorted(union["font"] - FONT_SIZES)
    if off:
        bad = True
        print("    font-size off the scale : %s" % ", ".join(off))
    off = sorted(union["pad"] - SPACING)
    if off:
        bad = True
        print("    spacing off the scale   : %s" % ", ".join(off))
    off = sorted(union["radius"] - RADII)
    if off:
        bad = True
        print("    radius off the scale    : %s" % ", ".join(off))
    off = sorted(union["hex"] - TOKEN_HEX)
    if off:
        bad = True
        print("    colour outside tokens   : %s" % ", ".join(off))
    for f in fails:
        bad = True
        print("    contrast                : %s" % f)
    if not bad:
        print("    none")

    print("  " + "-" * 62)
    if bad:
        print("  FAIL - a page has drifted off the design system\n")
        return 1
    print("  PASS\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
