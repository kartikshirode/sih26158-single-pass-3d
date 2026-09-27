"""
Give the faces no photo saw a colour from the dense cloud instead of TextureMesh's flat
empty colour.

Run:  python src/pipeline/texture_fill.py <geometry_dir> --out <new_dir> [--report <json>]
In a run, local_gpu calls fill_in_place on its work folder right after TextureMesh.

TextureMesh maps every face it could not texture to one texel of the empty colour, so on
the demo 3.2% of the faces (6.8k) share a single UV point and render as orange blotches.
Those faces still have dense points around them, coloured from the photos by
DensifyPointCloud. This gives each such face its own small cell in a strip appended to
the bottom of its atlas, and paints the cell by interpolating the colours of the dense
points nearest the face's three corners. Nothing else in the OBJ changes except the v
coordinate of every existing texture vertex, rescaled for the taller atlas.

Reads scene_tex.obj, its MTL and atlases, points_fused.npy and colors_fused.npy (the
geometry frame, the same as the OBJ's). Writes a copy; never touches the input folder.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time

import cv2
import numpy as np
from scipy.spatial import cKDTree

CELL = 8          # texels per side of one face's cell; 1 texel of it is margin
NEIGHBOURS = 8


def parse(obj_path: str):
    lines = open(obj_path, encoding="utf-8", errors="replace").read().splitlines()
    V, VT, faces = [], [], []          # faces: (line index, [v...], [vt...], material)
    mat = None
    for i, ln in enumerate(lines):
        if ln.startswith("v "):
            V.append([float(x) for x in ln.split()[1:4]])
        elif ln.startswith("vt "):
            VT.append([float(x) for x in ln.split()[1:3]])
        elif ln.startswith("usemtl"):
            mat = ln.split(None, 1)[1].strip()
        elif ln.startswith("f "):
            parts = [p.split("/") for p in ln.split()[1:]]
            if len(parts) == 3 and all(len(p) > 1 and p[1] for p in parts):
                faces.append((i, [int(p[0]) - 1 for p in parts],
                              [int(p[1]) - 1 for p in parts], mat))
    return lines, np.asarray(V, np.float64), np.asarray(VT, np.float64), faces


def materials(geometry: str, lines: list) -> tuple[str, dict]:
    mtl = next(ln.split(None, 1)[1].strip() for ln in lines if ln.startswith("mtllib"))
    atlases, cur = {}, None
    for ln in open(os.path.join(geometry, mtl), encoding="utf-8"):
        ln = ln.strip()
        if ln.startswith("newmtl"):
            cur = ln.split(None, 1)[1].strip()
        elif ln.startswith("map_Kd") and cur:
            atlases[cur] = ln.split(None, 1)[1].strip()
    return mtl, atlases


def unseen(faces: list, VT: np.ndarray) -> np.ndarray:
    """Faces whose three texture corners coincide: TextureMesh's mark for no photo."""
    t = VT[np.array([f[2] for f in faces])]
    e1, e2 = t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]
    area = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
    return area < 1e-12


def corner_colours(P: np.ndarray, C: np.ndarray, X: np.ndarray) -> np.ndarray:
    """Inverse-distance mean colour (BGR) of the dense points nearest each corner."""
    d, j = cKDTree(P).query(X, k=min(NEIGHBOURS, len(P)))
    d, j = d.reshape(len(X), -1), j.reshape(len(X), -1)
    w = 1.0 / np.maximum(d, 1e-9)
    rgb = (C[j].astype(np.float64) * w[..., None]).sum(1) / w.sum(1, keepdims=True)
    return rgb[:, ::-1]


def paint_strip(width: int, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    One CELL x CELL cell per face, laid left to right, top to bottom. Returns the strip
    image and each face's three corner texel positions (x, y) inside the strip. The cell
    is painted everywhere, margin included, by clamped barycentric weights, so mipmaps and
    bilinear filtering sample the face's own colours.
    """
    n = len(cols)
    per_row = width // CELL
    rows = int(np.ceil(n / per_row))
    strip = np.zeros((rows * CELL, width, 3), np.float64)
    k = np.arange(n)
    x0, y0 = (k % per_row) * CELL, (k // per_row) * CELL
    a = np.array([1.0, 1.0])
    b = np.array([CELL - 1.0, 1.0])
    c = np.array([1.0, CELL - 1.0])
    yy, xx = np.mgrid[0:CELL, 0:CELL] + 0.5
    q = np.stack([xx.ravel(), yy.ravel()], 1)                  # texel centres in a cell
    # Barycentric weights of each texel centre in the triangle (a, b, c), clamped.
    T = np.array([b - a, c - a]).T
    l12 = np.linalg.solve(T, (q - a).T).T
    wts = np.column_stack([1 - l12.sum(1), l12])
    wts = np.clip(wts, 0, None)
    wts /= wts.sum(1, keepdims=True)
    cell = np.einsum("tk,nkc->ntc", wts, cols)                  # (n, CELL*CELL, 3)
    for i in range(CELL * CELL):
        ty, tx = divmod(i, CELL)
        strip[y0 + ty, x0 + tx] = cell[:, i]
    corners = np.stack([np.column_stack([x0 + p[0], y0 + p[1]]) for p in (a, b, c)], 1)
    return np.clip(strip, 0, 255).astype(np.uint8), corners


def fill(geometry: str, out: str, cloud: str | None = None) -> dict:
    t0 = time.perf_counter()
    obj = os.path.join(geometry, "scene_tex.obj")
    lines, V, VT, faces = parse(obj)
    mtl, atlases = materials(geometry, lines)
    bad = unseen(faces, VT)
    report = {"faces": len(faces), "unseen_faces": int(bad.sum()),
              "unseen_fraction": round(float(bad.mean()), 5), "materials": {}}
    os.makedirs(out, exist_ok=True)
    VT = VT.copy()
    new_vt = []
    face_vt = {}
    if bad.any():
        P = np.load(os.path.join(cloud or geometry, "points_fused.npy"))
        C = np.load(os.path.join(cloud or geometry, "colors_fused.npy"))
        if C.dtype != np.uint8:
            C = (np.clip(C, 0, 1) * 255).astype(np.uint8) if C.max() <= 1 else C.astype(np.uint8)
        idx = np.flatnonzero(bad)
        mats = [faces[i][3] for i in idx]
        vt_used = {m: set() for m in atlases}
        for f in faces:
            vt_used.setdefault(f[3], set()).update(f[2])
        for m in sorted(set(mats), key=str):
            if m not in atlases:
                continue
            sel = idx[np.array([x == m for x in mats])]
            img = cv2.imread(os.path.join(geometry, atlases[m]), cv2.IMREAD_COLOR)
            H, W = img.shape[:2]
            corners3d = V[np.array([faces[i][1] for i in sel])].reshape(-1, 3)
            cols = corner_colours(P, C, corners3d).reshape(len(sel), 3, 3)
            strip, xy = paint_strip(W, cols)
            H2 = H + strip.shape[0]
            # Existing texture vertices of this material keep their texels in a taller image.
            used = np.fromiter(vt_used[m], int)
            VT[used, 1] = 1.0 - (1.0 - VT[used, 1]) * H / H2
            base = len(VT) + len(new_vt)
            for j, fi in enumerate(sel):
                ids = []
                for k in range(3):
                    x, y = xy[j, k]
                    new_vt.append((x / W, 1.0 - (H + y) / H2))
                    ids.append(base + 3 * j + k)
                face_vt[fi] = ids
            name = os.path.splitext(atlases[m])[0] + "_filled.jpg"
            cv2.imwrite(os.path.join(out, name), np.vstack([img, strip]),
                        [cv2.IMWRITE_JPEG_QUALITY, 97])
            atlases[m] = name
            report["materials"][m] = {"filled": int(len(sel)), "atlas": [W, H2]}
    # Write the OBJ: existing vt rescaled, new vt appended after the last vt line, the
    # unseen faces pointed at their cells.
    out_lines = []
    last_vt = max((i for i, ln in enumerate(lines) if ln.startswith("vt ")), default=-1)
    vt_i = 0
    face_at = {f[0]: (fi, f) for fi, f in enumerate(faces)}
    for i, ln in enumerate(lines):
        if ln.startswith("vt "):
            out_lines.append(f"vt {VT[vt_i, 0]:.6f} {VT[vt_i, 1]:.6f}")
            vt_i += 1
            if i == last_vt:
                out_lines += [f"vt {u:.6f} {v:.6f}" for u, v in new_vt]
        elif i in face_at and face_at[i][0] in face_vt:
            fi, f = face_at[i]
            out_lines.append("f " + " ".join(f"{v + 1}/{t + 1}"
                                             for v, t in zip(f[1], face_vt[fi])))
        else:
            out_lines.append(ln)
    with open(os.path.join(out, "scene_tex.obj"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out_lines) + "\n")
    with open(os.path.join(out, mtl), "w", encoding="utf-8", newline="\n") as f:
        for ln in open(os.path.join(geometry, mtl), encoding="utf-8"):
            s = ln.strip()
            if s.startswith("newmtl"):
                cur = s.split(None, 1)[1].strip()
            if s.startswith("map_Kd") and cur in atlases:
                ln = f"map_Kd {atlases[cur]}\n"
            f.write(ln)
    for name in set(atlases.values()):
        if not os.path.exists(os.path.join(out, name)):
            shutil.copyfile(os.path.join(geometry, name), os.path.join(out, name))
    src = os.path.join(geometry, "sparse_txt")
    if os.path.isdir(src) and not os.path.exists(os.path.join(out, "sparse_txt")):
        shutil.copytree(src, os.path.join(out, "sparse_txt"))
    report["seconds"] = round(time.perf_counter() - t0, 2)
    return report


def fill_in_place(work: str) -> dict:
    """fill() into a temporary folder, then replace the work folder's OBJ, MTL and atlas."""
    import tempfile
    tmp = tempfile.mkdtemp(prefix="fill-", dir=work)
    try:
        report = fill(work, tmp)
        if report["unseen_faces"]:
            _, atlases = materials(work, parse(os.path.join(work, "scene_tex.obj"))[0])
            for name in os.listdir(tmp):
                if name != "sparse_txt":
                    shutil.move(os.path.join(tmp, name), os.path.join(work, name))
            _, now = materials(work, parse(os.path.join(work, "scene_tex.obj"))[0])
            for old in set(atlases.values()) - set(now.values()):
                if os.path.exists(os.path.join(work, old)):
                    os.remove(os.path.join(work, old))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("geometry")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cloud", help="folder with points_fused.npy and colors_fused.npy, "
                    "when it is not the geometry folder")
    ap.add_argument("--report")
    a = ap.parse_args()
    if os.path.abspath(a.out) == os.path.abspath(a.geometry):
        ap.error("--out must be a new folder")
    r = fill(a.geometry, a.out, a.cloud)
    if a.report:
        json.dump(r, open(a.report, "w"), indent=2)
    print(json.dumps(r))


if __name__ == "__main__":
    main()
