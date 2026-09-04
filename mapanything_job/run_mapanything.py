"""
Run MapAnything (Apache checkpoint) on rendered single-pass frames, CPU-only.

Purpose: replace the ONE simulated stage in the demo pipeline with the real model,
and measure what it costs without a GPU - which is the number that sizes the
deployment.
"""
import json
import os
import time

import numpy as np
import torch

BUCKET = os.environ.get("BUCKET", "sih26158-mumbai")
IN_PREFIX = os.environ.get("IN_PREFIX", "mapanything/ma_input")
OUT_PREFIX = os.environ.get("OUT_PREFIX", "mapanything/out")
MAX_VIEWS = int(os.environ.get("MAX_VIEWS", "8"))
WORK = "/tmp/ma"


def gcs():
    from google.cloud import storage
    return storage.Client().bucket(BUCKET)


def fetch():
    os.makedirs(WORK, exist_ok=True)
    b = gcs()
    names = []
    for blob in b.list_blobs(prefix=IN_PREFIX + "/"):
        fn = os.path.basename(blob.name)
        if not fn:
            continue
        blob.download_to_filename(os.path.join(WORK, fn))
        names.append(fn)
    print(f"  fetched {len(names)} files from gs://{BUCKET}/{IN_PREFIX}")
    return sorted(n for n in names if n.endswith(".png"))


def main():
    print("=" * 74)
    print("MapAnything on CPU  |  torch", torch.__version__,
          "| threads", torch.get_num_threads())
    print("=" * 74)

    pngs = fetch()
    meta = json.load(open(os.path.join(WORK, "meta.json")))
    pngs = pngs[:MAX_VIEWS]
    print(f"  using {len(pngs)} of {len(meta['frames'])} views (MAX_VIEWS={MAX_VIEWS})")

    from mapanything.models import MapAnything
    from mapanything.utils.image import load_images

    t0 = time.perf_counter()
    model = MapAnything.from_pretrained("facebook/map-anything-apache").to("cpu")
    model.eval()
    t_load = time.perf_counter() - t0
    n_params = sum(p.numel() for p in model.parameters())
    print(f"  model loaded in {t_load:.1f}s  ({n_params/1e9:.2f}B params, apache ckpt)")

    views = load_images([os.path.join(WORK, p) for p in pngs])
    print(f"  {len(views)} views prepared")

    t0 = time.perf_counter()
    with torch.no_grad():
        preds = model.infer(views, memory_efficient_inference=True,
                            use_amp=False, apply_mask=True)
    t_inf = time.perf_counter() - t0
    print(f"\n  INFERENCE {t_inf:.1f}s for {len(views)} views "
          f"({t_inf/len(views):.1f}s/view, CPU)")

    pts, cams = [], []
    for i, p in enumerate(preds):
        k = {kk: tuple(vv.shape) for kk, vv in p.items() if hasattr(vv, "shape")}
        if i == 0:
            print("  prediction keys:", list(k)[:10])
        if "pts3d" in p:
            a = p["pts3d"].squeeze(0).reshape(-1, 3).float().cpu().numpy()
            m = None
            if "mask" in p:
                m = p["mask"].squeeze(0).reshape(-1).cpu().numpy().astype(bool)
            pts.append(a[m] if m is not None and m.shape[0] == a.shape[0] else a)
        if "camera_poses" in p:
            cams.append(p["camera_poses"].squeeze(0).float().cpu().numpy())

    os.makedirs("/tmp/out", exist_ok=True)
    result = {
        "n_views": len(views),
        "params_B": round(n_params / 1e9, 3),
        "load_s": round(t_load, 2),
        "inference_s": round(t_inf, 2),
        "seconds_per_view_cpu": round(t_inf / max(len(views), 1), 2),
        "torch_threads": torch.get_num_threads(),
        "checkpoint": "facebook/map-anything-apache",
    }
    if pts:
        allp = np.concatenate(pts, 0)
        keep = np.isfinite(allp).all(1)
        allp = allp[keep]
        np.save("/tmp/out/points.npy", allp.astype(np.float32))
        result["points"] = int(len(allp))
        result["bbox_extent"] = [round(float(x), 2)
                                 for x in (allp.max(0) - allp.min(0))]
        print(f"  point cloud: {len(allp):,} pts  extent {result['bbox_extent']}")
    if cams:
        np.save("/tmp/out/cameras.npy", np.stack(cams))
        result["cameras"] = len(cams)

    json.dump(result, open("/tmp/out/mapanything_result.json", "w"), indent=2)
    b = gcs()
    for fn in os.listdir("/tmp/out"):
        b.blob(f"{OUT_PREFIX}/{fn}").upload_from_filename(f"/tmp/out/{fn}")
        print(f"  uploaded gs://{BUCKET}/{OUT_PREFIX}/{fn}")
    print("\n" + json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
