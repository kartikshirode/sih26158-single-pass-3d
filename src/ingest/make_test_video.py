"""
Generate a REAL 1080p drone video with a DJI-format SRT sidecar.

Why this exists. The problem statement's mandatory input is a video
("Drone video (1080p/4K)" + "GPS coordinates" + "flight metadata"), and until now the
pipeline consumed synthetic poses in memory or still JPEGs - never a video file. That
meant stage S1 (demux, decode, SRT parsing, keyframing) was specified but never
exercised, which is exactly where the unknown-dataset risk lives.

This renders the synthetic single pass, encodes it to H.264 at 1080p30, and writes a
sidecar in the modern DJI SRT layout so the parser is tested against the real format
rather than a convenient one. Motion blur and compression are applied, so the blur
rejection in S1 has something genuine to reject.

Usage:
    python src/ingest/make_test_video.py data/test_flight.mp4 --seconds 20
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from simscene.scene import build_scene, SceneSpec, single_pass, Camera   # noqa: E402
from simscene.render import render_view, shade_faces, apply_motion_blur  # noqa: E402
from eval3d.gnss import CONSUMER_GNSS, RTK_GNSS, simulate_gnss_error     # noqa: E402


# --------------------------------------------------------------------------------------
# ENU -> geodetic, so the SRT carries real lat/lon the way a drone would
# --------------------------------------------------------------------------------------

WGS84_A = 6378137.0
WGS84_E2 = (1 / 298.257223563) * (2 - 1 / 298.257223563)


def enu_to_geodetic(enu, lat0, lon0, h0):
    la, lo = np.radians(lat0), np.radians(lon0)
    N0 = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(la) ** 2)
    o = np.array([(N0 + h0) * np.cos(la) * np.cos(lo),
                  (N0 + h0) * np.cos(la) * np.sin(lo),
                  (N0 * (1 - WGS84_E2) + h0) * np.sin(la)])
    R = np.array([[-np.sin(lo), np.cos(lo), 0.0],
                  [-np.sin(la) * np.cos(lo), -np.sin(la) * np.sin(lo), np.cos(la)],
                  [np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)]])
    ecef = np.asarray(enu) @ R + o
    x, y, z = ecef[:, 0], ecef[:, 1], ecef[:, 2]
    lon = np.arctan2(y, x)
    p = np.hypot(x, y)
    lat = np.arctan2(z, p * (1 - WGS84_E2))
    for _ in range(6):
        N = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(lat) ** 2)
        h = p / np.cos(lat) - N
        lat = np.arctan2(z, p * (1 - WGS84_E2 * N / (N + h)))
    N = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(lat) ** 2)
    h = p / np.cos(lat) - N
    return np.degrees(lat), np.degrees(lon), h


def srt_timestamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(path, lat, lon, rel_alt, abs_alt, yaw, pitch, fps, focal_mm=24.0):
    """
    Modern DJI SRT layout (Mavic 3 generation).

    Deliberately faithful, including the traps the parser has to survive:
      - fields packed several to a bracket ([rel_alt: .. abs_alt: ..])
      - a <font> wrapper around the payload
      - FrameCnt / DiffTime preamble
      - abs_alt = rel_alt + a CONSTANT takeoff offset, because on real DJI files it is
        a barometric channel, not an independent GNSS height.
    """
    n = len(lat)
    dt_ms = 1000.0 / fps
    with open(path, "w", encoding="utf-8") as f:
        for i in range(n):
            t0 = srt_timestamp(i / fps)
            t1 = srt_timestamp((i + 1) / fps)
            f.write(f"{i + 1}\n{t0} --> {t1}\n")
            f.write(f'<font size="28">FrameCnt: {i + 1}, DiffTime: {dt_ms:.0f}ms\n')
            f.write(f"2026-09-05 10:{(i // 60) % 60:02d}:{(i % 60):02d}.{(i * 33) % 1000:03d}\n")
            f.write("[iso: 100] [shutter: 1/800.0] [fnum: 2.8] [ev: 0] "
                    "[color_md : default] [ae_meter_md: 1]\n")
            f.write(f"[focal_len: {focal_mm:.2f}] [dzoom_ratio: 1.00], "
                    f"[latitude: {lat[i]:.6f}] [longitude: {lon[i]:.6f}]\n")
            f.write(f"[rel_alt: {rel_alt[i]:.3f} abs_alt: {abs_alt[i]:.3f}] "
                    f"[gb_yaw: {yaw[i]:.1f} gb_pitch: {pitch[i]:.1f} gb_roll: 0.0] </font>\n\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="data/test_flight.mp4")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--alt", type=float, default=110.0)
    ap.add_argument("--pitch", type=float, default=60.0)
    ap.add_argument("--gnss", choices=["consumer", "rtk"], default="rtk")
    ap.add_argument("--lat", type=float, default=28.6139)     # Delhi
    ap.add_argument("--lon", type=float, default=77.2090)
    ap.add_argument("--site-alt", type=float, default=250.0)
    ap.add_argument("--crf", type=int, default=26, help="higher = more compression artefacts")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    import av

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    n_frames = int(a.seconds * a.fps)
    rng = np.random.default_rng(a.seed)

    scene = build_scene(SceneSpec(seed=a.seed))
    cam = Camera(width=a.width, height=a.height)
    pos, R = single_pass(scene, n_frames=n_frames, alt=a.alt, pitch_deg=a.pitch)

    spec = RTK_GNSS if a.gnss == "rtk" else CONSUMER_GNSS
    gps_enu = pos + simulate_gnss_error(n_frames, 1.0 / a.fps, spec, rng)
    lat, lon, h_ell = enu_to_geodetic(gps_enu, a.lat, a.lon, a.site_alt)

    # abs_alt on a real DJI file is barometric: rel_alt plus a fixed takeoff offset.
    rel_alt = gps_enu[:, 2] - gps_enu[0, 2] + a.alt
    abs_alt = rel_alt + (a.site_alt - a.alt)
    yaw = np.full(n_frames, 0.0)
    pitch_arr = np.full(n_frames, -(90.0 - a.pitch))

    face_rgb = shade_faces(scene.mesh, scene.labels, rng=np.random.default_rng(11))
    V = np.asarray(scene.mesh.vertices)
    F = np.asarray(scene.mesh.faces)

    container = av.open(a.out, mode="w")
    stream = container.add_stream("libx264", rate=a.fps)
    stream.width, stream.height = a.width, a.height
    stream.pix_fmt = "yuv420p"
    stream.options = {"crf": str(a.crf), "preset": "medium"}

    print(f"rendering {n_frames} frames at {a.width}x{a.height} -> {a.out}")
    for i in range(n_frames):
        img, _ = render_view(V, F, face_rgb, pos[i], R[i], cam.K,
                             a.width, a.height, rng=rng)
        # Motion blur on a duty cycle, so ~1 frame in 6 is genuinely degraded and the
        # keyframe selector has real blur to reject rather than a synthetic flag.
        if i % 6 == 0:
            img = apply_motion_blur(img, px=int(rng.integers(5, 11)))
        frame = av.VideoFrame.from_ndarray(img, format="rgb24")
        for packet in stream.encode(frame):
            container.mux(packet)
        if i % 60 == 0:
            print(f"  {i}/{n_frames}", end="\r", flush=True)

    for packet in stream.encode():
        container.mux(packet)
    container.close()

    srt = os.path.splitext(a.out)[0] + ".SRT"
    write_srt(srt, lat, lon, rel_alt, abs_alt, yaw, pitch_arr, a.fps)

    size_mb = os.path.getsize(a.out) / 1e6
    print(f"\nwrote {a.out}  {size_mb:.1f} MB  ({n_frames} frames, {a.seconds:.0f}s @ {a.fps}fps)")
    print(f"wrote {srt}  ({n_frames} SRT blocks, DJI Mavic-3 layout, {a.gnss.upper()} GPS)")
    print(f"site {a.lat:.4f}, {a.lon:.4f}   H.264 crf={a.crf}   1-in-6 frames motion-blurred")


if __name__ == "__main__":
    main()
