"""
One HTML page for one tesseract run: the model to turn around, plus everything the run
recorded about itself (stages, timings, the PS targets, screen and ingest facts, the
files it wrote and every keyframe).

Run:  python tools/build_run_page.py out/runs/<run>      -> out/runs/<run>/index.html

The 3D payload is inlined as base64 int16, so the model opens straight from disk with
no server. Keyframe thumbnails and file links are relative paths, so the page only
works while it sits inside its run folder. The textured OBJ from local_gpu is drawn
with its photo texture when the run has one. Otherwise the mesh is thinned by vertex
clustering in numpy (no open3d here; cruder than build_viewer.py's quadric
decimation) and coloured from the nearest dense point.
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

CODES = {
    "ADM-HORIZON": "horizon in frame; cropped off rather than refused",
    "ADM-SKY": "too much sky; cropped off rather than refused",
    "ADM-SHOTS": "several shots; only the longest was kept",
    "ADM-OVERLAY": "burned-in overlay or watermark; cropped",
    "ING-NOGNSS": "no GPS track, so no metres and no map position",
    "ING-SCHEMA": "telemetry file did not parse",
    "ING-REJECT": "ingest could not select usable video frames",
    "GEO-UNREG": "some views failed to register",
    "GEO-REPROJ": "reprojection error over the gate",
    "MVS-RC": "a reconstruction tool exited non-zero",
    "REF-BALLPARK": "GPS alignment only ballpark",
    "REF-7DOF": "7-DoF alignment to GPS failed",
    "EXP-FORMAT": "an export format could not be written",
    "STAGE-UNAVAILABLE": "a tool or artefact this host lacks",
    "BUDGET": "predicted cost exceeds the time left",
}


def read_mesh_ply(path: str):
    """Binary little-endian PLY with scalar vertex props and triangle faces."""
    with open(path, "rb") as f:
        head = b""
        while not head.endswith(b"end_header\n"):
            line = f.readline()
            if not line:
                raise ValueError(f"{path}: no end_header")
            head += line
        body = f.read()
    text = head.decode("ascii")
    if "binary_little_endian" not in text:
        raise ValueError(f"{path}: only binary_little_endian is read")
    nv = int(re.search(r"element vertex (\d+)", text).group(1))
    nf = int(re.search(r"element face (\d+)", text).group(1))
    vblock = text.split("element vertex")[1].split("element face")[0]
    size = {"float32": "<f4", "float": "<f4", "float64": "<f8", "double": "<f8",
            "uint8": "u1", "uchar": "u1", "int32": "<i4", "uint32": "<u4"}
    props = re.findall(r"property (\w+) (\w+)", vblock)
    vdt = np.dtype([(n, size[t]) for t, n in props])
    V = np.frombuffer(body, vdt, nv)
    xyz = np.stack([V["x"], V["y"], V["z"]], 1).astype(np.float64)
    fdt = np.dtype([("n", "u1"), ("i", "<u4", 3)])
    Fr = np.frombuffer(body, fdt, nf, offset=nv * vdt.itemsize)
    if not np.all(Fr["n"] == 3):
        raise ValueError(f"{path}: non-triangle faces")
    return xyz, Fr["i"].astype(np.int64)


def read_obj(path: str):
    """Vertices, texture coordinates, face corners as (vertex, uv) indices, texture file."""
    V, T, F, tex = [], [], [], None
    base = os.path.dirname(path)
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            if ln.startswith("v "):
                V.append(ln.split()[1:4])
            elif ln.startswith("vt "):
                T.append(ln.split()[1:3])
            elif ln.startswith("f "):
                c = [p.split("/") for p in ln.split()[1:4]]
                F.append([int(x[0]) for x in c] + [int(x[1]) for x in c])
            elif ln.startswith("mtllib "):
                mtl = os.path.join(base, ln.split(None, 1)[1].strip())
                if os.path.exists(mtl):
                    for m in open(mtl, encoding="utf-8", errors="replace"):
                        if m.strip().startswith("map_Kd"):
                            tex = os.path.join(base, m.split(None, 1)[1].strip())
    F = np.asarray(F, np.int64) - 1
    return (np.asarray(V, np.float64), np.asarray(T, np.float64), F[:, :3], F[:, 3:], tex)


def similarity(src: np.ndarray, dst: np.ndarray):
    """Umeyama: s, R, t with dst ~ s R src + t."""
    ms, md = src.mean(0), dst.mean(0)
    a, b = src - ms, dst - md
    U, S, Vt = np.linalg.svd(b.T @ a / len(src))
    D = np.eye(3)
    D[2, 2] = np.sign(np.linalg.det(U @ Vt))
    R = U @ D @ Vt
    s = float(np.trace(np.diag(S) @ D) / (a ** 2).sum(1).mean())
    return s, R, md - s * R @ ms


def cluster_decimate(V, F, target: int):
    """Merge vertices on a grid until roughly `target` triangles survive."""
    lo = V.min(0)
    cell = float((V.max(0) - lo).max()) / 600.0
    for _ in range(14):
        key = np.floor((V - lo) / cell).astype(np.int64)
        _, inv = np.unique(key, axis=0, return_inverse=True)
        inv = inv.ravel()
        G = inv[F]
        keep = (G[:, 0] != G[:, 1]) & (G[:, 1] != G[:, 2]) & (G[:, 0] != G[:, 2])
        n = int(keep.sum())
        if 0.7 * target <= n <= 1.1 * target or (n < target and cell <= 1e-9):
            break
        cell *= float(np.sqrt(n / target))       # triangle count goes as 1 / cell^2
    G = G[keep]
    _, first = np.unique(np.sort(G, 1), axis=0, return_index=True)
    G = G[np.sort(first)]
    k = int(inv.max()) + 1
    cnt = np.bincount(inv, minlength=k).astype(np.float64)
    W = np.stack([np.bincount(inv, V[:, j], k) for j in range(3)], 1) / cnt[:, None]
    used = np.unique(G)
    remap = np.full(k, -1, np.int64)
    remap[used] = np.arange(len(used))
    return W[used], remap[G]


def pack(run: str, tri_budget: int, pt_budget: int, log=print):
    from scipy.spatial import cKDTree

    P4 = np.load(os.path.join(run, "points.npy")).astype(np.float64)
    # The export frame: levelled (F5), or georeferenced (F6/F7) when S5 ran and S5b
    # skipped. Either way the same points as points.npy, in the same order.
    p5 = os.path.join(run, "points_llf.npy")
    P5 = np.load(p5 if os.path.exists(p5) else os.path.join(run, "points_geo.npy"))
    P5 = P5.astype(np.float64)
    C = np.load(os.path.join(run, "colors.npy"))
    if C.dtype != np.uint8:
        C = (np.clip(C, 0, 1) * 255).astype(np.uint8) if C.max() <= 1.0 else C.astype(np.uint8)

    # The mesh and the cameras are in the geometry frame (F4); the page shows the
    # levelled frame (F5). points.npy and points_llf.npy are the same points in the
    # two frames, so the map between them is fitted rather than re-derived.
    rng = np.random.default_rng(0)
    sel = rng.choice(len(P4), min(len(P4), 50_000), replace=False)
    s, R, t = similarity(P4[sel], P5[sel])
    fit = float(np.abs(s * P4[sel] @ R.T + t - P5[sel]).max())
    to5 = lambda X: s * X @ R.T + t

    cams = np.load(os.path.join(run, "cameras.npy"))
    cams = cams[np.isfinite(cams.reshape(len(cams), -1)).all(1)]   # unregistered views
    K5 = to5(cams[:, :3, 3])
    # Robust box over the cloud, widened to hold every camera so the flight path
    # stays one unbroken line.
    lo = np.minimum(np.percentile(P5, 0.5, 0), K5.min(0))
    hi = np.maximum(np.percentile(P5, 99.5, 0), K5.max(0))
    mid = (lo + hi) / 2.0
    half = float((hi - lo).max()) / 2.0 * 1.25
    # Levelled z is up; the viewer's y is up.
    gl = lambda X: np.stack([X[:, 0], X[:, 2], -X[:, 1]], 1)
    q = lambda X: np.round((gl(X) - gl(mid[None])) / half * 32000)
    inside = lambda Q: np.all(np.abs(Q) <= 32767, 1)

    Qp = q(P5)
    ok = inside(Qp)
    idx = np.flatnonzero(ok)
    if len(idx) > pt_budget:
        idx = np.sort(rng.choice(idx, pt_budget, replace=False))
    Qp, Cp = Qp[idx].astype(np.int16), C[idx]

    mesh = {"vpos": "", "vcol": "", "idx": "", "nv": 0, "nt": 0, "nt_full": 0,
            "tpos": "", "tuv": "", "tex": "", "ntc": 0}
    mpath = os.path.join(run, "geometry", "scene_dense_mesh.ply")
    opath = os.path.join(run, "geometry", "scene_tex.obj")
    if os.path.exists(opath):
        # The textured mesh, drawn as it is: one position and one texture coordinate
        # per face corner, since OBJ seams give a vertex several of them.
        import cv2

        V, T, F, FT, tex = read_obj(opath)
        Qv = q(to5(V))
        keep = inside(Qv)[F].all(1)
        F, FT = F[keep], FT[keep]
        img = cv2.imread(tex) if tex else None
        if img is not None:
            # Faces no photo covers carry TextureMesh's empty colour, a saturated orange
            # (0xFF7F27); on the demo 3.8% of faces, mostly in the grazing far field.
            # Drawn, they read as orange paint on the model, so they are left out.
            h_, w_ = img.shape[:2]
            uvc = T[FT].mean(1)
            texel = img[np.clip(((1 - uvc[:, 1]) * h_).astype(int), 0, h_ - 1),
                        np.clip((uvc[:, 0] * w_).astype(int), 0, w_ - 1)].astype(int)
            covered = np.abs(texel - np.array([39, 127, 255])).max(1) >= 25
            F, FT = F[covered], FT[covered]
            s_ = 4096 / max(img.shape[:2])
            if s_ < 1:
                img = cv2.resize(img, None, fx=s_, fy=s_, interpolation=cv2.INTER_AREA)
            jpg = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])[1]
            uv = np.clip(np.round(T[FT.ravel()] * 65535), 0, 65535).astype(np.uint16)
            nt_full = len(read_mesh_ply(mpath)[1]) if os.path.exists(mpath) else len(F)
            mesh.update({"tpos": b64(Qv[F.ravel()].astype(np.int16)), "tuv": b64(uv),
                         "tex": base64.b64encode(jpg.tobytes()).decode(),
                         "ntc": int(F.size), "nt": int(len(F)), "nt_full": int(nt_full)})
            log(f"  textured mesh {len(F):,} faces, texture {img.shape[1]}x{img.shape[0]}")
    if not mesh["ntc"] and os.path.exists(mpath):
        V, F = read_mesh_ply(mpath)
        nt_full = len(F)
        if len(F) > tri_budget:
            V, F = cluster_decimate(V, F, tri_budget)
        V5 = to5(V)
        Qv = q(V5)
        F = F[inside(Qv)[F].all(1)]
        used = np.unique(F)
        remap = np.full(len(V5), -1, np.int64)
        remap[used] = np.arange(len(used))
        V5, Qv, F = V5[used], Qv[used], remap[F]
        # OpenMVS's mesh is colourless: take each vertex's colour from the nearest
        # dense point, which is what finish_mvs.py does too.
        _, nn = cKDTree(P5).query(V5, k=1, workers=-1)
        mesh.update({"vpos": b64(Qv.astype(np.int16)), "vcol": b64(C[nn]),
                     "idx": b64(F.astype(np.uint32)), "nv": int(len(V5)), "nt": int(len(F)),
                     "nt_full": int(nt_full)})

    Qc = q(K5)
    Qc = Qc[inside(Qc)].astype(np.int16)

    log(f"  frame fit F4->F5 max residual {fit:.2e} (scale {s:.4f})")
    log(f"  points {len(Qp):,} of {len(P5):,}; mesh {mesh['nt']:,} of "
        f"{mesh['nt_full']:,} triangles; cameras {len(Qc)}")
    return {"ppos": b64(Qp), "pcol": b64(Cp), "np": int(len(Qp)), "np_full": int(len(P5)),
            "cpos": b64(Qc), "nc": int(len(Qc)), "half": half, "fit": fit, **mesh}


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def scalars(d: dict) -> list:
    return [[k, v] for k, v in (d or {}).items() if isinstance(v, (str, int, float, bool))]


def describe(run: str) -> dict:
    m = json.load(open(os.path.join(run, "run_manifest.json"), encoding="utf-8"))
    ing = {}
    if os.path.exists(os.path.join(run, "ingest.json")):
        ing = json.load(open(os.path.join(run, "ingest.json"), encoding="utf-8")).get("stats", {})
    st = {s["id"]: s for s in m.get("stages", [])}
    geo = (st.get("S3-geometry", {}).get("facts") or {}).get("local_gpu") or {}
    screen = (st.get("S0-screen", {}).get("facts") or {}).get("screen") or {}

    files = []
    for name, a in (m.get("artefacts") or {}).items():
        p = os.path.join(run, a.get("path", ""))
        if a.get("path") and os.path.isfile(p):
            files.append({"name": name, "path": a["path"].replace(os.sep, "/"),
                          "bytes": os.path.getsize(p), "frame": a.get("frame", ""),
                          "units": a.get("units", "")})
    for name, rel in (("mesh (OpenMVS)", "geometry/scene_dense_mesh.ply"),
                      ("dense cloud (OpenMVS)", "geometry/scene_dense.ply"),
                      ("QA report", "qa_report.md"), ("run manifest", "run_manifest.json")):
        if os.path.isfile(os.path.join(run, rel)):
            files.append({"name": name, "path": rel,
                          "bytes": os.path.getsize(os.path.join(run, rel)),
                          "frame": "F4" if rel.startswith("geometry") else "", "units": ""})

    kfs = sorted(os.path.relpath(p, run).replace(os.sep, "/")
                 for p in glob.glob(os.path.join(run, "keyframes", "kf_*.jpg")))

    return {
        "run_id": m.get("run_id"), "source": m.get("source"), "started": m.get("started"),
        "git": m.get("git_sha"), "config": (m.get("config_sha256") or "")[:12],
        "host": m.get("host", {}), "seconds": m.get("seconds"), "budget": m.get("budget_s"),
        "within": m.get("within_budget"), "level": m.get("level"),
        "quality": m.get("quality"), "units": m.get("units"), "frame": m.get("frame"),
        "scale": m.get("scale", {}), "georef": m.get("georeferenced"),
        "codes": [[c, CODES.get(c, "")] for c in m.get("codes", [])],
        "verdicts": list((m.get("verdicts") or {}).items()),
        "stages": [{"id": s["id"], "seconds": s.get("seconds", 0), "skipped": s.get("skipped"),
                    "codes": s.get("codes", []), "note": s.get("note", ""),
                    "facts": scalars(s.get("facts"))} for s in m.get("stages", [])],
        "s3": [[x["stage"], x["seconds"]] for x in geo.get("stages", [])],
        "s3_total": geo.get("total_seconds"),
        "sparse": list((geo.get("sparse_after_bundle_adjustment") or {}).items()),
        "screen": scalars(screen), "reasons": screen.get("reasons", []),
        "screen_note": st.get("S0-screen", {}).get("note", ""),
        "ingest": scalars(ing) + [["overlay crop (t, r, b, l)", ", ".join(
            f"{v:.2f}" for v in ing.get("overlay_crop_trbl", []))]],
        "level_facts": scalars((st.get("S5b-level", {}).get("facts") or {}).get("gravity")),
        "dsm": scalars((st.get("S6-export", {}).get("facts") or {}).get("dsm")),
        "files": files, "keyframes": kfs,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run", help="a tesseract run folder, e.g. out/runs/demo_gpu")
    ap.add_argument("--out", default=None, help="default <run>/index.html")
    ap.add_argument("--tris", type=int, default=200_000)
    ap.add_argument("--points", type=int, default=300_000)
    a = ap.parse_args(argv)
    if not os.path.exists(os.path.join(a.run, "run_manifest.json")):
        print(f"{a.run}: no run_manifest.json", file=sys.stderr)
        return 2
    out = a.out or os.path.join(a.run, "index.html")
    data, run = pack(a.run, a.tris, a.points), describe(a.run)
    tpl = open(os.path.join(HERE, "run_page_template.html"), encoding="utf-8").read()
    enc = lambda o: json.dumps(o, ensure_ascii=True).replace("</", "<\\/")
    html = (tpl.replace("__TITLE__", f"Run {run['run_id']}")
               .replace("__DATA__", enc(data)).replace("__RUN__", enc(run)))
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"{os.path.getsize(out) / 1e6:.1f} MB  {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
