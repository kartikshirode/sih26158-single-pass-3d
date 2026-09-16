# -*- coding: utf-8 -*-
"""Build all three demo pages, then refuse to pass if any of them drifted.

    python tools/build_all.py

The checks are not optional extras run when someone remembers. A design system
that is only a file is a suggestion; running the audit in the same breath as the
build is what makes it a constraint. Any non-zero step fails the whole run.

  build_demo.py     /            the one-clip walkthrough
  build_gallery.py  /gallery/    every clip, video beside 3D, baseline vs MVS
  build_qa.py       /qa/         52 Q&As; re-greps all 54 figures against sources
  check_design.py                scales, tokens and WCAG contrast
  check_wiring.py                every scripted element still exists
"""

from __future__ import print_function

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

STEPS = [
    ("build_demo.py", "walkthrough"),
    ("build_gallery.py", "gallery"),
    ("build_qa.py", "Q&A"),
    ("check_design.py", "design audit"),
    ("check_wiring.py", "wiring audit"),
]


def main():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    failed = []
    for script, label in STEPS:
        # flush: without it the parent's headers sit in a buffer and land after
        # every subprocess's output, so the log reads in the wrong order.
        print("\n=== %s (%s) " % (label, script) + "=" * (46 - len(label) - len(script)),
              flush=True)
        r = subprocess.run([sys.executable, os.path.join(HERE, script)], env=env)
        if r.returncode != 0:
            failed.append(label)

    print("\n" + "=" * 64)
    if failed:
        print("  FAILED: " + ", ".join(failed))
        print("  The pages may be built but they are NOT clean. Fix before deploying.\n")
        return 1
    print("  All three pages built and both audits pass.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
