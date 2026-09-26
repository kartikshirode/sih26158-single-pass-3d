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
    version: str = "4"          # high-flow edits between similar scenes split shots
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
        try:
            r = ingest_video(ctx.source.path,
                             target_keyframes=cfg.get("target_keyframes", 600),
                             horizon_policy=cfg.get("horizon_policy", "reject"),
                             skip_start_s=cfg.get("skip_start_s", 0.0),
                             end_s=cfg.get("end_s"),
                             srt_path=ctx.source.telemetry, progress=False)
        except RuntimeError as e:
            raise StageError(Code.ING_REJECT, str(e), fatal=True) from e
        outdir = ctx.path("keyframes/.")
        os.makedirs(os.path.dirname(outdir), exist_ok=True)
        # Clear the last run's keyframes first, as the ingest CLI does. The local GPU
        # provider lists this folder, and a re-run of the same clip with other ingest
        # settings mixed two keyframe sets into one reconstruction (audit 1).
        for old in os.listdir(os.path.dirname(outdir)):
            if old.startswith("kf_") and old.endswith(".jpg"):
                os.remove(os.path.join(os.path.dirname(outdir), old))
        import cv2
        from concurrent.futures import ThreadPoolExecutor

        # JPEG encoding releases the GIL; 600 1080p keyframes took ~10 s on one thread.
        def write(job):
            i, fi, img = job
            cv2.imwrite(ctx.path("keyframes", f"kf_{i:03d}_f{fi:05d}.jpg"), img,
                        [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(write, [(i, int(fi), img) for i, (fi, img) in
                                enumerate(zip(r.keyframe_indices, r.frames))]))
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
    level_sensitive: bool = True    # L2 halves the dense set

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
    version: str = "5"          # local GPU: global-mapper poses, fuse filter
    needs: tuple = ("plan",)
    # S3 on a synthetic source also reads the scene straight from ctx.source; the
    # orchestrator keys every stage on the source's fingerprint, which covers that.
    produces: tuple = ("points", "cameras")
    levels: tuple = ("L0", "L1", "L2", "L3", "L4")

    # measured rates, docs/13 section 6: feed-forward on a T4, MVS on 8 vCPU
    S_PER_VIEW_POSE_GPU = 0.55
    S_PER_VIEW_DENSE_CPU = 39.0
    # measured on the RTX 4060 laptop, research/09-gpu-pipeline.md, 600 uncropped
    # views: poses, SIFT, matching, triangulation and BA 0.58 s per pose view; densify,
    # undistortion and meshing 0.54 s per dense view. With the first-draft rates
    # (1.2 and 0.35 plus 90 s) a 10-minute clip was estimated at 915 s and sent down
    # the ladder by the 900 s budget it fits in.
    S_PER_VIEW_LOCAL_SPARSE = 0.6
    S_PER_VIEW_LOCAL_DENSE = 0.55
    S_LOCAL_FIXED = 30.0

    def estimate(self, ctx: Context) -> float:
        n_pose = int(ctx.facts.get("pose_views") or 0)
        n_dense = int(ctx.facts.get("dense_views") or 0)
        if ctx.config.get("adopt"):
            return 5.0                                   # reading files, not computing
        if not hasattr(ctx.source, "path"):
            return 0.02 * max(n_pose, 1)
        if ctx.config.get("geometry") == "local":
            return (self.S_LOCAL_FIXED + n_pose * self.S_PER_VIEW_LOCAL_SPARSE
                    + n_dense * self.S_PER_VIEW_LOCAL_DENSE)
        cost = n_pose * self.S_PER_VIEW_POSE_GPU
        if ctx.level in ("L0", "L1", "L2"):
            cost += n_dense * self.S_PER_VIEW_DENSE_CPU * (0.25 if ctx.level == "L1" else 1.0)
        return cost

    def execute(self, ctx: Context) -> StageResult:
        if ctx.config.get("adopt"):
            return self._adopt(ctx)
        if not hasattr(ctx.source, "path"):
            return self._sense(ctx)
        if ctx.config.get("geometry") == "local":
            return self._local(ctx)
        raise StageError(
            Code.STAGE_UNAVAILABLE,
            "no geometry provider on this host. Run the containers "
            "(gcloud run jobs execute kolu-ma --region=asia-south1 with IN_PREFIX/"
            "OUT_PREFIX/MAX_VIEWS, then sih26158-mvs) and re-run with --adopt "
            "<out/RUN>, or use --source synthetic. NOT sih26158-mapanything: that job "
            "runs the mapanything:v1 image, which is the synthetic harness and needs a "
            "meta.json the rasteriser writes. kolu-ma runs v2 and takes bare keyframes")

    # ---- provider: adopt a real run's artefacts
    @staticmethod
    def _adopt_files(ctx: Context) -> tuple[str, str | None, str | None]:
        """The points, colours and cameras files an adopted run supplies (or None)."""
        d = os.path.join(K.ROOT, ctx.config["adopt"])
        colors = os.path.join(d, "colors_fused.npy")
        # Prefer full cam2world poses: gravity.estimate can then check the terrain
        # normal against the gimbal roll-zero constraint. Centres alone leave the
        # levelling on a PCA axis whose sign is arbitrary (docs/04 defect list).
        cams = next((c for c in (ctx.config.get("cameras"),
                                 os.path.join(d, "cameras.npy"),
                                 os.path.join(K.ROOT, "out",
                                              os.path.basename(d).replace("mvs3d", "_raw"),
                                              "cameras.npy"),
                                 os.path.join(d, "cam_centres.npy"))
                     if c and os.path.exists(c)), None)
        return (os.path.join(d, "points_fused.npy"),
                colors if os.path.exists(colors) else None, cams)

    def key_extra(self, ctx: Context):
        # An adopted run lives outside this run's directory. Re-running MVS into the
        # same out/<run> must invalidate S3, so key on the files' content, not their
        # names (audit F-01).
        if not ctx.config.get("adopt"):
            return None
        return [{"path": os.path.relpath(p, K.ROOT).replace(os.sep, "/"),
                 "sha256": K.file_sha256(p)} if p and os.path.exists(p) else None
                for p in self._adopt_files(ctx)]

    def _adopt(self, ctx: Context) -> StageResult:
        pts_p, colors_p, cams_p = self._adopt_files(ctx)
        if not os.path.exists(pts_p):
            raise StageError(Code.STAGE_UNAVAILABLE, f"{pts_p} does not exist", fatal=True)
        return self._load(ctx, pts_p, colors_p, cams_p,
                          {"geometry_provider": "adopt",
                           "adopted_from": ctx.config["adopt"]},
                          f"adopted {ctx.config['adopt']}")

    # ---- provider: poses, sparse and dense on this machine's GPU
    def _local(self, ctx: Context) -> StageResult:
        """
        src/pipeline/local_gpu.py on S1's keyframes, densifying S2's dense set.

        Missing tools or no GPU is STAGE_UNAVAILABLE, so the ladder steps down as it
        does for any host that cannot run a stage. A failed S3b gate is GEO_REPROJ.
        L1 ("half-res") densifies one resolution level lower than L0.
        """
        sys.path.insert(0, os.path.join(K.ROOT, "src", "pipeline"))
        from local_gpu import SparseError, frame_order, run as run_local

        if ctx.level not in ("L0", "L1", "L2"):
            raise StageError(Code.STAGE_UNAVAILABLE,
                             f"the local GPU provider has no {ctx.level} mode")
        # Poses, matching and the S3b gate do not change with the level, so a sparse
        # failure is not worth rerunning at L1 and L2 (audit 1): replay it.
        failed = getattr(self, "_sparse_failed", None)
        if failed and failed[0] == (ctx.run_id, ctx.workdir):
            raise StageError(failed[1], f"{failed[2]} (not rerun at {ctx.level})")
        kf = ctx.path("keyframes")
        with io.open(ctx.path("ingest.json"), encoding="utf-8") as f:
            crop = json.load(f)["stats"].get("overlay_crop_trbl")
        names = sorted((n for n in os.listdir(kf) if n.lower().endswith(".jpg")),
                       key=frame_order)
        idx = np.load(os.path.join(ctx.workdir, ctx.need("plan").path))
        dense = [names[i] for i in idx if 0 <= i < len(names)]
        opts = dict(ctx.config.get("local_gpu") or {})
        if ctx.level == "L1":
            opts["dense_resolution_level"] = int(opts.get("dense_resolution_level", 1)) + 1
        # After a dense failure the poses on disk passed the S3b gate, and L1 and L2
        # change only the dense half, so they are reused rather than solved again
        # (130 of the demo's 314 s).
        g = ctx.path("geometry")
        reuse = None
        if getattr(self, "_dense_failed", None) == (ctx.run_id, ctx.workdir):
            try:
                with io.open(os.path.join(g, "local_gpu_result.json"), encoding="utf-8") as f:
                    prev = json.load(f)
                if prev.get("n_views") == len(names) and prev["ba_gate"]["passed"]:
                    reuse = g
            except (OSError, ValueError, KeyError, TypeError):
                pass
        try:
            res = run_local(kf, g, crop_trbl=crop, dense_names=dense,
                            options=opts, sparse_from=reuse, log=ctx.log)
        except FileNotFoundError as e:
            raise StageError(Code.STAGE_UNAVAILABLE, str(e))
        except SparseError as e:
            code = (Code.STAGE_UNAVAILABLE if "no CUDA device" in str(e) else
                    Code.GEO_REPROJ)
            self._sparse_failed = ((ctx.run_id, ctx.workdir), code, str(e)[-800:])
            raise StageError(code, str(e)[-800:])
        except (RuntimeError, SystemExit) as e:
            self._dense_failed = (ctx.run_id, ctx.workdir)
            raise StageError(Code.MVS_RC, str(e)[-800:])
        colors = os.path.join(g, "colors_fused.npy")
        lost = res.get("unregistered") or []
        out = self._load(ctx, os.path.join(g, "points_fused.npy"),
                         colors if os.path.exists(colors) else None,
                         os.path.join(g, "cameras.npy"),
                         {"geometry_provider": "local",
                          "registered_views": len(names) - len(lost),
                          "local_gpu": {k: res[k] for k in
                                        ("n_views", "pose_method", "dense_points",
                                         "total_seconds",
                                         "sparse_after_bundle_adjustment", "sparse_from",
                                         "stages", "unregistered", "mesh_error",
                                         "textured_mesh", "texture_error")
                                        if k in res}},
                         f"local GPU, {res.get('total_seconds')} s")
        if lost:
            # docs/09: drop unregistered views, warn under 80%. The run goes on with the
            # views the mapper placed; the part of the flight the rest saw is missing.
            out.codes.append(Code.GEO_UNREG)
            frac = 1 - len(lost) / max(len(names), 1)
            out.note += (f"; {len(lost)} of {len(names)} views unregistered"
                         + (" (under 80%: coverage is partial)" if frac < 0.8 else ""))
        return out

    def _load(self, ctx: Context, pts_p, colors_p, cams_p, facts: dict,
              note: str) -> StageResult:
        P = np.load(pts_p).astype(np.float64)
        C = np.load(colors_p) if colors_p else None
        cams = np.load(cams_p) if cams_p else None

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
                           facts={"points": int(len(P)), **facts}, note=note)

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

        # A real reconstruction arrives in an arbitrary gauge: any rotation, any scale.
        # This used to be a yaw and a translation at scale 1.0, which is already level
        # and already metric, the exact two things the georeferencing fit assumes and
        # never has to establish, so the synthetic accuracy could not see a missing
        # levelling step (audit F-07). Roll and pitch up to 25 degrees, scale 0.1-2x.
        th = rng.uniform(0, 2 * np.pi)
        t_arb = rng.uniform(-400, 400, 3)
        roll, pitch = rng.uniform(-np.radians(25), np.radians(25), 2)
        s_arb = float(10 ** rng.uniform(-1.0, 0.3))
        Rz = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0],
                       [0, 0, 1.0]])
        Rx = np.array([[1.0, 0, 0], [0, np.cos(roll), -np.sin(roll)],
                       [0, np.sin(roll), np.cos(roll)]])
        Ry = np.array([[np.cos(pitch), 0, np.sin(pitch)], [0, 1.0, 0],
                       [-np.sin(pitch), 0, np.cos(pitch)]])
        R_arb = Rz @ Rx @ Ry
        P = apply_transform(P, R_arb, t_arb, s_arb)
        # Full cam2world poses, as MapAnything gives: S5 and S5b can then check the
        # ground-plane vertical against the gimbal's roll-zero constraint.
        traj = np.repeat(np.eye(4)[None], len(w["pos"]), axis=0)
        traj[:, :3, :3] = np.einsum("ij,njk->nik", R_arb, w["R"])
        traj[:, :3, 3] = apply_transform(w["pos"], R_arb, t_arb, s_arb)

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

    @staticmethod
    def _calibration_run(ctx: Context) -> str:
        return ctx.config.get("calibration_run") or \
            os.path.basename(ctx.config.get("adopt", "") or "") or ctx.run_id

    def key_extra(self, ctx: Context):
        # The calibration file is read by name from research/calibration/, outside the
        # run. Key on what it resolves to, so `tesseract calibrate` and an edited factor
        # both take effect on the next resume instead of being served from the cache
        # (audit F-01).
        try:
            return scale_svc.load(self._calibration_run(ctx))
        except ValueError as e:                      # execute() raises it properly
            return {"unusable": str(e)}

    def execute(self, ctx: Context) -> StageResult:
        cal = scale_svc.load(self._calibration_run(ctx))
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

    Never 7-DOF. EXP-09 measured a full 7-DOF fit throwing the scene 267-311 m off a
    straight pass even with RTK, so an unrestricted fit is refused rather than offered.
    The fit is 6-DOF: the one rotation a straight track cannot constrain, roll about
    its own axis, comes from gravity; the other two come from the track (ADR-026).
    """

    id: str = "S5-georef"
    version: str = "3"          # gravity lengths in metres, not the raw gauge's units
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

        from eval3d.gnss import robust_track_sim3
        from eval3d.metrics import apply_transform

        w = ctx.source.world()
        P = np.load(os.path.join(ctx.workdir, ctx.need("points").path)).astype(np.float64)
        cam = np.load(os.path.join(ctx.workdir, ctx.need("cameras").path))
        # A yaw-only fit assumes its input is already level, Z up. A reconstruction in
        # F3/F4 is not: its gauge has an arbitrary roll and pitch, and on a straight
        # pass the GNSS track cannot supply them. This stage used to fit the raw frame,
        # which only worked because the synthetic source handed it a frame that was
        # already level; a 5 degree roll gave a perfect track fit and a scene 21 m off
        # (audit F-07). Level first, with the same vertical S5b would use, then fit.
        B, grav, centres = _level_basis(P, cam)
        origin = P.mean(0)
        rng = np.random.default_rng(ctx.source.seed + 5)
        # Yaw and the track's slope from the GNSS; only the roll about the track from
        # gravity, which is the one rotation a straight pass cannot give (ADR-026).
        Rg, tg, sg, inl = robust_track_sim3(_level(centres, B, origin), w["gps"],
                                            thresh="auto", rng=rng)
        P_enu = apply_transform(_level(P, B, origin), Rg, tg, sg)

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
                                  "sim3_scale": round(float(sg), 6), "dof": 6,
                                  "rotation_from": {"gnss": ["yaw", "track slope"],
                                                    "gravity": ["roll about the track"]},
                                  # Measured on the raw gauge; the fit's scale makes
                                  # them metres.
                                  "gravity": _gravity_lengths(grav, sg, Units.METRES),
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


# ------------------------------------------------------------------ levelling
def _level_basis(P: np.ndarray, cam_array: np.ndarray | None):
    """
    The F3/F4 -> level rotation, shared by S5 and S5b so both use one vertical.

    Returns (B, gravity facts, camera centres). B's rows are [e1, up, e2], which is a
    left-handed triple; `_level` reorders to [e1, e2, up], which is right-handed with
    Z up, the frame a yaw-only fit to ENU assumes.

    The vertical comes from the ground plane cross-checked against the gimbal roll-zero
    constraint (ADR-007) when full cam2world poses exist, and from the thin principal
    axis signed by the camera centres when only centres do.
    """
    sys.path.insert(0, os.path.join(K.ROOT, "src", "pipeline"))
    from gravity import estimate, frame as basis_from_up
    from render_views import upright_frame

    cams, centres = None, None
    if cam_array is not None and len(cam_array):
        # A view the mapper could not register keeps a NaN row (local_gpu), so the
        # file still lines up with the keyframes; it has no pose to level with.
        cam_array = cam_array[np.isfinite(cam_array.reshape(len(cam_array), -1)).all(1)]
    if cam_array is not None and len(cam_array):
        full = cam_array.ndim == 3 and cam_array.shape[-2:] == (4, 4)
        cams = cam_array if full else None
        centres = cam_array[:, :3, 3] if full else cam_array
    if cams is not None:
        g = estimate(cams.astype(np.float64), P, log=lambda *_: None)
        facts = {k: (round(v, 3) if isinstance(v, float) else
                     (v.tolist() if isinstance(v, np.ndarray) else v))
                 for k, v in g.items()}
        return basis_from_up(g["up"]), facts, centres
    return upright_frame(P, centres), {"method": "pca+centres", "checked": False}, centres


def _gravity_lengths(grav: dict, k: float, units: str) -> dict:
    """
    Scale gravity.estimate's lengths by `k` and name them by their unit, in place.

    Lengths carry their unit in the key (docs/15 conventions). gravity.estimate
    measures in whatever frame it is handed and names the result `_m` regardless. S5b
    published those names on unvalidated runs (audit F-06), and S5 published them in
    the reconstruction's own gauge on a run whose units were metres.
    """
    sfx = "_m" if units == Units.METRES else "_model"
    for key in ("camera_above_ground_m", "horiz_track_m", "altitude_spread_m"):
        if key in grav:
            grav[key[:-2] + sfx] = round(grav.pop(key) * k, 2)
    return grav


def _level(X: np.ndarray, B: np.ndarray, origin: np.ndarray) -> np.ndarray:
    """Rotate into the level frame: [e1, e2, up], right-handed, Z up, about `origin`."""
    return ((np.asarray(X, np.float64) - origin) @ B.T)[:, [0, 2, 1]]


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
    version: str = "3"          # writes its transform for S6's mesh exports
    needs: tuple = ("points",)
    produces: tuple = ("points_llf", "level_transform")
    levels: tuple = ("L0", "L1", "L2", "L3", "L4")

    def execute(self, ctx: Context) -> StageResult:
        if "points_geo" in ctx.artefacts:
            return StageResult(self.id, 0.0, skipped=True,
                               note="already georeferenced (F7); nothing to level")
        P = np.load(os.path.join(ctx.workdir, ctx.need("points").path)).astype(np.float64)
        c = (np.load(os.path.join(ctx.workdir, ctx.artefacts["cameras"].path))
             if "cameras" in ctx.artefacts else None)
        B, grav, _ = _level_basis(P, c)
        facts: dict = {"gravity": grav}

        k = float((ctx.facts.get("scale") or {}).get("factor", 1.0))
        units = ctx.facts.get("units", Units.MODEL)
        origin = P.mean(0)
        L = _level(P, B, origin) * k                      # [e1, e2, up], then scaled
        art = _save_npy(ctx, "points_llf", L.astype(np.float32), frame=Frame.F5_LLF,
                        units=units, kind="point-cloud")
        # The transform itself, so S6 can carry the textured mesh into the same frame
        # as the cloud rather than refitting one from the points.
        with io.open(ctx.path("level.json"), "w", encoding="utf-8") as f:
            json.dump({"from": Frame.F4_REFINED_WORLD, "to": Frame.F5_LLF,
                       "basis_rows": B.tolist(), "origin": origin.tolist(), "scale": k,
                       "apply": "((X - origin) @ basis_rows.T)[:, [0, 2, 1]] * scale"},
                      f, indent=2)
        lt = Artefact("level.json", "transform", frame=Frame.F5_LLF).stamp(ctx.workdir)
        # `extent_m` too was published on unvalidated runs (audit F-06).
        sfx = "_m" if units == Units.METRES else "_model"
        _gravity_lengths(facts.get("gravity", {}), k, units)
        facts["frame"] = Frame.F5_LLF
        facts["extent" + sfx] = [round(float(x), 2) for x in np.ptp(L, axis=0)]
        return StageResult(self.id, 0.0, outputs={"points_llf": art, "level_transform": lt},
                           facts=facts, note=f"levelled and scaled x{k:.2f}")


# ------------------------------------------------------------------ S6 · export
@dataclass
class Export(BaseStage):
    """
    One frame, one unit, for every file - and the scale written in, not left to a viewer.

    docs/08 S2: the files are the product. A viewer-only correction leaves a download
    disagreeing with the page that offered it.
    """

    id: str = "S6-export"
    version: str = "3"          # the textured mesh too, as OBJ, GLB and FBX
    needs: tuple = ("points", "points_llf")
    produces: tuple = ("exports",)
    levels: tuple = ("L0", "L1", "L2", "L3", "L4")

    def execute(self, ctx: Context) -> StageResult:
        import laspy
        import rasterio
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
        paths: dict[str, str] = {}

        # The same coordinates as the LAS and the GeoTIFF, in doubles. trimesh writes
        # float32, which spaces UTM northings over India 0.25 m apart, so this used to
        # subtract a min-corner origin first and then label the shifted file F7 with no
        # record of the shift: a PLY and a LAS of one run did not overlay (audit F-03).
        p = ctx.path("export", "cloud.ply")
        _write_ply_f64(p, P)
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

        # The textured mesh, when S3 made one, in the same frame as the cloud: OBJ,
        # GLB and FBX (R-O5). Only the levelled frame has its transform on disk; a
        # georeferenced run would need S5's, so its mesh is not exported yet.
        notes = []
        tex = ctx.path("geometry", "scene_tex.obj")
        if os.path.isfile(tex) and not geo and "level_transform" in ctx.artefacts:
            with io.open(os.path.join(ctx.workdir, ctx.artefacts["level_transform"].path),
                         encoding="utf-8") as f:
                lt = json.load(f)
            sys.path.insert(0, os.path.join(K.ROOT, "src", "pipeline"))
            from mesh_export import export_textured
            got, why = export_textured(tex, ctx.path("export"), np.asarray(lt["basis_rows"]),
                                       np.asarray(lt["origin"]), float(lt["scale"]))
            paths.update(got)
            notes += why
        elif os.path.isfile(tex):
            notes.append("textured mesh not exported: no levelled-frame transform")

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
                                          "crs": str(crs) if crs else None}},
                           note="; ".join(notes))


# ------------------------------------------------------------------ S7 · score
def _write_ply_f64(path: str, P: np.ndarray) -> None:
    """Binary little-endian PLY with double x, y, z: exact for projected coordinates."""
    P = np.ascontiguousarray(P, dtype="<f8")
    head = ("ply\nformat binary_little_endian 1.0\n"
            "comment frame, units and CRS are in run_manifest.json\n"
            f"element vertex {len(P)}\n"
            "property double x\nproperty double y\nproperty double z\nend_header\n")
    with open(path, "wb") as f:
        f.write(head.encode("ascii"))
        f.write(P.tobytes())


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
    version: str = "4"          # R-O6 needs a model to view
    produces: tuple = ()
    cacheable: bool = False     # it judges the run's facts, which its cache key cannot see

    def execute(self, ctx: Context) -> StageResult:
        f = ctx.facts
        v = {
            "R-O1 reconstruction type": "met" if f.get("points") else "not met",
            "R-O2 processing time": _verdict_time(ctx),
            "R-O3 spatial accuracy": (
                "met" if f.get("accuracy_absolute_rmse_m", 1e9) <= 1.0 else
                "not met" if "accuracy_absolute_rmse_m" in f else
                "not measurable (no ground truth)"),
            "R-O4 coverage": _verdict_coverage(f),
            "R-O5 formats": _verdict_formats(f.get("exports", [])),
            # A viewer with nothing to show is not an answer for this run.
            "R-O6 viewer": ("met (tools/build_viewer.py, demo/)" if f.get("exports")
                            else "not measurable (no model was built to view)"),
        }
        scale = f.get("scale") or {}
        v["scale"] = scale.get("label", "unvalidated (model units)")
        return StageResult(self.id, 0.0, facts={"verdicts": v})


# PS p.38 Output Formats row. glTF and GLB are one row ("glb/gltf"), so either counts.
R_O5_FORMATS = ("obj", "ply", "las", "geotiff", "gltf", "fbx")

# R-O2 is "< 15 minutes for a 10-minute video". A shorter clip, or a synthetic scene,
# says nothing about that input, whatever its own wall clock was.
R_O2_VIDEO_S = 600.0


# R-O4 is "the entire visible scene"; 90% recall at 1 m over what the flight could see.
R_O4_RECALL = 0.9


def _verdict_coverage(f: dict) -> str:
    """
    Judged on the observable denominator, which is what the PS asks for, with the
    whole-scene figure always printed beside it (ADR-022): a pass on the easy surface
    must not hide that most of the scene is missing (audit F-08).

    Synthetic sensing is not judged at all. Its cloud IS the ground truth over the
    observable mask, plus noise, so observable recall is 100% by construction and only
    says whether the points landed within 1 m: a placement figure, already R-O3's.
    """
    if "recall_at_1m_observable" not in f:
        return "not measurable (no ground truth)"
    both = (f"observable {f['recall_at_1m_observable']:.0%}; whole scene "
            f"{f.get('recall_at_1m_whole_scene', float('nan')):.0%}")
    if f.get("geometry_provider") == "sense":
        return (f"not measurable (synthetic sensing returns every observable point by "
                f"construction; {both})")
    verdict = "met" if f["recall_at_1m_observable"] >= R_O4_RECALL else "not met"
    return f"{verdict} ({both})"


def _verdict_formats(exports) -> str:
    """
    Met only when every format the PS lists was written. This used to require just the
    three S6 writes (PLY, LAS, GeoTIFF), so a run with no OBJ, glTF or FBX at all said
    `met` on the console for every run it showed (audit F-02).
    """
    have = set(exports) | ({"gltf"} if "glb" in exports else set())
    missing = [x for x in R_O5_FORMATS if x not in have]
    if not missing:
        return "met"
    return (f"not met ({len(R_O5_FORMATS) - len(missing)} of {len(R_O5_FORMATS)} "
            f"written; missing {', '.join(missing)})")


def _verdict_time(ctx: Context) -> str:
    """
    Met only for a timed, uncached run of a video at least ten minutes long. A 240-frame
    synthetic scene finishing inside 900 s was being reported as meeting the target, and
    so was a resumed run whose cached stages count as zero seconds (audit F-09).
    """
    f = ctx.facts
    if not hasattr(ctx.source, "path"):
        return "not measurable (synthetic source: no video was processed)"
    if f.get("geometry_provider") == "adopt":
        return "not measurable (stage adopted, not timed here)"
    dur = (f.get("screen") or {}).get("duration_s")
    if dur is None:
        return "not measurable (clip duration unknown)"
    if dur < R_O2_VIDEO_S:
        return (f"not measurable (clip is {dur:.0f} s; the target is for a "
                f"{R_O2_VIDEO_S / 60:.0f}-minute video)")
    if ctx.cached:
        n = len(ctx.cached)
        return (f"not measurable ({n} stage{'s' if n != 1 else ''} reused from cache, "
                f"so the wall clock is not the pipeline's)")
    return "met" if ctx.spent_s <= ctx.budget_s else "not met"


DEFAULT_STAGES = [Screen(), Ingest(), PlanKeyframes(), Geometry(), Scale(),
                  Georeference(), Level(), Export(), Score(), Verdicts()]
