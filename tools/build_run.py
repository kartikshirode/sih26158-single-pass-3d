# -*- coding: utf-8 -*-
"""
Build demo/run/index.html: upload a clip, watch it reconstruct, take the model.

Unlike the other three pages this one is not self-contained. It talks to `/api/*`,
so it cannot open from file:// the way `docs/15` requires of the rest. That is a
deliberate exception for one page, not a change of policy: everything the page
*displays* still comes from the pipeline's own status file rather than from anything
written here.

The limits below are printed on the page because a user who is told a cap up front
reads a refusal as a rule; one who is not reads it as a bug. They are the same values
the orchestrator enforces (run_job/run_upload.py), kept in one place here and passed
through the template.

    python tools/build_run.py
"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from design_system import css as ds_css                          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.join(ROOT, "tools")
OUT = os.path.join(ROOT, "demo", "run")

TITLE = "SIH26158 - reconstruct a clip"
DESC = ("Upload a single-pass drone video and watch the pipeline reconstruct it: "
        "screening, keyframes, camera poses, then photometric densification.")

# Must match run_job/run_upload.py. A 10-minute cap is the PS's own figure for the
# Desired Output; 60 views is what fits inside both job timeouts, since 297 views would
# need about 3.2 h of densification against a 3 h limit.
LIMITS = ("One continuous pass, up to 10 minutes and 600 MB. "
          "Sixty keyframes are selected however long the clip is. "
          "A run takes roughly 70 minutes end to end; a usable preview arrives at "
          "about 20. Results expire, and uploads never appear in the gallery.")


def main():
    os.makedirs(OUT, exist_ok=True)
    with io.open(os.path.join(HERE, "run_template.html"), encoding="utf-8") as f:
        tpl = f.read()
    html = (tpl.replace("__DS_CSS__", ds_css("viewer"))
               .replace("__TITLE__", TITLE)
               .replace("__DESC__", DESC)
               .replace("__LIMITS__", LIMITS))
    if "__" in html.split("<script>")[0]:
        sys.exit("an unfilled template placeholder survived")
    p = os.path.join(OUT, "index.html")
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  -> {p}  {os.path.getsize(p)//1024} KB")


if __name__ == "__main__":
    main()
