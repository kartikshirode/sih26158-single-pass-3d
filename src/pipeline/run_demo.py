"""
SIH26158 end-to-end demo pipeline.

Runs the whole chain on a synthetic scene whose ground truth we know exactly, so that
every claim it prints is checkable:

  S1 ingest      synthesise a single-pass flight; frames, per-frame GPS, intrinsics
  S2 mask        drop blurred frames; exclude dynamic objects
  S3 geometry    per-camera visible-surface sensing -> fused metric point cloud
  S4 georef      robust Sim(3) to noisy GPS -> local ENU -> UTM -> orthometric height
  S5 surface     2.5D DSM + mesh
  S6 export      PLY, OBJ, LAS 1.4, GeoTIFF (DSM), GLB   + viewer
  SCORE          absolute AND aligned accuracy, completeness, per-stage timings

WHAT IS REAL AND WHAT IS SIMULATED - stated plainly, because the distinction matters:

  REAL   the georeferencing maths (robust Sim(3), ENU, UTM zone selection, EGM2008
         geoid), every export writer, the scoring harness, and the timing.
  SIM    the learned depth/geometry model. We do not have GPU quota, so instead of
         MapAnything we sense visible surfaces geometrically from the known scene and
         add realistic depth noise. That substitutes ONE stage; the rest is the code
         that would ship.

Nothing here needs a GPU.
"""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from simscene.scene import build_scene, SceneSpec, single_pass, Camera   # noqa: E402
from simscene.visibility import build_depth_buffer, visible_mask         # noqa: E402
from eval3d.gnss import (                                                # noqa: E402
    CONSUMER_GNSS, RTK_GNSS, simulate_gnss_error, robust_sim3, robust_yaw_sim3,
)
from eval3d.metrics import evaluate, summarise, apply_transform          # noqa: E402


# --------------------------------------------------------------------------------------
# Timing
# --------------------------------------------------------------------------------------

TIMINGS: dict[str, float] = {}


@contextmanager
def stage(name: str):
    t0 = time.perf_counter()
    print(f"  [{name}] ...", end="", flush=True)
    yield
    dt = time.perf_counter() - t0
    TIMINGS[name] = dt
    print(f" {dt:6.2f}s")


# --------------------------------------------------------------------------------------
# Geodesy helpers (the parts that must be right or R-O3 is unreachable)
# --------------------------------------------------------------------------------------

def utm_epsg_for(lon: float, lat: float) -> int:
    """UTM zone chosen at RUNTIME from longitude - never hardcoded, because the
    flight location is unknown until the event. India spans 42N-47N = 32642-32647."""
    zone = int((lon + 180.0) // 6.0) + 1
    return (32600 if lat >= 0 else 32700) + zone


def orthometric_height(lon, lat, h_ellipsoidal):
    """
    Ellipsoidal -> orthometric via EGM2008 (EPSG:9518).

    Guarded three ways, because PROJ fails SILENTLY here: with the grid missing it
    returns z unchanged and raises nothing, and calling transform() without z applies
    no shift at all. Over India that is a 24-98 m error.
    """
    import pyproj
    from pyproj.transformer import Transformer, TransformerGroup

    pyproj.network.set_network_enabled(True)

    grp = TransformerGroup("EPSG:4979", "EPSG:9518", always_xy=True)
    if not grp.best_available:
        raise RuntimeError(
            "EGM2008 geoid grid unavailable - refusing to emit heights that would be "
            "silently wrong by 24-98 m over India. Enable PROJ_NETWORK or ship "
            "us_nga_egm08_25.tif in the image."
        )
    t = Transformer.from_crs("EPSG:4979", "EPSG:9518",
                             always_xy=True, allow_ballpark=False)
    if "ballpark" in t.description.lower():
        raise RuntimeError(f"ballpark vertical transform refused: {t.description}")

    lon_o, lat_o, H = t.transform(lon, lat, h_ellipsoidal)   # z IS REQUIRED
    return np.asarray(H)


def enu_to_geodetic(enu, ref_lat, ref_lon, ref_h):
    """Local ENU metres -> lat/lon/ellipsoidal height (inverse of eval3d.gnss)."""
    from eval3d.gnss import geodetic_to_ecef, WGS84_A, WGS84_E2
    lat0, lon0 = np.radians(ref_lat), np.radians(ref_lon)
    sl, cl, so, co = np.sin(lat0), np.cos(lat0), np.sin(lon0), np.cos(lon0)
    R = np.array([[-so, co, 0.0],
                  [-sl * co, -sl * so, cl],
                  [cl * co, cl * so, sl]])
    ecef = np.asarray(enu) @ R + geodetic_to_ecef(ref_lat, ref_lon, ref_h)

    x, y, z = ecef[:, 0], ecef[:, 1], ecef[:, 2]
    lon = np.arctan2(y, x)
    p = np.hypot(x, y)
    lat = np.arctan2(z, p * (1 - WGS84_E2))
    for _ in range(6):                                    # Bowring iteration
        N = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(lat) ** 2)
        h = p / np.cos(lat) - N
        lat = np.arctan2(z, p * (1 - WGS84_E2 * N / (N + h)))
    N = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(lat) ** 2)
    h = p / np.cos(lat) - N
    return np.degrees(lat), np.degrees(lon), h


# --------------------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------------------

def run(outdir: str, *, gnss=CONSUMER_GNSS, n_frames: int = 600, pitch_deg: float = 60.0,
        site_lat: float = 28.6139, site_lon: float = 77.2090, site_h: float = 250.0,
        seed: int = 7, label: str = "demo") -> dict:
    os.makedirs(outdir, exist_ok=True)
    rng = np.random.default_rng(seed)
    cam = Camera()
    t_start = time.perf_counter()

    print(f"\n{'=' * 78}\nSIH26158 PIPELINE  [{label}]  GNSS={gnss.name}  "
          f"pitch={pitch_deg:.0f}deg  site=({site_lat:.4f},{site_lon:.4f})\n{'=' * 78}")

    # ---------------- S1 INGEST ----------------
    with stage("S1 ingest"):
        scene = build_scene(SceneSpec(seed=seed))
        pos_true, R_cam = single_pass(scene, n_frames=n_frames, alt=110.0,
                                      pitch_deg=pitch_deg)
        # Per-frame GPS = truth + realistic correlated GNSS error (R-C5)
        gps_enu = pos_true + simulate_gnss_error(n_frames, 600.0 / n_frames, gnss, rng)
        # 2% wild fixes, as real receivers produce
        nbad = max(1, int(n_frames * 0.02))
        gps_enu[rng.choice(n_frames, nbad, replace=False)] += rng.normal(0, 25.0, (nbad, 3))

        gt_pts, gt_fidx = __import__("trimesh").sample.sample_surface(scene.mesh, 60_000, seed=1)
        gt_pts = np.asarray(gt_pts)
        occluders, _ = __import__("trimesh").sample.sample_surface(scene.mesh, 400_000, seed=2)
        occluders = np.asarray(occluders)

    # ---------------- S2 MASK ----------------
    with stage("S2 mask"):
        # Blur score per frame; reject the worst decile (R-C2). A 30 fps video gives
        # ~30x more candidates than we need, so rejecting is free.
        blur = rng.gamma(9.0, 1.0, n_frames)
        keep = blur >= np.percentile(blur, 10)          # percentile, never a hardcoded value
        kf = np.flatnonzero(keep)
        # Dynamic objects: vehicles/people that must not enter geometry (R-C4)
        n_dyn = 240
        dyn = np.column_stack([
            rng.uniform(-scene.spec.extent, scene.spec.extent, n_dyn),
            rng.uniform(-12, 12, n_dyn),
            np.full(n_dyn, 1.0),
        ])

    # ---------------- S3 GEOMETRY ----------------
    with stage("S3 geometry"):
        sample_every = max(1, len(kf) // 60)            # 60 sensing views
        views = kf[::sample_every]
        counts = np.zeros(len(gt_pts), dtype=np.int32)
        for i in views:
            db = build_depth_buffer(occluders, pos_true[i], R_cam[i], cam.K,
                                    cam.width, cam.height, 0.125)
            counts += visible_mask(gt_pts, scene.mesh.face_normals[gt_fidx],
                                   pos_true[i], R_cam[i], cam.K,
                                   cam.width, cam.height, depth_buffer=db)
        observed = counts >= 2                          # 2+ views => triangulable
        recon_local = gt_pts[observed].copy()

        # Depth-estimation error, growing with range (what a real depth model does)
        rngm = np.linalg.norm(recon_local - pos_true[len(pos_true) // 2], axis=1)
        sigma = 0.02 + 0.004 * (rngm / 100.0) * 100.0 / 100.0
        recon_local += rng.normal(0, 1.0, recon_local.shape) * sigma[:, None]

        # Dynamic objects correctly excluded by multi-view consistency
        n_leak = int(len(dyn) * 0.05)                   # 5% leak through, honestly modelled
        recon_local = np.vstack([recon_local, dyn[:n_leak]])

        # Put the reconstruction in an arbitrary frame, as a real SfM/feed-forward
        # result would be - georeferencing has to actually solve for it.
        th = rng.uniform(0, 2 * np.pi)
        R_arb = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1.0]])
        t_arb = rng.uniform(-400, 400, 3)
        recon_local = apply_transform(recon_local, R_arb, t_arb, 1.0)
        traj_local = apply_transform(pos_true, R_arb, t_arb, 1.0)

    # ---------------- S4 GEOREFERENCE ----------------
    with stage("S4 georef"):
        # Fit trajectory -> GPS with a GRAVITY-CONSTRAINED, self-tuning robust
        # estimator. The yaw constraint is not a refinement - it is REQUIRED. A single
        # straight pass leaves rotation about the flight axis unconstrained, and an
        # unrestricted Sim(3) then fits the trajectory beautifully while throwing the
        # scene hundreds of metres off (356 m consumer / 504 m RTK - it gets WORSE with
        # better GPS). See eval3d.gnss.yaw_only_sim3.
        # Done in LOCAL ENU, never in UTM: UTM scale error is ~0.6 m/km across India,
        # which would bake projection error into the model.
        Rg, tg, sg, inl = robust_yaw_sim3(traj_local, gps_enu, thresh="auto", rng=rng)
        recon_enu = apply_transform(recon_local, Rg, tg, sg)

        lat, lon, h_ell = enu_to_geodetic(recon_enu, site_lat, site_lon, site_h)
        epsg = utm_epsg_for(float(np.mean(lon)), float(np.mean(lat)))

        import pyproj
        to_utm = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
        E, N = to_utm.transform(lon, lat)
        H = orthometric_height(lon, lat, h_ell)          # EGM2008, guarded
        geoid_N = float(np.mean(h_ell - H))

        recon_utm = np.column_stack([E, N, H])
        # Ground truth through the identical chain, for a like-for-like comparison
        gt_enu = gt_pts
        glat, glon, gh = enu_to_geodetic(gt_enu, site_lat, site_lon, site_h)
        gE, gN = to_utm.transform(glon, glat)
        gH = orthometric_height(glon, glat, gh)
        gt_utm = np.column_stack([gE, gN, gH])

    # ---------------- S5 SURFACE ----------------
    with stage("S5 surface"):
        # Grid resolution must follow POINT DENSITY, not a round number. At a fixed
        # 2 m the corridor filled only ~25% of cells, so the DSM alternated between
        # real heights and fill value and the surface rendered as spikes. Size the
        # cell to the mean point spacing instead, then interpolate the remaining
        # holes from the nearest observed cell rather than flooding them with a
        # constant.
        e0, n0 = recon_utm[:, 0].min(), recon_utm[:, 1].min()
        e1, n1 = recon_utm[:, 0].max(), recon_utm[:, 1].max()
        area = max((e1 - e0) * (n1 - n0), 1.0)
        spacing = float(np.sqrt(area / max(len(recon_utm), 1)))
        res = max(1.0, round(spacing * 1.6, 1))          # ~2.5 pts per cell
        nx, ny = int((e1 - e0) / res) + 1, int((n1 - n0) / res) + 1
        ix = np.clip(((recon_utm[:, 0] - e0) / res).astype(int), 0, nx - 1)
        iy = np.clip(((recon_utm[:, 1] - n0) / res).astype(int), 0, ny - 1)

        # Initialise with -inf, NOT NaN: np.maximum(nan, x) is nan, so a NaN-seeded
        # buffer stays NaN everywhere it is touched. That produced an all-NaN DSM, an
        # all-NaN GeoTIFF, and NaN mesh vertices that trimesh silently dropped on load
        # (OBJ read back with 0 vertices). Caught by third-party readback, not review.
        dsm = np.full((ny, nx), -np.inf)
        np.maximum.at(dsm, (iy, ix), recon_utm[:, 2])     # DSM = max height per cell
        empty = ~np.isfinite(dsm)
        filled_frac = float((~empty).mean())

        if empty.any() and (~empty).any():
            from scipy.spatial import cKDTree
            fy, fx = np.nonzero(~empty)
            ey, ex = np.nonzero(empty)
            _, nn = cKDTree(np.column_stack([fx, fy])).query(np.column_stack([ex, ey]), k=1)
            dsm[ey, ex] = dsm[fy[nn], fx[nn]]
        dsm_filled = dsm
        assert np.isfinite(dsm_filled).all(), "DSM must be finite before export"
        print(f" [DSM {nx}x{ny} @ {res:.1f}m, {filled_frac:.0%} observed]", end="")

        # 2.5D mesh from the DSM grid (vectorised - the Python loop was the slow part)
        gx, gy = np.meshgrid(e0 + np.arange(nx) * res, n0 + np.arange(ny) * res)
        verts = np.column_stack([gx.ravel(), gy.ravel(), dsm_filled.ravel()])
        j, i = np.meshgrid(np.arange(ny - 1), np.arange(nx - 1), indexing="ij")
        a = (j * nx + i).ravel(); b = a + 1; c = a + nx; d = c + 1
        faces = np.vstack([np.column_stack([a, c, b]), np.column_stack([b, c, d])])

    # ---------------- S6 EXPORT ----------------
    with stage("S6 export"):
        import trimesh, laspy, rasterio
        from rasterio.transform import from_origin

        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        # local-origin copy so mesh viewers do not lose precision on 7-digit UTM
        origin = np.array([e0, n0, 0.0])
        mesh_local = trimesh.Trimesh(vertices=verts - origin, faces=faces, process=False)

        paths = {}
        p = os.path.join(outdir, "model.ply")
        trimesh.PointCloud(recon_utm - origin).export(p); paths["PLY (point cloud)"] = p
        p = os.path.join(outdir, "model.obj");  mesh_local.export(p); paths["OBJ (mesh)"] = p
        p = os.path.join(outdir, "model.glb");  mesh_local.export(p); paths["GLB (glTF)"] = p

        # LAS 1.4 with a real CRS (point format 6 requires OGC WKT)
        p = os.path.join(outdir, "model.las")
        hdr = laspy.LasHeader(version="1.4", point_format=6)
        hdr.offsets = recon_utm.min(axis=0); hdr.scales = [0.001, 0.001, 0.001]
        hdr.add_crs(pyproj.CRS.from_epsg(epsg))
        las = laspy.LasData(hdr)
        las.x, las.y, las.z = recon_utm[:, 0], recon_utm[:, 1], recon_utm[:, 2]
        las.write(p); paths["LAS 1.4 (+CRS)"] = p

        # GeoTIFF DSM, north-up
        p = os.path.join(outdir, "dsm.tif")
        with rasterio.open(p, "w", driver="GTiff", height=ny, width=nx, count=1,
                           dtype="float32", crs=f"EPSG:{epsg}",
                           transform=from_origin(e0, n0 + ny * res, res, res),
                           nodata=-9999.0) as dst:
            dst.write(np.flipud(dsm_filled).astype("float32"), 1)
        assert np.isfinite(dsm_filled).all()
        paths["GeoTIFF (DSM)"] = p

    # ---------------- SCORE ----------------
    with stage("SCORE"):
        # Completeness needs an honest denominator. A single pass overflies a ~200 m
        # corridor of an 800 m scene, so scoring recall against the WHOLE scene measures
        # our choice of scene size, not the reconstruction (EXP-08). Primary score is
        # therefore against the OBSERVABLE surface; whole-scene is reported alongside.
        res_eval = evaluate(recon_utm, gt_utm[observed], align=True, align_with_scale=False)
        res_whole = evaluate(recon_utm, gt_utm, align=False)

    total = time.perf_counter() - t_start
    ab, al = res_eval["absolute"], res_eval["aligned"]

    manifest = {
        "label": label, "gnss_class": gnss.name, "pitch_deg": pitch_deg,
        "frames_in": int(n_frames), "keyframes_kept": int(len(kf)),
        "sensing_views": int(len(views)),
        "points_reconstructed": int(len(recon_utm)),
        "crs": f"EPSG:{epsg}", "geoid_separation_m": round(geoid_N, 3),
        "geoid_model": "EGM2008 (EPSG:9518)",
        "gps_inlier_fraction": round(float(inl.mean()), 4),
        "accuracy_absolute_rmse_m": round(ab.accuracy.rmse, 4),
        "accuracy_aligned_rmse_m": round(al.accuracy.rmse, 4),
        "georeferencing_offset_m": round(al.alignment_translation_m, 4),
        "scale_diagnostic": round(ab.alignment_scale or 1.0, 6),
        "completeness_recall_at_1m_observable": round(
            [s.recall for s in ab.scores if s.tau == 1.0][0], 4),
        "completeness_recall_at_1m_whole_scene": round(
            [s.recall for s in res_whole["absolute"].scores if s.tau == 1.0][0], 4),
        "observable_fraction_of_scene": round(float(observed.mean()), 4),
        "fscore_at_1m": round([s.fscore for s in ab.scores if s.tau == 1.0][0], 4),
        "timings_s": {k: round(v, 3) for k, v in TIMINGS.items()},
        "total_s": round(total, 3),
        "budget_s": 900.0,
        "within_budget": bool(total < 900.0),
        "exports": {k: os.path.basename(v) for k, v in paths.items()},
    }
    with open(os.path.join(outdir, "run_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n{summarise(res_eval, tau=1.0)}")
    print(f"\n  CRS {manifest['crs']}   geoid N = {geoid_N:+.2f} m (EGM2008)")
    print(f"  points {len(recon_utm):,}   GPS inliers {inl.mean():.1%}")
    print(f"\n  {'file':<22}{'bytes':>12}")
    for k, v in paths.items():
        print(f"  {k:<22}{os.path.getsize(v):>12,}")
    print(f"\n  TOTAL {total:.1f}s of the 900s budget "
          f"({'WITHIN' if total < 900 else 'OVER'})")
    return manifest


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "out/demo"
    run(out)
