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


_LINEAR_FIELDS = ("latitude", "longitude", "height", "rel_alt", "abs_alt", "altitude",
                  "gb_pitch")


def _interpolate_fix(a: dict, b: dict, w: float) -> dict:
    """Record `a` moved `w` of the way to `b`: position, heights and gimbal angles."""
    if w <= 0:
        return a
    if w >= 1:
        return b
    out = dict(a if w < 0.5 else b)
    for k in _LINEAR_FIELDS:
        x, y = a.get(k), b.get(k)
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            out[k] = float(x + w * (y - x))
    x, y = a.get("gb_yaw"), b.get("gb_yaw")
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        d = (y - x + 180.0) % 360.0 - 180.0             # the short way round
        out["gb_yaw"] = float((x + w * d + 180.0) % 360.0 - 180.0)
    return out


def telemetry_for_frames(records: list[dict], frame_idx, fps: float,
                         times_s=None) -> list[dict]:
    """
    The telemetry record for each source frame index, keyed the way the file allows.

    Never positional. Record i is source frame i only in the modern per-frame files,
    and even there `parse_dji_srt` drops blocks without a fix, which shifts every
    later index. The legacy families write one block per second, so positional
    lookup on a 30 fps clip would hand frame 300 the record from five minutes in.

      1. FrameCnt / SrtCnt, 1-based, when the records carry it;
      2. else by time, from the timing line. A frame's time is its presentation
         timestamp from `times_s` (seconds from the first frame) when the caller has
         it, and index / fps only when it does not. Phones and some drones record
         variable frame rate, where index / average rate drifts: a frame shown at
         2.0 s after a rate change would be looked up at 1.0 s and handed a plausible
         but wrong fix. Between two fixes the position, heights and gimbal angles are
         interpolated: the legacy files write one fix a second, and the nearest one
         can be half a second, 5 m at 10 m/s, from where the frame was taken. Each
         record's time is its block's start, so a frame up to one interval past the
         last fix keeps it, and one up to half an interval before the first takes it;
      3. else nothing, rather than a guess.
    """
    if not records:
        return [{} for _ in frame_idx]
    by_cnt = {r["frame_cnt"]: r for r in records if "frame_cnt" in r}
    if len(by_cnt) == len(records):
        return [by_cnt.get(int(fi) + 1, {}) for fi in frame_idx]
    if (times_s is not None or (fps and fps > 0)) and all("t_us" in r for r in records):
        ts = np.asarray([r["t_us"] for r in records], np.float64)
        order = np.argsort(ts)
        ts = ts[order]
        gap = float(np.median(np.diff(ts))) if len(ts) > 1 else 1e6
        out = []
        for i, fi in enumerate(frame_idx):
            t_s = times_s[i] if times_s is not None else None
            t = (t_s if t_s is not None else int(fi) / fps) * 1e6
            if t < ts[0] - gap / 2 or t > ts[-1] + gap:
                out.append({})
            elif t <= ts[0] or t >= ts[-1]:
                out.append(records[order[0 if t <= ts[0] else -1]])
            else:
                j = int(np.searchsorted(ts, t, side="right"))
                a, b = records[order[j - 1]], records[order[j]]
                w = (t - ts[j - 1]) / max(ts[j] - ts[j - 1], 1e-9)
                # Two fixes further apart than two intervals bracket a dropout: no
                # interpolating across it, the nearer one within an interval or nothing.
                if ts[j] - ts[j - 1] > 2 * gap:
                    near = a if w <= 0.5 else b
                    out.append(near if min(t - ts[j - 1], ts[j] - t) <= gap else {})
                else:
                    out.append(_interpolate_fix(a, b, w))
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


def letterbox_rows(bgr_small: np.ndarray, dark: float = 20.0,
                   max_frac: float = 0.2) -> tuple[int, int]:
    """
    Rows of black bar at the top and bottom of a letterboxed frame, as (top, bottom).

    Re-edited clips often carry them: the demo clip has 34 black rows above and below
    its 1920x1012 picture. They matter twice. The sky test below anchors on the top
    edge, and a black bar there hid the sky of every frame (screen said sky 0.0 and
    horizon 0.0 on a clip whose top 15% is sky). And a bar is a perfectly static,
    textureless band that no reconstruction can use.
    """
    v = bgr_small.max(axis=2).mean(axis=1)
    lim = int(len(v) * max_frac)
    lit_top, lit_bot = v[:lim] >= dark, v[::-1][:lim] >= dark
    top = int(np.argmax(lit_top)) if lit_top.any() else 0
    bot = int(np.argmax(lit_bot)) if lit_bot.any() else 0
    return top, bot


def letterbox_box(frames_small: list) -> tuple:
    """Crop box (top, bottom, left, right fractions) removing letterbox bars, clip-wide."""
    if not frames_small:
        return (0.0, 0.0, 0.0, 0.0)
    h = frames_small[0].shape[0]
    med = np.median(np.asarray([letterbox_rows(f) for f in frames_small]), axis=0)
    # The median across the clip, so a fade or a dark frame cannot set the crop, plus
    # one row, because the bar's edge row is usually a blend.
    t, b = (med + (med > 0)).astype(int)
    return (float(t) / h, float(b) / h, 0.0, 0.0)


def sky_mask(bgr_small: np.ndarray) -> np.ndarray:
    """
    Sky: bright, low-saturation, AND connected to the top edge of the picture.

    The connectivity term is not cosmetic. Brightness-and-saturation alone calls
    pale arid ground sky - graded desert fill has exactly the signature, high value
    and low saturation - so a near-nadir view of a construction site in Arizona
    scored 23% "sky" with no sky in the frame at all, and the admission gate threw
    it out. Real sky is one region touching the top edge; bright ground below a
    horizon is not.
    """
    hsv = cv2.cvtColor(bgr_small, cv2.COLOR_BGR2HSV)
    raw = ((hsv[..., 1] < 70) & (hsv[..., 2] > 120)).astype(np.uint8)
    # The top of the PICTURE, below any letterbox bar, is the edge sky touches.
    t0 = letterbox_rows(bgr_small)[0]
    if not raw[t0].any():
        return np.zeros(raw.shape, bool)
    n, lab = cv2.connectedComponents(raw, connectivity=8)
    top = np.unique(lab[t0][raw[t0] > 0])
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
    return sky_and_horizon(bgr_small, min_sky)[1]


def sky_and_horizon(bgr_small: np.ndarray, min_sky: float = 0.06) -> tuple[float, bool]:
    """
    sky_fraction and horizon_present from ONE sky mask.

    S1 called both on every frame and each built its own mask: 6 of the 24 ms spent
    per frame on the demo clip, half of it duplicated.
    """
    m = sky_mask(bgr_small)
    frac = float(m.mean())
    if frac < min_sky:
        return frac, False
    # Row-wise sky coverage; a horizon shows as rows that are almost entirely sky
    # at the top, falling away sharply at one row.
    spanning = m.mean(axis=1) > 0.80
    return frac, bool(spanning[: int(m.shape[0] * 0.75)].any())


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
    t0 = letterbox_rows(bgr_small)[0]           # count from the top of the picture
    cum = np.cumsum(m[t0:].mean(axis=1)) / np.arange(1, h - t0 + 1)
    good = np.flatnonzero(cum >= purity)
    if len(good) == 0:
        return None
    r = int(good[-1])
    return t0 + r if r >= h * 0.03 else None


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
    mask = (spread < std_thr) & (np.abs(grad) > grad_thr)
    # A letterbox bar's edge is static and sharp too. Left in, it put "overlay" at the
    # very top and bottom of the demo clip, no edge crop under 12% could clear both,
    # and the real watermark above the bottom bar was kept in every keyframe.
    # The clip's median bars, as letterbox_box takes them: one dark sample (a fade)
    # measured none and brought the bar edges back.
    t, b = np.median(np.asarray([letterbox_rows(f) for f in frames_small]),
                     axis=0).astype(int)
    if t:
        mask[:t + 2] = False
    if b:
        mask[mask.shape[0] - b - 2:] = False
    return mask


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

    Histogram correlation catches most cuts. A large flow jump catches an edit
    between visually similar scenes, provided the histogram also changed. A fast
    camera move through the same scene is not enough on its own.
    """
    n = len(hists)
    flows = np.asarray(flows, float)
    good = flows[np.isfinite(flows) & (flows > 0)]
    typical = float(np.median(good)) if len(good) else 0.0
    flow_cut = max(10.0, 6.0 * typical)
    cuts = []
    for i in range(1, n):
        c = cv2.compareHist(hists[i - 1].astype(np.float32),
                            hists[i].astype(np.float32), cv2.HISTCMP_CORREL)
        if c < corr_thr or (c < 0.9 and flows[i] > flow_cut):
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


def select_keyframes(ok, usable, flows, scores, flow_budget: float, target: int, *,
                     bridge: float = 1.5) -> tuple[np.ndarray, int]:
    """
    Keyframes along the clip: a frame that passed the gates (`ok`) once the flow since
    the last keyframe reaches `flow_budget`. Where none arrives before `bridge` budgets,
    the sharpest `usable` frame past one budget is taken, so the chain of shared views
    never breaks. Returns the indices and how many were bridged.
    """
    ok, usable = np.asarray(ok, bool), np.asarray(usable, bool)
    scores = np.asarray(scores, float)
    cum = np.cumsum(np.asarray(flows, float))
    first = np.flatnonzero(ok)
    if not len(first):
        return np.zeros(0, int), 0
    last = int(first[0])
    selected, bridged = [last], 0
    for j in np.flatnonzero(usable):
        if j <= last:
            continue
        gap = cum[j] - cum[last]
        if ok[j] and gap >= flow_budget:
            last = int(j)
        elif gap >= bridge * flow_budget:
            span = np.arange(last + 1, j + 1)
            span = span[usable[span] & (cum[span] - cum[last] >= flow_budget)]
            last = int(span[np.argmax(scores[span])])
            bridged += 1
        else:
            continue
        selected.append(last)
        if len(selected) >= target:
            break
    return np.asarray(selected), bridged


def keyframe_budget(ok, usable, flows, scores, target: int, *, floor: float,
                    bridge: float = 1.5) -> tuple[float, np.ndarray, int]:
    """
    The smallest flow budget, at least `floor`, whose `target` keyframes reach the end
    of the clip; returns (budget, keyframes, bridged).

    The budget used to be the median flow of the gated frames times their count over
    the target, which assumes keyframes land on gated frames spaced by the median. The
    gap is summed over every frame, though, and each keyframe overshoots its budget, so
    a long clip met the target early and the loop stopped: the 10-minute loop's 600
    keyframes ended at frame 12,604 of 18,000, and the last 30% of the flight was never
    reconstructed. A clip that fits under the target keeps `floor`, and the selection
    it always had.
    """
    flows = np.asarray(flows, float)
    usable = np.asarray(usable, bool)
    cum = np.cumsum(flows)
    tail = int(np.flatnonzero(usable)[-1]) if usable.any() else len(flows) - 1

    def cut(budget):
        sel, br = select_keyframes(ok, usable, flows, scores, budget, target, bridge=bridge)
        # Stopped by the target with at least one more budget of flight left.
        return (len(sel) >= target and cum[tail] - cum[sel[-1]] >= budget), sel, br

    short, sel, br = cut(floor)
    if not short:
        return float(floor), sel, br
    lo, hi = float(floor), max(float(cum[tail] - cum[0]), float(floor))
    for _ in range(40):
        if hi - lo <= 1e-3 * lo:
            break
        mid = (lo + hi) / 2
        if cut(mid)[0]:
            lo = mid
        else:
            hi = mid
    _, sel, br = cut(hi)
    return hi, sel, br


def ingest_video(path: str, *, target_keyframes: int = 600,
                 blur_reject_pct: float = 25.0, max_sky: float = 0.15,
                 horizon_policy: str = "reject", single_shot: bool = True,
                 skip_start_s: float = 0.0, end_s: float | None = None,
                 analyse_scale: float = 0.25, analyse_every: int | None = None,
                 flow_method: str = "dis", workers: int | None = None,
                 min_flow_px: float = 1.0, srt_path: str | None = None,
                 bridge: float = 1.5, bridge_max_sky: float = 0.5,
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
         pair carries real baseline instead of being near-duplicates, and bridge any
         stretch the gates emptied with its sharpest frame              (bridge)

    `analyse_every` scores one frame in N (all are still decoded, which the codec needs
    anyway); flow is then measured between the scored frames, so the accumulated
    baseline means the same thing. The default scores about 15 frames a second: on
    the 10-minute test clip that halved S1 (240 s to 108 s) and moved the chosen
    keyframes by at most two frames, where keyframes are ~30 frames apart.
    `flow_method` "dis" is OpenCV's DIS flow at its ultrafast preset; "farneback" is
    the original. `workers` scans time segments on
    threads; the default uses them for constant-rate clips of a minute or more.
    """
    import av

    container = av.open(path)
    stream = container.streams.video[0]
    # Frame threading: the decoder was single-threaded by default.
    stream.thread_type = "AUTO"
    fps = float(stream.average_rate or 30.0)
    W, H = stream.codec_context.width, stream.codec_context.height
    # Skip and end are compared with each frame's presentation time when the stream
    # has one; frame counts at the average rate are only the fallback. On a
    # variable-frame-rate clip the two disagree, and the time is what the caller means.
    skip_n = int(skip_start_s * fps)
    if analyse_every is None:
        analyse_every = max(1, int(round(fps / 15.0)))
    # Ending early is a real lever, not a convenience. Keyframe budget is fixed by
    # the time budget, so halving the covered ground doubles the view density over
    # what remains - which is what resolves structure standing off the ground.
    end_n = int(end_s * fps) if end_s else None

    # `smalls`, not full frames. Retaining every decoded frame at full resolution cost
    # W*H*3 each: 17.8 GB on a 114 s 1080p clip, which SIGKILLed the web orchestrator at
    # 16 GiB, and would be about 112 GB on the 10-minute video the PS asks for (R-O2).
    # Every use below either downscales immediately or wants only the ~60 SELECTED
    # frames, so the analysis copy is kept here and the selected frames are decoded
    # again in a second pass: O(clip) memory at 1/16 the constant, O(keyframes) at full
    # resolution.
    container.close()
    # Parallel scoring over time segments for long constant-rate clips; the one
    # sequential pass otherwise. They select the same frames (research/09 section 5).
    workers = _scan_workers(path, fps, workers)
    scan = None
    if workers > 1:
        scan = _scan_parallel(path, W, H, fps, workers, analyse_scale=analyse_scale,
                              every=analyse_every, flow_method=flow_method,
                              skip_start_s=skip_start_s, end_s=end_s)
    if scan is None:
        workers = 1
        scan = _scan(path, W, H, fps, analyse_scale=analyse_scale, every=analyse_every,
                     flow_method=flow_method, skip_start_s=skip_start_s, end_s=end_s,
                     skip_n=skip_n, end_n=end_n, progress=progress)
    scores, skies, slates, horiz = scan["score"], scan["sky"], scan["slate"], scan["horiz"]
    flows, kept_idx, smalls, hists = scan["flow"], scan["n"], scan["small"], scan["hist"]
    times, n = scan["t"], scan["decoded"]

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
    sub = [cv2.resize(smalls[i], (480, int(480 * ar))) for i in idx_shot]
    crop = overlay_crop_box(static_overlay_mask(sub))
    # Letterbox bars go too, whatever the overlay test found.
    crop = tuple(max(a, b) for a, b in zip(crop, letterbox_box(sub)))

    ok = in_shot.copy()
    if horizon_policy == "reject":
        ok &= ~horiz                                   # 2a. unbounded depth
    elif horizon_policy == "crop":
        # 2b. keep the frames, remove the far field. Compose with any overlay crop.
        ht = horizon_crop_fraction(sub)
        crop = (max(crop[0], ht), crop[1], crop[2], crop[3])
        # Re-score sky and blur on the CROPPED frame - the uncropped numbers describe
        # an image we are no longer using, and the sky gate would reject everything.
        # On threads, like the scan: this loop alone was 30 s of a 66 s S1 on the
        # 10-minute clip. (It also resized each frame to the size it already had.)
        from concurrent.futures import ThreadPoolExecutor

        def rescore(j):
            c = apply_crop(smalls[j], crop)
            return j, sky_fraction(c), sharpness(cv2.cvtColor(c, cv2.COLOR_BGR2GRAY))
        with ThreadPoolExecutor(max_workers=max(workers, 1) + 2) as ex:
            for j, sk, sc in ex.map(rescore, np.flatnonzero(in_shot), chunksize=64):
                skies[j], scores[j] = sk, sc
    ok &= skies <= max_sky                             # 3. sky / flare washout
    ok &= ~slates
    blur_thr = np.percentile(scores[ok], blur_reject_pct) if ok.any() else 0.0
    ok &= scores >= blur_thr                           # 4. motion blur

    idx_ok = np.flatnonzero(ok)
    if len(idx_ok) == 0:
        raise RuntimeError(
            "every frame rejected. Check out/screen.json - this clip is probably "
            "not a survey pass (horizon in frame, or mostly sky).")

    # 5. baseline budget, and no hole in the chain. The gates used to be absolute: on
    #    the demo clip the sky gate dropped frames 82-144 (pale sand read as sky, 0.15
    #    to 0.19 against 0.15) and the percentile blur gate dropped 240-306, a stretch
    #    that was only less textured. Each hole cut the chain of shared views, and the
    #    poses on either side came out as separate pieces. Now a gated frame is only
    #    preferred: once the flow since the last keyframe passes `bridge` budgets with no
    #    frame passing the gates, the sharpest frame past one budget is taken instead.
    #    The budget starts at the median flow of a gated frame and grows only as far as
    #    it must for the target to span the whole shot (keyframe_budget).
    usable = in_shot & ~slates & (skies <= max(bridge_max_sky, max_sky))
    flow_budget, selected, bridged = keyframe_budget(
        ok, usable, np.where(in_shot, flows, 0.0), scores, target_keyframes,
        floor=max(float(np.median(flows[idx_ok])), min_flow_px), bridge=bridge)

    srt = srt_path or (os.path.splitext(path)[0] + ".SRT")
    tel_all = parse_dji_srt(srt)
    # Each keyframe's own presentation time, not its index at the average rate
    # (audit F-13). A frame with no timestamp falls back to index / fps.
    telemetry = telemetry_for_frames(tel_all, [int(kept_idx[s_]) for s_ in selected], fps,
                                     times_s=[times[s_] for s_ in selected])

    stats = {
        "video": os.path.basename(path), "resolution": f"{W}x{H}",
        "fps": round(fps, 2), "frames_decoded": int(n),
        "variable_frame_rate": _is_vfr(times, fps, analyse_every),
        "frames_analysed": int(len(scores)), "analyse_every": int(analyse_every),
        "scan_workers": int(workers),
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
        "bridged_keyframes": int(bridged),
        "has_gps_sidecar": bool(tel_all), "srt_records": len(tel_all),
    }
    # Second pass for the frames that survive. Only these are needed at full
    # resolution, and there are ~60 of them, so this is ~370 MB instead of the whole
    # clip. One extra sequential decode (about 20 s on a 114 s 1080p clip) in exchange
    # for memory that no longer grows with clip length at full resolution.
    want = np.asarray(kept_idx)[selected]
    # The analysis copies are done with; on the 10-minute test clip they and the full
    # frames together peaked at 11.8 GB.
    del smalls, sub
    # After a parallel scan the frame numbers come from timestamps, so the sequential
    # fallback must number frames the same way, not by decode count (audit 2).
    full = ((_decode_frames_parallel(path, want, crop, fps, workers) or
             _decode_frames(path, want, crop, pts_fps=fps)) if workers > 1
            else _decode_frames(path, want, crop))
    return IngestResult(keyframe_indices=want, frames=[full[i] for i in want],
                        telemetry=telemetry, stats=stats)


def _score(small, gray, prev_gray, dis):
    """The per-frame S1 measurements, shared by the sequential and parallel scans."""
    sky, hz = sky_and_horizon(small)
    if prev_gray is None:
        flow = 0.0
    else:
        fl = (dis.calc(prev_gray, gray, None) if dis is not None else
              cv2.calcOpticalFlowFarneback(prev_gray, gray, None,
                                           0.5, 2, 13, 2, 5, 1.1, 0))
        flow = float(np.linalg.norm(fl, axis=2).mean())
    return sharpness(gray), sky, is_slate(small), hz, frame_hist(small), flow


class _FreshDIS:
    """
    DIS flow with no memory between calls.

    Farneback was 60% of S1's time on the demo clip (14.4 of 24 ms per frame at
    480x270); DIS at its ultrafast preset measures the same mean motion in pixels.
    But one DIS object carries state from call to call: on a small test clip the same
    pair gave 1.17 px after a run of calls and 3.41 px from a fresh object, so a
    threaded scan disagreed with the sequential one at every segment start. A new
    object per pair costs microseconds and makes the result depend on the pair alone
    (on the demo's 480x270 frames the two agree exactly).
    """

    def calc(self, a, b, flow):
        return cv2.DISOpticalFlow_create(
            cv2.DISOPTICAL_FLOW_PRESET_ULTRAFAST).calc(a, b, flow)


def _new_dis(flow_method: str):
    return _FreshDIS() if flow_method == "dis" else None


_SCAN_KEYS = ("n", "t", "score", "sky", "slate", "horiz", "hist", "flow", "small")


def _scan(path, W, H, fps, *, analyse_scale, every, flow_method, skip_start_s, end_s,
          skip_n, end_n, progress=False) -> dict:
    """One sequential pass: every frame decoded, one in `every` scored. VFR-safe."""
    import av

    out = {k: [] for k in _SCAN_KEYS}
    container = av.open(path)
    container.streams.video[0].thread_type = "AUTO"
    dis, prev, n, in_range = _new_dis(flow_method), None, 0, 0
    size = (int(W * analyse_scale), int(H * analyse_scale))
    # A microsecond of slack on both limits: with a first timestamp other than 0,
    # t - t_first lands just under whole seconds, and the frame at exactly 1.0 s failed
    # "t >= 1.0" here while _scan_parallel's frame numbers counted it (audit 2).
    eps = 1e-6
    for n, frame, t_rel in timed_frames(container):
        if end_s and (t_rel >= end_s - eps if t_rel is not None else n >= end_n):
            n += 1
            break
        if (t_rel >= skip_start_s - eps) if t_rel is not None else (n >= skip_n):
            in_range += 1
            if (in_range - 1) % max(every, 1) == 0:
                small = cv2.resize(frame.to_ndarray(format="bgr24"), size)
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                vals = _score(small, gray, prev, dis)
                for k, v in zip(_SCAN_KEYS, (n, t_rel) + vals + (small,)):
                    out[k].append(v)
                prev = gray
        n += 1
        if progress and n % 150 == 0:
            print(f"    decoded {n} frames", end="\r", flush=True)
    container.close()
    out["decoded"] = n
    return out


def _scan_workers(path: str, fps: float, workers: int | None) -> int:
    """How many parallel scans: 1 for short or variable-rate clips (see _scan_parallel)."""
    if workers is not None:
        return max(1, int(workers))
    import av

    c = av.open(path)
    try:
        st = c.streams.video[0]
        dur = float(c.duration / av.time_base) if c.duration else 0.0
        if dur < 60.0 or not fps:
            return 1
        ts = []
        for fr in c.decode(video=0):
            if fr.time is None:
                return 1
            ts.append(fr.time)
            if len(ts) >= 90:
                break
    finally:
        c.close()
    d = np.diff(np.asarray(ts))
    if len(d) < 10 or np.abs(d - 1.0 / fps).max() > 0.25 / fps:
        return 1
    return int(min(10, max(2, (os.cpu_count() or 4) // 2)))


def _scan_parallel(path, W, H, fps, workers, *, analyse_scale, every, flow_method,
                   skip_start_s, end_s) -> dict | None:
    """
    The same scan in `workers` time segments on threads, or None to fall back.

    S1 on a 10-minute clip was one thread decoding and scoring 18,000 frames. PyAV,
    OpenCV and most of numpy release the GIL, so threads each seeking to their own
    segment scale without copying frames between processes. Frame numbers come from
    presentation times, which is exact only at a constant frame rate: _scan_workers
    probes for that, and a segment whose decoded count does not match its span sends
    the whole scan back to the sequential pass rather than guessing.
    """
    import av
    from concurrent.futures import ThreadPoolExecutor

    c = av.open(path)
    st = c.streams.video[0]
    tb, t_first = st.time_base, None
    for fr in c.decode(video=0):
        t_first = fr.time
        break
    total = st.frames or int(round(float(c.duration / av.time_base) * fps))
    c.close()
    if t_first is None or not total:
        return None
    n_skip = int(np.ceil(skip_start_s * fps - 1e-6)) if skip_start_s else 0
    n_end = min(total, int(np.ceil(end_s * fps - 1e-6))) if end_s else total
    span = (n_end - n_skip + every - 1) // every          # scored frames in range
    per = -(-span // workers) * every                     # frames per segment, stride-aligned
    bounds = [(n_skip + k * per, min(n_skip + (k + 1) * per, n_end))
              for k in range(workers) if n_skip + k * per < n_end]
    size = (int(W * analyse_scale), int(H * analyse_scale))

    def seg(lo_hi):
        lo, hi = lo_hi
        first = lo - every if lo > n_skip else lo         # one earlier frame for the flow
        out = {k: [] for k in _SCAN_KEYS}
        cont = av.open(path)
        s = cont.streams.video[0]
        s.thread_type = "AUTO"
        s.codec_context.thread_count = 2
        dis, prev, seen, last = _new_dis(flow_method), None, 0, -1
        need_ref = lo > n_skip
        try:
            target = t_first + max(first - 1, 0) / fps
            cont.seek(int(target / tb), stream=s, backward=True, any_frame=False)
            for fr in cont.decode(s):
                if fr.time is None:
                    return None
                t_rel = fr.time - t_first
                n = int(round(t_rel * fps))
                if n < first:
                    continue
                if n >= hi:
                    break
                if n <= last:                                # duplicate timestamp
                    return None
                last = n
                if n >= lo:
                    seen += 1
                if (n - n_skip) % every:
                    continue
                small = cv2.resize(fr.to_ndarray(format="bgr24"), size)
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                if n < lo:                                    # the flow reference only
                    prev = gray
                    continue
                if need_ref and prev is None:
                    # The seek landed past the reference frame, so this segment's
                    # first flow would silently read 0. Fall back (audit 2).
                    return None
                vals = _score(small, gray, prev, dis)
                for k, v in zip(_SCAN_KEYS, (n, t_rel) + vals + (small,)):
                    out[k].append(v)
                prev = gray
        finally:
            cont.close()
        return out if seen == hi - lo else None

    with ThreadPoolExecutor(max_workers=len(bounds)) as ex:
        parts = list(ex.map(seg, bounds))
    if any(p is None for p in parts):
        return None
    out = {k: [v for p in parts for v in p[k]] for k in _SCAN_KEYS}
    out["decoded"] = n_end
    return out


def timed_frames(container):
    """
    Yield (decode index, frame, seconds since the first frame's presentation time).

    The time is None for a frame without a timestamp. It is the presentation time,
    not index / average rate: the two agree only at a constant frame rate.
    """
    t_first = None
    for n, frame in enumerate(container.decode(video=0)):
        t = frame.time
        if t is not None and t_first is None:
            t_first = t
        yield n, frame, (t - t_first) if (t is not None and t_first is not None) else None


def _is_vfr(times, fps: float, every: int = 1) -> bool | None:
    """
    True when frame spacing departs from the average rate; None without timestamps.

    `times` holds the scored frames only, `every` apart. Comparing their gaps with
    1 / fps called every clip above ~23 fps variable once S1 began scoring every
    second frame.
    """
    t = np.asarray([x for x in times if x is not None], np.float64)
    if len(t) < 3 or not fps:
        return None
    step = every / fps
    return bool(np.abs(np.diff(t) - step).max() > 0.5 / fps)


def _decode_frames_parallel(path, indices, crop, fps, workers) -> dict | None:
    """
    _decode_frames over `workers` contiguous groups of the wanted frames, on threads.

    Only called after _scan_workers found a constant frame rate, since frame numbers
    come from presentation times; any frame not found returns None and the caller
    falls back to the sequential pass.
    """
    import av
    from concurrent.futures import ThreadPoolExecutor

    want = sorted(int(i) for i in indices)
    groups = [g for g in np.array_split(np.asarray(want), workers) if len(g)]
    c = av.open(path)
    t_first = next((fr.time for fr in c.decode(video=0)), None)
    c.close()
    if t_first is None:
        return None

    def part(g):
        need, got = set(int(i) for i in g), {}
        cont = av.open(path)
        s = cont.streams.video[0]
        s.thread_type = "AUTO"
        s.codec_context.thread_count = 2
        try:
            cont.seek(int((t_first + max(int(g[0]) - 1, 0) / fps) / s.time_base),
                      stream=s, backward=True, any_frame=False)
            for fr in cont.decode(s):
                if fr.time is None:
                    return None
                n = int(round((fr.time - t_first) * fps))
                if n > g[-1]:
                    break
                if n in need:
                    got[n] = apply_crop(fr.to_ndarray(format="bgr24"), crop).copy()
        finally:
            cont.close()
        return got if len(got) == len(need) else None

    with ThreadPoolExecutor(max_workers=len(groups)) as ex:
        parts = list(ex.map(part, groups))
    if any(p is None for p in parts):
        return None
    return {k: v for p in parts for k, v in p.items()}


def _decode_frames(path, indices, crop=(0.0, 0.0, 0.0, 0.0), pts_fps=None):
    """Decode exactly `indices` (original frame numbers) at full resolution, cropped.

    Each frame is cropped as it is decoded and kept as its own copy. A crop is a
    view, and the views used to keep every uncropped 1080p frame alive until the end.

    Sequential rather than seeking: these clips are long-GOP VP9/H.264, where seeking
    to an arbitrary frame means decoding from the previous keyframe anyway, and a
    single ordered pass is both simpler and no slower for a set this dense.
    """
    import av

    want = set(int(i) for i in indices)
    out, n, t_first = {}, 0, None
    container = av.open(path)
    container.streams.video[0].thread_type = "AUTO"
    try:
        for i, frame in enumerate(container.decode(video=0)):
            n = i
            if pts_fps and frame.time is not None:          # number frames by timestamp
                t_first = frame.time if t_first is None else t_first
                n = int(round((frame.time - t_first) * pts_fps))
            if n in want:
                # .copy(), not ascontiguousarray: a top-and-bottom crop is already
                # contiguous, so that returned the view and kept the frame alive.
                out[n] = apply_crop(frame.to_ndarray(format="bgr24"), crop).copy()
                if len(out) == len(want):
                    break
    finally:
        container.close()
    missing = want - set(out)
    if missing:
        raise RuntimeError(f"second pass could not decode frames {sorted(missing)[:5]}")
    return out


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
