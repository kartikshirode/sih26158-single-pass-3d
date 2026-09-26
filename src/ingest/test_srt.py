"""
EXP-23: does any telemetry schema crash S1, or worse, parse wrong without saying so?

Run:  python src/ingest/test_srt.py

Two halves. The first reads the twenty real DJI files under fixtures/dji_srt (MIT,
JuanIrache/DJI_SRT_Parser) and pins what each must yield: position, height, fix count,
frame counter, time base, unit flags. The values come from reading the files by hand
and from the reference parser's own interpretation (research/04-dji-srt-formats.md).
The second half is fuzz: the deformations `docs/12` EXP-23 lists, written to a temp
directory. Pass is zero exceptions and every file either parsed or empty.

The alignment helper is tested last, because it is where the old code was wrong in a
way no fixture would show: positional lookup on a one-record-per-second file.
"""
from __future__ import annotations

import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ingest.video_ingest import parse_dji_srt, telemetry_for_frames  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures", "dji_srt")
FAILED: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def near(a, b, tol=1e-6):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def section(t):
    print(f"\n{t}")


# ------------------------------------------------------------------ real files
section("T1: the real files, one expectation each")

# file: (records expected?, lat, lon, height, extras)
EXPECT = {
    "MAVIC3.srt":            (3.41531, -3.37440, -2.400,
                              {"frame_cnt": 1, "focal_len": 24.0, "t_us": 0}),
    "air2s.srt":             (41.424724, 2.234156, 117.0,
                              {"frame_cnt": 1, "focal_len": 24.0, "flag": "focal_len_x10"}),
    "mavic_air2.srt":        (41.420684, 2.162162, 27.3, {"focal_len": 24.0}),
    "m2zoom.SRT":            (31.452012, 74.398751, 213.983002, {"focal_len": 24.0}),
    "broken_incomplete2.SRT": (-34.869950, -57.823395, 74.725998,
                               {"focal_len": 28.0, "flag": "focal_len_x10"}),
    "mavic_2pro_new.SRT":    (-35.080155, -60.286702, None,
                              {"frame_cnt": 218, "flag": "no_height"}),
    "mavic_2_style.SRT":     (-20.2533, 149.0251, None,
                              {"flag": "t_from_wall_clock", "t_us": 0}),
    "matrice_300.srt":       (36.6146, -6.1120, 0.3, {"flag": "gps_tuple_m300", "t_us": 0}),
    "mavic_pro.SRT":         (-20.2533, 149.0251, 1.9,
                              {"satellites": 16, "flag": "gps_tuple_lon_lat",
                               "t_us": 1_000_000}),
    "mavic_pro_buggy.SRT":   (42.4668, -1.2218, 0.0, {"satellites": 11}),
    "old_format.SRT":        (-20.2533, 149.0251, 1.9, {"satellites": 16}),
    "broken_incomplete.SRT": (-34.7383, -58.4563, 20.1, {"satellites": 19}),
    "p4_rtk.SRT":            (-34.237922, -58.851745, 85.80, {"satellites": 15, "t_us": 0}),
    "p4p_sample.SRT":        (47.4692, 8.2090, 45.60, {"satellites": 18}),
    "mavic_mini.SRT":        (48.0771, -121.7458, 200.70, {"satellites": 17}),
    "mix_p4rtk_mavic2pro.srt": (-34.650200, -59.409424, 17.39,
                                {"satellites": 16, "t_us": 904_904_000}),
}
EMPTY = ("mavic_air.SRT", "broken_empty.SRT", "broken_empty2.SRT")

for name, (lat, lon, h, extra) in EXPECT.items():
    recs = parse_dji_srt(os.path.join(FIX, name))
    if not recs:
        check(f"{name}: parsed", False, "no records")
        continue
    r = recs[0]
    ok = near(r["latitude"], lat) and near(r["longitude"], lon)
    ok &= (r["height"] is None) if h is None else near(r["height"], h, 1e-3)
    for k, v in extra.items():
        if k == "flag":
            ok &= v in r["flags"]
        else:
            ok &= near(r.get(k), v, 1e-3)
    check(f"{name}: first record", ok,
          f"{len(recs)} recs  lat {r['latitude']} lon {r['longitude']} h {r['height']} "
          f"flags {r['flags']}" + ("" if ok else f"  expected {lat},{lon},{h},{extra}"))

recs = parse_dji_srt(os.path.join(FIX, "Mini_SE.SRT"))
check("Mini SE: the 12 MB debug-dump format still yields a track",
      len(recs) > 100 and near(recs[0]["latitude"], -43.0639) and near(recs[0]["longitude"], 91.458),
      f"{len(recs)} recs")

for name in EMPTY:
    recs = parse_dji_srt(os.path.join(FIX, name))
    check(f"{name}: no position, no records, no exception", recs == [])

# Every record of every file keeps its coordinates on the planet and its height sane.
bad = []
for name in os.listdir(FIX):
    if not name.lower().endswith(".srt"):
        continue
    for r in parse_dji_srt(os.path.join(FIX, name)):
        if not (-90 <= r["latitude"] <= 90 and -180 <= r["longitude"] <= 180):
            bad.append(name)
        if r["height"] is not None and abs(r["height"]) > 10_000:
            bad.append(name + " height")
check("every record of every file is on the planet and below 10 km", not bad, str(set(bad)))

# The Mavic 2 legacy file has no timing line; the time base must still be monotonic.
recs = parse_dji_srt(os.path.join(FIX, "mavic_2_style.SRT"))
ts = [r["t_us"] for r in recs]
d = np.diff(ts)
check("wall-clock time base is monotonic, at one record per second",
      ts == sorted(ts) and len(d) and float(np.median(d)) == 1_000_000,
      f"{len(ts)} records, gaps {sorted(set(d.tolist()))[:6]}")

# ------------------------------------------------------------------ fuzz
section("T2: fuzz - the deformations docs/12 EXP-23 lists")

MODERN = ('1\n00:00:00,000 --> 00:00:00,033\n<font size="28">FrameCnt: 1, DiffTime: 33ms\n'
          '2026-01-30 09:58:21.637\n[iso: 100] [shutter: 1/1250.0] [fnum: 2.2] [ev: -1.3] '
          '[focal_len: 24.00] [latitude: 28.613900] [longitude: 77.209000] '
          '[rel_alt: 57.200 abs_alt: 204.644] </font>\n\n')
LEGACY = ('1\n00:00:00,000 --> 00:00:01,000\nF/5.6, SS 400, ISO 100, EV 0, '
          'GPS (77.209000, 28.613900, 15), HOME (77.208000, 28.613000, 210.00m), '
          'D 10.00m, H 57.20m, H.S 0.00m/s, V.S 0.00m/s\n\n')

tmp = tempfile.mkdtemp(prefix="srtfuzz_")


def write(name, data: bytes) -> str:
    p = os.path.join(tmp, name)
    with open(p, "wb") as f:
        f.write(data)
    return p


def block(i, body):
    return f"{i}\n00:00:{i:02d},000 --> 00:00:{i + 1:02d},000\n{body}\n\n"


cases = {
    "crlf": MODERN.replace("\n", "\r\n").encode(),
    "bom": b"\xef\xbb\xbf" + MODERN.encode(),
    "utf16_garbage": MODERN.encode("utf-16"),
    "binary": bytes(range(256)) * 40,
    "empty": b"",
    "index_only": b"1\n",
    "truncated_mid_block": (MODERN + MODERN.replace("FrameCnt: 1", "FrameCnt: 2"))[:-60].encode(),
    "no_arrow_line": MODERN.replace("00:00:00,000 --> 00:00:00,033\n", "").encode(),
    "no_rel_alt": MODERN.replace("[rel_alt: 57.200 abs_alt: 204.644] ", "").encode(),
    "longtitude": MODERN.replace("longitude", "longtitude").encode(),
    "focal_x10": MODERN.replace("focal_len: 24.00", "focal_len : 240").encode(),
    "fnum_x100": MODERN.replace("fnum: 2.2", "fnum : 220").encode(),
    "zeros_before_fix": MODERN.replace("28.613900", "0.000000").replace("77.209000", "0.000000").encode(),
    "off_planet": MODERN.replace("28.613900", "95.5").encode(),
    "nan_inf": MODERN.replace("28.613900", "nan").replace("57.200", "inf").encode(),
    "huge_number": MODERN.replace("57.200", "9" * 400).encode(),
    "giant_line": (MODERN[:-8] + "x" * 1_000_000 + "\n\n").encode(),
    "legacy": LEGACY.encode(),
    "legacy_hs_only": LEGACY.replace("H 57.20m, ", "").encode(),
    "mixed_families": (MODERN + LEGACY.replace("1\n00:00:00,000 --> 00:00:01,000",
                                               "2\n00:00:01,000 --> 00:00:02,000")).encode(),
    "date_variants": "".join(block(i, d + "\n[latitude: 1.0] [longitude: 2.0]") for i, d in
                             enumerate(["2017.8.5 14:11:51", "2019-09-27 10:28:08,438,904",
                                        "2021-12-25 12:27:52.373", "0000-00-00 99:99:99",
                                        "not a date"])).encode(),
}

results = {}
for name, data in cases.items():
    p = write(name + ".SRT", data)
    try:
        results[name] = parse_dji_srt(p)
        err = None
    except Exception as e:                       # the test is that this never happens
        results[name] = None
        err = f"{type(e).__name__}: {e}"
    check(f"{name}: no exception", err is None, err or f"{len(results[name])} recs")

r = results


def first(name):
    return r[name][0] if r.get(name) else {}


check("crlf and bom parse identically to lf", first("crlf") == first("bom") and r["crlf"])
check("binary, empty and index-only files give no records",
      r["binary"] == [] and r["empty"] == [] and r["index_only"] == [])
check("truncated file keeps the complete block", len(r["truncated_mid_block"]) >= 1)
check("no timing line: the wall clock becomes the time base, and the record says so",
      first("no_arrow_line").get("t_us") == 0
      and "t_from_wall_clock" in first("no_arrow_line")["flags"])
check("missing rel_alt gives height None and says so",
      first("no_rel_alt").get("height") is None and "no_height" in first("no_rel_alt")["flags"])
check("longtitude is longitude", near(first("longtitude").get("longitude"), 77.209))
check("focal_len 240 and 24.00 both mean 24 mm, and the x10 one is flagged",
      near(first("focal_x10").get("focal_len"), 24.0) and near(first("crlf").get("focal_len"), 24.0)
      and "focal_len_x10" in first("focal_x10")["flags"])
check("GPS(0,0) before a fix is dropped, not a point in the Gulf of Guinea",
      r["zeros_before_fix"] == [])
check("a latitude of 95.5 is dropped", r["off_planet"] == [])
check("nan and inf never become numbers", r["nan_inf"] == [] or
      all(np.isfinite(v) for v in first("nan_inf").values() if isinstance(v, float)))
check("a 400-digit height does not raise", r["huge_number"] is not None)
check("a 1 MB line does not raise", r["giant_line"] is not None)
leg = first("legacy")
check("legacy tuple is (lon, lat, satellites) and H is the height",
      near(leg.get("latitude"), 28.6139) and near(leg.get("longitude"), 77.209)
      and leg.get("satellites") == 15 and near(leg.get("height"), 57.2, 1e-3)
      and "gps_tuple_lon_lat" in leg["flags"])
check("H.S is never mistaken for H", first("legacy_hs_only").get("height") is None)
check("a file mixing families parses both", len(r["mixed_families"]) == 2 and
      near(r["mixed_families"][1].get("height"), 57.2, 1e-3))
dv = r["date_variants"]
check("three date spellings parse and two impossible ones only set a flag",
      len(dv) == 5 and sum("wall_us" in x for x in dv) == 3
      and all("t_us" in x for x in dv))         # timing lines carry the time base here

# ------------------------------------------------------------------ alignment
section("T3: keyframe alignment is keyed, never positional")

per_frame = [{"frame_cnt": c, "latitude": float(c), "longitude": 0.0, "height": 1.0, "flags": []}
             for c in (1, 2, 4, 5)]           # block 3 had no fix and was dropped
got = telemetry_for_frames(per_frame, [0, 1, 2, 3, 4], fps=30.0)
check("FrameCnt keys the lookup, and a dropped block leaves a hole rather than a shift",
      [g.get("latitude") for g in got] == [1.0, 2.0, None, 4.0, 5.0],
      str([g.get("latitude") for g in got]))

one_hz = [{"t_us": int(i * 1e6), "latitude": float(i), "longitude": 0.0, "height": 1.0,
           "flags": []} for i in range(60)]
got = telemetry_for_frames(one_hz, [0, 46, 300, 1799, 1800 * 3], fps=30.0)
check("a one-record-per-second file is looked up by time at the clip's frame rate, "
      "between fixes by interpolation",
      all(near(a, b) for a, b in zip([g.get("latitude") for g in got][:3], [0.0, 46 / 30, 10.0])),
      str([g.get("latitude") for g in got]))
check("a frame inside the last record's second keeps that record",
      got[3].get("latitude") == 59.0, str(got[3].get("latitude")))
check("a frame past the end of the telemetry gets nothing, not the last record",
      got[4] == {})
check("frame 300 positional would have been record 300; keyed by time it is record 10",
      got[2].get("latitude") == 10.0)
got = telemetry_for_frames([{"latitude": 1.0, "longitude": 2.0, "height": None, "flags": []}],
                           [0, 1], fps=30.0)
check("records with neither counter nor time yield nothing rather than a guess",
      got == [{}, {}])
check("no records: one empty dict per frame", telemetry_for_frames([], [0, 1, 2], 30.0) == [{}] * 3)

# Variable frame rate (audit F-13). Index / average rate is a time only at a constant
# rate; the lookup must use the frame's presentation time when it has one.
got = telemetry_for_frames(one_hz, [30, 31], fps=30.0, times_s=[3.0, None])
check("a presentation time keys the lookup; a frame without one falls back to index / fps",
      [g.get("latitude") for g in got] == [3.0, 31 / 30] or
      all(near(a, b) for a, b in zip([g.get("latitude") for g in got], [3.0, 31 / 30])),
      str([g.get("latitude") for g in got]))
yaw = [{"t_us": 0, "latitude": 0.0, "longitude": 0.0, "height": 1.0, "gb_yaw": 170.0,
        "flags": []},
       {"t_us": 1_000_000, "latitude": 0.0, "longitude": 0.0, "height": 1.0,
        "gb_yaw": -170.0, "flags": []}]
got = telemetry_for_frames(yaw, [15], fps=30.0)
check("a yaw across +-180 is interpolated the short way round",
      near(abs(got[0].get("gb_yaw", 0)), 180.0), str(got[0].get("gb_yaw")))
got = telemetry_for_frames(one_hz, [int(-0.7 * 30)], fps=30.0, times_s=[-0.7])
check("a frame well before the first fix gets nothing", got == [{}], str(got))

try:
    import av
    from fractions import Fraction
    from ingest.video_ingest import timed_frames
except ImportError as e:                      # CI installs av; a bare checkout may not
    print(f"  SKIP  variable-frame-rate clip: {e}")
else:
    # 30 frames at 10 fps, then 60 at 30 fps, in a stream that declares 30 fps. Frame
    # 30 is shown at 3.0 s; at the declared rate it would be looked up at 1.0 s.
    vfr = os.path.join(tempfile.mkdtemp(), "vfr.mkv")
    out = av.open(vfr, "w")
    st = out.add_stream("mpeg4", rate=30)
    st.width, st.height, st.pix_fmt = 64, 64, "yuv420p"
    st.codec_context.time_base = Fraction(1, 1000)
    for i, ms in enumerate([k * 100 for k in range(30)] +
                           [3000 + round(k * 1000 / 30) for k in range(60)]):
        fr = av.VideoFrame.from_ndarray(np.full((64, 64, 3), i, np.uint8), format="rgb24")
        fr.pts, fr.time_base = ms, Fraction(1, 1000)
        for pk in st.encode(fr):
            out.mux(pk)
    for pk in st.encode():
        out.mux(pk)
    out.close()
    c = av.open(vfr)
    rate = float(c.streams.video[0].average_rate)
    times = {n: t for n, _, t in timed_frames(c)}
    c.close()
    got = telemetry_for_frames(one_hz, [30, 89], fps=rate, times_s=[times[30], times[89]])
    old = telemetry_for_frames(one_hz, [30, 89], fps=rate)
    check("on a variable-frame-rate clip, frame 30 (shown at 3.0 s) gets the 3 s fix",
          near(got[0].get("latitude"), 3.0) and near(got[1].get("latitude"), times[89], 1e-3),
          f"times {times[30]}, {times[89]}; got {[g.get('latitude') for g in got]}")
    check("index / declared rate would have given it the 1 s fix",
          old[0].get("latitude") == 1.0, str([g.get("latitude") for g in old]))

print()
if FAILED:
    print(f"{len(FAILED)} TEST(S) FAILED: {FAILED}")
    sys.exit(1)
print("ALL PASS")
