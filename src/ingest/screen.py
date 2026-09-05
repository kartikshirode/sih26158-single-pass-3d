"""
S1 ADMISSION TEST - decide whether a clip can be reconstructed at all, before
spending GPU time finding out that it cannot.

Every metric here exists because a specific clip got through without it. Run this
on any candidate video and read the verdict; a REJECT is not a quality opinion, it
is a statement that the geometry is unrecoverable from this input.
"""
from __future__ import annotations
import os, sys, json
import av, cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ingest.video_ingest import (sky_fraction, horizon_present, sharpness,
                                 is_slate, frame_hist, detect_shots,
                                 static_overlay_mask, overlay_crop_box)


def screen(path: str, n_samples: int = 140) -> dict:
    c = av.open(path)
    st = c.streams.video[0]
    fps = float(st.average_rate or 30.0)
    dur = float(st.duration * st.time_base) if st.duration else \
          float(c.duration / av.time_base if c.duration else 0)
    W, H = st.codec_context.width, st.codec_context.height

    step = max(int(round(fps * dur / n_samples)), 1)
    small, skies, horiz, sharps, slates, hists = [], [], [], [], [], []
    n = 0
    for fr in c.decode(video=0):
        if n % step == 0:
            img = fr.to_ndarray(format="bgr24")
            s = cv2.resize(img, (480, int(480 * H / W)))
            small.append(s)
            g = cv2.cvtColor(s, cv2.COLOR_BGR2GRAY)
            skies.append(sky_fraction(s)); horiz.append(horizon_present(s))
            sharps.append(sharpness(g));   slates.append(is_slate(s))
            hists.append(frame_hist(s))
        n += 1
    c.close()

    hists = np.asarray(hists)
    shots = detect_shots(hists, np.zeros(len(hists)))
    longest = max(shots, key=lambda ab: ab[1] - ab[0])
    lo, hi = longest
    body = slice(lo, hi)

    ov = static_overlay_mask(small[body][:60])
    box = overlay_crop_box(ov)

    sky_med   = float(np.median(np.asarray(skies)[body]))
    horiz_fr  = float(np.mean(np.asarray(horiz)[body]))
    shot_secs = (hi - lo) * step / fps

    reasons = []
    if horiz_fr > 0.30: reasons.append(f"horizon in {horiz_fr:.0%} of frames -> unbounded depth")
    if sky_med  > 0.15: reasons.append(f"median sky {sky_med:.0%} -> too much frame carries no geometry")
    if shot_secs < 8:   reasons.append(f"longest continuous shot only {shot_secs:.1f}s")
    return {
        "file": os.path.basename(path), "resolution": f"{W}x{H}",
        "fps": round(fps, 2), "duration_s": round(dur, 1),
        "shots_detected": len(shots),
        "longest_shot_s": round(shot_secs, 1),
        "longest_shot_frac": round((hi - lo) / max(len(hists), 1), 2),
        "median_sky": round(sky_med, 3),
        "horizon_frac": round(horiz_fr, 3),
        "median_sharpness": round(float(np.median(np.asarray(sharps)[body])), 0),
        "static_overlay_px_frac": round(float(ov.mean()), 5),
        "overlay_crop": [round(x, 3) for x in box],
        "verdict": "REJECT" if reasons else "ACCEPT",
        "reasons": reasons,
    }


if __name__ == "__main__":
    rows = [screen(p) for p in sys.argv[1:]]
    for r in rows:
        print(f"\n=== {r['file']}  [{r['verdict']}] ===")
        for k, v in r.items():
            if k not in ("file", "verdict", "reasons"):
                print(f"  {k:24s} {v}")
        for x in r["reasons"]:
            print(f"  ! {x}")
    json.dump(rows, open("out/screen.json", "w"), indent=2)
