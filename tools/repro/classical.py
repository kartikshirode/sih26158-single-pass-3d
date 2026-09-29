"""Classical baseline on the demo keyframes: COLMAP's own video workflow (one shared
SIMPLE_RADIAL camera self-calibrated, sequential matching, the incremental mapper, all at
their defaults), then OpenMVS. Scored on the same held-out views (every tenth keyframe
kept out of dense and texture, posed by the mapper like the rest).

python tools/repro/classical.py sparse            # solve and undistort into out/exp/bl-cl
python tools/repro/classical.py dense <tag> [defaults|defaults_ns|ours]

`defaults`: every OpenMVS setting at its default (ROI estimate and crop on, fusion filter
2, 8 neighbours, seam levelling on, sharpening on, no decimation), what a practitioner
gets out of the box. `ours`: the same poses through Tesseract's dense and texture stage,
so the row isolates the poses.
"""
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import EXP, demo_keyframes, tool  # noqa: E402
from pipeline.local_gpu import frame_order, read_images_txt, run  # noqa: E402

COLMAP = tool("SIH_COLMAP")
KF = demo_keyframes()
BL = os.path.join(EXP, "bl-cl")
names = sorted((x for x in os.listdir(KF) if x.endswith(".jpg")), key=frame_order)
held = names[9::10]


def sh(args):
    t = time.perf_counter()
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stdout[-1500:] + p.stderr[-1500:])
    return time.perf_counter() - t


def sparse():
    os.makedirs(BL, exist_ok=True)
    img = os.path.join(BL, "images")
    shutil.rmtree(img, ignore_errors=True)
    shutil.copytree(KF, img, ignore=shutil.ignore_patterns("*.json"))
    db = os.path.join(BL, "db.db")
    if os.path.exists(db):
        os.remove(db)
    T = {}
    T["feature_extractor"] = sh([COLMAP, "feature_extractor", "--database_path", db, "--image_path", img,
                                 "--ImageReader.single_camera", "1"])
    T["sequential_matcher"] = sh([COLMAP, "sequential_matcher", "--database_path", db])
    out = os.path.join(BL, "sparse")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    T["mapper"] = sh([COLMAP, "mapper", "--database_path", db, "--image_path", img, "--output_path", out])
    models = [os.path.join(out, d) for d in os.listdir(out) if os.path.exists(os.path.join(out, d, "images.bin"))]
    best = max(models, key=lambda m: os.path.getsize(os.path.join(m, "images.bin")))
    und = os.path.join(BL, "undist")
    shutil.rmtree(und, ignore_errors=True)
    T["image_undistorter"] = sh([COLMAP, "image_undistorter", "--image_path", img, "--input_path", best,
                                 "--output_path", und, "--output_type", "COLMAP"])
    txt = os.path.join(BL, "sparse_txt")
    shutil.rmtree(txt, ignore_errors=True)
    os.makedirs(txt)
    sh([COLMAP, "model_converter", "--input_path", os.path.join(und, "sparse"), "--output_path", txt,
        "--output_type", "TXT"])
    raw = os.path.join(BL, "raw_txt")
    shutil.rmtree(raw, ignore_errors=True)
    os.makedirs(raw)
    sh([COLMAP, "model_converter", "--input_path", best, "--output_path", raw, "--output_type", "TXT"])
    cam = next(ln.split() for ln in open(os.path.join(raw, "cameras.txt")) if ln.strip() and not ln.startswith("#"))
    poses = read_images_txt(os.path.join(txt, "images.txt"))
    # A fake run folder for view_check.score: the undistorted keyframes as "keyframes".
    fake_run = os.path.join(BL, "run")
    os.makedirs(fake_run, exist_ok=True)
    shutil.rmtree(os.path.join(fake_run, "keyframes"), ignore_errors=True)
    shutil.copytree(os.path.join(und, "images"), os.path.join(fake_run, "keyframes"))
    # And a finished "work folder" for local_gpu.reuse_sparse.
    np.save(os.path.join(BL, "cameras.npy"), np.stack([poses.get(n, np.full((4, 4), np.nan)) for n in names]))
    res = {"n_views": len(names), "ba_gate": {"passed": True, "problems": []}, "options": {},
           "pose_method": "colmap incremental", "unregistered": [n for n in names if n not in poses]}
    json.dump(res, open(os.path.join(BL, "local_gpu_result.json"), "w"), indent=1)
    info = {"seconds": {k: round(v, 1) for k, v in T.items()}, "models": len(models),
            "registered": len(poses), "of": len(names), "raw_camera": cam,
            "held_out_registered": sum(n in poses for n in held)}
    json.dump(info, open(os.path.join(BL, "sparse.json"), "w"), indent=1)
    print(info)


def dense(tag, mode):
    from view_check import score
    work = os.path.join(EXP, f"bl-{tag}")
    shutil.rmtree(work, ignore_errors=True)
    poses = read_images_txt(os.path.join(BL, "sparse_txt", "images.txt"))
    dn = [n for n in names if n not in set(held) and n in poses]
    opts = {"keep_intermediate": False}
    if mode in ("defaults", "defaults_ns"):
        opts.update({"dense_min_resolution": 640, "dense_views_fuse": 2, "dense_neighbours": 8,
                     "dense_fusion_filter": 2, "mesh_min_point_distance": 2.5,
                     "texture_decimate": 1.0, "texture_sharpness": 0.5, "texture_smoothness": 0.1,
                     "texture_fill": False, "texture_level": False,
                     "densify_extra": "--estimate-roi 2 --crop-to-roi 1",
                     "texture_extra": "--global-seam-leveling 1 --local-seam-leveling 1"})
        if mode == "defaults_ns":
            # The one change: seam levelling off, since in this Windows build of OpenMVS
            # it samples most faces black (research/10), which is a bug and not a setting.
            opts["texture_extra"] = ""
    t = time.perf_counter()
    res = run(os.path.join(BL, "run", "keyframes"), work, dense_names=dn, options=opts, sparse_from=BL)
    wall = time.perf_counter() - t
    s = score(os.path.join(BL, "run"), work, held, scale=1)
    json.dump(s, open(os.path.join(work, "view_check.json"), "w"), indent=1)
    out = {"tag": tag, "mode": mode, "dense_wall_s": round(wall, 1), "dense_points": res.get("dense_points"),
           **{k: s[k] for k in ("mean_coverage", "mean_psnr_db", "mean_ssim")}, "unposed": s["unposed"]}
    json.dump(out, open(os.path.join(work, "baseline.json"), "w"), indent=1)
    print(out)


if __name__ == "__main__":
    if sys.argv[1] == "sparse":
        sparse()
    else:
        dense(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "defaults")
