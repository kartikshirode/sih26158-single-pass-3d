"""
S3 and S4 on one machine with an NVIDIA GPU: poses, bundle adjustment, dense cloud and
mesh, with no cloud job in the loop (docs/10 ADR-027, research/09-gpu-pipeline.md).

The cloud path (mapanything_job/, mvs_job/) runs on CPU because the GCP account has no
GPU quota. On Kolu that meant 11.45 s per view for poses, an exhaustive matcher that
grows with the square of the view count (391 s for 45 views), and 46 s per view to
densify (77% of a 34-minute run). Here, measured on an RTX 4060 laptop (8 GB):

  camera   MapAnything in bf16 on a spread subset of the views; one shared camera
           is fitted from its point maps
  poses    COLMAP with GPU SIFT, a wide sequential matching window (video order) and
           the global mapper with that camera held fixed, then the S3b gate. The
           older path (pose_method "mapanything") took MapAnything's stitched window
           poses, triangulated against them and ran a short bundle adjustment
  dense    OpenMVS DensifyPointCloud on CUDA over the dense view set only
  mesh     OpenMVS ReconstructMesh, then TextureMesh to a decimated textured OBJ;
           both optional and neither fails the stage

Writes points_fused.npy, colors_fused.npy and cameras.npy (the files the tesseract
`adopt` provider reads) plus local_gpu_result.json with every stage's time.

Tools are found through SIH_COLMAP (the colmap executable) and SIH_OPENMVS (the folder
holding DensifyPointCloud), else on PATH. Nothing here downloads anything.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "mvs_job"))

CHECKPOINT = "facebook/map-anything-apache"   # Apache-2.0; the default is CC-BY-NC

DEFAULTS = {
    # "global": MapAnything fits the intrinsics only, and COLMAP's global mapper solves
    # every pose from long feature tracks. "mapanything": MapAnything's stitched window
    # poses, triangulated and refined. On the demo clip the second drifted between
    # windows and stacked the ground in three or four tilted sheets; the first kept 78%
    # of the sparse ground within 3% of one plane, against 45% (research/10).
    "pose_method": "global",
    "global_match_overlap": 30,  # one ground point stays matchable ~30 keyframes apart
    "pose_window": 0,           # views per MapAnything call; 0 sizes it to the GPU
    "pose_overlap": 8,          # shared views between windows, for the Sim(3) stitch
    "pose_size": 0,             # 0: the model's own 518 mapping; else the longest side
    "intrinsics_views": 60,     # the camera is shared, so a subset fits it as well
    # Measured on 568 views (research/09 section 4): 8192 features, 100 BA iterations
    # and five triangulation refinements took 657 s for matching, triangulation and
    # BA; 4096, 10 and one took 150 s and ended at 0.49 px against 0.46.
    "sift_features": 4096,
    # Overlap 10 took 135 s on 600 uncropped views; 6 took 43 s and ended at 0.63 px
    # against 0.64 (research/09 section 6). Quadratic overlap still adds far pairs.
    "match_overlap": 6,         # sequential neighbours matched per image
    "tri_refinements": 1,
    "tri_ba_iterations": 3,
    "ba_iterations": 10,        # the cost is flat after 10 (0.3587 px; 0.3582 at 100)
    # Share of the views the mapper must place for the run to go on. The rest are left
    # out of the dense set and flagged GEO-UNREG (docs/09): 46 featureless frames past
    # the end of the synthetic site used to refuse a 600-view run that placed 554.
    "min_registered": 0.5,
    "dense_resolution_level": 1,
    "dense_views_fuse": 3,
    "dense_neighbours": 5,      # views per depth map (OpenMVS default 8): 107 s to 96 s
    # OpenMVS fusion filter: 0 merge, 1 fuse, 2 dense-fuse (its default). On the demo's
    # global poses dense-fuse kept 160k points from 52M depths, all from the first few
    # frames, while the depth maps themselves were 90-96% valid; fuse kept 7.9M covering
    # 90-96% of every view (research/10).
    "dense_fusion_filter": 1,
    # ReconstructMesh's minimum point spacing in pixels (default 1.5): 91 s and 4.0M
    # faces at 1.5, 60 s and 2.6M at 2.5, on 600 views.
    "mesh_min_point_distance": 2.5,
    "mesh": True,
    "texture": True,            # OpenMVS TextureMesh on the mesh, to a textured OBJ
    "texture_decimate": 0.1,    # fraction of the mesh's faces kept before texturing
    # Extra arguments for one tool, split on spaces and appended last so they win; for
    # an operator or an experiment trying a flag no option above covers yet.
    "mapper_extra": "",
    "densify_extra": "",
    "mesh_extra": "",
    "texture_extra": "",
    # Depth maps (6.6 MB each at 967x297), undistorted images, the matches database and
    # the intermediate sparse models were 1.4 of the 1.5 GB a 134-view demo run left.
    "keep_intermediate": False,
}


def find_tools() -> dict:
    colmap = os.environ.get("SIH_COLMAP") or shutil.which("colmap")
    mvs = os.environ.get("SIH_OPENMVS")
    if not mvs:
        d = shutil.which("DensifyPointCloud")
        mvs = os.path.dirname(d) if d else None
    exe = ".exe" if os.name == "nt" else ""
    if not colmap or not os.path.exists(colmap):
        raise FileNotFoundError("COLMAP not found: set SIH_COLMAP to the colmap "
                                "executable (a CUDA build) or put colmap on PATH")
    tools = {n: os.path.join(mvs or "", n + exe) for n in
             ("InterfaceCOLMAP", "DensifyPointCloud", "ReconstructMesh", "TextureMesh")}
    missing = [n for n, t in tools.items() if not os.path.exists(t)]
    if missing:
        raise FileNotFoundError(f"OpenMVS {', '.join(missing)} not found: set SIH_OPENMVS "
                                "to the folder of a CUDA build")
    import importlib.util
    for mod in ("torch", "mapanything"):
        if importlib.util.find_spec(mod) is None:
            raise FileNotFoundError(f"python module {mod} is not installed "
                                    "(research/09-gpu-pipeline.md section 1)")
    return {"colmap": colmap, "openmvs": tools}


def with_extra(args: list, extra: str) -> list:
    """
    `args` with the flags in `extra` in place of their own. The tools refuse an option
    given twice, so an extra flag has to replace the default rather than follow it.
    """
    flag = re.compile(r"-+[A-Za-z]")
    toks, pairs, i = extra.split(), [], 0
    while i < len(toks):
        val = toks[i + 1] if i + 1 < len(toks) and not flag.match(toks[i + 1]) else None
        pairs.append((toks[i], val))
        i += 1 if val is None else 2
    drop, out, j = {f for f, _ in pairs}, [], 0
    while j < len(args):
        a = str(args[j])
        if a in drop:
            j += 2 if j + 1 < len(args) and not flag.match(str(args[j + 1])) else 1
            continue
        out.append(args[j])
        j += 1
    for f, v in pairs:
        out += [f] if v is None else [f, v]
    return out


class SparseError(RuntimeError):
    """Poses, intrinsics, matching or the S3b gate failed: no dense setting can help."""


def frame_order(name: str):
    """Keyframes in time order: kf_1000_... must come after kf_999_..., not kf_100_."""
    m = re.match(r"kf_(\d+)", name)
    return (0, int(m.group(1)), name) if m else (1, 0, name)


class Runner:
    """Runs the stages into one work folder, logging each tool and timing each stage."""

    def __init__(self, work: str, log=print):
        self.work = os.path.abspath(work)
        os.makedirs(os.path.join(self.work, "logs"), exist_ok=True)
        self.log = log
        self.times: list[dict] = []

    def timed(self, label: str, fn, *a, **kw):
        t0 = time.perf_counter()
        out = fn(*a, **kw)
        dt = time.perf_counter() - t0
        self.times.append({"stage": label, "seconds": round(dt, 2)})
        self.log(f"  {label:<24} {dt:8.1f} s")
        return out

    def sh(self, args: list, label: str, cwd: str | None = None) -> str:
        """Run a tool; its whole output goes to logs/<label>.log. Fails loudly."""
        def go():
            p = subprocess.run([str(a) for a in args], cwd=cwd or self.work,
                               capture_output=True, text=True, errors="replace")
            out = (p.stdout or "") + (p.stderr or "")
            with open(os.path.join(self.work, "logs", f"{label}.log"), "w",
                      encoding="utf-8") as f:
                f.write(out)
            if p.returncode != 0:
                raise RuntimeError(f"{label} exited {p.returncode}; tail:\n{out[-1500:]}")
            return out
        return self.timed(label, go)


# ---------------------------------------------------------------------- poses
def mapanything_poses(paths: list[str], *, window: int, overlap: int, size: int = 0,
                      log=print) -> dict:
    """
    Poses and point maps for every view, in the frame of the first window.

    One call over all views would need memory for all of them at once, and the
    multi-view attention grows with the view count, so a long clip is cut into
    overlapping windows (window_fuse.plan_windows). Each window after the first is
    carried into the running frame by a robust Sim(3) on its shared views' points,
    the same fit window_fuse.stitch uses. A view keeps the pose from the first window
    that saw it.
    """
    import torch
    from mapanything.models import MapAnything
    from mapanything.utils.image import load_images
    from window_fuse import plan_windows, robust_sim3_from_pairs

    if not torch.cuda.is_available():
        raise RuntimeError("no CUDA device: local_gpu needs an NVIDIA GPU")
    t0 = time.perf_counter()
    model = MapAnything.from_pretrained(CHECKPOINT).to("cuda").eval()
    t_load = time.perf_counter() - t0
    t0 = time.perf_counter()
    views = (load_images(paths, resize_mode="longest_side", size=size) if size
             else load_images(paths))
    t_images = time.perf_counter() - t0
    t_infer = t_stitch = 0.0
    n = len(views)
    H, W = views[0]["img"].shape[-2:]
    if window <= 0:
        window = pose_window_for(H, W, torch.cuda.get_device_properties(0).total_memory)
    wins = plan_windows(n, window, overlap) if n > window else [(0, n)]

    pts: list = [None] * n
    conf: list = [None] * n
    mask: list = [None] * n
    cams: list = [None] * n
    report = []
    torch.cuda.reset_peak_memory_stats()
    for k, (lo, hi) in enumerate(wins):
        t0 = time.perf_counter()
        # Copies of the view dicts: infer moves the image tensors to the GPU inside the
        # dicts it is given, and the originals then kept every finished window's images
        # on the card. On 600 uncropped views that grew past 8 GB, the driver spilled
        # into shared system memory, and the run slowed from minutes to never.
        with torch.no_grad():
            preds = model.infer([dict(v) for v in views[lo:hi]],
                                memory_efficient_inference=True,
                                use_amp=True, amp_dtype="bf16", apply_mask=True)
        torch.cuda.synchronize()
        t_infer += time.perf_counter() - t0
        t0 = time.perf_counter()
        wp, wc, wm, wcam = [], [], [], []
        for p in preds:
            t = p["pts3d"].squeeze(0).float().cpu().numpy()
            H, W = t.shape[:2]
            wp.append(t.reshape(-1, 3))
            wc.append(p["conf"].squeeze(0).reshape(-1).float().cpu().numpy()
                      if "conf" in p else np.ones(H * W, np.float32))
            mk = np.ones(H * W, bool)
            for key in ("non_ambiguous_mask", "mask"):
                if key in p:
                    v = p[key].squeeze(0).reshape(-1).cpu().numpy().astype(bool)
                    if v.shape[0] == H * W:
                        mk = v
                        break
            wm.append(mk)
            wcam.append(p["camera_poses"].squeeze(0).float().cpu().numpy())
        del preds

        s, R, tr = 1.0, np.eye(3), np.zeros(3)
        if k > 0:
            src, dst = [], []
            for g in range(lo, hi):
                if pts[g] is None:
                    continue
                a, b, c = wp[g - lo], pts[g], wc[g - lo]
                ok = (np.isfinite(a).all(1) & np.isfinite(b).all(1) & wm[g - lo]
                      & (c >= np.percentile(c, 60)))
                idx = np.flatnonzero(ok)
                if len(idx) > 4000:
                    idx = np.random.default_rng(g).choice(idx, 4000, replace=False)
                src.append(a[idx]); dst.append(b[idx])
            if len(src) < 3:
                raise RuntimeError(f"window {k} shares fewer than 3 views with the last")
            s, R, tr, inl, _ = robust_sim3_from_pairs(np.concatenate(src),
                                                      np.concatenate(dst))
            report.append({"window": k, "views": [lo, hi], "scale": round(float(s), 5),
                           "inlier_frac": round(float(inl), 3)})
        for j, g in enumerate(range(lo, hi)):
            if pts[g] is not None:
                continue
            pts[g] = (s * (R @ wp[j].T).T + tr).astype(np.float32)
            c2w = wcam[j].copy()
            c2w[:3, :3] = R @ c2w[:3, :3]
            c2w[:3, 3] = s * (R @ c2w[:3, 3]) + tr
            cams[g], conf[g], mask[g] = c2w, wc[j], wm[j]
        torch.cuda.empty_cache()
        t_stitch += time.perf_counter() - t0
    peak = torch.cuda.max_memory_allocated() / 2**30
    del model
    torch.cuda.empty_cache()
    log(f"  MapAnything: {n} views in {len(wins)} window(s) of {window}, grid {W}x{H}: model "
        f"{t_load:.1f} s, images {t_images:.1f} s, inference {t_infer:.1f} s, "
        f"outputs and stitching {t_stitch:.1f} s, peak {peak:.2f} GiB")
    return {"points": np.stack(pts), "conf": np.stack(conf), "mask": np.stack(mask),
            "cams": np.stack(cams).astype(np.float64), "grid": (int(H), int(W)),
            "windows": report, "load_s": round(t_load, 1), "peak_gib": round(peak, 2),
            "split_s": {"model": round(t_load, 1), "images": round(t_images, 1),
                        "inference": round(t_infer, 1), "stitch": round(t_stitch, 1)}}


# Measured on the RTX 4060 (8 GB): weights take 4.62 GiB; 48 views at 518x168 (444
# patch tokens each) peaked at 6.44 GiB and 32 at 518x294 (777 each) at 6.74, both
# about 8.5e-5 GiB per token. Past ~24k tokens a window gets slower per view (0.13 s
# at 48x444, 0.15 at 64x444), so that is the target when memory allows.
WEIGHTS_GIB, GIB_PER_TOKEN, HEADROOM_GIB, TARGET_TOKENS = 4.62, 1.82 / (48 * 444), 0.8, 24000


def pose_window_for(H: int, W: int, total_bytes: int) -> int:
    """
    Views per MapAnything window for this GPU and grid.

    The demo clip's top crop makes a wide 518x168 grid; an uncropped 16:9 frame is
    518x294, 1.75 times the tokens, so a window sized for one does not fit the other.
    """
    tokens = max((H // 14) * (W // 14), 1)
    budget = (total_bytes / 2**30 - WEIGHTS_GIB - HEADROOM_GIB) / GIB_PER_TOKEN
    return int(max(12, min(64, budget // tokens, TARGET_TOKENS // tokens)))


def fit_camera(ma: dict, h0: int, w0: int, crop, *, views: int, log=print) -> tuple:
    """One shared camera for the full keyframes, from a spread subset of the views."""
    from colmap_export import derive_intrinsics, full_frame_camera

    n = len(ma["cams"])
    pick = np.unique(np.linspace(0, n - 1, min(views, n)).astype(int))
    P, C, M = ma["points"][pick], ma["conf"][pick], ma["mask"][pick]
    # Same gate as mvs_job/run_mvs.py: the mask alone kept 99.9% of Toolse's pixels
    # and the fit came out at 10.7 px; gated on confidence it was 0.21 px.
    gate = C >= np.percentile(C, 30.0) if float(C.min()) != float(C.max()) else True
    H, W = ma["grid"]
    K, resid = derive_intrinsics(P.reshape(-1, 3), ma["cams"][pick], H, W,
                                 mask=(M & gate).reshape(-1))
    cam = full_frame_camera(K, H, W, h0, w0, log=log, crop_trbl=crop)
    if resid > 2.0:
        raise RuntimeError(f"intrinsics fit is bad ({resid:.2f} px); refusing to build on it")
    return cam, float(resid)


# ---------------------------------------------------------------------- COLMAP
def analyze(r: Runner, colmap: str, model: str, label: str) -> dict:
    out = r.sh([colmap, "model_analyzer", "--path", model], label)
    got = {}
    for line in out.splitlines():
        body = line.split("] ", 1)[-1].strip()
        for key in ("Registered images", "Points", "Observations", "Mean track length",
                    "Mean observations per image", "Mean reprojection error"):
            if body.startswith(key + ":") and key not in got:
                got[key] = body.split(":", 1)[1].strip()
    return got


def global_sparse(r: Runner, colmap: str, img: str, db: str, cam: dict, o: dict) -> str:
    """
    Poses from COLMAP's global mapper over long feature tracks, the camera held fixed.

    The camera is fixed because it cannot be recovered here. Self-calibrating, the
    incremental mapper put the demo's focal length at 576 px against the 1100 px
    MapAnything fits, and the ground curled into a bowl: a forward flight over flat
    ground barely constrains focal length. PINHOLE, so the undistorter hands OpenMVS a
    camera it accepts (a SIMPLE_RADIAL with k = 0 is copied through and refused).
    """
    r.sh([colmap, "feature_extractor", "--database_path", db, "--image_path", img,
          "--ImageReader.single_camera", "1",
          "--ImageReader.camera_model", "PINHOLE",
          "--ImageReader.camera_params",
          f"{cam['f']},{cam['f']},{cam['cx']},{cam['cy']}",
          "--FeatureExtraction.use_gpu", "1",
          "--SiftExtraction.max_num_features", o["sift_features"]], "feature_extractor")
    # Wide, not exhaustive: exhaustive grows with the square of the view count. On the
    # demo, keyframes still shared 50+ verified matches 30-40 apart, and a window of 30
    # kept 78% of the ground on one plane against 82% for all pairs, in 14 s against
    # about 100 s.
    r.sh([colmap, "sequential_matcher", "--database_path", db,
          "--SequentialMatching.overlap", o["global_match_overlap"],
          "--FeatureMatching.use_gpu", "1"], "sequential_matcher")
    out = os.path.join(r.work, "sparse_g")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    r.sh(with_extra([colmap, "global_mapper", "--database_path", db, "--image_path", img,
          "--output_path", out,
          "--GlobalMapper.ba_refine_focal_length", "0",
          "--GlobalMapper.ba_refine_principal_point", "0",
          "--GlobalMapper.ba_refine_extra_params", "0"], o["mapper_extra"]),
         "global_mapper")
    models = [os.path.join(out, d) for d in os.listdir(out)
              if os.path.exists(os.path.join(out, d, "images.bin"))]
    if not models:
        raise RuntimeError("global_mapper wrote no model")
    # Several models mean the views split into groups with no shared tracks; the
    # largest is kept and the S3b gate then refuses the run for the views it lacks.
    return max(models, key=lambda m: os.path.getsize(os.path.join(m, "images.bin")))


def mapanything_sparse(r: Runner, colmap: str, img: str, db: str, names: list,
                       cams_ma: np.ndarray, cam: dict, o: dict, log=print) -> tuple:
    """MapAnything's stitched poses, triangulated against and refined by BA."""
    from colmap_export import write_model

    r.sh([colmap, "feature_extractor", "--database_path", db, "--image_path", img,
          "--ImageReader.single_camera", "1",
          "--ImageReader.camera_model", "SIMPLE_RADIAL",
          "--FeatureExtraction.use_gpu", "1",
          "--SiftExtraction.max_num_features", o["sift_features"]], "feature_extractor")
    # Sequential, not exhaustive. Exhaustive over 45 views was 391 s on 8 vCPU and
    # grows with the square of the count: about 19 h at 600 views. A video's
    # neighbours are its neighbours in time.
    r.sh([colmap, "sequential_matcher", "--database_path", db,
          "--SequentialMatching.overlap", o["match_overlap"],
          "--FeatureMatching.use_gpu", "1"], "sequential_matcher")

    sp_in, sp_tri, sp_ba, sp_f = (os.path.join(r.work, d) for d in
                                  ("sparse_in", "sparse_tri", "sparse_ba", "sparse_f"))
    for d in (sp_in, sp_tri, sp_ba, sp_f):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    write_model(sp_in, cams_ma, names, cam, db, log=log)
    r.sh([colmap, "point_triangulator", "--database_path", db, "--image_path", img,
          "--input_path", sp_in, "--output_path", sp_tri,
          "--Mapper.ba_global_max_refinements", o["tri_refinements"],
          "--Mapper.ba_global_max_num_iterations", o["tri_ba_iterations"]],
         "point_triangulator")
    before = analyze(r, colmap, sp_tri, "analyze_triangulated")
    r.sh([colmap, "bundle_adjuster", "--input_path", sp_tri, "--output_path", sp_ba,
          "--BundleAdjustment.refine_focal_length", "1",
          "--BundleAdjustment.refine_principal_point", "1",
          "--BundleAdjustment.refine_extra_params", "1",
          "--BundleAdjustmentCeres.max_num_iterations", o["ba_iterations"]],
         "bundle_adjuster")
    # Drop the observations BA could not explain. The demo's first run converged to a
    # 0.28 px cost, yet model_analyzer reported a mean error of 2.0e149 px: a handful
    # of points triangulated at near-zero depth dominate a plain mean. The mapper does
    # this filtering itself; triangulating against known poses skips it. The COLMAP
    # 4.2 Windows build has no CUDA Ceres, so BA stays on the CPU.
    r.sh([colmap, "point_filtering", "--input_path", sp_ba, "--output_path", sp_f,
          "--max_reproj_error", "4", "--min_tri_angle", "1.5"], "point_filtering")
    return before, sp_f


def read_images_txt(path: str) -> dict:
    """{name: cam2world 4x4} from a COLMAP text model's images.txt."""
    from scipy.spatial.transform import Rotation

    out, lines = {}, open(path, encoding="utf-8").read().splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("#") or not ln.strip():
            i += 1
            continue
        p = ln.split()
        qw, qx, qy, qz, tx, ty, tz = map(float, p[1:8])
        R = Rotation.from_quat([qx, qy, qz, qw]).as_matrix()      # world -> camera
        c2w = np.eye(4)
        c2w[:3, :3] = R.T
        c2w[:3, 3] = -R.T @ np.array([tx, ty, tz])
        out[p[9]] = c2w
        i += 2
    return out


_PLY = {"float": "<f4", "float32": "<f4", "double": "<f8", "float64": "<f8",
        "uchar": "u1", "uint8": "u1", "char": "i1", "int8": "i1", "short": "<i2",
        "int16": "<i2", "ushort": "<u2", "uint16": "<u2", "int": "<i4", "int32": "<i4",
        "uint": "<u4", "uint32": "<u4"}


def read_ply_points(path: str) -> tuple[np.ndarray, np.ndarray | None]:
    """
    xyz (float32) and rgb (uint8) from a binary little-endian PLY's vertex element.

    OpenMVS writes two list properties per vertex (view_indices, view_weights), so
    records are variable length and one fixed-size frombuffer reads garbage: the first
    attempt returned values up to 3.4e38. plyfile parses it correctly but took 7.5 s
    for 708k points; this walks the list lengths once and gathers the fixed fields.
    """
    with open(path, "rb") as f:
        head = []
        while True:
            ln = f.readline().decode("ascii", "replace").strip()
            head.append(ln)
            if ln == "end_header":
                break
        data = f.read()
    if "format binary_little_endian 1.0" not in head:
        raise ValueError(f"{path}: expected binary little-endian PLY")
    n, fixed, lists, in_vertex = 0, [], [], False
    for ln in head:
        p = ln.split()
        if p[:2] == ["element", "vertex"]:
            n, in_vertex = int(p[2]), True
        elif p and p[0] == "element":
            in_vertex = False
        elif in_vertex and p[:1] == ["property"]:
            if p[1] == "list":
                lists.append((np.dtype(_PLY[p[2]]).itemsize, np.dtype(_PLY[p[3]]).itemsize))
            elif lists:
                raise ValueError(f"{path}: scalar vertex property after a list")
            else:
                fixed.append((p[2], _PLY[p[1]]))
    rec = np.dtype(fixed)
    if not lists:
        v = np.frombuffer(data, dtype=rec, count=n)
    else:
        if any(c != 1 for c, _ in lists):
            raise ValueError(f"{path}: only uint8 list counts are supported")
        offs = np.empty(n, np.int64)
        o, fs = 0, rec.itemsize
        for i in range(n):
            offs[i] = o
            o += fs
            for _, item in lists:
                o += 1 + item * data[o]
        buf = np.frombuffer(data, np.uint8)
        v = np.empty(n, rec)
        raw = v.view(np.uint8).reshape(n, fs)
        raw[:] = buf[offs[:, None] + np.arange(fs)]
    xyz = np.column_stack([v["x"], v["y"], v["z"]]).astype(np.float32)
    rgb = (np.column_stack([v["red"], v["green"], v["blue"]]).astype(np.uint8)
           if "red" in v.dtype.names else None)
    return xyz, rgb


# ---------------------------------------------------------------------- pipeline
def run(images_dir: str, work: str, *, crop_trbl=None, dense_names: list | None = None,
        options: dict | None = None, sparse_from: str | None = None, log=print) -> dict:
    """
    Keyframes in, geometry out. `dense_names` limits densification to the dense view
    set (docs/13 section 3.2: poses want every view, density an even subset).
    `sparse_from` is a finished work folder whose poses are reused (reuse_sparse).
    """
    import cv2

    o = dict(DEFAULTS, **(options or {}))
    tools = find_tools()
    colmap, mvs = tools["colmap"], tools["openmvs"]
    r = Runner(work, log)
    t_all = time.perf_counter()
    names = sorted((f for f in os.listdir(images_dir)
                    if f.lower().endswith((".jpg", ".jpeg", ".png"))), key=frame_order)
    if len(names) < 3:
        raise RuntimeError(f"{images_dir}: {len(names)} keyframes; need at least 3")
    # COLMAP reads every file in its image folder, so a folder holding anything but
    # the keyframes (ingest.json, from the CLI) is copied; tesseract's is used as is.
    img = os.path.abspath(images_dir)
    if len(names) != len([f for f in os.listdir(img)
                          if os.path.isfile(os.path.join(img, f))]):
        img = os.path.join(r.work, "images")
        shutil.rmtree(img, ignore_errors=True)
        shutil.copytree(images_dir, img, ignore=shutil.ignore_patterns("*.json"))
    h0, w0 = cv2.imread(os.path.join(img, names[0])).shape[:2]

    def finish():
        result["stages"] = r.times
        result["total_seconds"] = round(time.perf_counter() - t_all, 1)
        with open(os.path.join(r.work, "local_gpu_result.json"), "w",
                  encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        return result

    sp_txt = os.path.join(r.work, "sparse_txt")
    if sparse_from:
        result = reuse_sparse(sparse_from, r.work, names, o)
    else:
        result = sparse(r, colmap, img, names, h0, w0, crop_trbl, o, log)
        if not result["ba_gate"]["passed"]:
            finish()
            raise SparseError("S3b gate failed: " + "; ".join(result["ba_gate"]["problems"]))
        sp_f = result.pop("model")
        shutil.rmtree(sp_txt, ignore_errors=True)
        os.makedirs(sp_txt)
        r.sh([colmap, "model_converter", "--input_path", sp_f, "--output_path", sp_txt,
              "--output_type", "TXT"], "model_converter")
        poses = read_images_txt(os.path.join(sp_txt, "images.txt"))
        np.save(os.path.join(r.work, "cameras.npy"),
                np.stack([poses.get(n, np.full((4, 4), np.nan)) for n in names]))
        result["unregistered"] = [n for n in names if n not in poses]
    result["options"] = o
    # A view the mapper could not place has no pose to densify from; its row in
    # cameras.npy is NaN, so consumers keep their index into the keyframes.
    lost = set(result.get("unregistered") or ())
    if lost:
        log(f"  {len(lost)} of {len(names)} views unregistered; densifying the rest")
        dense_names = [n for n in (dense_names or names) if n not in lost]
    # Written now as well as at the end, so a run that fails in the dense half leaves
    # poses that a rerun at the next ladder level can take (reuse_sparse).
    finish()
    return dense(r, mvs, colmap, img, sp_txt, names, dense_names, o, result, finish, log)


# The poses half of a result, which a dense-only rerun copies from the run it reuses.
SPARSE_KEYS = ("n_views", "keyframe_size", "pose_method", "mapanything_views", "camera",
               "intrinsics_fit_residual_px", "stitch", "mapanything_s",
               "mapanything_peak_gib", "sparse_after_triangulation",
               "sparse_after_bundle_adjustment", "ba_gate", "unregistered")


def reuse_sparse(src: str, work: str, names: list, o: dict) -> dict:
    """
    Take the poses of a finished run in `src` instead of solving them again.

    Everything up to the S3b gate depends only on the keyframes and the pose options,
    so a dense-only change (a ladder step after a densify failure, or an experiment on
    the dense settings) need not pay for MapAnything, matching and the mapper again:
    on the demo that is 130 of 314 s.
    """
    with open(os.path.join(src, "local_gpu_result.json"), encoding="utf-8") as f:
        prev = json.load(f)
    if prev.get("n_views") != len(names):
        raise SparseError(f"{src} solved {prev.get('n_views')} views, not {len(names)}")
    if not (prev.get("ba_gate") or {}).get("passed"):
        raise SparseError(f"{src} did not pass the S3b gate")
    pose_opts = [k for k in DEFAULTS if k not in DENSE_OPTIONS]
    changed = [k for k in pose_opts if (prev.get("options") or {}).get(k) != o.get(k)]
    if changed:
        raise SparseError(f"pose options differ from {src}: {', '.join(changed)}")
    for f in ("sparse_txt", "cameras.npy"):
        a, b = os.path.join(src, f), os.path.join(work, f)
        if os.path.abspath(a) == os.path.abspath(b):
            continue
        if os.path.isdir(a):
            shutil.rmtree(b, ignore_errors=True)
            shutil.copytree(a, b)
        else:
            shutil.copyfile(a, b)
    out = {k: prev[k] for k in SPARSE_KEYS if k in prev}
    out["sparse_from"] = os.path.abspath(src)
    return out


# Options read only after the S3b gate. reuse_sparse checks that the rest match.
DENSE_OPTIONS = ("dense_resolution_level", "dense_views_fuse", "dense_neighbours",
                 "dense_fusion_filter", "mesh_min_point_distance", "mesh", "texture",
                 "texture_decimate", "keep_intermediate", "densify_extra", "mesh_extra",
                 "texture_extra")


def sparse(r: Runner, colmap: str, img: str, names: list, h0: int, w0: int, crop_trbl,
           o: dict, log=print) -> dict:
    """Camera, matches and poses up to the S3b gate; the solved model is in "model"."""
    from run_mvs import ba_gate

    # Everything up to the S3b gate depends on the poses and the matches, not on the
    # ladder level, so a failure here is a SparseError: tesseract does not rerun it
    # at L1 and L2 to meet the same failure (audit 1). colmap_export refuses with
    # SystemExit, which would otherwise end the whole process with no manifest.
    try:
        glob_poses = o["pose_method"] == "global"
        if o["pose_method"] not in ("global", "mapanything"):
            raise RuntimeError(f"pose_method {o['pose_method']!r}: global or mapanything")
        # The global path wants MapAnything only for the camera, which one spread subset
        # of the views fits as well as all of them.
        ma_names = ([names[i] for i in np.unique(np.linspace(
                        0, len(names) - 1, min(o["intrinsics_views"], len(names))).astype(int))]
                    if glob_poses else names)
        ma = r.timed("poses (MapAnything)", mapanything_poses,
                     [os.path.join(img, n) for n in ma_names],
                     window=o["pose_window"], overlap=o["pose_overlap"], size=o["pose_size"],
                     log=log)
        cam, resid = r.timed("intrinsics fit", fit_camera, ma, h0, w0, crop_trbl,
                             views=o["intrinsics_views"], log=log)
        cams_ma = ma.pop("cams")
        stitch, ma_load, ma_peak = ma["windows"], ma["split_s"], ma["peak_gib"]
        del ma

        db = os.path.join(r.work, "db.db")
        if os.path.exists(db):
            os.remove(db)
        if glob_poses:
            before, sp_f = None, global_sparse(r, colmap, img, db, cam, o)
        else:
            before, sp_f = mapanything_sparse(r, colmap, img, db, names, cams_ma, cam, o,
                                              log=log)
        after = analyze(r, colmap, sp_f, "analyze_adjusted")
    except (SystemExit, ImportError) as e:
        raise SparseError(str(e)) from None
    except RuntimeError as e:
        raise SparseError(str(e)) from e
    problems = ba_gate(after, len(names), min_registered=o["min_registered"])
    return {"n_views": len(names), "keyframe_size": [w0, h0],
            "pose_method": o["pose_method"], "mapanything_views": len(ma_names),
            "camera": {k: (round(v, 3) if isinstance(v, float) else v)
                       for k, v in cam.items() if k != "crop_span_full"},
            "intrinsics_fit_residual_px": round(resid, 4), "stitch": stitch,
            "mapanything_s": ma_load, "mapanything_peak_gib": ma_peak,
            "sparse_after_triangulation": before,
            "sparse_after_bundle_adjustment": after,
            "ba_gate": {"passed": not problems, "problems": problems}, "model": sp_f}


def dense(r: Runner, mvs: dict, colmap: str, img: str, sp_txt: str, names: list,
          dense_names: list | None, o: dict, result: dict, finish, log=print) -> dict:
    """Undistort, densify, mesh and texture on the solved poses in `sp_txt`."""
    from run_mvs_sharded import filter_model

    dense_model = sp_txt
    if dense_names and len(dense_names) < len(names):
        dense_model = os.path.join(r.work, "sparse_dense")
        shutil.rmtree(dense_model, ignore_errors=True)
        r.timed("dense subset", filter_model, sp_txt, dense_model, set(dense_names))
    undist = os.path.join(r.work, "dense")
    shutil.rmtree(undist, ignore_errors=True)
    r.sh([colmap, "image_undistorter", "--image_path", img, "--input_path", dense_model,
          "--output_path", undist, "--output_type", "COLMAP"], "image_undistorter")
    r.sh([mvs["InterfaceCOLMAP"], "-i", undist, "-o", "scene.mvs", "-w", r.work],
         "InterfaceCOLMAP")
    # No region of interest: OpenMVS estimates one assuming a Z-up scene and trims the
    # cloud to it, which cut the far field of this oblique, forward-looking footage.
    # Tower mode is for orbits around a vertical structure and would add a cylinder of
    # points to pick neighbours with.
    r.sh(with_extra([mvs["DensifyPointCloud"], "scene.mvs", "-w", r.work,
          "--resolution-level", o["dense_resolution_level"],
          "--number-views-fuse", o["dense_views_fuse"],
          "--number-views", o["dense_neighbours"],
          "--fusion-filter", o["dense_fusion_filter"],
          "--estimate-roi", "0", "--crop-to-roi", "0", "--tower-mode", "0",
          "--cuda-device", "0", "--max-threads", "0"], o["densify_extra"]),
         "DensifyPointCloud")
    P, C = read_ply_points(os.path.join(r.work, "scene_dense.ply"))
    np.save(os.path.join(r.work, "points_fused.npy"), P)
    if C is not None:
        np.save(os.path.join(r.work, "colors_fused.npy"), C)
    result["dense_points"] = int(len(P))
    if o["mesh"]:
        # The mesh is a product, not an input: tesseract loads the dense cloud. A
        # meshing failure is recorded rather than failing the stage (audit 1).
        try:
            r.sh(with_extra([mvs["ReconstructMesh"], "scene_dense.mvs", "-w", r.work,
                  "-d", o["mesh_min_point_distance"]], o["mesh_extra"]),
                 "ReconstructMesh")
        except RuntimeError as e:
            result["mesh_error"] = str(e)[-500:]
            log("  ReconstructMesh failed; continuing without a mesh")
    if o["mesh"] and o["texture"] and "mesh_error" not in result:
        # Colour from the photos, not from the nearest dense point: the page coloured
        # each vertex of a thinned mesh that way and the result was a smear. Textured
        # after decimating to `texture_decimate`, so the OBJ is one a browser can hold
        # (demo: 2.1M faces to 208k, 60 s, one 4096 px atlas). Seam levelling is off:
        # with it on, 73% of the demo's faces sampled black from the atlas (95% with
        # the global pass alone, 66% with the local one), and 0.2% with both off.
        try:
            r.sh(with_extra([mvs["TextureMesh"], "scene.mvs", "-m", "scene_dense_mesh.ply",
                  "-w", r.work, "--decimate", o["texture_decimate"],
                  "--global-seam-leveling", "0", "--local-seam-leveling", "0",
                  "--export-type", "obj", "-o", "scene_tex.mvs"], o["texture_extra"]),
                 "TextureMesh")
            result["textured_mesh"] = "scene_tex.obj"
        except RuntimeError as e:
            result["texture_error"] = str(e)[-500:]
            log("  TextureMesh failed; continuing with the untextured mesh")
    if not o["keep_intermediate"]:
        clean_work(r.work)
        if img == os.path.join(r.work, "images"):
            shutil.rmtree(img, ignore_errors=True)
    return finish()


# Rebuilt by any rerun and read by nothing after S3. scene_dense.ply is the same cloud
# as points_fused.npy plus colors_fused.npy with OpenMVS's per-point view lists, 3.7
# times their size: 376 MB of a 1.24 GB demo run, and S6 exports the cloud again.
INTERMEDIATE = ("db.db", "dense", "sparse_in", "sparse_tri", "sparse_ba",
                "sparse_dense", "sparse_g", "scene_dense.ply")


def clean_work(work: str) -> list[str]:
    """Delete S3's bulky intermediates from `work`; returns the names removed."""
    gone = []
    for f in sorted(os.listdir(work)):
        p = os.path.join(work, f)
        if f.endswith(".dmap") or f in INTERMEDIATE:
            shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
            gone.append(f)
    return gone


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("keyframes", help="folder of keyframes, with ingest.json if S1 wrote it")
    ap.add_argument("--work", required=True)
    ap.add_argument("--dense-every", type=int, default=1,
                    help="densify every Nth keyframe (1 = all)")
    ap.add_argument("--no-mesh", action="store_true")
    ap.add_argument("--sparse-from", help="a finished work folder whose poses to reuse")
    ap.add_argument("--set", action="append", default=[],
                    help="option=value, any key of DEFAULTS")
    a = ap.parse_args()
    opts = {"mesh": not a.no_mesh}
    for kv in a.set:
        k, v = kv.split("=", 1)
        opts[k] = type(DEFAULTS[k])(v) if not isinstance(DEFAULTS[k], bool) else v == "1"
    crop = None
    ij = os.path.join(a.keyframes, "ingest.json")
    if os.path.exists(ij):
        crop = json.load(open(ij, encoding="utf-8"))["stats"].get("overlay_crop_trbl")
    kfs = sorted((f for f in os.listdir(a.keyframes) if f.lower().endswith(".jpg")),
                 key=frame_order)
    res = run(a.keyframes, a.work, crop_trbl=crop, dense_names=kfs[::a.dense_every],
              options=opts, sparse_from=a.sparse_from)
    print(json.dumps({k: res[k] for k in ("n_views", "dense_points", "total_seconds",
                                          "ba_gate", "stages") if k in res}, indent=2))
