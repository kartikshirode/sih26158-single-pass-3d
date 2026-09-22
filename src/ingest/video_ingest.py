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
# SILENT - a wrong guess corrupts rather than errors. The families, from the twenty
# real files under fixtures/dji_srt (MIT, JuanIrache/DJI_SRT_Parser) and the DJI
# support note for the Zenmuse H20N (research/04-dji-srt-formats.md):
#
#   bracket   [latitude: 41.42] [longitude: 2.23] [rel_alt: 10.2 abs_alt: 142.8]
#             Mavic 2 onward. "longtitude" on Mavic 2 / Zenmuse. fnum and focal_len
#             are x100 / x10 integers up to the Air 2S, literal decimals from the
#             Mavic 3. Air 2 / 2S write [altitude: ...] and nothing else.
#   tuple     GPS(149.0251,-20.2533,16) BAROMETER:1.9        Mavic Pro, Phantom 4
#             F/5.6, SS 400, ..., GPS (-58.85, -34.24, 15), H 85.80m   P4 RTK / P4P / Mini
#             The tuple is (lon, lat, satellites). Not altitude: 16 is the fix count.
#             Height above take-off is BAROMETER, Hb, or H. The Matrice 300 form
#             GPS(36.6146,-6.1120,0.0M) is the one exception: (lat, lon, precision).
#   none      Mavic Air: exposure only, no position at all.
_NUM = r"[-+]?\d*\.?\d+"
_PATTERNS = {
    "latitude":  re.compile(rf"\[?latitude\s*:\s*({_NUM})", re.I),
    # Mavic 2 and the Zenmuse line spell it "longtitude". The pattern this replaced,
    # long?titude, matched only the misspelling: every Mavic 3 / Mini 3 / Air 3 file,
    # and the synthetic test video, parsed to no telemetry at all until 2026-09-22.
    "longitude": re.compile(rf"\[?longt?itude\s*:\s*({_NUM})", re.I),
    "rel_alt":   re.compile(rf"rel_alt\s*:\s*({_NUM})", re.I),
    "abs_alt":   re.compile(rf"abs_alt\s*:\s*({_NUM})", re.I),
    "altitude":  re.compile(rf"\[altitude\s*:\s*({_NUM})", re.I),        # Air 2/2S
    "gb_yaw":    re.compile(rf"gb_yaw\s*:\s*({_NUM})", re.I),
    "gb_pitch":  re.compile(rf"gb_pitch\s*:\s*({_NUM})", re.I),
    "focal_len": re.compile(rf"focal_len\s*:\s*({_NUM})", re.I),
    "frame_cnt": re.compile(r"(?:FrameCnt|SrtCnt)\s*:\s*(\d+)", re.I),
    "baro":      re.compile(rf"(?:BAROMETER|Hb)\s*[:(]\s*({_NUM})", re.I),
    # "H 85.80m" and "H=1.5m", but not "H.S 1.84m/s" and not "HOME (".
    "h_above":   re.compile(rf"(?:^|[\s,])H[\s=:]+({_NUM})\s*m\b", re.I | re.M),
}
_GPS_TUPLE = re.compile(rf"\bGPS\s*\(\s*({_NUM})\s*,\s*({_NUM})\s*,\s*({_NUM})\s*([mM]?)\s*\)")
_TIMING = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->")
_DATE = re.compile(r"(\d{4})[-.](\d{1,2})[-.](\d{1,2})[ T](\d{1,2}):(\d{2}):(\d{2})"
                   r"(?:[.,](\d{3}))?")


def _num(x: str) -> float | None:
    try:
        v = float(x)
    except ValueError:
        return None
    return v if np.isfinite(v) else None


def parse_dji_srt(path: str) -> list[dict]:
    """
    Parse a DJI SRT sidecar into per-record telemetry.

    Tolerant by design: blocks may or may not carry a timing line, fields are packed
    several to a bracket, encodings differ between models, and files appear with CRLF
    and BOMs. Anything unparseable is skipped rather than raising, and every skip or
    unit guess is written into the record's `flags` so a run can say what it did.

    Each record carries `latitude`, `longitude`, `height` (metres above take-off, the
    best of rel_alt / BAROMETER / H, else None) and, where the file has them,
    `t_us` (video-relative, from the timing line), `frame_cnt`, `satellites`,
    `focal_len` in millimetres, `gb_yaw`, `gb_pitch`, `abs_alt`, `wall_us`.
    """
    if not os.path.exists(path):
        return []
    try:
        text = open(path, "r", encoding="utf-8-sig", errors="replace").read()
    except OSError:
        return []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", text)
    out = []
    for b in blocks:
        if not b.strip():
            continue
        rec: dict = {}
        flags: list[str] = []
        for key, pat in _PATTERNS.items():
            m = pat.search(b)
            if m:
                v = _num(m.group(1))
                if v is not None:
                    rec[key] = v
        if "latitude" not in rec or "longitude" not in rec:
            m = _GPS_TUPLE.search(b)
            if m:
                a, c, third, unit = _num(m.group(1)), _num(m.group(2)), m.group(3), m.group(4)
                if a is None or c is None:
                    continue
                if unit:                       # Matrice 300: (lat, lon, precision M)
                    rec["latitude"], rec["longitude"] = a, c
                    flags.append("gps_tuple_m300")
                else:                          # everyone else: (lon, lat, satellites)
                    rec["latitude"], rec["longitude"] = c, a
                    flags.append("gps_tuple_lon_lat")
                    if re.fullmatch(r"\d+", third):
                        rec["satellites"] = int(third)
        if "latitude" not in rec or "longitude" not in rec:
            continue
        if not (-90.0 <= rec["latitude"] <= 90.0 and -180.0 <= rec["longitude"] <= 180.0):
            continue                           # radians, or a scrubbed placeholder
        if rec["latitude"] == 0.0 and rec["longitude"] == 0.0:
            continue                           # no fix yet; DJI writes zeros

        # Unit normalisation. focal_len is millimetres on some models and tenths of a
        # millimetre on others; a 240 that means 24 mm is the classic silent corruption.
        if rec.get("focal_len", 0) > 100:
            rec["focal_len"] /= 10.0
            flags.append("focal_len_x10")

        # Height: metres above take-off, whichever field this family carries. abs_alt
        # is BAROMETRIC on real DJI files (abs_alt minus rel_alt is constant to the
        # millimetre across a flight), so it is not an independent GNSS observation
        # and must never be treated as one. Absent height stays None, not 0.0: a
        # zero would later be read as "on the ground".
        h = None
        for k in ("rel_alt", "altitude", "baro", "h_above"):
            if k in rec:
                h = rec.pop(k) if k in ("baro", "h_above") else rec[k]
                break
        rec["height"] = h
        if h is None:
            flags.append("no_height")

        m = _TIMING.search(b)
        if m:
            hh, mm, ss, frac = m.groups()
            rec["t_us"] = ((int(hh) * 3600 + int(mm) * 60 + int(ss)) * 1_000_000
                           + int(frac.ljust(3, "0")) * 1000)
        m = _DATE.search(b)
        if m:
            import datetime as _dt
            try:
                y, mo, d, hh, mi, se, ms = m.groups()
                t = _dt.datetime(int(y), int(mo), int(d), int(hh), int(mi), int(se),
                                 int(ms or 0) * 1000)
                rec["wall_us"] = int(t.timestamp() * 1e6)
            except (ValueError, OverflowError, OSError):
                flags.append("bad_date")
        if "frame_cnt" in rec:
            rec["frame_cnt"] = int(rec["frame_cnt"])
        rec["flags"] = flags
        out.append(rec)

    # A file with no timing lines (Mavic 2 style) still has a clock: use it.
    if out and not any("t_us" in r for r in out) and all("wall_us" in r for r in out):
        t0 = out[0]["wall_us"]
        for r in out:
            r["t_us"] = r["wall_us"] - t0
            r["flags"].append("t_from_wall_clock")
    return out


def telemetry_for_frames(records: list[dict], frame_idx, fps: float) -> list[dict]:
    """
    The telemetry record for each source frame index, keyed the way the file allows.

    Never positional. Record i is source frame i only in the modern per-frame files,
    and even there `parse_dji_srt` drops blocks without a fix, which shifts every
    later index. The legacy families write one block per second, so positional
    lookup on a 30 fps clip would hand frame 300 the record from five minutes in.

      1. FrameCnt / SrtCnt, 1-based, when the records carry it;
      2. else nearest by time, from the timing line at the clip's frame rate;
      3. else nothing, rather than a guess.
    """
    if not records:
        return [{} for _ in frame_idx]
    by_cnt = {r["frame_cnt"]: r for r in records if "frame_cnt" in r}
    if len(by_cnt) == len(records):
        return [by_cnt.get(int(fi) + 1, {}) for fi in frame_idx]
    if fps and fps > 0 and all("t_us" in r for r in records):
        ts = np.asarray([r["t_us"] for r in records], np.float64)
        order = np.argsort(ts)
        ts = ts[order]
        out = []
        for fi in frame_idx:
            t = int(fi) / fps * 1e6
            j = int(np.searchsorted(ts, t))
            cands = [k for k in (j - 1, j) if 0 <= k < len(ts)]
            k = min(cands, key=lambda k: abs(ts[k] - t))
            # Half a record interval is as far as "nearest" honestly reaches.
            gap = np.median(np.diff(ts)) if len(ts) > 1 else 1e6
            out.append(records[order[k]] if abs(ts[k] - t) <= gap else {})
        return out
    return [{} for _ in frame_idx]


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
    """
    Sky: bright, low-saturation, AND connected to the top edge of the frame.

    The connectivity term is not cosmetic. Brightness-and-saturation alone calls
    pale arid ground sky - graded desert fill has exactly the signature, high value
    and low saturation - so a near-nadir view of a construction site in Arizona
    scored 23% "sky" with no sky in the frame at all, and the admission gate threw
    it out. Real sky is one region touching the top edge; bright ground below a
    horizon is not.
    """
    hsv = cv2.cvtColor(bgr_small, cv2.COLOR_BGR2HSV)
    raw = ((hsv[..., 1] < 70) & (hsv[..., 2] > 120)).astype(np.uint8)
    if not raw[0].any():
        return np.zeros(raw.shape, bool)
    n, lab = cv2.connectedComponents(raw, connectivity=8)
    top = np.unique(lab[0][raw[0] > 0])
    return np.isin(lab, top[top > 0])


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


def horizon_row(bgr_small: np.ndarray, purity: float = 0.70) -> int | None:
    """
    Deepest row such that everything above it is still mostly sky, or None.

    Defined by CUMULATIVE coverage rather than by finding a row that is itself
    almost entirely sky. A real skyline is ragged - mountains, buildings, trees -
    so no single row near it is uniformly sky, and a per-row test locks onto the
    top of the ragged band instead of the bottom. What the caller actually wants is
    "how far down can I cut and still be removing mostly sky", which is exactly the
    cumulative measure.
    """
    m = sky_mask(bgr_small)
    h = m.shape[0]
    cum = np.cumsum(m.mean(axis=1)) / np.arange(1, h + 1)
    good = np.flatnonzero(cum >= purity)
    if len(good) == 0:
        return None
    r = int(good[-1])
    return r if r >= h * 0.03 else None


def horizon_crop_fraction(frames_small: list, margin: float = 0.04) -> float:
    """
    Fraction of frame height to trim from the TOP, across a whole clip.

    Taken as a high percentile of the per-frame horizon row rather than the mean: the
    camera pitches during a flight, and a crop chosen at the average leaves sky in
    every frame where the nose came up. A margin below the skyline also removes the
    haze band, which carries texture but no usable depth.
    """
    rows = [horizon_row(f) for f in frames_small]
    rows = [r for r in rows if r is not None]
    if not rows:
        return 0.0
    h = frames_small[0].shape[0]
    return float(min(np.percentile(rows, 85) / h + margin, 0.75))


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
    # Spread measured by INTERQUARTILE RANGE, not standard deviation. A title card
    # that covers part of the frame for a fraction of the clip inflates the std
    # wherever it overlaps, and that is enough to hide a genuinely permanent
    # watermark underneath it - which is exactly what happened on a clip whose
    # opening title sat over the creator's bug. A quartile spread ignores a
    # disturbance present in under a quarter of the frames.
    q25, q50, q75 = np.percentile(stack, [25, 50, 75], axis=0)
    spread = q75 - q25
    grad = cv2.Laplacian(q50.astype(np.float32), cv2.CV_32F)
    return (spread < std_thr) & (np.abs(grad) > grad_thr)


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
                 horizon_policy: str = "reject", single_shot: bool = True,
                 skip_start_s: float = 0.0, end_s: float | None = None,
                 analyse_scale: float = 0.25,
                 min_flow_px: float = 1.0, srt_path: str | None = None,
                 progress: bool = True) -> IngestResult:
    """
    Decode `path`, score every frame, and return the selected keyframes.

    Selection is a scored trade-off, not uniform sampling. The order matters: the
    structural gates run FIRST, because a per-frame quality score is meaningless
    once the frames come from two different flights.

      0. segment into shots and keep only the longest continuous one   (single_shot)
      1. locate and crop any burned-in overlay
      2. handle the horizon: reject those frames, or CROP below the skyline
         and keep the near field                                        (horizon_policy)
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
    # Ending early is a real lever, not a convenience. Keyframe budget is fixed by
    # the time budget, so halving the covered ground doubles the view density over
    # what remains - which is what resolves structure standing off the ground.
    end_n = int(end_s * fps) if end_s else None

    scores, skies, slates, horiz, flows, kept_idx, thumbs, hists =         [], [], [], [], [], [], [], []
    prev_small = None
    n = 0

    for frame in container.decode(video=0):
        if end_n is not None and n >= end_n:
            n += 1
            break
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
    # Sample ACROSS the shot, not its first 80 frames. A drone pitches during a
    # flight, so a horizon estimated from the opening seconds under-crops the rest;
    # and a title card burned over the opening frames moves, which hides a genuinely
    # static watermark from the temporal-variance test.
    _all = np.flatnonzero(in_shot)
    idx_shot = _all[np.linspace(0, len(_all) - 1, min(90, len(_all))).astype(int)]
    ar = H / W
    sub = [cv2.resize(thumbs[i], (480, int(480 * ar))) for i in idx_shot]
    crop = overlay_crop_box(static_overlay_mask(sub))

    ok = in_shot.copy()
    if horizon_policy == "reject":
        ok &= ~horiz                                   # 2a. unbounded depth
    elif horizon_policy == "crop":
        # 2b. keep the frames, remove the far field. Compose with any overlay crop.
        ht = horizon_crop_fraction(sub)
        crop = (max(crop[0], ht), crop[1], crop[2], crop[3])
        # Re-score sky and blur on the CROPPED frame - the uncropped numbers describe
        # an image we are no longer using, and the sky gate would reject everything.
        for j in np.flatnonzero(in_shot):
            c = apply_crop(cv2.resize(thumbs[j], (int(W * analyse_scale),
                                                  int(H * analyse_scale))), crop)
            skies[j] = sky_fraction(c)
            scores[j] = sharpness(cv2.cvtColor(c, cv2.COLOR_BGR2GRAY))
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

    srt = srt_path or (os.path.splitext(path)[0] + ".SRT")
    tel_all = parse_dji_srt(srt)
    telemetry = telemetry_for_frames(tel_all, [int(kept_idx[s_]) for s_ in selected], fps)

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
        "horizon_policy": horizon_policy,
        "horizon_in_frame": int((horiz & in_shot).sum()),
        "rejected_horizon": int((horiz & in_shot).sum()) if horizon_policy == "reject" else 0,
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
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--max-sky", type=float, default=0.15)
    ap.add_argument("--horizon", choices=["reject", "crop"], default="reject")
    a = ap.parse_args()

    print(f"S1 INGEST  {a.video}")
    r = ingest_video(a.video, target_keyframes=a.n, skip_start_s=a.skip,
                     end_s=a.end, max_sky=a.max_sky, horizon_policy=a.horizon)
    # Clear first. Keyframe filenames carry their source frame index, so a re-run
    # with different settings leaves the previous run's files behind and the next
    # stage silently reconstructs a mixture of both.
    if os.path.isdir(a.out):
        for f in os.listdir(a.out):
            if f.startswith("kf_") and f.endswith(".jpg"):
                os.remove(os.path.join(a.out, f))
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
