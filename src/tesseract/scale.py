"""
The scale service: what turns model units into metres, and what refuses to.

EXP-14 (docs/08) measured the Kolu reconstruction 5.3-5.8x too small. The factor came
from the feed-forward model and nothing had ever checked it against a length from
outside the model. So scale is resolved here, in one place, in a fixed order of
preference, and a run that has nothing better than the model's own assertion is
`unvalidated` and may not print metres.

  1. GNSS / RTK     the 5-DOF fit's scale, in a real metric frame
  2. known object   an operator or an audit measured something of published size
  3. witness        an independent model's opinion - a CHECK, never the source
  4. model prior    unvalidated

There is deliberately no global default factor. The factor is a property of one run.
"""

from __future__ import annotations

import glob
import io
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAL_DIR = os.path.join(ROOT, "research", "calibration")

UNVALIDATED = {
    "factor": 1.0,
    "bracket": None,
    "status": "unvalidated",
    "method": None,
    "summary": "no external ruler or GNSS for this clip",
    "source": None,
}


def load(run: str) -> dict:
    """The calibration covering `run`, or the unvalidated default."""
    for path in sorted(glob.glob(os.path.join(CAL_DIR, "*.json"))):
        with io.open(path, encoding="utf-8") as f:
            cal = json.load(f)
        if run in cal.get("runs", []):
            if cal.get("status") not in ("calibrated", "gnss", "gnss+rtk"):
                raise ValueError(f"{path}: unusable status {cal.get('status')!r}")
            out = {k: cal.get(k, v) for k, v in UNVALIDATED.items()}
            out["source"] = os.path.relpath(path, ROOT).replace(os.sep, "/")
            out["references"] = cal.get("references", [])
            out["floor_checks"] = cal.get("floor_checks", [])
            return out
    return dict(UNVALIDATED)


def from_gnss(scale: float, *, rtk: bool, residual_m: float | None = None) -> dict:
    """Scale taken from the georeferencing fit. The only source that needs no ruler."""
    return {
        "factor": float(scale),
        "bracket": None,
        "status": "gnss+rtk" if rtk else "gnss",
        "method": "sim3-fit",
        "summary": ("RTK/PPK track" if rtk else "consumer GNSS track")
                   + (f", residual {residual_m:.2f} m" if residual_m is not None else ""),
        "source": "georef.json",
    }


def for_page(cal: dict) -> dict:
    """The subset a page or a label needs."""
    if cal["status"] == "unvalidated":
        label = "unvalidated (model units)"
    elif cal["bracket"]:
        lo, hi = cal["bracket"]
        label = f"calibrated x{cal['factor']:.2f} ({lo:.2f}-{hi:.2f})"
    else:
        label = f"{cal['status']} x{cal['factor']:.3f}"
    return {"factor": cal["factor"], "status": cal["status"], "label": label,
            "basis": cal["summary"]}


# ------------------------------------------------------------------ the automatic check
def footprint_check(focal_px: float, image_width_px: int, camera_height: float,
                    factor: float, *, content_span_m: float | None = None) -> dict:
    """
    The check that would have caught EXP-14 automatically (docs/08 S5).

    A camera's ground footprint follows from its own intrinsics: at height h with a
    horizontal field of view t, a nadir view spans 2h*tan(t/2). The Kolu run said the
    camera was 10.6 m up with a 67 deg lens - a 14 m footprint - while the keyframes
    showed a four-lane highway, an ecoduct and its verges. The plausibility band that
    passed that error compared the model with itself; this compares it with the picture.

    `content_span_m` is the smallest real width the imagery is known to contain. Pass
    what the scene demonstrably shows (a carriageway, a structure of published size);
    leave it None and the check only reports, it cannot fail.
    """
    hfov = 2.0 * math.atan(image_width_px / (2.0 * focal_px))
    footprint_model = 2.0 * camera_height * math.tan(hfov / 2.0)
    footprint_m = footprint_model * factor
    out = {
        "hfov_deg": round(math.degrees(hfov), 2),
        "camera_height_model": round(camera_height, 3),
        "footprint_model": round(footprint_model, 2),
        "factor": factor,
        "footprint_m": round(footprint_m, 2),
        "content_span_m": content_span_m,
        "ok": True,
        "note": "nadir-equivalent footprint; an oblique view sees more, never less",
    }
    if content_span_m is not None:
        out["ok"] = footprint_m >= content_span_m
        if not out["ok"]:
            out["note"] = (f"the imagery shows at least {content_span_m:g} m of ground, "
                           f"but the intrinsics and this scale allow only "
                           f"{footprint_m:.1f} m - the scale is too small")
    return out


def implied_factor(focal_px: float, image_width_px: int, camera_height: float,
                   content_span_m: float) -> float:
    """The factor that would make the footprint exactly fit the known content span."""
    hfov = 2.0 * math.atan(image_width_px / (2.0 * focal_px))
    return content_span_m / (2.0 * camera_height * math.tan(hfov / 2.0))


def describe(cal: dict) -> str:
    if cal["status"] == "unvalidated":
        return "scale unvalidated - lengths are model units, not metres"
    b = f" (bracket {cal['bracket'][0]:.2f}-{cal['bracket'][1]:.2f})" if cal["bracket"] else ""
    return f"scale {cal['status']} x{cal['factor']:.3f}{b} from {cal['summary']}"


if __name__ == "__main__":
    import sys
    run = sys.argv[1] if len(sys.argv) > 1 else "kolumvs3d"
    cal = load(run)
    print(run, "->", describe(cal))
    if cal["status"] != "unvalidated":
        # the Kolu numbers, as a worked example of the automatic check
        print(footprint_check(1450.547, 1920, 10.59, cal["factor"], content_span_m=40.0))
        print("uncalibrated would have failed:",
              not footprint_check(1450.547, 1920, 10.59, 1.0, content_span_m=40.0)["ok"])
