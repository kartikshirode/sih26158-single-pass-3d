"""
The principal-point guard in colmap_export.full_frame_camera, with and without S1's crop.

Run:  python src/pipeline/test_colmap_export.py

Audit F-10: S1 can cut the top off every keyframe (--horizon crop, which the web path
always asks for), and that moves the camera's physical principal point off the
keyframe centre. The guard only knew the keyframe centre, so a fit that recovered the
true centre of a 20% top crop was refused at 12.5% off. Built here from a known pinhole
camera, pushed through the same cover-crop onto a model grid that the job undoes.
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from colmap_export import full_frame_camera, parse_crop  # noqa: E402

FAILED: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def grid_K(f, cx, cy, h0, w0, H=224, W=518, n=5):
    """Keyframe intrinsics as the model grid sees them: the inverse of full_frame_camera."""
    s = max(H / h0, W / w0)
    x0, y0 = (w0 * s - W) / 2.0, (h0 * s - H) / 2.0
    return np.tile([f * s, f * s, cx * s - x0, cy * s - y0], (n, 1)), H, W


def refused(K, H, W, h0, w0, crop):
    try:
        full_frame_camera(K, H, W, h0, w0, log=lambda *_: None, crop_trbl=crop)
    except SystemExit as e:
        return str(e)
    return None


# 1920x1080 source, principal point at its centre, 20% cut off the top by S1.
SRC_W, SRC_H, F = 1920, 1080, 1000.0
CROP = (0.2, 0.0, 0.0, 0.0)
w0, h0 = SRC_W, SRC_H - int(SRC_H * 0.2)                  # the 1920x864 keyframe
true_cx, true_cy = SRC_W / 2, SRC_H / 2 - int(SRC_H * 0.2)  # (960, 324) in it

print("\nT1: a top-cropped keyframe")
K, H, W = grid_K(F, true_cx, true_cy, h0, w0)
cam = None
if refused(K, H, W, h0, w0, CROP) is None:
    cam = full_frame_camera(K, H, W, h0, w0, log=lambda *_: None, crop_trbl=CROP)
check("the true, crop-shifted principal point passes when the crop is known",
      cam is not None and abs(cam["cx"] - 960) < 1e-6 and abs(cam["cy"] - 324) < 1e-6
      and cam["pp_reference"].startswith("source centre"),
      str(cam and {k: cam[k] for k in ("cx", "cy", "pp_reference")}))
why = refused(K, H, W, h0, w0, None)
check("without the crop the same fit is refused, as it was before the fix",
      why is not None and "12.5%" in why, str(why))

K, H, W = grid_K(F, w0 / 2, h0 / 2, h0, w0)
cam = full_frame_camera(K, H, W, h0, w0, log=lambda *_: None, crop_trbl=CROP)
check("a principal point at the keyframe centre still passes (feed-forward fits land there)",
      cam["pp_reference"] == "keyframe centre")

K, H, W = grid_K(F, w0 / 2, h0 / 2 + 0.2 * h0, h0, w0)
why = refused(K, H, W, h0, w0, CROP)
check("far from both centres is still refused", why is not None, str(why))

print("\nT2: the crop as the job receives it")
check("four fractions parse", parse_crop("0.2,0,0,0.05") == (0.2, 0.0, 0.0, 0.05))
check("unset and all-zero mean uncropped",
      parse_crop("") is None and parse_crop(None) is None and parse_crop("0,0,0,0") is None)
for bad in ("0.2,0", "a,b,c,d", "0.6,0.5,0,0", "-0.1,0,0,0"):
    try:
        parse_crop(bad)
        ok = False
    except SystemExit:
        ok = True
    check(f"{bad!r} is refused", ok)

print()
if FAILED:
    print(f"{len(FAILED)} TEST(S) FAILED: {FAILED}")
    sys.exit(1)
print("ALL PASS")
