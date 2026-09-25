"""
S3 and S4 on one machine with an NVIDIA GPU: poses, bundle adjustment, dense cloud and
mesh, with no cloud job in the loop (docs/10 ADR-027, research/09-gpu-pipeline.md).

The cloud path (mapanything_job/, mvs_job/) runs on CPU because the GCP account has no
GPU quota. On Kolu that meant 11.45 s per view for poses, an exhaustive matcher that
grows with the square of the view count (391 s for 45 views), and 46 s per view to
densify (77% of a 34-minute run). Here, measured on an RTX 4060 laptop (8 GB):

  poses    MapAnything in bf16, in overlapping windows of views stitched into one
           frame, weights loaded once: about 0.13 s per view
  sparse   COLMAP with GPU SIFT and SEQUENTIAL matching (video order), triangulation
           against the known poses, bundle adjustment, then the S3b gate
  dense    OpenMVS DensifyPointCloud on CUDA over the dense view set only
  mesh     OpenMVS ReconstructMesh, optional

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
    "dense_resolution_level": 1,
    "dense_views_fuse": 3,
    "dense_neighbours": 5,      # views per depth map (OpenMVS default 8): 107 s to 96 s
    # ReconstructMesh's minimum point spacing in pixels (default 1.5): 91 s and 4.0M
    # faces at 1.5, 60 s and 2.6M at 2.5, on 600 views.
    "mesh_min_point_distance": 2.5,
    "mesh": True,
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
             ("InterfaceCOLMAP", "DensifyPointCloud", "ReconstructMesh")}
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
        options: dict | None = None, log=print) -> dict:
    """
    Keyframes in, geometry out. `dense_names` limits densification to the dense view
    set (docs/13 section 3.2: poses want every view, density an even subset).
    """
    import cv2
    from colmap_export import write_model
    from run_mvs import ba_gate
    from run_mvs_sharded import filter_model

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

    # Everything up to the S3b gate depends on the poses and the matches, not on the
    # ladder level, so a failure here is a SparseError: tesseract does not rerun it
    # at L1 and L2 to meet the same failure (audit 1). colmap_export refuses with
    # SystemExit, which would otherwise end the whole process with no manifest.
    try:
        ma = r.timed("poses (MapAnything)", mapanything_poses,
                     [os.path.join(img, n) for n in names],
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
        after = analyze(r, colmap, sp_f, "analyze_adjusted")
    except (SystemExit, ImportError) as e:
        raise SparseError(str(e)) from None
    except RuntimeError as e:
        raise SparseError(str(e)) from e
    problems = ba_gate(after, len(names))
    result = {"n_views": len(names), "keyframe_size": [w0, h0], "options": o,
              "camera": {k: (round(v, 3) if isinstance(v, float) else v)
                         for k, v in cam.items() if k != "crop_span_full"},
              "intrinsics_fit_residual_px": round(resid, 4), "stitch": stitch,
              "mapanything_s": ma_load, "mapanything_peak_gib": ma_peak,
              "sparse_after_triangulation": before,
              "sparse_after_bundle_adjustment": after,
              "ba_gate": {"passed": not problems, "problems": problems}}

    def finish():
        result["stages"] = r.times
        result["total_seconds"] = round(time.perf_counter() - t_all, 1)
        with open(os.path.join(r.work, "local_gpu_result.json"), "w",
                  encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        return result

    if problems:
        finish()
        raise SparseError("S3b gate failed: " + "; ".join(problems))

    sp_txt = os.path.join(r.work, "sparse_txt")
    shutil.rmtree(sp_txt, ignore_errors=True)
    os.makedirs(sp_txt)
    r.sh([colmap, "model_converter", "--input_path", sp_f, "--output_path", sp_txt,
          "--output_type", "TXT"], "model_converter")
    poses = read_images_txt(os.path.join(sp_txt, "images.txt"))
    np.save(os.path.join(r.work, "cameras.npy"),
            np.stack([poses.get(n, np.full((4, 4), np.nan)) for n in names]))

    dense_model = sp_txt
    if dense_names and len(dense_names) < len(names):
        dense_model = os.path.join(r.work, "sparse_dense")
        shutil.rmtree(dense_model, ignore_errors=True)
        r.timed("dense subset", filter_model, sp_txt, dense_model, set(dense_names))
    dense = os.path.join(r.work, "dense")
    shutil.rmtree(dense, ignore_errors=True)
    r.sh([colmap, "image_undistorter", "--image_path", img, "--input_path", dense_model,
          "--output_path", dense, "--output_type", "COLMAP"], "image_undistorter")
    r.sh([mvs["InterfaceCOLMAP"], "-i", dense, "-o", "scene.mvs", "-w", r.work],
         "InterfaceCOLMAP")
    r.sh([mvs["DensifyPointCloud"], "scene.mvs", "-w", r.work,
          "--resolution-level", o["dense_resolution_level"],
          "--number-views-fuse", o["dense_views_fuse"],
          "--number-views", o["dense_neighbours"],
          "--cuda-device", "0", "--max-threads", "0"], "DensifyPointCloud")
    P, C = read_ply_points(os.path.join(r.work, "scene_dense.ply"))
    np.save(os.path.join(r.work, "points_fused.npy"), P)
    if C is not None:
        np.save(os.path.join(r.work, "colors_fused.npy"), C)
    result["dense_points"] = int(len(P))
    if o["mesh"]:
        # The mesh is a product, not an input: tesseract loads the dense cloud. A
        # meshing failure is recorded rather than failing the stage (audit 1).
        try:
            r.sh([mvs["ReconstructMesh"], "scene_dense.mvs", "-w", r.work,
                  "-d", o["mesh_min_point_distance"]], "ReconstructMesh")
        except RuntimeError as e:
            result["mesh_error"] = str(e)[-500:]
            log("  ReconstructMesh failed; continuing without a mesh")
    if not o["keep_intermediate"]:
        for f in os.listdir(r.work):
            p = os.path.join(r.work, f)
            if f.endswith(".dmap") or f in ("db.db", "dense", "sparse_in", "sparse_tri",
                                              "sparse_ba", "sparse_dense"):
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
        if img == os.path.join(r.work, "images"):
            shutil.rmtree(img, ignore_errors=True)
    return finish()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("keyframes", help="folder of keyframes, with ingest.json if S1 wrote it")
    ap.add_argument("--work", required=True)
    ap.add_argument("--dense-every", type=int, default=1,
                    help="densify every Nth keyframe (1 = all)")
    ap.add_argument("--no-mesh", action="store_true")
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
              options=opts)
    print(json.dumps({k: res[k] for k in ("n_views", "dense_points", "total_seconds",
                                          "ba_gate", "stages") if k in res}, indent=2))
