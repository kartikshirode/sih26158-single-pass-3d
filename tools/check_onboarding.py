# -*- coding: utf-8 -*-
"""
Re-grep every headline figure in docs/00-start-here.md against the document it cites.

    python tools/check_onboarding.py

`00-start-here.md` is a synthesis: it restates about forty numbers that live in eighteen
other documents. A synthesis is the easiest kind of document to let rot, because nothing
breaks when a figure moves. This is the same guard `build_qa.py` puts on the Q&A page, and
it carries the same caveat that `docs/08` made expensive: it checks that a figure still
*appears in* its source, not that the source is right.

Numbers are compared after normalising the typography, so the source may write
"5.3-5.8x" with an en dash and a multiplication sign while the onboarding document writes
plain ASCII.
"""
from __future__ import annotations

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "00-start-here.md")

# (source document, the figures the onboarding doc takes from it)
CLAIMS = [
    ("docs/02-architecture.md", [
        "18,000",        # frames in a 10-minute 4K video
        "179,700",       # pairs under exhaustive matching at 600 keyframes
        "1,073",         # 4K feature extraction, seconds
        "1,485",         # sequential matching, seconds
        "186%", "339%",  # front end alone, as a share of the budget
    ]),
    ("docs/05-quality-analysis.md", [
        "2.2 cm",        # ground sampling
        "1.525", "0.414",  # Short: reprojection before and after BA
        "1.730", "0.366",  # Kolu: the same
        "18 min 03 s", "32 min 43 s",
        "135%",          # Kolu planimetric coverage vs the feed-forward baseline
    ]),
    ("docs/06-gcp-deployment.md", [
        "35-43 s",       # per-view densify
        "1.42x",         # what sharding bought
        "216 vCPU",      # what 15 minutes would need
    ]),
    ("docs/08-measurement-validation.md", [
        "5.38", "5.77",  # lane-width bracket
        "5.32", "5.57",  # ecoduct-waist bracket
        "3.85",          # the clearance floor
        "0.650", "3.95", "1.30",   # the three measured lengths, in model metres
        "5.0 m",         # the Estonian clearance norm
        "5.54",          # the applied factor
    ]),
    ("docs/09-interface-contracts.md", [
        "32642", "9518",   # UTM zone range and the EGM2008 3-D transform
    ]),
    ("docs/11-state-of-the-art.md", [
        "75%", "60%", "85%",   # Pix4D overlap guidance
        "5.1%", "89.3%",       # AerialMetric, before and after LoRA adaptation
        "2,078.7",             # Kolu wall clock on 8 vCPU, the speed row
    ]),
    ("docs/13-target-architecture.md", [
        "0.42-0.55",           # MapAnything, seconds per view on a T4
        "6.4-11.4",            # the same on 8 vCPU
    ]),
    ("README.md", [
        "311 m", "267 m",      # 7-DOF scene error, straight pass and RTK
        "0.097", "4.1 m",      # RTK and consumer GNSS absolute error
        "14.3%", "52.0%",      # facade visibility, nadir and 60 degrees
        "1.68 m", "0.6 m/km",  # EGM96 vs EGM2008, and UTM scale error
        "-24.3 m", "-98.2 m",  # geoid separation across India
        "2.260", "0.098",      # synthetic end to end, consumer and RTK
    ]),
]

# Typographic variants the suite uses that the onboarding document spells out in ASCII.
SUBS = [("–", "-"), ("—", "-"), ("−", "-"), ("×", "x"),
        ("≤", "<="), ("≥", ">="), ("’", "'"), (" ", " "),
        (" to ", "-")]          # the suite writes ranges with a dash, this document in words


def norm(s: str) -> str:
    for a, b in SUBS:
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).lower()


def read(rel: str) -> str:
    with io.open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return norm(f.read())


def main() -> int:
    if not os.path.exists(DOC):
        print("  docs/00-start-here.md is missing")
        return 2
    doc = read("docs/00-start-here.md")
    missing, orphaned, n = [], [], 0

    for src, figures in CLAIMS:
        body = read(src)
        for fig in figures:
            n += 1
            f = norm(fig)
            if f not in body:
                missing.append(f"{fig!r} is not in {src}")
            if f not in doc:
                orphaned.append(f"{fig!r} left 00-start-here.md but is still checked")

    # The suite writes em and en dashes freely; this document does not, so that the
    # console's own typography check and this one agree about what a dash is.
    raw = io.open(DOC, encoding="utf-8").read()
    dashes = [c for c in ("—", "–") if c in raw]

    for m in missing:
        print("  ! " + m)
    for o in orphaned:
        print("  ~ " + o)
    for d in dashes:
        print(f"  ! docs/00-start-here.md contains {d!r}")

    bad = len(missing) + len(orphaned) + len(dashes)
    print(f"\n  {n} figures re-grepped across {len(CLAIMS)} sources"
          + (f"\n  FAIL - {bad} problem(s)" if bad else "\n  PASS"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
