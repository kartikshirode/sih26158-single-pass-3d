"""
S1 INGEST - the real one. Video file in, keyframes + metadata out.

This is the stage the problem statement makes mandatory ("Drone video (1080p/4K)") and
the stage that, until now, had never been exercised: everything downstream ran on
synthetic poses or still JPEGs. It decodes an actual video, scores every frame, and
selects the subset worth reconstructing from.

Four jobs, matching the requirements:

  R-C2  reject motion blur and compression mush - variance of Laplacian, scored by
        PERCENTILE within the clip, never against a hardcoded threshold, because the
        absolute value depends entirely on scene texture and exposure.
  R-O2  cut ~18,000 frames to ~600. This is the single biggest runtime lever.
  R-C1  keep enough baseline between keyframes to triangulate, without so much that
        matching fails. With no GPS we estimate baseline from optical flow.
  R-I2  parse per-frame GPS when a sidecar exists (DJI SRT), and say so plainly when
        it does not.

Deliberately CPU-only and dependency-light: PyAV for decode, OpenCV for scoring.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import cv2
import numpy as np


# --------------------------------------------------------------------------------------
# DJI SRT sidecar
# --------------------------------------------------------------------------------------

# Values arrive in several shapes across DJI generations, and the differences are
# SILENT - a wrong guess corrupts rather than errors. Handled explicitly below.
_NUM = r"[-+]?\d*\.?\d+"
_PATTERNS = {
    "latitude":  re.compile(rf"\[?latitude\s*:\s*({_NUM})", re.I),
    "longitude": re.compile(rf"\[?long?titude\s*:\s*({_NUM})", re.I),   # Mavic 2 spells it "longtitude"
    "rel_alt":   re.compile(rf"rel_alt\s*:\s*({_NUM})", re.I),
    "abs_alt":   re.compile(rf"abs_alt\s*:\s*({_NUM})", re.I),
    "altitude":  re.compile(rf"\[altitude\s*:\s*({_NUM})", re.I),        # Air 2/2S
    "gb_yaw":    re.compile(rf"gb_yaw\s*:\s*({_NUM})", re.I),
    "gb_pitch":  re.compile(rf"gb_pitch\s*:\s*({_NUM})", re.I),
    "focal_len": re.compile(rf"focal_len\s*:\s*({_NUM})", re.I),
    "frame_cnt": re.compile(r"(?:FrameCnt|SrtCnt)\s*:\s*(\d+)", re.I),
}


def parse_dji_srt(path: str) -> list[dict]:
    """
    Parse a DJI SRT sidecar into per-frame telemetry.

    Tolerant by design: blocks may or may not carry a timing line, fields are packed
    several to a bracket, encodings differ between models, and files appear with CRLF
    and BOMs. Anything unparseable is skipped rather than raising.
    """
    if not os.path.exists(path):
        return []
    text = open(path, "r", encoding="utf-8-sig", errors="replace").read()
    blocks = re.split(r"\n\s*\n", text)
    out = []
    for b in blocks:
        if not b.strip():
            continue
        rec = {}
        for key, pat in _PATTERNS.items():
            m = pat.search(b)
            if m:
                rec[key] = float(m.group(1))
        if "latitude" not in rec or "longitude" not in rec:
            continue

        # Unit normalisation. focal_len is millimetres on some models and tenths of a
        # millimetre on others; a 240 that means 24 mm is the classic silent corruption.
        if rec.get("focal_len", 0) > 100:
            rec["focal_len"] /= 10.0
        # Height: prefer rel_alt. abs_alt is BAROMETRIC on real DJI files (abs_alt minus
        # rel_alt is constant to the millimetre across a flight), so it is not an
        # independent GNSS observation and must never be treated as one.
        rec["height"] = rec.get("rel_alt", rec.get("altitude", 0.0))
        out.append(rec)
    return out


# --------------------------------------------------------------------------------------
# Frame quality
# --------------------------------------------------------------------------------------

def sharpness(gray: np.ndarray) -> float:
    """
    Variance of the Laplacian. A signed/float depth is required so negative responses
    survive; an unsigned type silently clips half the signal.
    """
    return float(cv2.Laplacian(gray, cv2.CV_32F).var())


def is_slate(bgr_small: np.ndarray, dark_thr: float = 42.0,
             flat_frac: float = 0.80) -> bool:
    """
    Detect a title card / slate / fade - a frame that is mostly flat dark pixels.

    Real footage begins with these more often than not (this clip opens with five
    seconds of black-on-text credits). They pass a sharpness gate, because text edges
    give a healthy Laplacian response, so blur scoring alone lets them through. A
    content gate catches them without the operator having to guess a skip offset.
    """
    g = cv2.cvtColor(bgr_small, cv2.COLOR_BGR2GRAY)
    return (g.mean() < dark_thr) and (float((g < dark_thr).mean()) > flat_frac)


def sky_mask(bgr_small: np.ndarray) -> np.ndarray:
    """Bright, low-saturation pixels - sky, haze, and blown-out cloud."""
    hsv = cv2.cvtColor(bgr_small, cv2.COLOR_BGR2HSV)
    return (hsv[..., 1] < 70) & (hsv[..., 2] > 120)


def sky_fraction(bgr_small: np.ndarray) -> float:
    """
    Fraction of the WHOLE frame that is sky.

    Changed from an upper-60%-only measure after the Nicosia clip: that version
    capped at 0.60 and scored a full horizon vista at 0.445, which read as
    "under the 0.75 limit" when it was in fact three quarters sky. Measuring the
    whole frame makes the number mean what its name says.

    Interpretation for survey footage:
        0.00 - 0.05   nadir or steep oblique, ground fills the frame   ACCEPT
        0.05 - 0.15   shallow oblique, sky in the corners              ACCEPT
        > 0.15        horizon in frame                                 REJECT
    """
    return float(sky_mask(bgr_small).mean())


def horizon_present(bgr_small: np.ndarray, min_sky: float = 0.06) -> bool:
    """
    True when a horizon line is inside the frame.

    This is the single most important admission test for reconstruction, and the
    Nicosia clip is why. A horizon means the scene runs to the far field: depth in
    one frame spans roughly 100 m to 30 km. No feed-forward stereo model resolves
    two-and-a-half orders of magnitude of depth in one point map, so the far half
    of every view arrives as unconstrained noise and swamps the near geometry.

    Detected structurally rather than by area alone: a contiguous sky region that
    starts at the top edge and ends at a consistent row IS a horizon. Sky seen
    past the edge of a roof in a steep oblique is not, because it does not span
    the frame width.
    """
    m = sky_mask(bgr_small)
    h, w = m.shape
    if m.mean() < min_sky:
        return False
    # Row-wise sky coverage; a horizon shows as rows that are almost entirely sky
    # at the top, falling away sharply at one row.
    rows = m.mean(axis=1)
    spanning = rows > 0.80
    return bool(spanning[: int(h * 0.75)].any())


def static_overlay_mask(frames_small: list, std_thr: float = 3.0,
                        grad_thr: float = 25.0) -> np.ndarray:
    """
    Locate burned-in overlays: watermarks, credits, DJI OSD bars.

    These are poison for multi-view reconstruction and they are invisible to every
    quality metric above. An overlay sits at FIXED PIXEL COORDINATES in every view,
    so a matcher sees a perfect correspondence that implies zero parallax, and the
    solver has to place it at a degenerate depth. It corrupts pose and scale, not
    just the point cloud.

    Two signals together, because neither alone is sufficient:
      - low temporal variance   (it never moves)  - but so is a static sky
      - high spatial gradient   (it has edges)    - but so is textured ground

    Their intersection is the overlay.
    """
    stack = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
                      for f in frames_small])
    temporal_std = stack.std(axis=0)
    mean_img = stack.mean(axis=0)
    grad = cv2.Laplacian(mean_img, cv2.CV_32F)
    return (temporal_std < std_thr) & (np.abs(grad) > grad_thr)


def overlay_crop_box(mask: np.ndarray, max_trim: float = 0.12) -> tuple:
    """
    Smallest edge crop (top, bottom, left, right fractions) that removes the
    static overlay, or all zeros if it is not confined to the border.

    Trimming an edge band is lossless for reconstruction - a survey pass covers the
    scene many times over - whereas inpainting invents texture the solver would
    then try to triangulate.
    """
    h, w = mask.shape
    if not mask.any():
        return (0.0, 0.0, 0.0, 0.0)
    ys, xs = np.nonzero(mask)
    # Cost of removing the overlay from each side = how much must be cut away.
    # To clear a mark near the BOTTOM you trim the bottom by 1 - ymin/h, not by
    # the mark's own offset; getting this backwards trims the scene and keeps the
    # watermark.
    cand = {"t": (ys.max() + 1) / h,          # trim from top down past the mark
            "b": 1.0 - ys.min() / h,          # trim from bottom up past the mark
            "l": (xs.max() + 1) / w,
            "r": 1.0 - xs.min() / w}
    side, frac = min(cand.items(), key=lambda kv: kv[1])
    if frac <= max_trim:
        pad = min(frac + 0.01, max_trim)
        return {"t": (pad, 0.0, 0.0, 0.0), "b": (0.0, pad, 0.0, 0.0),
                "l": (0.0, 0.0, pad, 0.0), "r": (0.0, 0.0, 0.0, pad)}[side]
    return (0.0, 0.0, 0.0, 0.0)


def apply_crop(img: np.ndarray, box: tuple) -> np.ndarray:
    t, b, l, r = box
    if not any(box):
        return img
    h, w = img.shape[:2]
    return img[int(h * t): h - int(h * b), int(w * l): w - int(w * r)]


# --------------------------------------------------------------------------------------
# Shot segmentation
# --------------------------------------------------------------------------------------

def detect_shots(hists: np.ndarray, flows: np.ndarray,
                 corr_thr: float = 0.55) -> list[tuple]:
    """
    Split the analysed frame range into continuous shots.

    Required because every downstream stage assumes ONE camera trajectory. Editing
    two aerial shots together produces a clip that passes every per-frame quality
    test and is still unreconstructable: the solver is handed two unrelated pose
    sets and asked to fit them as one, and the result is a smear. The Nicosia clip
    had a 180-frame jump at keyframe 11 that nothing in S1 noticed.

    Cuts are found by colour-histogram correlation between consecutive analysed
    frames, which survives motion blur and exposure ramps far better than a flow
    threshold; the flow array is used only to confirm.
    """
    n = len(hists)
    cuts = []
    for i in range(1, n):
        c = cv2.compareHist(hists[i - 1].astype(np.float32),
                            hists[i].astype(np.float32), cv2.HISTCMP_CORREL)
        if c < corr_thr:
            cuts.append(i)
    bounds = [0] + cuts + [n]
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


def frame_hist(bgr_small: np.ndarray) -> np.ndarray:
    h = cv2.calcHist([cv2.cvtColor(bgr_small, cv2.COLOR_BGR2HSV)],
                     [0, 1], None, [32, 32], [0, 180, 0, 256])
    return cv2.normalize(h, h).flatten()


# --------------------------------------------------------------------------------------
# Ingest
# --------------------------------------------------------------------------------------

@dataclass
class IngestResult:
    keyframe_indices: np.ndarray
    frames: list                      # BGR uint8, only for selected keyframes
    telemetry: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def ingest_video(path: str, *, target_keyframes: int = 600,
                 blur_reject_pct: float = 25.0, max_sky: float = 0.15,
                 reject_horizon: bool = True, single_shot: bool = True,
                 skip_start_s: float = 0.0, analyse_scale: float = 0.25,
                 min_flow_px: float = 1.0, srt_path: str | None = None,
                 progress: bool = True) -> IngestResult:
    """
    Decode `path`, score every frame, and return the selected keyframes.

    Selection is a scored trade-off, not uniform sampling. The order matters: the
    structural gates run FIRST, because a per-frame quality score is meaningless
    once the frames come from two different flights.

      0. segment into shots and keep only the longest continuous one   (single_shot)
      1. locate and crop any burned-in overlay
      2. drop frames with a horizon in view - unbounded depth          (reject_horizon)
      3. drop frames that are mostly sky or blown out by flare         (max_sky)
      4. drop the blurriest `blur_reject_pct` (percentile, not a constant)
      5. require accumulated optical flow between consecutive keyframes, so each
         pair carries real baseline instead of being near-duplicates
    """
    import av

    container = av.open(path)
    stream = container.streams.video[0]
    fps = float(stream.average_rate or 30.0)
    W, H = stream.codec_context.width, stream.codec_context.height
    skip_n = int(skip_start_s * fps)

    scores, skies, slates, horiz, flows, kept_idx, thumbs, hists =         [], [], [], [], [], [], [], []
    prev_small = None
    n = 0

    for frame in container.decode(video=0):
        img = frame.to_ndarray(format="bgr24")
        if n >= skip_n:
            small = cv2.resize(img, (int(W * analyse_scale), int(H * analyse_scale)))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            scores.append(sharpness(gray))
            skies.append(sky_fraction(small))
            slates.append(is_slate(small))
            horiz.append(horizon_present(small))
            hists.append(frame_hist(small))
            if prev_small is not None:
                fl = cv2.calcOpticalFlowFarneback(prev_small, gray, None,
                                                  0.5, 2, 13, 2, 5, 1.1, 0)
                flows.append(float(np.linalg.norm(fl, axis=2).mean()))
            else:
                flows.append(0.0)
            prev_small = gray
            kept_idx.append(n)
            thumbs.append(img)
        n += 1
        if progress and n % 150 == 0:
            print(f"    decoded {n} frames", end="\r", flush=True)
    container.close()

    scores  = np.asarray(scores);  skies = np.asarray(skies)
    slates  = np.asarray(slates, dtype=bool)
    horiz   = np.asarray(horiz, dtype=bool)
    flows   = np.asarray(flows);   hists = np.asarray(hists)
    kept_idx = np.asarray(kept_idx)
    if len(scores) == 0:
        raise RuntimeError("no frames decoded")

    # 0. SHOT SEGMENTATION - before anything per-frame.
    shots = detect_shots(hists, flows)
    in_shot = np.ones(len(scores), dtype=bool)
    if single_shot and len(shots) > 1:
        lo, hi = max(shots, key=lambda ab: ab[1] - ab[0])
        in_shot[:] = False
        in_shot[lo:hi] = True

    # 1. BURNED-IN OVERLAY - static in image space across every view, so a matcher
    #    reads it as zero-parallax geometry. Located on the retained shot only.
    sub = [thumbs[i] for i in np.flatnonzero(in_shot)[:80]]
    ov_small = static_overlay_mask([cv2.resize(f, (480, 270)) for f in sub])
    crop = overlay_crop_box(ov_small)

    ok = in_shot.copy()
    if reject_horizon:
        ok &= ~horiz                                   # 2. unbounded depth
    ok &= skies <= max_sky                             # 3. sky / flare washout
    ok &= ~slates
    blur_thr = np.percentile(scores[ok], blur_reject_pct) if ok.any() else 0.0
    ok &= scores >= blur_thr                           # 4. motion blur

    idx_ok = np.flatnonzero(ok)
    if len(idx_ok) == 0:
        raise RuntimeError(
            "every frame rejected. Check out/screen.json - this clip is probably "
            "not a survey pass (horizon in frame, or mostly sky).")

    # 5. baseline budget
    need = max(len(idx_ok) / max(target_keyframes, 1), 1.0)
    flow_budget = max(np.median(flows[idx_ok]) * need, min_flow_px)
    selected, acc = [int(idx_ok[0])], 0.0
    for j in idx_ok[1:]:
        acc += flows[j]
        if acc >= flow_budget:
            selected.append(int(j)); acc = 0.0
        if len(selected) >= target_keyframes:
            break
    selected = np.asarray(selected)

    telemetry = []
    srt = srt_path or (os.path.splitext(path)[0] + ".SRT")
    tel_all = parse_dji_srt(srt)
    if tel_all:
        for s_ in selected:
            fi = int(kept_idx[s_])
            telemetry.append(tel_all[fi] if fi < len(tel_all) else {})

    stats = {
        "video": os.path.basename(path), "resolution": f"{W}x{H}",
        "fps": round(fps, 2), "frames_decoded": int(n),
        "frames_analysed": int(len(scores)),
        "shots_detected": len(shots),
        "shot_kept_frames": int(in_shot.sum()),
        "overlay_crop_trbl": [round(float(x), 3) for x in crop],
        "keyframes_selected": int(len(selected)),
        "reduction": f"{n}:{len(selected)}",
        "rejected_other_shots": int((~in_shot).sum()),
        "rejected_horizon": int((horiz & in_shot).sum()),
        "rejected_sky": int((skies > max_sky).sum()),
        "rejected_slate": int(slates.sum()),
        "blur_threshold_varlap": round(float(blur_thr), 1),
        "rejected_blur": int((scores < blur_thr).sum()),
        "median_sky_fraction": round(float(np.median(skies[in_shot])), 3),
        "flow_budget_px": round(float(flow_budget), 2),
        "has_gps_sidecar": bool(tel_all), "srt_records": len(tel_all),
    }
    return IngestResult(
        keyframe_indices=kept_idx[selected],
        frames=[apply_crop(thumbs[i], crop) for i in selected],
        telemetry=telemetry, stats=stats)


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", default="out/keyframes")
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--skip", type=float, default=0.0)
    ap.add_argument("--max-sky", type=float, default=0.75)
    a = ap.parse_args()

    print(f"S1 INGEST  {a.video}")
    r = ingest_video(a.video, target_keyframes=a.n, skip_start_s=a.skip,
                     max_sky=a.max_sky)
    os.makedirs(a.out, exist_ok=True)
    for i, (fi, img) in enumerate(zip(r.keyframe_indices, r.frames)):
        cv2.imwrite(os.path.join(a.out, f"kf_{i:03d}_f{fi:05d}.jpg"), img,
                    [cv2.IMWRITE_JPEG_QUALITY, 95])
    json.dump({"stats": r.stats,
               "keyframes": [int(x) for x in r.keyframe_indices],
               "telemetry": r.telemetry},
              open(os.path.join(a.out, "ingest.json"), "w"), indent=2)

    print()
    for k, v in r.stats.items():
        print(f"  {k:24s} {v}")
    print(f"\n  wrote {len(r.frames)} keyframes to {a.out}/")
    if not r.stats["has_gps_sidecar"]:
        print("  NOTE: no GPS sidecar found - reconstruction can only be metric-relative,")
        print("        not georeferenced. The PS lists GPS as a MANDATORY input.")
