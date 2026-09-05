"""Generate the video-derived Kaggle notebook. Run: python notebooks/_build_nb_video.py"""
import json, os, ast

def md(s):
    return {"cell_type": "markdown", "metadata": {}, "source": s.splitlines(keepends=True)}

def code(s):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": s.splitlines(keepends=True)}

C = []

C.append(md("""# SIH26158 - real VIDEO to 3D, on a free GPU

The problem statement's mandatory input is a **video**. This notebook closes the last gap in the
pipeline: keyframes extracted from an actual drone video file, through the real learned model, to
a 3D point cloud.

**The video:** 40 s of drone footage over Nicosia, Cyprus - Wikimedia Commons, **CC BY 3.0**
(The Track Record - BTS). 4K downscaled to 1080p, as the PS specifies.

**S1 ran locally** (`src/ingest/video_ingest.py`) on real H.264:

| | |
|---|---|
| Frames decoded | 1,199 |
| Rejected as slate / title card | 293 (9.8 s of credits, found automatically) |
| Rejected as blurry | 300 (25th percentile of the clip, not a hardcoded value) |
| Keyframes selected | 20, by optical-flow baseline budget |

**This is the target case, not a stand-in for one.** A single oblique pass from a moving UAV is
exactly what the PS describes - *"there is often only a single opportunity to capture data over
the target area"*, with Key Challenge (i) being **"Limited viewing angles due to single flight
path."** A planned survey grid is what the PS says you do *not* get.

**The one real limitation:** this clip carries **no GPS**, so nothing here can be georeferenced -
only metric-relative. That is a missing input, not a wrong kind of footage. The PS lists GPS as
mandatory precisely because without it the problem is unsolvable as stated.

**Before running:** Accelerator **GPU T4 x2**, Internet **On**, and attach the keyframe dataset."""))

C.append(code("""import os, sys, glob, json, time
import numpy as np
import torch

print("torch", torch.__version__, "| CUDA", torch.cuda.is_available())
if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    print("GPU:", p.name, round(p.total_memory/1e9, 1), "GB x", torch.cuda.device_count())
else:
    print("!! No GPU. Settings -> Accelerator -> GPU T4 x2.")"""))

C.append(md("## 1. Install MapAnything"))

C.append(code("""%%capture
# Kaggle ships torch 2.10.0+cu128. Installing MapAnything WITH deps can pull a different
# torch and break CUDA, so --no-deps plus its declared requirements by hand.
!pip install -q hydra-core omegaconf einops huggingface_hub safetensors trimesh scipy matplotlib pillow
!pip install -q "opencv-python-headless==4.10.0.84" "rerun-sdk~=0.24.1" "uniception==0.1.7"
!pip install -q --no-deps git+https://github.com/facebookresearch/map-anything.git"""))

C.append(code("""import importlib, torch
for m in ("hydra", "omegaconf", "einops", "uniception", "mapanything"):
    importlib.import_module(m)
print("imports OK | torch", torch.__version__, "| CUDA", torch.cuda.is_available())
assert torch.cuda.is_available(), "CUDA lost - a dependency replaced torch"
from mapanything.models import MapAnything
print("MapAnything OK")"""))

C.append(md("## 2. Find the keyframes\n\nThese came out of the local S1 stage. Attach the dataset via **Add Input** if the search below finds nothing."))

C.append(code("""cands = sorted(glob.glob("/kaggle/input/**/kf_*.jpg", recursive=True))
if not cands:
    cands = sorted(glob.glob("/kaggle/input/**/*.jpg", recursive=True))
assert cands, "No keyframes found - attach the dataset with Add Input"

IMGS = cands[:20]
print(len(IMGS), "keyframes")
for p in IMGS[:3]:
    print("  ", os.path.basename(p))

meta = glob.glob("/kaggle/input/**/ingest.json", recursive=True)
if meta:
    ing = json.load(open(meta[0]))
    print("\\nS1 stats from the local ingest:")
    for k, v in ing["stats"].items():
        print(f"  {k:24s} {v}")"""))

C.append(md("## 3. MapAnything on the keyframes"))

C.append(code("""from mapanything.models import MapAnything
from mapanything.utils.image import load_images

device = "cuda" if torch.cuda.is_available() else "cpu"

t0 = time.perf_counter()
# APACHE checkpoint - the default is CC-BY-NC and unusable for this customer.
model = MapAnything.from_pretrained("facebook/map-anything-apache").to(device).eval()
print("loaded in", round(time.perf_counter()-t0, 1), "s")

views = load_images(IMGS)
print(len(views), "views prepared")

# bf16 needs Ampere (SM 8.0+); a T4 is Turing 7.5, so fp16 there.
AMP = "fp32"
if device == "cuda":
    AMP = "bf16" if torch.cuda.get_device_capability(0)[0] >= 8 else "fp16"
print("autocast dtype:", AMP)

if device == "cuda":
    torch.cuda.synchronize(); torch.cuda.reset_peak_memory_stats()
t0 = time.perf_counter()
with torch.no_grad():
    preds = model.infer(views, memory_efficient_inference=True,
                        use_amp=(device == "cuda"), amp_dtype=AMP, apply_mask=True)
if device == "cuda":
    torch.cuda.synchronize()
t_inf = time.perf_counter() - t0
per_view = t_inf/len(views)

print("\\nINFERENCE", round(t_inf, 1), "s for", len(views), "views =",
      round(per_view, 2), "s/view")
if device == "cuda":
    print("peak VRAM", round(torch.cuda.max_memory_allocated()/1e9, 1), "GB")"""))

C.append(md("""### Full-video extrapolation

This clip is 40 s and yields 20 keyframes. The PS budget is 900 s for a **10-minute** video, which
our architecture keyframes to ~600."""))

C.append(code("""KEYFRAMES, BUDGET = 600, 900.0
geom = BUDGET * 0.45
est = per_view * KEYFRAMES
print("measured        ", round(per_view, 2), "s/view")
print("600 keyframes   ", round(est), "s")
print("geometry budget ", round(geom), "s  (45% of 900 s)")
print("WITHIN BUDGET" if est <= geom else "OVER BUDGET",
      "-", round(geom/est, 2), "x headroom" if est <= geom else "x over")
print("\\nS1 ingest measured locally on the same clip: 1,199 frames decoded and scored.")"""))

C.append(md("## 4. The reconstruction"))

C.append(code("""pts, cols = [], []
import cv2
for i, p in enumerate(preds):
    if "pts3d" not in p:
        continue
    a = p["pts3d"].squeeze(0).reshape(-1, 3).float().cpu().numpy()
    keep = np.ones(len(a), bool)
    if "non_ambiguous_mask" in p:
        m = p["non_ambiguous_mask"].squeeze(0).reshape(-1).cpu().numpy().astype(bool)
        if m.shape[0] == a.shape[0]:
            keep = m
    # colour from the source frame, so the cloud is inspectable rather than uniform
    im = cv2.cvtColor(cv2.imread(IMGS[i]), cv2.COLOR_BGR2RGB)
    hh = int(np.sqrt(a.shape[0] * im.shape[0] / im.shape[1]))
    ww = a.shape[0] // max(hh, 1)
    small = cv2.resize(im, (ww, hh)).reshape(-1, 3)
    n = min(len(small), len(a))
    pts.append(a[:n][keep[:n]])
    cols.append(small[:n][keep[:n]])

P = np.concatenate(pts, 0); Ccol = np.concatenate(cols, 0)
ok = np.isfinite(P).all(1)
P, Ccol = P[ok], Ccol[ok]

# Trim the far tail: sky and distant mountains dominate a cinematic shot and would
# otherwise set the scale of every plot.
d = np.linalg.norm(P - np.median(P, 0), axis=1)
near = d < np.percentile(d, 92)
P, Ccol = P[near], Ccol[near]

print(f"{len(P):,} points   extent {np.round(P.max(0)-P.min(0), 2)} (model units)")
np.save("/kaggle/working/points.npy", P.astype(np.float32))
np.save("/kaggle/working/colors.npy", Ccol.astype(np.uint8))
json.dump({"seconds_per_view": round(per_view, 3), "n_views": len(views),
           "points": int(len(P)), "device": device, "amp": AMP,
           "est_600_keyframes_s": round(est, 1), "source": "Nicosia CC BY 3.0, 1080p video"},
          open("/kaggle/working/result.json", "w"), indent=2)
print("wrote points.npy, colors.npy, result.json")"""))

C.append(code("""import matplotlib.pyplot as plt

idx = np.random.default_rng(0).choice(len(P), min(150000, len(P)), replace=False)
S, SC = P[idx], Ccol[idx]/255.0
fig, ax = plt.subplots(1, 3, figsize=(17, 5))
ax[0].scatter(S[:,0], S[:,2], c=SC, s=0.5); ax[0].set_title("Top-down (X-Z)")
ax[0].set_xlabel("X"); ax[0].set_ylabel("Z")
ax[1].scatter(S[:,0], -S[:,1], c=SC, s=0.5); ax[1].set_title("Front (X-Y)")
ax[1].set_xlabel("X"); ax[1].set_ylabel("-Y")
h = ax[2].scatter(S[:,0], S[:,2], c=-S[:,1], s=0.5, cmap="viridis")
ax[2].set_title("Top-down, coloured by height"); ax[2].set_xlabel("X"); ax[2].set_ylabel("Z")
plt.colorbar(h, ax=ax[2])
for a_ in ax: a_.set_aspect("equal")
plt.tight_layout(); plt.show()"""))

C.append(md("""## What this run establishes

**Establishes:** a real drone **video file** goes in and a 3D point cloud comes out. Decode,
slate rejection, blur rejection, baseline-aware keyframing and learned reconstruction all ran on
genuine H.264 footage, and the per-view GPU cost extrapolates to the 900 s budget.

**Does not establish:** georeferencing or accuracy. This clip carries **no GPS**, so there is no
absolute frame to place the model in and no ground truth to score against. The PS lists GPS as a
mandatory input precisely because without it the problem is unsolvable as stated.

**Also worth seeing in the plots:** geometry degrades with distance from the camera. That is the
problem this PS poses, not a flaw in the footage - an oblique single pass puts most pixels in the
far field where a monocular model has little parallax. It implies the deliverable should carry
per-point confidence and report accuracy per range band, rather than quoting one number that
holds near the camera and fails at the horizon."""))

nb = {"cells": C,
      "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python",
                                  "name": "python3"},
                   "language_info": {"name": "python", "version": "3.11"},
                   "accelerator": "GPU"},
      "nbformat": 4, "nbformat_minor": 5}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "kaggle_video_to_3d.ipynb")
with open(out, "w", encoding="utf-8") as f:
    json.dump(nb, f, indent=1)

bad = 0
for i, c in enumerate(nb["cells"]):
    if c["cell_type"] != "code":
        continue
    src = "".join(c["source"])
    if src.lstrip().startswith(("%%", "!")):
        continue
    try:
        ast.parse(src)
    except SyntaxError as e:
        bad += 1
        print("SYNTAX ERROR cell", i, ":", e)

print("wrote", out, "| cells:", len(nb["cells"]), "| syntax errors:", bad)
