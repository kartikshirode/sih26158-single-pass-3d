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
    return sorted(n for n in names if n.lower().endswith((".png", ".jpg", ".jpeg")))


def main():
    print("=" * 74)
    print("MapAnything on CPU  |  torch", torch.__version__,
          "| threads", torch.get_num_threads())
    print("=" * 74)

    pngs = fetch()
    n_avail = len(pngs)
    pngs = pngs[:MAX_VIEWS]
    print(f"  using {len(pngs)} of {n_avail} views (MAX_VIEWS={MAX_VIEWS})")

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

    # Save the FULL per-view output, not just XYZ. The previous version kept points
    # alone and threw away the confidence channel and the colours, which is why the
    # first reconstruction was an unfilterable smear: with no conf there is nothing
    # to gate on, and with no colour there is nothing to look at. Filtering, fusion
    # and meshing happen downstream, where they can be re-run without paying for
    # inference again.
    import cv2
    pts, cols, cnf, msk, cams, shapes, intr, dz = [], [], [], [], [], [], [], []
    for i, p in enumerate(preds):
        if i == 0:
            print("  prediction keys:", [k for k in p])
        if "pts3d" not in p:
            continue
        t = p["pts3d"].squeeze(0)                       # (H, W, 3)
        H, W = t.shape[:2]
        shapes.append([int(H), int(W)])
        pts.append(t.reshape(-1, 3).float().cpu().numpy().astype(np.float32))

        cnf.append(p["conf"].squeeze(0).reshape(-1).float().cpu().numpy().astype(np.float32)
                   if "conf" in p else np.ones(H * W, np.float32))

        mk = np.ones(H * W, bool)
        for key in ("non_ambiguous_mask", "mask"):
            if key in p:
                v = p[key].squeeze(0).reshape(-1).cpu().numpy().astype(bool)
                if v.shape[0] == H * W:
                    mk = v
                    break
        msk.append(mk)

        # Colour sampled at the point-map grid. Read H,W from the tensor; inferring
        # them from the flattened length shears every colour a row sideways.
        im = cv2.cvtColor(cv2.imread(os.path.join(WORK, pngs[i])), cv2.COLOR_BGR2RGB)
        cols.append(cv2.resize(im, (W, H), interpolation=cv2.INTER_AREA)
                    .reshape(-1, 3).astype(np.uint8))

        if "camera_poses" in p:
            cams.append(p["camera_poses"].squeeze(0).float().cpu().numpy())

        # INTRINSICS and metric depth. The model emits both on every view and the
        # first version of this script threw both away, which is what blocked the
        # COLMAP/OpenMVS export: without a K matrix there is no way to hand these
        # poses to a classical MVS stage, and re-deriving one by inverting the pose
        # against the world-frame point map is fiddly and unverifiable. Keeping them
        # costs one array each. See docs/05-quality-analysis.md section 3.
        if "intrinsics" in p:
            intr.append(p["intrinsics"].squeeze(0).float().cpu().numpy())
        if "depth_z" in p:
            dz.append(p["depth_z"].squeeze(0).reshape(-1).float().cpu().numpy()
                      .astype(np.float32))

    os.makedirs("/tmp/out", exist_ok=True)
    result = {
        "n_views": len(views),
        "params_B": round(n_params / 1e9, 3),
        "load_s": round(t_load, 2),
        "inference_s": round(t_inf, 2),
        "seconds_per_view_cpu": round(t_inf / max(len(views), 1), 2),
        "torch_threads": torch.get_num_threads(),
        "checkpoint": "facebook/map-anything-apache",
        "view_shapes": shapes,
        "images": pngs,
    }
    if pts:
        np.save("/tmp/out/points.npy",  np.concatenate(pts, 0))
        np.save("/tmp/out/colors.npy",  np.concatenate(cols, 0))
        np.save("/tmp/out/conf.npy",    np.concatenate(cnf, 0))
        np.save("/tmp/out/mask.npy",    np.concatenate(msk, 0))
        allp = np.concatenate(pts, 0)
        fin = np.isfinite(allp).all(1)
        result["points"] = int(len(allp))
        result["points_finite"] = int(fin.sum())
        result["bbox_extent"] = [round(float(x), 2)
                                 for x in (allp[fin].max(0) - allp[fin].min(0))]
        print(f"  saved {len(allp):,} pts (+colour, conf, mask)  "
              f"extent {result['bbox_extent']}")
    if cams:
        np.save("/tmp/out/cameras.npy", np.stack(cams))
        result["cameras"] = len(cams)
    if intr:
        np.save("/tmp/out/intrinsics.npy", np.stack(intr))
        result["intrinsics"] = len(intr)
        print(f"  intrinsics K[0] = {np.round(intr[0], 2).tolist()}")
    if dz:
        np.save("/tmp/out/depth_z.npy", np.concatenate(dz, 0))
        result["depth_z"] = int(sum(len(x) for x in dz))

    json.dump(result, open("/tmp/out/mapanything_result.json", "w"), indent=2)
    b = gcs()
    for fn in os.listdir("/tmp/out"):
        b.blob(f"{OUT_PREFIX}/{fn}").upload_from_filename(f"/tmp/out/{fn}")
        print(f"  uploaded gs://{BUCKET}/{OUT_PREFIX}/{fn}")
    print("\n" + json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
