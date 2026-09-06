"""
Sharded MVS: trade the GPU we cannot get for the CPU width we can.

There is no usable GPU on this billing account (docs/06-gcp-deployment.md), and the
single-task CPU pipeline does not meet the PS speed budget on a full-length clip:
45 views cost 33 min, of which 27 min is densification, and a 10-minute video is ~600
views. Vertical scaling is closed - Cloud Run caps a task at 8 vCPU.

Horizontal is wide open, and nobody had looked. Cloud Run's quota is a separate domain
from Compute Engine's: **20 vCPU and 40 GiB per project per region**, and the billing
account has **five** projects, all in asia-south1. That is 100 vCPU and 200 GiB of Mumbai
compute - in the region the geospatial rules require, which no GPU option offered.

The reason this shards cleanly is the architecture we already have. Poses come from ONE
global bundle adjustment over all views, so every window's dense cloud is already in the
same metric frame: the shards CONCATENATE. EXP-13 needed a Sim(3) chain to stitch windows
precisely because it had no global BA to lean on. Here that whole problem is absent.

Three stages, one container, selected by STAGE:

  prep      1 task   ingest poses, SIFT, match, triangulate, GLOBAL bundle adjust
  densify   N tasks  one view-window each -> per-shard dense PLY   <- the parallel one
  fuse      1 task   concatenate shards, dedupe the overlap, mesh
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np

BUCKET = os.environ.get("BUCKET", "sih26158-mumbai")
KF_PREFIX = os.environ.get("KF_PREFIX", "mapanything/kolu_input")
MA_PREFIX = os.environ.get("MA_PREFIX", "mapanything/kolu_out")
OUT_PREFIX = os.environ.get("OUT_PREFIX", "mvs/kolu_sharded")
STAGE = os.environ.get("STAGE", "prep")
RES_LEVEL = os.environ.get("RESOLUTION_LEVEL", "0")
N_SHARDS = int(os.environ.get("N_SHARDS", "5"))
OVERLAP = int(os.environ.get("SHARD_OVERLAP", "4"))
TASK = int(os.environ.get("CLOUD_RUN_TASK_INDEX", "0"))
W = "/tmp/mvs"
TIMES: list = []


def sh(cmd, stage, fatal=True, tail=10):
    t0 = time.perf_counter()
    print(f"\n>>> {stage}", flush=True)
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    dt = time.perf_counter() - t0
    for line in ((p.stdout or "") + (p.stderr or "")).strip().splitlines()[-tail:]:
        print("    " + line[:190], flush=True)
    TIMES.append({"stage": stage, "seconds": round(dt, 1), "rc": p.returncode})
    print(f"    [{stage}] rc={p.returncode} in {dt:.1f}s", flush=True)
    if p.returncode and fatal:
        sys.exit(f"FAILED at {stage}")
    return (p.stdout or "") + (p.stderr or "")


def bucket():
    from google.cloud import storage
    return storage.Client().bucket(BUCKET)


def pull(prefix, dest, only=None):
    os.makedirs(dest, exist_ok=True)
    n = 0
    for blob in bucket().list_blobs(prefix=prefix + "/"):
        fn = os.path.relpath(blob.name, prefix)
        if only and os.path.basename(fn) not in only:
            continue
        p = os.path.join(dest, fn)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        blob.download_to_filename(p)
        n += 1
    return n


def push(local, name):
    bucket().blob(f"{OUT_PREFIX}/{name}").upload_from_filename(local)
    print(f"  uploaded {name} ({os.path.getsize(local)/1e6:.1f} MB)", flush=True)


def push_dir(local, prefix):
    b = bucket()
    for root, _, files in os.walk(local):
        for f in files:
            p = os.path.join(root, f)
            rel = os.path.relpath(p, local).replace("\\", "/")
            b.blob(f"{OUT_PREFIX}/{prefix}/{rel}").upload_from_filename(p)
    print(f"  uploaded dir {prefix}", flush=True)


def windows(n_views, n_shards, overlap):
    """Contiguous view windows with overlap, so seams are covered from both sides."""
    base = max(1, -(-n_views // n_shards))
    out = []
    for i in range(n_shards):
        lo = max(0, i * base - overlap)
        hi = min(n_views, (i + 1) * base + overlap)
        if lo < hi:
            out.append((lo, hi))
    return out


# ---------------------------------------------------------------- stage: prep
def stage_prep():
    pull(KF_PREFIX, f"{W}/images")
    pull(MA_PREFIX, f"{W}/ma", only={"cameras.npy", "points.npy", "mask.npy",
                                     "mapanything_result.json"})
    res = json.load(open(f"{W}/ma/mapanything_result.json"))
    names, (H, W_) = res["images"], res["view_shapes"][0]
    cams = np.load(f"{W}/ma/cameras.npy").astype(np.float64)
    pts = np.load(f"{W}/ma/points.npy")
    msk = np.load(f"{W}/ma/mask.npy") if os.path.exists(f"{W}/ma/mask.npy") else None

    import cv2
    h0, w0 = cv2.imread(f"{W}/images/{names[0]}").shape[:2]
    sys.path.insert(0, "/app")
    from colmap_export import derive_intrinsics, full_frame_camera, write_model

    K, resid = derive_intrinsics(pts, cams, H, W_, mask=msk)
    cam = full_frame_camera(K, H, W_, h0, w0)
    print(f"  intrinsics f={cam['f']:.1f} cx={cam['cx']:.1f} cy={cam['cy']:.1f} "
          f"resid={resid:.4f}px", flush=True)
    if resid > 2.0:
        sys.exit(f"intrinsics fit {resid:.2f} px - refusing")
    del pts

    db = f"{W}/db.db"
    sh(["colmap", "feature_extractor", "--database_path", db, "--image_path",
        f"{W}/images", "--ImageReader.single_camera", "1",
        "--ImageReader.camera_model", "SIMPLE_RADIAL",
        "--FeatureExtraction.use_gpu", "0",
        "--SiftExtraction.max_image_size", str(max(h0, w0)),
        "--SiftExtraction.max_num_features", "16384"], "feature_extractor")
    sh(["colmap", "exhaustive_matcher", "--database_path", db,
        "--FeatureMatching.use_gpu", "0"], "exhaustive_matcher")
    os.makedirs(f"{W}/sparse_in", exist_ok=True)
    write_model(f"{W}/sparse_in", cams, names, cam, db)
    os.makedirs(f"{W}/sparse_tri", exist_ok=True)
    sh(["colmap", "point_triangulator", "--database_path", db, "--image_path",
        f"{W}/images", "--input_path", f"{W}/sparse_in", "--output_path",
        f"{W}/sparse_tri", "--Mapper.ba_use_gpu", "0"], "point_triangulator")

    # THE step that makes sharding trivial: one global bundle adjustment, so every
    # window inherits the same metric frame and the dense shards just concatenate.
    os.makedirs(f"{W}/sparse_ba", exist_ok=True)
    shutil.copytree(f"{W}/sparse_tri", f"{W}/sparse_ba", dirs_exist_ok=True)
    sh(["colmap", "bundle_adjuster", "--input_path", f"{W}/sparse_tri",
        "--output_path", f"{W}/sparse_ba",
        "--BundleAdjustment.refine_focal_length", "1",
        "--BundleAdjustment.refine_principal_point", "1",
        "--BundleAdjustment.refine_extra_params", "1",
        "--BundleAdjustment.use_gpu", "0"], "bundle_adjuster")
    out = sh(["colmap", "model_analyzer", "--path", f"{W}/sparse_ba"],
             "model_analyzer", fatal=False)
    err = next((l.split(":")[-1].strip() for l in out.splitlines()
                if "Mean reprojection error" in l), "?")

    sh(["colmap", "model_converter", "--input_path", f"{W}/sparse_ba",
        "--output_path", f"{W}/sparse_ba", "--output_type", "TXT"],
       "model_converter", fatal=False)
    push_dir(f"{W}/sparse_ba", "sparse_ba")
    plan = windows(len(names), N_SHARDS, OVERLAP)
    meta = {"n_views": len(names), "images": names, "windows": plan,
            "reproj_after_ba": err, "camera": cam, "stages": TIMES}
    json.dump(meta, open(f"{W}/prep.json", "w"), indent=2)
    push(f"{W}/prep.json", "prep.json")
    print(f"\n  {len(names)} views -> {len(plan)} windows {plan}", flush=True)


# ------------------------------------------------------------- stage: densify
def filter_model(src, dst, keep_names):
    """Write a COLMAP model containing only `keep_names`, with tracks trimmed.

    DensifyPointCloud uses the sparse points to pick view neighbours and bound the
    depth search, so a window needs its own consistent sparse model - handing it the
    global one would have it reason about views whose images are not present.
    """
    os.makedirs(dst, exist_ok=True)
    shutil.copy(f"{src}/cameras.txt", f"{dst}/cameras.txt")
    keep_ids, lines = set(), open(f"{src}/images.txt").read().splitlines()
    out = ["# IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME"]
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("#") or not ln.strip():
            i += 1
            continue
        parts = ln.split()
        if parts[-1] in keep_names:
            keep_ids.add(int(parts[0]))
            out.append(ln)
            out.append(lines[i + 1] if i + 1 < len(lines) else "")
        i += 2
    open(f"{dst}/images.txt", "w").write("\n".join(out) + "\n")

    kept = 0
    with open(f"{dst}/points3D.txt", "w") as f:
        f.write("# POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[]\n")
        for ln in open(f"{src}/points3D.txt"):
            if ln.startswith("#") or not ln.strip():
                continue
            p = ln.split()
            head, track = p[:8], p[8:]
            pairs = [(track[j], track[j + 1]) for j in range(0, len(track) - 1, 2)]
            pairs = [(a, b) for a, b in pairs if int(a) in keep_ids]
            if len(pairs) >= 2:      # a point needs two views to be a constraint
                f.write(" ".join(head) + " " +
                        " ".join(f"{a} {b}" for a, b in pairs) + "\n")
                kept += 1
    print(f"  window model: {len(keep_ids)} images, {kept} points", flush=True)
    return len(keep_ids), kept


def stage_densify():
    meta = json.loads(bucket().blob(f"{OUT_PREFIX}/prep.json")
                      .download_as_text())
    # Recompute the plan from THIS job's env rather than trusting prep.json. The
    # first version baked the windows in at prep time, so retuning the shard count
    # meant either re-running 452 s of SfM or hand-patching a JSON in the bucket.
    plan = windows(meta["n_views"], N_SHARDS, OVERLAP)
    if [list(w) for w in plan] != meta.get("windows"):
        print(f"  note: re-planned windows {plan} (prep.json had {meta.get('windows')})",
              flush=True)
    if TASK >= len(plan):
        print(f"  task {TASK} has no window ({len(plan)} windows) - exiting clean")
        return
    lo, hi = plan[TASK]
    names = meta["images"][lo:hi]
    print(f"  task {TASK}: views [{lo}:{hi}] = {len(names)} images", flush=True)

    pull(KF_PREFIX, f"{W}/images", only=set(names))
    pull(f"{OUT_PREFIX}/sparse_ba", f"{W}/sparse_ba")
    filter_model(f"{W}/sparse_ba", f"{W}/sparse_win", set(names))

    sh(["colmap", "image_undistorter", "--image_path", f"{W}/images",
        "--input_path", f"{W}/sparse_win", "--output_path", f"{W}/dense",
        "--output_type", "COLMAP"], "image_undistorter")
    sh(["InterfaceCOLMAP", "-i", f"{W}/dense", "-o", f"{W}/scene.mvs", "-w", W],
       "InterfaceCOLMAP")
    sh(["DensifyPointCloud", f"{W}/scene.mvs", "-w", W,
        "--resolution-level", RES_LEVEL, "--number-views-fuse", "3",
        "--max-threads", str(os.cpu_count() or 4)], "DensifyPointCloud")

    ply = f"{W}/scene_dense.ply"
    if not os.path.exists(ply):
        sys.exit("densify produced no cloud")
    push(ply, f"shards/dense_{TASK:03d}.ply")
    json.dump({"task": TASK, "window": [lo, hi], "n_images": len(names),
               "stages": TIMES}, open(f"{W}/s.json", "w"), indent=2)
    push(f"{W}/s.json", f"shards/shard_{TASK:03d}.json")


# ---------------------------------------------------------------- stage: fuse
def stage_fuse():
    import open3d as o3d
    os.makedirs(f"{W}/shards", exist_ok=True)
    n = pull(f"{OUT_PREFIX}/shards", f"{W}/shards")
    plys = sorted(f for f in os.listdir(f"{W}/shards") if f.endswith(".ply"))
    print(f"  {len(plys)} shards", flush=True)
    if not plys:
        sys.exit("no shards to fuse")

    P, C = [], []
    for f in plys:
        pc = o3d.io.read_point_cloud(f"{W}/shards/{f}")
        P.append(np.asarray(pc.points))
        C.append(np.asarray(pc.colors))
        print(f"    {f}: {len(pc.points):,}", flush=True)
    P, C = np.concatenate(P), np.concatenate(C)
    print(f"  concatenated {len(P):,} points", flush=True)

    # The windows overlap by design, so the seam regions are reconstructed twice.
    # A voxel merge at the native point spacing removes the duplicates without
    # touching anything else; sized from the data rather than a constant.
    pc = o3d.geometry.PointCloud()
    pc.points = o3d.utility.Vector3dVector(P)
    pc.colors = o3d.utility.Vector3dVector(C)
    d = np.asarray(pc.compute_nearest_neighbor_distance())
    vox = float(np.median(d[np.isfinite(d) & (d > 0)]))
    pc = pc.voxel_down_sample(vox)
    print(f"  deduped to {len(pc.points):,} at voxel {vox:.4f}", flush=True)
    o3d.io.write_point_cloud(f"{W}/scene_dense.ply", pc)
    push(f"{W}/scene_dense.ply", "scene_dense.ply")

    pc.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=vox * 4, max_nn=30))
    m, dens = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
        pc, depth=11, scale=1.1, linear_fit=False)
    m.remove_vertices_by_mask(np.asarray(dens) < np.quantile(np.asarray(dens), 0.06))
    m.remove_degenerate_triangles(); m.remove_unreferenced_vertices()
    print(f"  mesh {len(m.vertices):,} v / {len(m.triangles):,} t", flush=True)
    o3d.io.write_triangle_mesh(f"{W}/scene_dense_mesh.ply", m)
    push(f"{W}/scene_dense_mesh.ply", "scene_dense_mesh.ply")
    json.dump({"shards": len(plys), "points": len(pc.points),
               "vertices": len(m.vertices), "triangles": len(m.triangles),
               "voxel": vox, "stages": TIMES},
              open(f"{W}/fuse.json", "w"), indent=2)
    push(f"{W}/fuse.json", "fuse.json")


if __name__ == "__main__":
    print("=" * 70)
    print(f"sharded MVS | STAGE={STAGE} TASK={TASK} shards={N_SHARDS}")
    print("=" * 70, flush=True)
    t0 = time.perf_counter()
    {"prep": stage_prep, "densify": stage_densify, "fuse": stage_fuse}[STAGE]()
    print(f"\nSTAGE {STAGE} done in {time.perf_counter()-t0:.1f}s", flush=True)
