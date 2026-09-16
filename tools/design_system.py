# -*- coding: utf-8 -*-
"""Load tools/design_system.css and hand a page the layers it actually needs.

The three demo pages must open from file:// with no server, so none of them can
<link> a stylesheet - the CSS has to be inlined into each build. That would
normally mean three diverging copies, which is exactly the state this replaced
(demo vs gallery CSS measured 60% similar and drifting). So: one file on disk,
inlined at build time, and tools/check_design.py re-audits the built HTML.

    from design_system import css
    css("base")    # -> tokens + text + controls + surfaces + tables
    css("viewer")  # -> the above PLUS canvas chrome, dock, HUD, measurement

The Q&A page has no canvas, so it takes "base" and ships ~4 KB less dead CSS.
"""

import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "design_system.css")

SENTINEL = "LAYER:VIEWER"


def _raw():
    with io.open(PATH, encoding="utf-8") as f:
        return f.read()


def css(layer="viewer", minify=True):
    """Return the stylesheet for `layer`, which is "base" or "viewer"."""
    if layer not in ("base", "viewer"):
        raise ValueError("layer must be 'base' or 'viewer', got %r" % (layer,))
    src = _raw()
    if layer == "base":
        cut = src.index(SENTINEL)
        # rewind to the start of the comment block that carries the sentinel
        src = src[: src.rindex("/*", 0, cut)]
    return _min(src) if minify else src


def _min(s):
    """Strip comments and collapse whitespace.

    Deliberately conservative: this runs over one known file, not arbitrary CSS.
    Comments are the documentation of *why* each token exists, so they live in
    the source and are dropped from the 6.5 MB shipped page, where they would be
    read by nobody.
    """
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*([{}:;,>])\s*", r"\1", s)
    # put back the one space that matters: `and (max-width:900px)` etc. is fine,
    # but selectors like `a :focus` are not used here, so this is safe.
    s = s.replace(";}", "}")
    return s.strip()


def token(name):
    """Read one token's value out of :root. Lets a builder emit a matching
    colour into a non-CSS context (an OG image, an SVG favicon) without
    hardcoding a hex that then drifts from the stylesheet."""
    m = re.search(r"--%s:\s*([^;]+);" % re.escape(name), _raw())
    if not m:
        raise KeyError("no --%s in design_system.css" % name)
    return m.group(1).strip()


if __name__ == "__main__":
    full, base = css("viewer"), css("base")
    raw = _raw()
    print("  source      %6d bytes" % len(raw))
    print("  base  (min) %6d bytes   budget 15360   %s"
          % (len(base), "OK" if len(base) < 15360 else "SPLIT NEEDED"))
    print("  viewer(min) %6d bytes" % len(full))
    print("  --accent = %s   --bg = %s" % (token("accent"), token("bg")))
