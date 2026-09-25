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
from ingest.video_ingest import (_is_vfr, horizon_present, horizon_row,  # noqa: E402
                                 letterbox_box, letterbox_rows, overlay_crop_box,
                                 sky_and_horizon, sky_fraction, static_overlay_mask)

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

faded = list(frames)
faded[len(faded) // 2] = np.zeros_like(faded[0])        # a fade to black mid-clip
box2 = overlay_crop_box(static_overlay_mask(faded))
check("one black sample in the middle does not bring the bar edges back", box2 == box,
      f"{box2} vs {box}")

print("\nT2: frames without bars behave as before")
g = frame(2, bars=0)
check("no bars, none measured", letterbox_rows(g) == (0, 0))
check("sky at the very top edge is still sky", sky_fraction(g) > 0.15)
check("a frame of ground has no sky and no horizon",
      sky_and_horizon(np.full((270, 480, 3), (40, 90, 120), np.uint8)) == (0.0, False))

print("\nT3: the variable-frame-rate flag with a scoring stride")
t = [i * 2 / 30.0 for i in range(100)]                  # 30 fps, every 2nd frame scored
check("constant 30 fps scored every 2nd frame is not variable", _is_vfr(t, 30.0, 2) is False)
check("the old comparison would have called it variable", _is_vfr(t, 30.0, 1) is True)
t2 = t[:50] + [t[49] + 0.2 + i * 2 / 30.0 for i in range(50)]
check("a real gap is still flagged", _is_vfr(t2, 30.0, 2) is True)

print("\nT3b: keyframe selection never leaves a hole in the chain")
from ingest.video_ingest import detect_shots, select_keyframes  # noqa: E402
n = 300
flows = np.full(n, 1.0)                                  # steady forward motion
scores = np.random.default_rng(1).uniform(900, 1000, n)
ok = np.ones(n, bool)
ok[80:146] = False                                       # the demo's sky-gated stretch
ok[240:306] = False                                      # and its blur-gated one
sel, bridged = select_keyframes(ok, np.ones(n, bool), flows, scores, 4.0, 1000)
gaps = np.diff(sel)
check("with the gates alone the stretches would be empty",
      not ok[80:146].any() and not ok[240:306].any())
check("no gap between keyframes passes 1.5 budgets", gaps.max() <= 6, f"max gap {gaps.max()}")
check("the stretches are bridged, and only they", bridged > 0 and
      all(not ok[s] for s in sel[1:] if 80 <= s < 146 or 240 <= s < 306)
      and bridged == sum(1 for s in sel[1:] if not ok[s]), f"{bridged} bridged")
sel0, b0 = select_keyframes(np.ones(n, bool), np.ones(n, bool), flows, scores, 4.0, 1000)
check("a clip the gates pass whole is picked every budget, nothing bridged",
      b0 == 0 and set(np.diff(sel0)) == {4}, f"{set(np.diff(sel0))}, {b0} bridged")
bad = np.ones(n, bool); bad[100:200] = False
sel1, _ = select_keyframes(np.ones(n, bool), bad, flows, scores, 4.0, 1000)
check("a frame that is not usable (a slate, or all sky) is never taken",
      not any(100 <= s < 200 for s in sel1))

print("\nT3c: a high-flow edit is a shot boundary")
before = np.array([1, 2, 3, 4], np.float32)
after = np.array([1, 2, 4, 3], np.float32)
hist = np.stack([before] * 3 + [after] * 3)
flow = np.array([0, 2, 2, 52, 2, 2], float)
check("an edit with histogram correlation above 0.55 still splits",
      detect_shots(hist, flow) == [(0, 3), (3, 6)],
      str(detect_shots(hist, flow)))
check("fast motion alone does not split a shot",
      detect_shots(np.stack([before] * 6), flow) == [(0, 6)])

print("\nT4: the threaded scan scores exactly what the sequential one does")
try:
    import tempfile
    from fractions import Fraction

    import av
    from ingest.video_ingest import _scan, _scan_parallel
except ImportError as e:                      # CI installs av
    print(f"  SKIP  threaded scan: {e}")
else:
    def encode(first_pts: int) -> str:
        """10 s of panning texture at 30 fps, the first frame at `first_pts` / 30 s."""
        clip = os.path.join(tempfile.mkdtemp(), f"cfr{first_pts}.mp4")
        out = av.open(clip, "w")
        st = out.add_stream("mpeg4", rate=30)
        st.width, st.height, st.pix_fmt = 320, 180, "yuv420p"
        st.codec_context.time_base = Fraction(1, 30)
        base = np.random.default_rng(0).integers(0, 255, (360, 640, 3), dtype=np.uint8)
        for i in range(300):
            fr = av.VideoFrame.from_ndarray(np.ascontiguousarray(
                base[i % 150:i % 150 + 180, 2 * i % 300:2 * i % 300 + 320]),
                format="rgb24")
            fr.pts, fr.time_base = first_pts + i, Fraction(1, 30)
            for pk in st.encode(fr):
                out.mux(pk)
        for pk in st.encode():
            out.mux(pk)
        out.close()
        return clip

    kw = dict(analyse_scale=0.25, every=2, flow_method="dis", skip_start_s=1.0, end_s=9.0)
    # A first timestamp of two frames put t - t_first just under 1.0 s, and the
    # sequential scan then started one frame later than the threaded one (audit 2).
    for first_pts in (0, 2):
        clip = encode(first_pts)
        seq = _scan(clip, 320, 180, 30.0, skip_n=30, end_n=270, **kw)
        par = _scan_parallel(clip, 320, 180, 30.0, 3, **kw)
        same = par is not None and all(
            np.allclose(np.asarray(seq[k], float), np.asarray(par[k], float))
            for k in ("n", "score", "sky", "flow"))
        check(f"first timestamp {first_pts}: three threads score the same frames with "
              "the same flow as one pass", same,
              "fell back" if par is None else
              f"{len(par['n'])} vs {len(seq['n'])} frames, first {seq['n'][:2]} vs "
              f"{par['n'][:2]}")

print()
if FAILED:
    print(f"{len(FAILED)} TEST(S) FAILED: {FAILED}")
    sys.exit(1)
print("ALL PASS")
