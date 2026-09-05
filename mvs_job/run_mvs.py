"""
S2b/S3/S4 - the MVS stage.

Replaces the feed-forward point maps as the source of geometry, keeping only the
model's poses. The point maps are quantised to one DINOv2 patch (14 px) and smoothly
interpolated below it, so they cannot carry detail finer than ~30-50 cm on this
footage no matter what is done downstream; PatchMatch estimates depth PER PIXEL by
photometric matching, on the full-resolution keyframe rather than the model's
392x518 grid. See docs/05-quality-analysis.md.

Order matters. Bundle adjustment runs BEFORE densification, not after: feed-forward
poses carry error that MVS would otherwise reproject faithfully into a surface that
looks sharper and is wrong.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import numpy as np

BUCKET = os.environ.get("BUCKET", "sih26158-mumbai")
KF_PREFIX = os.environ.get("KF_PREFIX", "mapanything/ytd_input")
MA_PREFIX = os.environ.get("MA_PREFIX", "mapanything/ytd_out")
OUT_PREFIX = os.environ.get("OUT_PREFIX", "mvs/ytd_out")
RES_LEVEL = os.environ.get("RESOLUTION_LEVEL", "0")     # 0 = full resolution
REFINE = os.environ.get("REFINE_MESH", "0") == "1"
W = "/tmp/mvs"
TIMES: list = []


def sh(cmd: list, stage: str, fatal=True, tail=14):
    t0 = time.perf_counter()
    print(f"\n>>> {stage}\n    $ {' '.join(str(c) for c in cmd)}", flush=True)
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    dt = time.perf_counter() - t0
    out = (p.stdout or "") + (p.stderr or "")
    for line in out.strip().splitlines()[-tail:]:
        print("    " + line[:200], flush=True)
    TIMES.append({"stage": stage, "seconds": round(dt, 1), "rc": p.returncode})
    print(f"    [{stage}] rc={p.returncode} in {dt:.1f}s", flush=True)
    if p.returncode and fatal:
        sys.exit(f"FAILED at {stage}")
    return out


def gcs():
    from google.cloud import storage
    return storage.Client().bucket(BUCKET)


def fetch():
    b = gcs()
    os.makedirs(f"{W}/images", exist_ok=True)
    os.makedirs(f"{W}/ma", exist_ok=True)
    n = 0
    for blob in b.list_blobs(prefix=KF_PREFIX + "/"):
        fn = os.path.basename(blob.name)
        if fn.lower().endswith((".jpg", ".jpeg", ".png")):
            blob.download_to_filename(f"{W}/images/{fn}")
            n += 1
    for want in ("cameras.npy", "points.npy", "mask.npy", "mapanything_result.json"):
        b.blob(f"{MA_PREFIX}/{want}").download_to_filename(f"{W}/ma/{want}")
    print(f"  fetched {n} keyframes + MapAnything poses", flush=True)
    return n


def push(paths: dict):
    b = gcs()
    for name, p in paths.items():
        if p and os.path.exists(p):
            b.blob(f"{OUT_PREFIX}/{name}").upload_from_filename(p)
            print(f"  uploaded gs://{BUCKET}/{OUT_PREFIX}/{name} "
                  f"({os.path.getsize(p)/1e6:.1f} MB)", flush=True)


def reproj_error(model_dir: str, label: str):
    """COLMAP's own mean reprojection error - the check that the poses and the
    derived intrinsics are mutually consistent. A bad seed shows up here as tens of
    pixels, long before it becomes a confidently wrong surface."""
    out = sh(["colmap", "model_analyzer", "--path", model_dir],
             f"model_analyzer ({label})", fatal=False, tail=12)
    got = {}
    # COLMAP logs through glog, so every line carries an
    # "I20260905 14:05:09.364653 1397... model.cc:467] " prefix - a startswith test
    # against the field name matches nothing and silently yields an empty dict.
    for line in out.splitlines():
        body = line.split("] ", 1)[-1].strip()
        for key in ("Registered images", "Cameras", "Images", "Points",
                    "Observations", "Mean track length",
                    "Mean observations per image", "Mean reprojection error"):
            if body.startswith(key + ":") and key not in got:
                got[key] = body.split(":", 1)[1].strip()
    return got


def main():
    print("=" * 74)
    print("MVS stage: MapAnything poses -> COLMAP BA -> OpenMVS dense + mesh (CPU)")
    print("=" * 74, flush=True)
    t_all = time.perf_counter()
    n_img = fetch()

    res = json.load(open(f"{W}/ma/mapanything_result.json"))
    names = res["images"]
    H, W_ = res["view_shapes"][0]
    cams = np.load(f"{W}/ma/cameras.npy").astype(np.float64)
    pts = np.load(f"{W}/ma/points.npy")

    import cv2
    im0 = cv2.imread(f"{W}/images/{names[0]}")
    h0, w0 = im0.shape[:2]

    sys.path.insert(0, "/app")
    from colmap_export import derive_intrinsics, full_frame_camera, write_model

    msk = np.load(f"{W}/ma/mask.npy") if os.path.exists(f"{W}/ma/mask.npy") else None
    K, resid = derive_intrinsics(pts, cams, H, W_, mask=msk)
    cam = full_frame_camera(K, H, W_, h0, w0)
    print(f"\n  intrinsics fitted from the point maps:"
          f"\n    grid {W_}x{H}  fx {np.median(K[:,0]):.2f}  fy {np.median(K[:,1]):.2f}"
          f"  (median of {len(K)} views, fx/fy "
          f"{np.median(K[:,0])/np.median(K[:,1]):.4f})"
          f"\n    reprojection residual {resid:.4f} px (median over {len(K)} views)"
          f"\n    full frame {w0}x{h0}  f={cam['f']:.1f} cx={cam['cx']:.1f} "
          f"cy={cam['cy']:.1f}"
          f"\n    model saw original x in "
          f"[{cam['crop_span_full'][0]:.1f}, {cam['crop_span_full'][1]:.1f}]", flush=True)
    if resid > 2.0:
        sys.exit(f"intrinsics fit is bad ({resid:.2f} px) - refusing to build on it")
    del pts

    db = f"{W}/db.db"
    sh(["colmap", "feature_extractor", "--database_path", db,
        "--image_path", f"{W}/images",
        "--ImageReader.single_camera", "1",
        "--ImageReader.camera_model", "SIMPLE_RADIAL",
        "--FeatureExtraction.use_gpu", "0",
        "--SiftExtraction.max_image_size", str(max(h0, w0)),
        "--SiftExtraction.max_num_features", "16384"], "feature_extractor")

    # Exhaustive over 42 images is 861 pairs - cheap, and it gives the triangulation
    # long-baseline pairs that a sequential-only pass would never form.
    sh(["colmap", "exhaustive_matcher", "--database_path", db,
        "--FeatureMatching.use_gpu", "0"], "exhaustive_matcher")

    os.makedirs(f"{W}/sparse_in", exist_ok=True)
    write_model(f"{W}/sparse_in", cams, names, cam, db)

    # Triangulate against the KNOWN poses: no incremental SfM, no chance of the
    # reconstruction fragmenting or flipping scale.
    os.makedirs(f"{W}/sparse_tri", exist_ok=True)
    sh(["colmap", "point_triangulator", "--database_path", db,
        "--image_path", f"{W}/images",
        "--input_path", f"{W}/sparse_in",
        "--output_path", f"{W}/sparse_tri",
        "--Mapper.ba_use_gpu", "0"], "point_triangulator")
    before = reproj_error(f"{W}/sparse_tri", "after triangulation")

    os.makedirs(f"{W}/sparse_ba", exist_ok=True)
    subprocess.run(["cp", "-r", f"{W}/sparse_tri/.", f"{W}/sparse_ba/"], check=True)
    sh(["colmap", "bundle_adjuster",
        "--input_path", f"{W}/sparse_tri", "--output_path", f"{W}/sparse_ba",
        "--BundleAdjustment.refine_focal_length", "1",
        "--BundleAdjustment.refine_principal_point", "1",
        "--BundleAdjustment.refine_extra_params", "1",
        "--BundleAdjustment.use_gpu", "0"], "bundle_adjuster")
    after = reproj_error(f"{W}/sparse_ba", "after bundle adjustment")

    sh(["colmap", "image_undistorter", "--image_path", f"{W}/images",
        "--input_path", f"{W}/sparse_ba", "--output_path", f"{W}/dense",
        "--output_type", "COLMAP"], "image_undistorter")

    sh(["InterfaceCOLMAP", "-i", f"{W}/dense", "-o", f"{W}/scene.mvs",
        "-w", W], "InterfaceCOLMAP")

    # THE stage this whole rebuild exists for: per-pixel photometric depth at full
    # resolution, with geometric-consistency filtering instead of voxel averaging.
    sh(["DensifyPointCloud", f"{W}/scene.mvs", "-w", W,
        "--resolution-level", RES_LEVEL,
        "--number-views-fuse", "3",
        "--max-threads", str(os.cpu_count() or 8)], "DensifyPointCloud")
    push({"scene_dense.ply": f"{W}/scene_dense.ply",
          "scene_dense.mvs": f"{W}/scene_dense.mvs"})

    # Delaunay + graph cut, not screened Poisson: it respects depth discontinuities
    # instead of closing smoothly over them.
    sh(["ReconstructMesh", f"{W}/scene_dense.mvs", "-w", W], "ReconstructMesh")
    mesh = f"{W}/scene_dense_mesh.mvs"
    if REFINE and os.path.exists(mesh):
        sh(["RefineMesh", mesh, "-w", W,
            "--resolution-level", "1"], "RefineMesh", fatal=False)
        mesh = f"{W}/scene_dense_mesh_refine.mvs" if os.path.exists(
            f"{W}/scene_dense_mesh_refine.mvs") else mesh
    sh(["TextureMesh", mesh, "-w", W], "TextureMesh", fatal=False)

    summary = {
        "n_images": n_img, "full_frame": [w0, h0], "model_grid": [W_, H],
        "intrinsics_fit_residual_px": round(resid, 4),
        "camera": {k: (round(v, 3) if isinstance(v, float) else v)
                   for k, v in cam.items() if k != "crop_span_full"},
        "sparse_after_triangulation": before,
        "sparse_after_bundle_adjustment": after,
        "resolution_level": RES_LEVEL,
        "stages": TIMES,
        "total_seconds": round(time.perf_counter() - t_all, 1),
    }
    json.dump(summary, open(f"{W}/mvs_result.json", "w"), indent=2)

    out = {"mvs_result.json": f"{W}/mvs_result.json"}
    for f in os.listdir(W):
        if f.endswith((".ply", ".mvs")) and os.path.getsize(f"{W}/{f}") < 900e6:
            out[f] = f"{W}/{f}"
    push(out)
    print("\n" + json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
