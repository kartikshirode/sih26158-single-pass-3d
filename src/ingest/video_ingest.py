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


def sky_fraction(bgr_small: np.ndarray) -> float:
    """
    Fraction of the frame that is probably sky - bright, low-saturation, upper region.

    Worth measuring because sky carries no geometry: a frame that is mostly sky
    contributes almost nothing to reconstruction however sharp it is. Cinematic drone
    footage is full of these; mapping footage is not.
    """
    hsv = cv2.cvtColor(bgr_small, cv2.COLOR_BGR2HSV)
    h, w = hsv.shape[:2]
    upper = hsv[: int(h * 0.6)]
    mask = (upper[..., 1] < 70) & (upper[..., 2] > 120)
    return float(mask.sum()) / float(h * w)


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
                 blur_reject_pct: float = 25.0, max_sky: float = 0.75,
                 skip_start_s: float = 0.0, analyse_scale: float = 0.25,
                 min_flow_px: float = 1.0, srt_path: str | None = None,
                 progress: bool = True) -> IngestResult:
    """
    Decode `path`, score every frame, and return the selected keyframes.

    Selection is a scored trade-off, not uniform sampling:
      1. drop the blurriest `blur_reject_pct` of frames (percentile, not a constant)
      2. drop frames that are mostly sky - no geometry to recover
      3. require accumulated optical flow between consecutive keyframes, so each pair
         has real baseline rather than being near-duplicates
    """
    import av

    container = av.open(path)
    stream = container.streams.video[0]
    fps = float(stream.average_rate or 30.0)
    W, H = stream.codec_context.width, stream.codec_context.height
    skip_n = int(skip_start_s * fps)

    scores, skies, slates, flows, kept_idx, thumbs = [], [], [], [], [], []
    prev_small = None
    acc_flow = 0.0
    n = 0

    for frame in container.decode(video=0):
        img = frame.to_ndarray(format="bgr24")
        if n >= skip_n:
            small = cv2.resize(img, (int(W * analyse_scale), int(H * analyse_scale)))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            scores.append(sharpness(gray))
            skies.append(sky_fraction(small))
            slates.append(is_slate(small))
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

    scores = np.asarray(scores)
    skies = np.asarray(skies)
    slates = np.asarray(slates, dtype=bool)
    flows = np.asarray(flows)
    kept_idx = np.asarray(kept_idx)

    if len(scores) == 0:
        raise RuntimeError("no frames decoded")

    # 1. blur gate, by percentile within THIS clip
    blur_thr = np.percentile(scores, blur_reject_pct)
    ok = scores >= blur_thr
    # 2. sky gate
    ok &= skies <= max_sky
    # 2b. slate/title-card gate
    ok &= ~slates

    # 3. baseline gate: walk forward, take a frame once enough flow has accumulated
    idx_ok = np.flatnonzero(ok)
    if len(idx_ok) == 0:
        raise RuntimeError("every frame rejected by blur/sky gates")

    need = max(len(idx_ok) / max(target_keyframes, 1), 1.0)
    flow_budget = max(np.median(flows[idx_ok]) * need, min_flow_px)

    selected = [int(idx_ok[0])]
    acc = 0.0
    for j in idx_ok[1:]:
        acc += flows[j]
        if acc >= flow_budget:
            selected.append(int(j))
            acc = 0.0
        if len(selected) >= target_keyframes:
            break
    selected = np.asarray(selected)

    telemetry = []
    srt = srt_path or (os.path.splitext(path)[0] + ".SRT")
    tel_all = parse_dji_srt(srt)
    if tel_all:
        for s in selected:
            fi = int(kept_idx[s])
            telemetry.append(tel_all[fi] if fi < len(tel_all) else {})

    stats = {
        "video": os.path.basename(path),
        "resolution": f"{W}x{H}",
        "fps": round(fps, 2),
        "frames_decoded": int(n),
        "frames_analysed": int(len(scores)),
        "keyframes_selected": int(len(selected)),
        "reduction": f"{n}:{len(selected)}",
        "blur_threshold_varlap": round(float(blur_thr), 1),
        "rejected_blur": int((scores < blur_thr).sum()),
        "rejected_sky": int((skies > max_sky).sum()),
        "rejected_slate": int(slates.sum()),
        "median_sky_fraction": round(float(np.median(skies)), 3),
        "flow_budget_px": round(float(flow_budget), 2),
        "has_gps_sidecar": bool(tel_all),
        "srt_records": len(tel_all),
    }
    return IngestResult(
        keyframe_indices=kept_idx[selected],
        frames=[thumbs[i] for i in selected],
        telemetry=telemetry,
        stats=stats,
    )


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
