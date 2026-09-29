"""One row of the demo clip's ablation table: the local pipeline with one option changed,
every tenth keyframe held out of dense and texture, scored on those views at scale 1.

python tools/repro/ablate.py <tag> [--kf DIR] [--solve] [--keep] [key=value ...]
    --kf     a keyframe folder with ingest.json (default out/exp/kf, the final run's)
    --solve  solve the poses again instead of reusing night-b1-final's
    --keep   keep the model; otherwise only the JSON is left in out/exp/ab-<tag>
python tools/repro/ablate.py keyframes-nobridge   # writes out/exp/kf-nobridge, bridging off
"""
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import EXP, ROOT, RUN, demo_keyframes  # noqa: E402
from pipeline.local_gpu import DEFAULTS, frame_order, run  # noqa: E402


if sys.argv[1] == "keyframes-nobridge":
    import cv2
    from ingest.video_ingest import ingest_video
    out = os.path.join(EXP, "kf-nobridge")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    r = ingest_video(os.path.join(ROOT, "SIH DEMO.mp4"), target_keyframes=600, horizon_policy="crop",
                     bridge=1e9, progress=False)
    for i, (fi, img) in enumerate(zip(r.keyframe_indices, r.frames)):
        cv2.imwrite(os.path.join(out, f"kf_{i:03d}_f{int(fi):05d}.jpg"), img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    json.dump({"stats": r.stats, "keyframes": [int(x) for x in r.keyframe_indices]},
              open(os.path.join(out, "ingest.json"), "w"), indent=1)
    print({k: r.stats.get(k) for k in ("keyframes", "bridged_keyframes", "max_gap_frames")}, len(r.frames))
    sys.exit()

tag = sys.argv[1]
kf = demo_keyframes()
solve = "--solve" in sys.argv
keep = "--keep" in sys.argv
opts = {"keep_intermediate": False}
args = [a for a in sys.argv[2:] if a not in ("--solve", "--keep")]
i = 0
while i < len(args):
    if args[i] == "--kf":
        kf = args[i + 1]
        i += 2
        continue
    k, v = args[i].split("=", 1)
    d = DEFAULTS[k]
    opts[k] = (v == "1") if isinstance(d, bool) else type(d)(v)
    i += 1
work = os.path.join(EXP, f"ab-{tag}")
shutil.rmtree(work, ignore_errors=True)
names = sorted((x for x in os.listdir(kf) if x.endswith(".jpg")), key=frame_order)
held = names[9::10]
crop = json.load(open(os.path.join(kf, "ingest.json")))["stats"].get("overlay_crop_trbl")
t = time.perf_counter()
res = run(kf, work, crop_trbl=crop, dense_names=[x for x in names if x not in set(held)], options=opts,
          sparse_from=None if solve else os.path.join(RUN, "geometry"))
wall = time.perf_counter() - t
fake = os.path.join(work, "_run")
os.makedirs(fake, exist_ok=True)
geo = work
cam = next(ln.split() for ln in open(os.path.join(work, "sparse_txt", "cameras.txt")) if ln.strip() and not ln.startswith("#"))
if cam[1] not in ("PINHOLE", "SIMPLE_PINHOLE"):
    # view_check renders pinhole cameras only; score through a copy with the distortion
    # dropped (the old pose path keeps a radial term), recorded in the result.
    geo = os.path.join(work, "_pinhole")
    shutil.copytree(os.path.join(work, "sparse_txt"), os.path.join(geo, "sparse_txt"), dirs_exist_ok=True)
    with open(os.path.join(geo, "sparse_txt", "cameras.txt"), "w") as f:
        f.write(" ".join([cam[0], "SIMPLE_PINHOLE", cam[2], cam[3], cam[4], cam[5], cam[6]]) + "\n")
    for f_ in os.listdir(work):
        if f_.startswith("scene_tex"):
            shutil.copyfile(os.path.join(work, f_), os.path.join(geo, f_))
shutil.copytree(kf, os.path.join(fake, "keyframes"), dirs_exist_ok=True)
from view_check import score  # noqa: E402

def score_each(run_dir, geo, names):
    """view_check.score one view at a time; a view the model barely covers counts as empty."""
    views = []
    for n in names:
        try:
            views += score(run_dir, geo, [n], scale=1)["views"]
        except ValueError:
            views.append({"name": n, "coverage": 0.0, "psnr_db": float("nan"), "ssim": float("nan")})
    import numpy as np
    return {"views": views, "mean_coverage": round(float(np.mean([v["coverage"] for v in views])), 5),
            "mean_psnr_db": round(float(np.nanmean([v["psnr_db"] for v in views])), 3),
            "mean_ssim": round(float(np.nanmean([v["ssim"] for v in views])), 5),
            "empty_views": sum(v["coverage"] == 0.0 for v in views)}


s = score_each(fake, geo, held)
s["scored_camera"] = cam[1:]
shutil.rmtree(fake, ignore_errors=True)
json.dump(s, open(os.path.join(work, "view_check.json"), "w"), indent=1)
ba = res.get("sparse_after_bundle_adjustment") or {}
out = {"tag": tag, "options": {k: v for k, v in opts.items() if k != "keep_intermediate"},
       "solved": solve, "keyframes": len(names), "wall_s": round(wall, 1),
       "registered": len(names) - len(res.get("unregistered") or []),
       "reprojection_px": ba.get("Mean reprojection error"), "dense_points": res.get("dense_points"),
       **{k: s[k] for k in ("mean_coverage", "mean_psnr_db", "mean_ssim", "empty_views", "scored_camera")}}
json.dump(out, open(os.path.join(work, "ablation.json"), "w"), indent=1)
# Only the numbers are kept: C: has little room and the models are rebuilt in minutes.
for f in (os.listdir(work) if not keep else []):
    if not f.endswith(".json"):
        p_ = os.path.join(work, f)
        shutil.rmtree(p_, ignore_errors=True) if os.path.isdir(p_) else os.remove(p_)
print(out)
