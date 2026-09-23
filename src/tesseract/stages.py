"""
The stages, in the order docs/13 puts them, each a pure function of its inputs.

Every stage here wraps code that already exists and is already measured - the screener,
the ingest, the georeferencing fit, the export writers. The rebuild is not a rewrite of
the geometry; it is the contracts, the frames, the scale and the ladder made explicit
around it, so that a stage can no longer pass on a length without saying what kind of
length it is.

Geometry has three providers, because this project has three real situations:

  sense    the synthetic scene, sensed geometrically. No GPU, ground truth known.
  adopt    artefacts a real run already produced (the Kolu MVS cloud). This is what
           makes a 34-minute GPU-less pipeline resumable on a laptop.
  request  neither is available: say exactly which command would produce it, and let
           the orchestrator step down the ladder rather than inventing geometry.
"""

from __future__ import annotations

import io
import json
import os
import sys
from dataclasses import dataclass

import numpy as np

from . import contracts as K
from . import scale as scale_svc
from .contracts import Artefact, Code, Frame, StageError, StageResult, Units
from .pipeline import BaseStage, Context

sys.path.insert(0, os.path.join(K.ROOT, "src"))


def _save_npy(ctx: Context, name: str, arr: np.ndarray, *, frame: str,
              units: str, kind: str = "array") -> Artefact:
    rel = f"{name}.npy"
    np.save(ctx.path(rel), arr)
    return Artefact(rel, kind, frame=frame, units=units).stamp(ctx.workdir)


# ------------------------------------------------------------------ S0 · admissibility
@dataclass
class Screen(BaseStage):
    id: str = "S0-screen"
    produces: tuple = ("screen",)
    levels: tuple = ("L0", "L1", "L2", "L3", "L4", "L5")

    def estimate(self, ctx: Context) -> float:
        return 40.0 if hasattr(ctx.source, "path") else 0.05

    def execute(self, ctx: Context) -> StageResult:
        if not hasattr(ctx.source, "path"):           # synthetic input is admissible
            return StageResult(self.id, 0.0, facts={"admissible": True},
                               note="synthetic source: nothing to screen")
        from ingest.screen import screen as screen_clip

        v = screen_clip(ctx.source.path)
        codes = []
        if v["horizon_frac"] > 0.30:
            codes.append(Code.ADM_HORIZON)
        if v["median_sky"] > 0.15:
            codes.append(Code.ADM_SKY)
        if v["shots_detected"] > 1:
            codes.append(Code.ADM_SHOTS)
        if v["static_overlay_px_frac"] > 0.0005:
            codes.append(Code.ADM_OVERLAY)

        rel = "screen.json"
        with io.open(ctx.path(rel), "w", encoding="utf-8") as f:
            json.dump(v, f, indent=2)
        art = Artefact(rel, "verdict").stamp(ctx.workdir)

        # A horizon and the sky above it are the one rejection with a remedy in the
        # pipeline: ingest can crop them off. Refusing the clip before applying the
        # remedy the caller asked for would make --horizon crop unreachable, so the
        # policy is honoured here - the codes stay on the run either way, because the
        # clip did need cropping and the manifest should say so.
        # Of the screener's three rejection thresholds (src/ingest/screen.py), the
        # horizon and the sky above it go away with the crop; a clip that is simply
        # cut too short does not.
        cropping = (ctx.config.get("ingest", {}).get("horizon_policy") == "crop"
                    and v["verdict"] == "REJECT" and v["longest_shot_s"] >= 8)
        if v["verdict"] == "REJECT" and not cropping and not ctx.config.get("force"):
            # Not a crash: a reasoned refusal is the answer (R-C9). The orchestrator
            # walks down to L5, where the verdict itself is the deliverable.
            raise StageError(codes[0] if codes else Code.ADM_SKY,
                             "; ".join(v["reasons"]))
        return StageResult(self.id, 0.0, outputs={"screen": art}, codes=codes,
                           facts={"admissible": True, "screen": v,
                                  "remedied_by_crop": bool(cropping)},
                           note="horizon cropped off rather than refused" if cropping
                                else "")


# ------------------------------------------------------------------ S1 · ingest
@dataclass
class Ingest(BaseStage):
    id: str = "S1-ingest"
    needs: tuple = ()
    produces: tuple = ("keyframes",)
    levels: tuple = ("L0", "L1", "L2", "L3", "L4")

    def estimate(self, ctx: Context) -> float:
        return 90.0 if hasattr(ctx.source, "path") else 0.5

    def execute(self, ctx: Context) -> StageResult:
        if not hasattr(ctx.source, "path"):
            w = ctx.source.world()
            n = len(w["pos"])
            rng = np.random.default_rng(ctx.source.seed + 1)
            blur = rng.gamma(9.0, 1.0, n)
            keep = np.flatnonzero(blur >= np.percentile(blur, 10))   # percentile, never fixed
            art = _save_npy(ctx, "keyframe_index", keep, frame=Frame.F0_SOURCE_PX,
                            units="index")
            return StageResult(self.id, 0.0, outputs={"keyframes": art},
                               facts={"frames_in": n, "keyframes": int(len(keep)),
                                      "has_telemetry": True},
                               note="synthetic flight; blur gate on a modelled score")

        from ingest.video_ingest import ingest_video

        cfg = ctx.config.get("ingest", {})
        r = ingest_video(ctx.source.path,
                         target_keyframes=cfg.get("target_keyframes", 600),
                         horizon_policy=cfg.get("horizon_policy", "reject"),
                         skip_start_s=cfg.get("skip_start_s", 0.0),
                         end_s=cfg.get("end_s"),
                         srt_path=ctx.source.telemetry, progress=False)
        outdir = ctx.path("keyframes/.")
        os.makedirs(os.path.dirname(outdir), exist_ok=True)
        import cv2
        for i, (fi, img) in enumerate(zip(r.keyframe_indices, r.frames)):
            cv2.imwrite(ctx.path("keyframes", f"kf_{i:03d}_f{fi:05d}.jpg"), img,
                        [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        rel = "ingest.json"
        with io.open(ctx.path(rel), "w", encoding="utf-8") as f:
            json.dump({"stats": r.stats, "keyframes": [int(x) for x in r.keyframe_indices],
                       "telemetry": r.telemetry}, f, indent=2)
        art = Artefact(rel, "keyframe-set", frame=Frame.F0_SOURCE_PX).stamp(ctx.workdir)

        # One dict per keyframe, empty where nothing aligned: a list of empties is
        # not telemetry, and bool() of it would say it was.
        has_tel = any(r.telemetry)
        codes = [] if has_tel else [Code.ING_NOGNSS]
        return StageResult(self.id, 0.0, outputs={"keyframes": art}, codes=codes,
                           facts={"frames_in": r.stats.get("frames_decoded"),
                                  "keyframes": r.stats.get("keyframes_selected"),
                                  "srt_records": r.stats.get("srt_records", 0),
                                  "has_telemetry": has_tel})


# ------------------------------------------------------------------ S2 · planner
@dataclass
class PlanKeyframes(BaseStage):
    """
    Pose set and dense set are different problems (docs/13 section 3.2).

    Pose wants every view that improves the graph and costs 0.42-0.55 s/view on a GPU.
    Dense wants an even subset with enough baseline and costs 35-43 s/view on 8 vCPU.
    Sizing them together is what makes the budget unmanageable, so they are sized apart
    and the dense set is the speed knob the ladder turns.
    """

    id: str = "S2-plan"
    needs: tuple = ("keyframes",)
    produces: tuple = ("plan",)
    levels: tuple = ("L0", "L1", "L2", "L3", "L4")

    def execute(self, ctx: Context) -> StageResult:
        n_pose = int(ctx.facts.get("keyframes") or 0)
        want = int(ctx.config.get("dense_views", 300))
        if ctx.level == "L2":
            want //= 2
        n_dense = max(1, min(n_pose, want))
        idx = np.unique(np.linspace(0, max(n_pose - 1, 0), n_dense).astype(int))
        art = _save_npy(ctx, "dense_index", idx, frame=Frame.F0_SOURCE_PX, units="index")
        return StageResult(self.id, 0.0, outputs={"plan": art},
                           facts={"pose_views": n_pose, "dense_views": int(len(idx))})


# ------------------------------------------------------------------ S3 · geometry
@dataclass
class Geometry(BaseStage):
    id: str = "S3-geometry"
    version: str = "2"          # full cam2world poses when the adopted run has them
    needs: tuple = ("plan",)
    produces: tuple = ("points", "cameras")
    levels: tuple = ("L0", "L1", "L2", "L3", "L4")

    # measured rates, docs/13 section 6: feed-forward on a T4, MVS on 8 vCPU
    S_PER_VIEW_POSE_GPU = 0.55
    S_PER_VIEW_DENSE_CPU = 39.0

    def estimate(self, ctx: Context) -> float:
        n_pose = int(ctx.facts.get("pose_views") or 0)
        n_dense = int(ctx.facts.get("dense_views") or 0)
        if ctx.config.get("adopt"):
            return 5.0                                   # reading files, not computing
        if not hasattr(ctx.source, "path"):
            return 0.02 * max(n_pose, 1)
        cost = n_pose * self.S_PER_VIEW_POSE_GPU
        if ctx.level in ("L0", "L1", "L2"):
            cost += n_dense * self.S_PER_VIEW_DENSE_CPU * (0.25 if ctx.level == "L1" else 1.0)
        return cost

    def execute(self, ctx: Context) -> StageResult:
        if ctx.config.get("adopt"):
            return self._adopt(ctx)
        if not hasattr(ctx.source, "path"):
            return self._sense(ctx)
        raise StageError(
            Code.STAGE_UNAVAILABLE,
            "no geometry provider on this host. Run the containers "
            "(gcloud run jobs execute kolu-ma --region=asia-south1 with IN_PREFIX/"
            "OUT_PREFIX/MAX_VIEWS, then sih26158-mvs) and re-run with --adopt "
            "<out/RUN>, or use --source synthetic. NOT sih26158-mapanything: that job "
            "runs the mapanything:v1 image, which is the synthetic harness and needs a "
            "meta.json the rasteriser writes. kolu-ma runs v2 and takes bare keyframes")

    # ---- provider: adopt a real run's artefacts
    def _adopt(self, ctx: Context) -> StageResult:
        d = os.path.join(K.ROOT, ctx.config["adopt"])
        pts_p = os.path.join(d, "points_fused.npy")
        if not os.path.exists(pts_p):
            raise StageError(Code.STAGE_UNAVAILABLE, f"{pts_p} does not exist", fatal=True)
        P = np.load(pts_p).astype(np.float64)
        C = np.load(os.path.join(d, "colors_fused.npy")) \
            if os.path.exists(os.path.join(d, "colors_fused.npy")) else None
        # Prefer full cam2world poses: gravity.estimate can then check the terrain
        # normal against the gimbal roll-zero constraint. Centres alone leave the
        # levelling on a PCA axis whose sign is arbitrary (docs/04 defect list).
        cams = None
        for cand in (ctx.config.get("cameras"),
                     os.path.join(d, "cameras.npy"),
                     os.path.join(K.ROOT, "out",
                                  os.path.basename(d).replace("mvs3d", "_raw"),
                                  "cameras.npy"),
                     os.path.join(d, "cam_centres.npy")):
            if cand and os.path.exists(cand):
                cams = np.load(cand)
                break

        pa = _save_npy(ctx, "points", P.astype(np.float32),
                       frame=Frame.F4_REFINED_WORLD, units=Units.MODEL, kind="point-cloud")
        outs = {"points": pa}
        if C is not None:
            outs["colors"] = _save_npy(ctx, "colors", C, frame=Frame.F4_REFINED_WORLD,
                                       units="rgb")
        outs["cameras"] = _save_npy(ctx, "cameras", cams if cams is not None
                                    else np.zeros((0, 3)),
                                    frame=Frame.F4_REFINED_WORLD, units=Units.MODEL)
        return StageResult(self.id, 0.0, outputs=outs,
                           facts={"points": int(len(P)),
                                  "geometry_provider": "adopt",
                                  "adopted_from": ctx.config["adopt"]},
                           note=f"adopted {ctx.config['adopt']}")

    # ---- provider: sense the synthetic scene
    def _sense(self, ctx: Context) -> StageResult:
        from eval3d.metrics import apply_transform
        from simscene.visibility import build_depth_buffer, visible_mask

        w = ctx.source.world()
        idx = np.load(os.path.join(ctx.workdir, ctx.need("plan").path))
        views = np.unique(np.clip(idx, 0, len(w["pos"]) - 1))
        views = views[:: max(1, len(views) // 60)]      # 60 sensing views is plenty
        counts = np.zeros(len(w["gt"]), np.int32)
        for i in views:
            db = build_depth_buffer(w["occ"], w["pos"][i], w["R"][i], w["cam"].K,
                                    w["cam"].width, w["cam"].height, 0.125)
            counts += visible_mask(w["gt"], w["scene"].mesh.face_normals[w["gt_fidx"]],
                                   w["pos"][i], w["R"][i], w["cam"].K,
                                   w["cam"].width, w["cam"].height, depth_buffer=db)
        observed = counts >= 2                           # 2+ views => triangulable
        P = w["gt"][observed].copy()

        rng = np.random.default_rng(ctx.source.seed + 3)
        rngm = np.linalg.norm(P - w["pos"][len(w["pos"]) // 2], axis=1)
        P += rng.normal(0, 1.0, P.shape) * (0.02 + 0.004 * rngm / 100.0)[:, None]

        # a real reconstruction arrives in an arbitrary frame; georeferencing must solve it
        th = rng.uniform(0, 2 * np.pi)
        R_arb = np.array([[np.cos(th), -np.sin(th), 0],
                          [np.sin(th), np.cos(th), 0], [0, 0, 1.0]])
        t_arb = rng.uniform(-400, 400, 3)
        P = apply_transform(P, R_arb, t_arb, 1.0)
        traj = apply_transform(w["pos"], R_arb, t_arb, 1.0)

        np.save(ctx.path("observed_mask.npy"), observed)
        outs = {
            "points": _save_npy(ctx, "points", P.astype(np.float32),
                                frame=Frame.F3_MODEL_WORLD, units=Units.MODEL,
                                kind="point-cloud"),
            "cameras": _save_npy(ctx, "cameras", traj, frame=Frame.F3_MODEL_WORLD,
                                 units=Units.MODEL),
        }
        return StageResult(self.id, 0.0, outputs=outs,
                           facts={"points": int(len(P)), "sensing_views": int(len(views)),
                                  "geometry_provider": "sense",
                                  "observable_fraction": round(float(observed.mean()), 4)})


# ------------------------------------------------------------------ S4 · scale
@dataclass
class Scale(BaseStage):
    """
    Resolve what this run may call a metre, and record why (docs/08, ADR-014).

    This runs before georeferencing because georeferencing may itself supply the answer;
    when it does, S5 overwrites what is set here with `gnss`.
    """

    id: str = "S4-scale"
    needs: tuple = ("points",)
    produces: tuple = ()
    levels: tuple = ("L0", "L1", "L2", "L3", "L4")

    def execute(self, ctx: Context) -> StageResult:
        name = ctx.config.get("calibration_run") or \
            os.path.basename(ctx.config.get("adopt", "") or "") or ctx.run_id
        cal = scale_svc.load(name)
        facts = {"scale": scale_svc.for_page(cal) | {"source": cal.get("source")},
                 "units": K.units_for(cal["status"])}

        cam = ctx.config.get("footprint_check")
        if cam:
            chk = scale_svc.footprint_check(cam["focal_px"], cam["image_width_px"],
                                            cam["camera_height_model"], cal["factor"],
                                            content_span_m=cam.get("content_span_m"))
            facts["footprint_check"] = chk
            if not chk["ok"]:
                raise StageError(Code.STAGE_UNAVAILABLE, chk["note"], fatal=True)
        return StageResult(self.id, 0.0, facts=facts, note=scale_svc.describe(cal))


# ------------------------------------------------------------------ S5 · georeference
@dataclass
class Georeference(BaseStage):
    """
    Trajectory to GNSS, in local ENU, then projected last (ADR-008).

    5-DOF only. EXP-09 measured a full 7-DOF fit throwing the scene 267-311 m off a
    straight pass even with RTK, so an unrestricted fit is refused rather than offered.
    """

    id: str = "S5-georef"
    needs: tuple = ("points", "cameras")
    produces: tuple = ("points_geo",)
    levels: tuple = ("L0", "L1", "L2", "L3", "L4")

    def execute(self, ctx: Context) -> StageResult:
        if not ctx.facts.get("has_telemetry"):
            return StageResult(self.id, 0.0, skipped=True, codes=[Code.ING_NOGNSS],
                               facts={"georeferenced": False, "frame": Frame.F5_LLF},
                               note="no telemetry: the result stays in a local frame")
        if not hasattr(ctx.source, "world"):
            # S1 now parses and aligns a real sidecar (EXP-23), but this stage still
            # reads GNSS through the synthetic source's world(). Until the video path
            # is wired (docs/09 GAP C-3, plan Phase 1.2) say so rather than crash.
            return StageResult(self.id, 0.0, skipped=True,
                               codes=[Code.STAGE_UNAVAILABLE],
                               facts={"georeferenced": False, "frame": Frame.F5_LLF,
                                      "telemetry_unwired": True},
                               note="telemetry parsed but not yet consumed on the video "
                                    "path (GAP C-3): the result stays in a local frame")
        if ctx.config.get("dof") == 7:
            raise StageError(Code.REF_7DOF,
                             "a 7-DOF fit on a single pass is refused (EXP-09)", fatal=True)

        from eval3d.gnss import robust_yaw_sim3
        from eval3d.metrics import apply_transform

        w = ctx.source.world()
        P = np.load(os.path.join(ctx.workdir, ctx.need("points").path)).astype(np.float64)
        traj = np.load(os.path.join(ctx.workdir, ctx.need("cameras").path))
        rng = np.random.default_rng(ctx.source.seed + 5)
        Rg, tg, sg, inl = robust_yaw_sim3(traj, w["gps"], thresh="auto", rng=rng)
        P_enu = apply_transform(P, Rg, tg, sg)

        lat0, lon0, h0 = w["site"]
        lat, lon, h = _enu_to_geodetic(P_enu, lat0, lon0, h0)
        epsg = _utm_epsg(float(np.mean(lon)), float(np.mean(lat)))
        import pyproj
        E, N = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}",
                                           always_xy=True).transform(lon, lat)
        H = _orthometric(lon, lat, h)
        P_utm = np.column_stack([E, N, H])

        art = _save_npy(ctx, "points_geo", P_utm, frame=Frame.F7_PROJECTED,
                        units=Units.METRES, kind="point-cloud")
        rtk = getattr(w["gnss_spec"], "name", "") == "rtk"
        cal = scale_svc.from_gnss(sg, rtk=rtk)
        return StageResult(self.id, 0.0, outputs={"points_geo": art},
                           facts={"georeferenced": True, "frame": Frame.F7_PROJECTED,
                                  "units": Units.METRES, "crs": f"EPSG:{epsg}",
                                  "geoid_model": "EGM2008 (EPSG:9518)",
                                  "geoid_separation_m": round(float(np.mean(h - H)), 3),
                                  "gnss_inlier_fraction": round(float(inl.mean()), 4),
                                  "sim3_scale": round(float(sg), 6), "dof": 5,
                                  "scale": scale_svc.for_page(cal)})


def _utm_epsg(lon: float, lat: float) -> int:
    """Zone at runtime from longitude - never hardcoded (the site is unknown)."""
    return (32600 if lat >= 0 else 32700) + int((lon + 180.0) // 6.0) + 1


def _orthometric(lon, lat, h):
    """EGM2008 via EPSG:9518, guarded three ways - PROJ fails silently here."""
    import pyproj
    from pyproj.transformer import Transformer, TransformerGroup

    pyproj.network.set_network_enabled(True)
    grp = TransformerGroup("EPSG:4979", "EPSG:9518", always_xy=True)
    if not grp.best_available:
        raise StageError(Code.REF_BALLPARK,
                         "EGM2008 grid unavailable; refusing heights that would be "
                         "silently wrong by 24-98 m over India", fatal=True)
    t = Transformer.from_crs("EPSG:4979", "EPSG:9518", always_xy=True,
                             allow_ballpark=False)
    if "ballpark" in t.description.lower():
        raise StageError(Code.REF_BALLPARK, f"ballpark transform: {t.description}",
                         fatal=True)
    return np.asarray(t.transform(lon, lat, h)[2])


def _enu_to_geodetic(enu, ref_lat, ref_lon, ref_h):
    from eval3d.gnss import WGS84_A, WGS84_E2, geodetic_to_ecef

    lat0, lon0 = np.radians(ref_lat), np.radians(ref_lon)
    sl, cl, so, co = np.sin(lat0), np.cos(lat0), np.sin(lon0), np.cos(lon0)
    R = np.array([[-so, co, 0.0], [-sl * co, -sl * so, cl], [cl * co, cl * so, sl]])
    ecef = np.asarray(enu) @ R + geodetic_to_ecef(ref_lat, ref_lon, ref_h)
    x, y, z = ecef[:, 0], ecef[:, 1], ecef[:, 2]
    lon = np.arctan2(y, x)
    p = np.hypot(x, y)
    lat = np.arctan2(z, p * (1 - WGS84_E2))
    for _ in range(6):
        N = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(lat) ** 2)
        h = p / np.cos(lat) - N
        lat = np.arctan2(z, p * (1 - WGS84_E2 * N / (N + h)))
    N = WGS84_A / np.sqrt(1 - WGS84_E2 * np.sin(lat) ** 2)
    return np.degrees(lat), np.degrees(lon), p / np.cos(lat) - N


# ------------------------------------------------------------------ S5b · level
@dataclass
class Level(BaseStage):
    """
    F3/F4 -> F5: rotate the reconstruction level, put it on its centroid, and apply the
    calibration. One transform, once, so every file downstream shares a frame.

    The vertical comes from the ground plane cross-checked against the gimbal roll-zero
    constraint (ADR-007) when full poses exist, and from the thin principal axis when
    only camera centres do. A georeferenced run skips this: F7 already is level, and
    rotating it again would undo the fit.
    """

    id: str = "S5b-level"
    needs: tuple = ("points",)
    produces: tuple = ("points_llf",)
    levels: tuple = ("L0", "L1", "L2", "L3", "L4")

    def execute(self, ctx: Context) -> StageResult:
        if "points_geo" in ctx.artefacts:
            return StageResult(self.id, 0.0, skipped=True,
                               note="already georeferenced (F7); nothing to level")
        sys.path.insert(0, os.path.join(K.ROOT, "src", "pipeline"))
        from gravity import estimate, frame as basis_from_up
        from render_views import upright_frame

        P = np.load(os.path.join(ctx.workdir, ctx.need("points").path)).astype(np.float64)
        cams = None
        if "cameras" in ctx.artefacts:
            c = np.load(os.path.join(ctx.workdir, ctx.artefacts["cameras"].path))
            cams = c if c.ndim == 3 and c.shape[-2:] == (4, 4) else None
            centres = c if cams is None else c[:, :3, 3]
        else:
            centres = None

        facts: dict = {}
        if cams is not None:
            g = estimate(cams.astype(np.float64), P, log=lambda *_: None)
            B = basis_from_up(g["up"])
            facts["gravity"] = {k: (round(v, 3) if isinstance(v, float) else
                                    (v.tolist() if isinstance(v, np.ndarray) else v))
                               for k, v in g.items()}
        else:
            B = upright_frame(P, centres)
            facts["gravity"] = {"method": "pca+centres", "checked": False}

        k = float((ctx.facts.get("scale") or {}).get("factor", 1.0))
        origin = P.mean(0)
        L = ((P - origin) @ B.T)[:, [0, 2, 1]] * k          # [e1, e2, up], then scaled
        art = _save_npy(ctx, "points_llf", L.astype(np.float32), frame=Frame.F5_LLF,
                        units=ctx.facts.get("units", Units.MODEL), kind="point-cloud")
        for key in ("camera_above_ground_m", "horiz_track_m", "altitude_spread_m"):
            if key in facts.get("gravity", {}):
                facts["gravity"][key] = round(facts["gravity"][key] * k, 2)
        facts["frame"] = Frame.F5_LLF
        facts["extent_m"] = [round(float(x), 2) for x in np.ptp(L, axis=0)]
        return StageResult(self.id, 0.0, outputs={"points_llf": art}, facts=facts,
                           note=f"levelled and scaled x{k:.2f}")


# ------------------------------------------------------------------ S6 · export
@dataclass
class Export(BaseStage):
    """
    One frame, one unit, for every file - and the scale written in, not left to a viewer.

    docs/08 S2: the files are the product. A viewer-only correction leaves a download
    disagreeing with the page that offered it.
    """

    id: str = "S6-export"
    needs: tuple = ("points", "points_llf")
    produces: tuple = ("exports",)
    levels: tuple = ("L0", "L1", "L2", "L3", "L4")

    def execute(self, ctx: Context) -> StageResult:
        import laspy
        import rasterio
        import trimesh
        from rasterio.transform import from_origin

        geo = "points_geo" in ctx.artefacts
        name = "points_geo" if geo else ("points_llf" if "points_llf" in ctx.artefacts
                                         else "points")
        src = ctx.need(name)
        P = np.load(os.path.join(ctx.workdir, src.path)).astype(np.float64)
        if name == "points":
            # Nothing levelled it and nothing georeferenced it: say so rather than
            # labelling an unlevelled cloud F5.
            raise StageError(Code.STAGE_UNAVAILABLE,
                             "no levelled or georeferenced cloud to export", fatal=True)
        frame = src.frame or (Frame.F7_PROJECTED if geo else Frame.F5_LLF)
        units = ctx.facts.get("units", Units.MODEL)
        crs = ctx.facts.get("crs") if geo else None

        out = ctx.path("export/.")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        origin = P.min(0)
        paths: dict[str, str] = {}

        p = ctx.path("export", "cloud.ply")
        trimesh.PointCloud(P - origin).export(p)
        paths["ply"] = p

        p = ctx.path("export", "cloud.las")
        hdr = laspy.LasHeader(version="1.4", point_format=6 if crs else 3)
        hdr.offsets, hdr.scales = P.min(0), [0.001, 0.001, 0.001]
        if crs:
            import pyproj
            hdr.add_crs(pyproj.CRS.from_epsg(int(str(crs).split(":")[1])))
        las = laspy.LasData(hdr)
        las.x, las.y, las.z = P[:, 0], P[:, 1], P[:, 2]
        las.write(p)
        paths["las"] = p

        # DSM: cell size follows point density, not a round number. A fixed cell left
        # ~25% of cells filled on the corridor and the surface rendered as spikes.
        e0, n0 = P[:, 0].min(), P[:, 1].min()
        span = max(float(np.ptp(P[:, 0]) * np.ptp(P[:, 1])), 1.0)
        res = float(max(0.05, round(np.sqrt(span / max(len(P), 1)) * 1.6, 2)))
        nx = int(np.ptp(P[:, 0]) / res) + 1
        ny = int(np.ptp(P[:, 1]) / res) + 1
        ix = np.clip(((P[:, 0] - e0) / res).astype(int), 0, nx - 1)
        iy = np.clip(((P[:, 1] - n0) / res).astype(int), 0, ny - 1)
        dsm = np.full((ny, nx), -np.inf)               # -inf, never NaN: maximum.at(nan)=nan
        np.maximum.at(dsm, (iy, ix), P[:, 2])
        filled = float(np.isfinite(dsm).mean())
        dsm[~np.isfinite(dsm)] = np.nan
        p = ctx.path("export", "dsm.tif")
        with rasterio.open(p, "w", driver="GTiff", height=ny, width=nx, count=1,
                           dtype="float32", nodata=np.nan, crs=crs,
                           transform=from_origin(e0 if crs else 0.0,
                                                 (n0 + ny * res) if crs else ny * res,
                                                 res, res), compress="deflate") as ds:
            ds.write(np.flipud(dsm).astype("float32"), 1)
            ds.update_tags(FRAME=frame, UNITS=units,
                           CRS_STATUS=str(crs) if crs else
                           "NONE - not georeferenced, no GNSS in source",
                           GSD=str(res))
        paths["geotiff"] = p

        arts = {}
        for fmt, path in paths.items():
            rel = os.path.relpath(path, ctx.workdir).replace(os.sep, "/")
            arts[f"export_{fmt}"] = Artefact(rel, fmt, frame=frame,
                                             units=units).stamp(ctx.workdir)
        arts["exports"] = Artefact("export", "directory", frame=frame, units=units)
        return StageResult(self.id, 0.0, outputs=arts,
                           facts={"frame": frame, "units": units,
                                  "exports": sorted(paths),
                                  "dsm": {"width": nx, "height": ny, "gsd": res,
                                          "filled_fraction": round(filled, 4),
                                          "crs": str(crs) if crs else None}})


# ------------------------------------------------------------------ S7 · score
@dataclass
class Score(BaseStage):
    """
    Absolute AND aligned, always, plus scale as a first-class number (ADR-003).

    Only the synthetic source can run this: it is the only input with ground truth.
    """

    id: str = "S7-score"
    needs: tuple = ("points",)
    produces: tuple = ()
    levels: tuple = ("L0", "L1", "L2", "L3", "L4")

    def execute(self, ctx: Context) -> StageResult:
        if hasattr(ctx.source, "path") or "points_geo" not in ctx.artefacts:
            return StageResult(self.id, 0.0, skipped=True,
                               note="no ground truth for this source")
        from eval3d.metrics import evaluate

        w = ctx.source.world()
        P = np.load(os.path.join(ctx.workdir, ctx.need("points_geo").path))
        observed = np.load(os.path.join(ctx.workdir, "observed_mask.npy"))
        lat, lon, h = _enu_to_geodetic(w["gt"], *w["site"])
        import pyproj
        epsg = int(str(ctx.facts["crs"]).split(":")[1])
        E, N = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}",
                                           always_xy=True).transform(lon, lat)
        gt = np.column_stack([E, N, _orthometric(lon, lat, h)])

        obs = evaluate(P, gt[observed], align=True, align_with_scale=False)
        whole = evaluate(P, gt, align=False)
        ab, al = obs["absolute"], obs["aligned"]
        at1 = lambda r: [s for s in r.scores if s.tau == 1.0][0]
        facts = {
            "accuracy_absolute_rmse_m": round(ab.accuracy.rmse, 4),
            "accuracy_aligned_rmse_m": round(al.accuracy.rmse, 4),
            "scale_diagnostic": round(ab.alignment_scale or 1.0, 6),
            "recall_at_1m_observable": round(at1(ab).recall, 4),
            "recall_at_1m_whole_scene": round(at1(whole["absolute"]).recall, 4),
            "fscore_at_1m": round(at1(ab).fscore, 4),
        }
        return StageResult(self.id, 0.0, facts=facts)


# ------------------------------------------------------------------ S8 · verdicts
@dataclass
class Verdicts(BaseStage):
    """
    The six PS targets, each met / not met / not measurable (docs/14 section 3.3).

    "Not measurable" is its own answer. Calling an unmeasured target a miss is as
    misleading as calling it a pass.
    """

    id: str = "S8-verdict"
    produces: tuple = ()

    def execute(self, ctx: Context) -> StageResult:
        f = ctx.facts
        exports = set(f.get("exports", []))
        need = {"ply", "las", "geotiff"}
        v = {
            "R-O1 reconstruction type": "met" if f.get("points") else "not met",
            "R-O2 processing time": ("met" if ctx.spent_s <= ctx.budget_s else "not met")
                                    if f.get("geometry_provider") == "sense"
                                    else "not measurable (stage adopted, not timed here)",
            "R-O3 spatial accuracy": (
                "met" if f.get("accuracy_absolute_rmse_m", 1e9) <= 1.0 else
                "not met" if "accuracy_absolute_rmse_m" in f else
                "not measurable (no ground truth)"),
            "R-O4 coverage": ("met" if f.get("recall_at_1m_observable", 0) >= 0.9
                              else "not met" if "recall_at_1m_observable" in f
                              else "not measurable"),
            "R-O5 formats": "met" if need <= exports else f"partial ({len(exports)})",
            "R-O6 viewer": "met (tools/build_viewer.py, demo/)",
        }
        scale = f.get("scale") or {}
        v["scale"] = scale.get("label", "unvalidated (model units)")
        return StageResult(self.id, 0.0, facts={"verdicts": v})


DEFAULT_STAGES = [Screen(), Ingest(), PlanKeyframes(), Geometry(), Scale(),
                  Georeference(), Level(), Export(), Score(), Verdicts()]
