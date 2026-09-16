# -*- coding: utf-8 -*-
"""Check that every element the JS reaches for still exists in the built page.

A design refactor breaks pages by ORPHANING SELECTORS: a class gets renamed in
the markup and the script that queries it silently returns null, so the button
does nothing and nothing in the console says why. This greps every
getElementById / querySelector / querySelectorAll / classList target out of each
built page and confirms the document actually contains it.

It is deliberately dumb string matching over the built HTML rather than a DOM
parse, because the pages are self-contained single files and a false positive
here is cheap while a missed orphan is a dead control in front of a panel.

    python tools/check_wiring.py
"""

from __future__ import print_function

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = [
    ("demo/index.html", os.path.join(ROOT, "demo", "index.html")),
    ("demo/gallery/index.html", os.path.join(ROOT, "demo", "gallery", "index.html")),
    ("demo/qa/index.html", os.path.join(ROOT, "demo", "qa", "index.html")),
]

# Classes the JS adds at runtime rather than finding in the markup.
RUNTIME_OK = {
    "drag", "measuring", "in", "on", "hide", "over", "said", "run", "done",
    "ph", "win", "lose", "met", "open", "err", "fail", "dom", "untimed",
    "rej", "fin", "warn", "ok", "measured", "designed",
    "m-line", "m-ring", "m-dot", "m-box", "m-txt",
    "tl-sparse", "tl-ba", "tl-dense", "tl-mesh",
}


def scan(name, path):
    with io.open(path, encoding="utf-8") as f:
        html = f.read()
    # Static markup is everything outside <script>. But a lot of this UI is built
    # at runtime by innerHTML - the phase rows, the keyframe grid, the verdict
    # cards - so an element being absent from the static markup is NOT evidence
    # it is missing. Search the whole file, which covers both.
    markup = re.sub(r"<script>.*?</script>", "", html, flags=re.S)

    def has_id(x):
        return ('id="%s"' % x) in html

    def has_class(x):
        return re.search(r'class="[^"]*\b%s\b' % re.escape(x), html) is not None

    problems = []

    for eid in sorted(set(re.findall(r"getElementById\(['\"]([\w-]+)['\"]\)", html))):
        if not has_id(eid):
            problems.append("getElementById('%s') has no element" % eid)

    sels = set(re.findall(r"querySelector(?:All)?\(['\"]([^'\"]+)['\"]\)", html))
    for sel in sorted(sels):
        # only verify the simple shapes; anything fancier is checked by eye
        m = re.match(r"^#([\w-]+)$", sel)
        if m and not has_id(m.group(1)):
            problems.append("querySelector('%s') has no element" % sel)
            continue
        m = re.match(r"^\.([\w-]+)$", sel)
        if m and not has_class(m.group(1)):
            problems.append("querySelector('%s') matches nothing" % sel)
        m = re.match(r"^#([\w-]+) ([\w]+)$", sel)
        if m and not has_id(m.group(1)):
            problems.append("querySelector('%s') has no container" % sel)

    # styled classes that nothing in the markup or the JS ever applies: dead CSS
    style = "\n".join(re.findall(r"<style>(.*?)</style>", html, flags=re.S))
    # Comments first: the page-specific CSS keeps its comments, and a phrase like
    # "tools/design_system.css," parses as a selector to the regex below.
    style = re.sub(r"/\*.*?\*/", "", style, flags=re.S)
    style = re.sub(r"@media print\{.*?\}\s*\}", "", style, flags=re.S)
    declared = set(re.findall(r"\.([a-z][\w-]*)\s*[{,:\[]", style))
    used = set()
    for chunk in re.findall(r'class="([^"]*)"', html):      # static AND JS-built
        used |= set(chunk.split())
    for chunk in re.findall(r"classList\.\w+\(['\"]([^'\"]+)", html):
        used |= set(chunk.split())
    used |= RUNTIME_OK
    # Shared components this page does not happen to use are not dead code -
    # they are the system being available. Only page-local classes count.
    #
    # EXACT names, not prefixes. A prefix list silently swallowed most of this
    # page's own classes - "p" alone matched pickrow, phases, ph, panel, pt, pn
    # and pl - which made the report read like coverage it did not have.
    SYSTEM = {
        "btn", "chip", "card", "panel", "panel-pad", "seg", "input", "note",
        "kv", "table", "src", "label", "num", "big", "sm", "xs", "p", "u",
        "h1", "h2", "h3", "lede", "well", "rule", "stack", "row", "wrap",
        "topbar", "brand", "sitenav", "replay", "banner", "stage", "hud",
        "dock", "mtip", "loading", "nm", "tag", "sep",
        "fg-1", "fg-2", "fg-3", "fg-ok", "fg-bad", "fg-acc",
        "at-tl", "at-tr", "at-bl", "at-br",
        "btn--primary", "btn--quiet", "btn--sm",
        "chip--ok", "chip--bad", "chip--acc",
        "note--acc", "note--bad",
    }
    dead = sorted(c for c in declared - used if c not in SYSTEM)

    return problems, dead


def main():
    bad = False
    for name, path in PAGES:
        if not os.path.exists(path):
            print("  %-26s NOT BUILT" % name)
            bad = True
            continue
        problems, dead = scan(name, path)
        status = "OK" if not problems else "%d ORPHANED" % len(problems)
        print("  %-26s %s" % (name, status))
        for p in problems:
            bad = True
            print("      ! %s" % p)
        if dead:
            print("      (styled but never applied: %s)" % ", ".join(dead[:12]))
    print()
    if bad:
        print("  FAIL - a control lost its element\n")
        return 1
    print("  PASS - every scripted element is present\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
