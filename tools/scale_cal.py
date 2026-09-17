# -*- coding: utf-8 -*-
"""Per-run metric scale, read from research/calibration/*.json (docs/09 section 2).

The reconstruction's coordinates are in the feed-forward model's units, which EXP-14
found 5.3-5.8x too small on Kolu. A run's lengths may be printed as metres only when a
calibration file names that run. Everything else is `unvalidated`, and there is no
default factor - a global correction would be wrong for every clip but one.
"""

from __future__ import annotations

import glob
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAL_DIR = os.path.join(ROOT, "research", "calibration")

UNVALIDATED = {
    "factor": 1.0, "bracket": None, "status": "unvalidated", "method": None,
    "summary": "no external ruler or GNSS for this clip",
}


def load(run: str) -> dict:
    """The calibration covering `run`, or the unvalidated default."""
    for path in sorted(glob.glob(os.path.join(CAL_DIR, "*.json"))):
        with io.open(path, encoding="utf-8") as f:
            cal = json.load(f)
        if run in cal.get("runs", []):
            if cal.get("status") not in ("calibrated", "gnss", "gnss+rtk"):
                raise ValueError(f"{path}: unknown status {cal.get('status')!r}")
            out = {k: cal.get(k) for k in UNVALIDATED}
            out["source"] = os.path.relpath(path, ROOT).replace(os.sep, "/")
            return out
    return dict(UNVALIDATED)


def for_page(cal: dict) -> dict:
    """The subset a page needs: a short label for tight panels, and `basis` for the
    sentence that says where the number came from."""
    if cal["status"] == "unvalidated":
        label = "unvalidated (model units)"
    else:
        lo, hi = cal["bracket"]
        label = f"calibrated x{cal['factor']:.2f} ({lo:.2f}-{hi:.2f})"
    return {"factor": cal["factor"], "status": cal["status"], "label": label,
            "basis": cal["summary"]}
