"""
Frame gates on letterboxed footage, and the S1 cost cuts that must not change them.

Run:  python src/ingest/test_frames.py

The demo clip (a Clipchamp re-edit) has 34 black rows above and below the picture. The
sky test anchored on the top edge, so the bar hid every frame's sky: screen said sky
0.0 and horizon 0.0 on a clip whose top 15% is sky. The overlay test saw the bars'
edges as a static overlay at both ends of the frame, found no crop under 12% that
cleared both, and kept the real watermark. Built here from a synthetic frame.
"""
from __future__ import annotations

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ingest.video_ingest import (horizon_present, horizon_row, letterbox_box,  # noqa: E402
                                 letterbox_rows, overlay_crop_box, sky_and_horizon,
                                 sky_fraction, static_overlay_mask)

FAILED: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def frame(seed: int, bars: int = 8, sky_rows: int = 50, h: int = 270, w: int = 480):
    """Textured brown ground, pale sky above it, black bars, a static white mark."""
    rng = np.random.default_rng(seed)
    img = np.zeros((h, w, 3), np.uint8)
    ground = rng.integers(40, 160, (h, w, 3), dtype=np.uint8)
    ground[..., 0] //= 2                                  # browner: blue channel low
    img[:] = ground
    # Pale, unsaturated sky with sensor noise: a perfectly constant band would itself
    # read as a static overlay, which real sky never is.
    img[bars:bars + sky_rows] = np.clip(
        np.array([228, 232, 235]) + rng.normal(0, 10, (sky_rows, w, 3)), 0, 255)
    img[:bars] = 0
    img[h - bars:] = 0
    cv2.putText(img, "WATERMARK", (10, h - bars - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (255, 255, 255), 2)
    return img


print("\nT1: letterboxed frames")
f = frame(1)
check("the bars are measured", letterbox_rows(f) == (8, 8), str(letterbox_rows(f)))
sky, hz = sky_and_horizon(f)
check("sky below a top bar is found", 0.15 < sky < 0.25, f"sky {sky:.3f}")
check("and so is the horizon", hz and horizon_present(f))
check("sky_and_horizon agrees with the single-purpose calls",
      abs(sky - sky_fraction(f)) < 1e-9 and hz == horizon_present(f))
r = horizon_row(f)
# Cumulative purity 0.70 over 50 sky rows reaches at most 50 / 0.7 rows down.
check("the horizon row is counted from the top of the frame, past the bar",
      r is not None and 8 + 50 <= r <= 8 + int(50 / 0.7) + 1, str(r))
frames = [frame(s) for s in range(40)]     # S1 samples up to 90
t, b, l, rr = letterbox_box(frames)
check("the clip-wide crop removes the bars", abs(t - 9 / 270) < 1e-9 and abs(b - 9 / 270) < 1e-9,
      str((t, b)))
box = overlay_crop_box(static_overlay_mask(frames))
check("the watermark above the bottom bar is cropped, not blocked by the bars",
      box[1] > 0.05 and box[0] == 0.0, str(box))

print("\nT2: frames without bars behave as before")
g = frame(2, bars=0)
check("no bars, none measured", letterbox_rows(g) == (0, 0))
check("sky at the very top edge is still sky", sky_fraction(g) > 0.15)
check("a frame of ground has no sky and no horizon",
      sky_and_horizon(np.full((270, 480, 3), (40, 90, 120), np.uint8)) == (0.0, False))

print()
if FAILED:
    print(f"{len(FAILED)} TEST(S) FAILED: {FAILED}")
    sys.exit(1)
print("ALL PASS")
