"""Generate the Kaggle notebook. Run: python notebooks/_build_nb.py"""
import json, os, ast

def md(s):
    return {"cell_type": "markdown", "metadata": {}, "source": s.splitlines(keepends=True)}

def code(s):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": s.splitlines(keepends=True)}

C = []

C.append(md("""# SIH26158 - MapAnything on real drone imagery (free GPU)

Runs the **real** learned-geometry stage on **real** drone photos with GPS, on a free Kaggle GPU,
and measures whether the 900-second budget is reachable.

**Why this notebook exists.** Everything else in the project runs on CPU. The one stage needing a
GPU is the learned reconstructor, and there is no GPU quota on our GCP account - verified across
Compute Engine, Cloud Run *and* Vertex AI. Kaggle gives 30 GPU-hours a week, guaranteed, no credit
card.

**Data:** OpenDroneMap `odm_data_aukerman` - 77 real drone images, 18 MP, Sony DSC-WX220, GPS in
EXIF, **CC0-1.0 (public domain)**. The EXIF carries no focal length, so this genuinely exercises
the unknown-intrinsics path (R-I6).

**Before running:** Settings -> Accelerator -> **GPU T4 x2** (or P100), and Internet -> **On**.

> US imagery, so India's geospatial data-residency rule does not apply here. Real Indian survey
> data finer than 1 m must be processed on infrastructure inside India - see the SRS."""))

C.append(code("""import os, sys, json, time
import numpy as np
import torch

print("torch", torch.__version__, "| CUDA", torch.cuda.is_available())
if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    print("GPU:", p.name, round(p.total_memory/1e9, 1), "GB  x", torch.cuda.device_count())
else:
    print("!! No GPU. Settings -> Accelerator -> GPU T4 x2, then re-run.")"""))

C.append(md("## 1. Install MapAnything and fetch the imagery"))

C.append(code("""%%capture
# Kaggle ships torch 2.10.0+cu128. Installing MapAnything WITH its deps can pull a
# different torch and break CUDA, so use --no-deps and add the pure-Python
# requirements by hand. A missing hydra-core is what broke the first run.
# MapAnything's own declared deps (pyproject): hydra-core, opencv-python-headless,
# rerun-sdk, uniception. uniception is on PyPI and is what broke run 2.
!pip install -q hydra-core omegaconf einops huggingface_hub safetensors trimesh scipy matplotlib pillow requests
!pip install -q "opencv-python-headless==4.10.0.84" "rerun-sdk~=0.24.1" "uniception==0.1.7"
!pip install -q --no-deps git+https://github.com/facebookresearch/map-anything.git
import torch as _t; print("torch after installs:", _t.__version__, "| CUDA", _t.cuda.is_available())"""))

C.append(code("""import importlib, torch
for m in ("hydra", "omegaconf", "einops", "uniception", "mapanything"):
    importlib.import_module(m)
# A dependency install can silently swap torch for a CPU build - check, do not assume.
print("all imports OK | torch", torch.__version__, "| CUDA", torch.cuda.is_available())
assert torch.cuda.is_available(), "CUDA lost - a dependency replaced torch"
from mapanything.models import MapAnything
print("MapAnything import OK")"""))

C.append(code("""import requests

N_IMAGES = 16          # raise once it works; a T4 16 GB handles ~24 views comfortably
os.makedirs("/kaggle/working/images", exist_ok=True)

api = "https://api.github.com/repos/OpenDroneMap/odm_data_aukerman/contents/images"
files = sorted(requests.get(api, timeout=60).json(), key=lambda f: f["name"])

# CONSECUTIVE frames, not strided. Sampling every ~5th of the 77 gave a mean baseline
# of 151 m (max 222 m) - far too wide for reliable multi-view matching.
START = 20
picked = files[START:START + N_IMAGES]

for f in picked:
    dst = "/kaggle/working/images/" + f["name"]
    if not os.path.exists(dst):
        open(dst, "wb").write(requests.get(f["download_url"], timeout=180).content)
print("downloaded", len(picked), "of", len(files), "images (CC0-1.0)")"""))

C.append(md("## 2. Read GPS from EXIF\n\nThis is the entire georeferencing input. No ground control points."))

C.append(code("""from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

def dms(v):
    d, m, s = [float(x) for x in v]
    return d + m/60.0 + s/3600.0

records = []
for fn in sorted(os.listdir("/kaggle/working/images")):
    im = Image.open("/kaggle/working/images/" + fn)
    ex = im.getexif()
    gi = ex.get_ifd(0x8825)
    g = {GPSTAGS.get(k, k): v for k, v in gi.items()} if gi else {}
    if not g.get("GPSLatitude"):
        continue
    lat = dms(g["GPSLatitude"]) * (-1 if g.get("GPSLatitudeRef") == "S" else 1)
    lon = dms(g["GPSLongitude"]) * (-1 if g.get("GPSLongitudeRef") == "W" else 1)
    records.append({"file": fn, "lat": lat, "lon": lon,
                    "alt": float(g.get("GPSAltitude", 0)), "size": im.size})

print(len(records), "images with GPS")
for r in records[:3]:
    print("  ", r["file"], round(r["lat"], 6), round(r["lon"], 6),
          "alt", round(r["alt"], 1), "m", r["size"])"""))

C.append(code("""# Geodetic -> local ENU metres. The fit must happen in a metric frame: lat/lon degrees
# are not Euclidean, and UTM carries ~0.6 m/km of scale error across a site.
A, F = 6378137.0, 1/298.257223563
E2 = F*(2-F)

def to_ecef(lat, lon, h):
    la, lo = np.radians(lat), np.radians(lon)
    N = A/np.sqrt(1-E2*np.sin(la)**2)
    return np.array([(N+h)*np.cos(la)*np.cos(lo),
                     (N+h)*np.cos(la)*np.sin(lo),
                     (N*(1-E2)+h)*np.sin(la)])

lat0 = float(np.mean([r["lat"] for r in records]))
lon0 = float(np.mean([r["lon"] for r in records]))
alt0 = float(np.mean([r["alt"] for r in records]))
origin = to_ecef(lat0, lon0, alt0)
la, lo = np.radians(lat0), np.radians(lon0)
R_enu = np.array([[-np.sin(lo), np.cos(lo), 0.0],
                  [-np.sin(la)*np.cos(lo), -np.sin(la)*np.sin(lo), np.cos(la)],
                  [ np.cos(la)*np.cos(lo),  np.cos(la)*np.sin(lo), np.sin(la)]])
gps_enu = np.array([R_enu @ (to_ecef(r["lat"], r["lon"], r["alt"]) - origin)
                    for r in records])

d = np.linalg.norm(np.diff(gps_enu, axis=0), axis=1)
print("site origin ", round(lat0, 6), round(lon0, 6))
print("track extent", np.round(gps_enu.max(0)-gps_enu.min(0), 1), "m")
print("baselines   ", "mean", round(d.mean(), 1), "min", round(d.min(), 1),
      "max", round(d.max(), 1), "m")"""))

C.append(md("## 3. MapAnything on GPU - the measurement that matters"))

C.append(code("""from mapanything.models import MapAnything
from mapanything.utils.image import load_images

device = "cuda" if torch.cuda.is_available() else "cpu"

t0 = time.perf_counter()
# APACHE checkpoint. The default is CC-BY-NC and unusable for an intelligence customer.
model = MapAnything.from_pretrained("facebook/map-anything-apache").to(device).eval()
t_load = time.perf_counter() - t0
n_par = sum(p.numel() for p in model.parameters())
print("loaded in", round(t_load, 1), "s  (", round(n_par/1e9, 2), "B params )")

views = load_images(["/kaggle/working/images/" + r["file"] for r in records])
print(len(views), "views prepared")

# bf16 needs Ampere (SM 8.0+). A T4 is Turing (7.5), so fall back to fp16 there -
# asking for bf16 on Turing is either emulated and slow, or an error.
AMP_DTYPE = "fp32"
if device == "cuda":
    major = torch.cuda.get_device_capability(0)[0]
    AMP_DTYPE = "bf16" if major >= 8 else "fp16"
print("autocast dtype:", AMP_DTYPE)

if device == "cuda":
    torch.cuda.synchronize(); torch.cuda.reset_peak_memory_stats()
t0 = time.perf_counter()
with torch.no_grad():
    preds = model.infer(views, memory_efficient_inference=True,
                        use_amp=(device == "cuda"), amp_dtype=AMP_DTYPE,
                        apply_mask=True)
if device == "cuda":
    torch.cuda.synchronize()
t_inf = time.perf_counter() - t0
per_view = t_inf/len(views)

print("\\nINFERENCE", round(t_inf, 1), "s for", len(views), "views  = ",
      round(per_view, 2), "s/view on", device)
if device == "cuda":
    print("peak VRAM", round(torch.cuda.max_memory_allocated()/1e9, 1), "GB")"""))

C.append(md("""### Does this clear the 900-second budget?

The PS allows **< 15 min for a 10-minute video**. The architecture keyframes ~18,000 frames down
to ~600. Per-view cost is not strictly linear - MapAnything solves views jointly - so treat this
as an order-of-magnitude check, not a promise."""))

C.append(code("""KEYFRAMES, BUDGET = 600, 900.0
est = per_view * KEYFRAMES
geom_budget = BUDGET * 0.45          # rest goes to ingest, meshing, export

print("measured        ", round(per_view, 2), "s/view on", device)
print("600 keyframes   ", round(est), "s  (", round(est/60, 1), "min )")
print("geometry budget ", round(geom_budget), "s  (45% of 900 s)")
print()
if est <= geom_budget:
    print("WITHIN BUDGET -", round(geom_budget/est, 1), "x headroom")
else:
    print("OVER by", round(est/geom_budget, 1), "x. Levers, best first:")
    print("  - fewer keyframes (400 rather than 600)")
    print("  - lower working resolution")
    print("  - a bigger GPU than this free T4")
print()
print("Reference measured on GCP Cloud Run, 8 vCPU, no GPU: 7.5 s/view")
if device == "cuda":
    print("  -> this GPU is", round(7.5/per_view), "x faster than CPU")"""))

C.append(md("""## 4. Georeference against GPS - gravity-constrained

A single pass leaves rotation *about the flight axis* weakly constrained. An unrestricted Sim(3)
fit can put the trajectory within metres while throwing the scene hundreds of metres out.
Constraining the fit to yaw (roll and pitch come from gravity) is what makes this work."""))

C.append(code("""def yaw_only_sim3(src, dst):
    \"\"\"5-DOF fit: yaw + translation + scale. Roll and pitch are fixed by gravity.\"\"\"
    mu_s, mu_d = src.mean(0), dst.mean(0)
    sc, dc = src - mu_s, dst - mu_d
    th = np.arctan2((sc[:, 0]*dc[:, 1] - sc[:, 1]*dc[:, 0]).sum(),
                    (sc[:, 0]*dc[:, 0] + sc[:, 1]*dc[:, 1]).sum())
    c, s_ = np.cos(th), np.sin(th)
    R = np.array([[c, -s_, 0.0], [s_, c, 0.0], [0.0, 0.0, 1.0]])
    rot = (R @ sc.T).T
    s = float((rot*dc).sum() / max((sc**2).sum(), 1e-12))
    return R, mu_d - s*(R @ mu_s), s

cams = []
for p in preds:
    if "camera_poses" in p:
        cams.append(p["camera_poses"].squeeze(0).float().cpu().numpy())
cams = np.stack(cams)
cen = cams[:, :3, 3] if cams.ndim == 3 and cams.shape[1] >= 4 else cams.reshape(len(cams), -1)[:, :3]

n = min(len(cen), len(gps_enu))
R, t, s = yaw_only_sim3(cen[:n], gps_enu[:n])
placed = (s*(R @ cen[:n].T).T) + t
resid = np.linalg.norm(placed - gps_enu[:n], axis=1)

print("recovered scale ", round(s, 4), " (model units -> metres)")
print("GPS residual    ", "mean", round(float(resid.mean()), 2),
      "median", round(float(np.median(resid)), 2),
      "max", round(float(resid.max()), 2), "m")
print()
print("That residual is agreement with a NOISE-BEARING sensor, not accuracy against truth.")
print("With no GCPs and no reference model there is no ground truth for this scene -")
print("do not report it as reconstruction accuracy.")"""))

C.append(code("""pts = []
for p in preds:
    if "pts3d" not in p:
        continue
    a = p["pts3d"].squeeze(0).reshape(-1, 3).float().cpu().numpy()
    if "non_ambiguous_mask" in p:
        m = p["non_ambiguous_mask"].squeeze(0).reshape(-1).cpu().numpy().astype(bool)
        if m.shape[0] == a.shape[0]:
            a = a[m]
    pts.append(a)

P = np.concatenate(pts, 0)
P = P[np.isfinite(P).all(1)]
P = (s*(R @ P.T).T) + t
print(f"{len(P):,} points   extent", np.round(P.max(0)-P.min(0), 1), "m")

np.save("/kaggle/working/points_enu.npy", P.astype(np.float32))
json.dump({"seconds_per_view": round(per_view, 3), "device": device,
           "n_views": len(views), "params_B": round(n_par/1e9, 3),
           "recovered_scale": round(s, 4),
           "gps_residual_mean_m": round(float(resid.mean()), 3),
           "est_600_keyframes_s": round(est, 1),
           "origin": {"lat": lat0, "lon": lon0, "alt": alt0}},
          open("/kaggle/working/result.json", "w"), indent=2)
print("wrote points_enu.npy + result.json")"""))

C.append(md("## 5. Look at it"))

C.append(code("""import matplotlib.pyplot as plt

idx = np.random.default_rng(0).choice(len(P), min(120000, len(P)), replace=False)
sub = P[idx]
fig, ax = plt.subplots(1, 2, figsize=(15, 5.5))
h = ax[0].scatter(sub[:, 0], sub[:, 1], c=sub[:, 2], s=0.4, cmap="viridis")
ax[0].plot(gps_enu[:, 0], gps_enu[:, 1], "r.-", lw=1.2, ms=7, label="GPS track")
ax[0].set_xlabel("East (m)"); ax[0].set_ylabel("North (m)")
ax[0].set_title("Top-down, coloured by height"); ax[0].legend(); ax[0].set_aspect("equal")
plt.colorbar(h, ax=ax[0], label="height (m)")
ax[1].scatter(sub[:, 0], sub[:, 2], s=0.4, c="steelblue")
ax[1].plot(gps_enu[:, 0], gps_enu[:, 2], "r.-", lw=1.2, ms=7)
ax[1].set_xlabel("East (m)"); ax[1].set_ylabel("Up (m)"); ax[1].set_title("Side view")
plt.tight_layout(); plt.show()"""))

C.append(md("""## What this establishes, and what it does not

**Establishes:** the real Apache checkpoint runs on real drone imagery with GPS; a measured GPU
cost per view; and whether 600 keyframes fits the time budget.

**Does not establish:** reconstruction *accuracy*. There is no ground truth for this scene, and
the GPS residual only measures agreement with a noisy sensor. A defensible accuracy number needs
a LiDAR or multi-pass survey reference - which is exactly what to ask the organisers for.

**Next:** raise `N_IMAGES`, then swap in Indian imagery when available - remembering that Indian
survey data finer than 1 m must be processed on infrastructure inside India."""))

nb = {"cells": C,
      "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python",
                                  "name": "python3"},
                   "language_info": {"name": "python", "version": "3.11"},
                   "accelerator": "GPU"},
      "nbformat": 4, "nbformat_minor": 5}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "kaggle_mapanything_real_drone.ipynb")
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

print("wrote", out)
print("cells:", len(nb["cells"]),
      "| code:", sum(1 for c in nb["cells"] if c["cell_type"] == "code"),
      "| syntax errors:", bad)
