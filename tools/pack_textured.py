"""
Pack a textured OpenMVS mesh for the console.

    <python 3.11> tools/pack_textured.py            # out/kolu_tex_mvs -> out/kolutex3d

Three things the per-vertex packer (tools/build_viewer.py) cannot do:

  1. Decimate without losing the atlas, if the mesh is over budget. MeshLab's
     texture-aware collapse keeps the coordinates, but it cannot make OpenMVS's
     per-face micro-charts any bigger: on the 1.9M-face Kolu mesh (median chart five
     texels) the result rendered as gutter. Texture a mesh that is already at web
     size instead (the job's MESH_BLOB mode) and this step becomes a no-op.
  2. Split vertices at chart seams. OpenMVS textures per face group, so one vertex
     carries a different (u, v) in each chart it borders. The GPU needs one (u, v)
     per vertex, so each distinct (vertex, u, v) becomes its own corner.
  3. Crop the atlas. TextureMesh packs charts from the top of an 8192 x 8192 image
     and fills the rest orange; on Kolu a quarter of the rows carry every chart. The
     packed UVs address the cropped image, measured from its top row, which is how
     WebGL sees an <img> uploaded without a flip.

Geometry goes into the same upright frame and the same int16 quantisation as the
per-vertex pack, from the same reference run, so the console's A/B toggle compares
geometry and nothing else. The point payload is copied from that reference run
unchanged: the measure tool picks against points, and the calibration must see the
same points whichever mesh is on screen.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.environ.get("SRC", os.path.join(ROOT, "out", "kolu_tex_mvs"))
REF = os.environ.get("REF", os.path.join(ROOT, "out", "kolumvs3d"))
OUT = os.environ.get("OUT", os.path.join(ROOT, "out", "kolutex3d"))
TRI = int(os.environ.get("TRI", "300000"))
# A 4x4 similarity taking this mesh into the reference run's frame. Two Cloud Run
# passes over the same poses came back in different gauges (the second 1.33x larger,
# 0.87 degrees rotated, 0.034 units RMSE once aligned), and the docs/08 calibration
# belongs to the first one's frame.
ALIGN = os.environ.get("ALIGN", "")
JPEG_Q = 82
FILL = np.array([255, 127, 39])          # OpenMVS's empty-atlas colour, approximately

sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))


def log(msg):
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def decimate(obj: str, target: int):
    import pymeshlab
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(obj)
    m = ms.current_mesh()
    n0 = (m.vertex_number(), m.face_number())
    log(f"loaded {n0[0]:,} vertices, {n0[1]:,} faces")
    if m.face_number() > target:
        ms.meshing_decimation_quadric_edge_collapse_with_texture(
            targetfacenum=target, qualitythr=0.3, extratcoordw=1.0,
            preserveboundary=True, optimalplacement=True, planarquadric=True)
        m = ms.current_mesh()
        log(f"decimated to {m.vertex_number():,} vertices, {m.face_number():,} faces")
    V = np.asarray(m.vertex_matrix(), np.float64)
    F = np.asarray(m.face_matrix(), np.int64)
    W = np.asarray(m.wedge_tex_coord_matrix(), np.float64)      # (3F, 2), corner order
    if W.shape[0] != 3 * len(F):
        sys.exit(f"wedge texcoords {W.shape} do not match {len(F)} faces")
    return V, F, W.reshape(len(F), 3, 2), n0


def main() -> int:
    # scene_mesh_texture.* is the texture-only job's output (a 300k-face mesh textured
    # against the sparse scene); scene_dense_mesh_texture.* the full-pipeline one.
    stem = next((n for n in ("scene_mesh_texture", "scene_dense_mesh_texture")
                 if os.path.exists(os.path.join(SRC, n + ".obj"))), None)
    if not stem:
        sys.exit(f"no textured OBJ under {SRC}")
    obj = os.path.join(SRC, stem + ".obj")
    mtl = io.open(os.path.join(SRC, stem + ".mtl"), encoding="utf-8").read()
    tex = re.search(r"map_Kd\s+(\S+)", mtl).group(1)
    for p in (obj, os.path.join(SRC, tex), os.path.join(REF, "viewer.html"),
              os.path.join(REF, "points_fused.npy")):
        if not os.path.exists(p):
            sys.exit(f"missing {p}")
    os.makedirs(OUT, exist_ok=True)

    V, F, W, n0 = decimate(obj, TRI)
    if ALIGN:
        T = np.load(ALIGN)
        V = V @ T[:3, :3].T + T[:3, 3]
        log(f"aligned to the reference frame with {os.path.basename(ALIGN)} "
            f"(scale {np.cbrt(np.linalg.det(T[:3, :3])):.4f})")

    # ---- corners: one per distinct (vertex, u, v)
    uvq = np.clip(np.round(W.reshape(-1, 2) * 65535.0), 0, 65535).astype(np.uint32)
    key = np.stack([F.reshape(-1).astype(np.uint32), uvq[:, 0], uvq[:, 1]], axis=1)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    corner_v = uniq[:, 0].astype(np.int64)
    corner_uv = uniq[:, 1:].astype(np.float64) / 65535.0
    idx = inv.reshape(len(F), 3).astype(np.uint32)
    log(f"{len(uniq):,} corners for {len(np.unique(corner_v)):,} vertices "
        f"({len(uniq) / max(1, len(np.unique(corner_v))):.2f} per vertex)")

    # ---- atlas: which rows do the UVs use? OBJ v runs upward from the bottom row.
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    img = Image.open(os.path.join(SRC, tex)).convert("RGB")
    Wd, Ht = img.size
    rows = (1.0 - corner_uv[:, 1]) * Ht
    r0 = int(max(0, np.floor(rows.min()) - 2))
    r1 = int(min(Ht, np.ceil(rows.max()) + 2))
    crop = img.crop((0, r0, Wd, r1))
    A = np.asarray(crop)
    fill_in = float((np.abs(A.astype(np.int16) - FILL).sum(-1) < 30).mean())
    log(f"atlas {Wd}x{Ht}: charts span rows {r0}..{r1} ({r1 - r0} rows); "
        f"fill colour covers {fill_in:.1%} of the crop")
    if fill_in > 0.5:
        sys.exit("the cropped rows are mostly fill: the UV convention guess is wrong")
    # Faces no camera saw carry the fill colour. Keep them, in a neutral grey: an
    # orange face claims a texture where there is none, a grey one reads as "unseen".
    # A JPEG halo survives around the fill, so the tolerance is generous.
    fill = np.abs(A.astype(np.int16) - FILL).sum(-1) < 90
    if fill.any():
        A = A.copy(); A[fill] = (96, 96, 96)
        crop = Image.fromarray(A)
        log(f"{fill.mean():.1%} of the crop was fill colour, now grey")
    uv_out = np.column_stack([corner_uv[:, 0], (rows - r0) / (r1 - r0)])
    uv16 = np.clip(np.round(uv_out * 65535.0), 0, 65535).astype(np.uint16)
    atlas_path = os.path.join(OUT, "atlas.jpg")
    crop.save(atlas_path, quality=JPEG_Q, optimize=True, subsampling=1)
    log(f"atlas.jpg {os.path.getsize(atlas_path) / 1e6:.1f} MB at {crop.size}")

    # ---- the reference run's frame, exactly as tools/build_viewer.py builds it
    from pipeline.render_views import upright_frame
    P = np.load(os.path.join(REF, "points_fused.npy")).astype(np.float64)
    cc = os.path.join(REF, "cam_centres.npy")
    centres = np.load(cc) if os.path.exists(cc) else None
    B = upright_frame(P, centres)
    c0 = P.mean(0)
    Vc = (V[corner_v] - c0) @ B.T

    # ---- the reference run's point payload, byte for byte, and its quantisation.
    # The points were quantised with the reference mesh's mid and scale; this mesh
    # has to use the same two numbers or the two payloads sit in different frames.
    # The mid is not stored, so recover it from the points: the same rng draw the
    # packer made, dequantised against the rotated cloud.
    from build_gallery import packed
    D0, _ = packed(os.path.basename(REF))
    scale = float(D0["scale"])
    Pq = np.frombuffer(base64.b64decode(D0["ppos"]), dtype=np.int16).reshape(-1, 3)
    Pr = (P - c0) @ B.T
    if len(Pr) > len(Pq):
        Pr = Pr[np.random.default_rng(0).choice(len(Pr), len(Pq), replace=False)]
    resid = Pr - Pq.astype(np.float64) / 32000.0 * scale
    mid = resid.mean(0)
    if float(np.abs(resid - mid).max()) > scale / 32000.0 * 1.5:
        sys.exit("could not recover the reference quantisation: the point payloads differ")
    vpos = np.clip(np.round((Vc - mid) / scale * 32000), -32768, 32767).astype(np.int16)
    log(f"reference frame: scale {scale:.4f}, mid {np.round(mid, 4).tolist()}")
    b64 = lambda a: base64.b64encode(a.tobytes()).decode()
    D = {
        "vpos": b64(vpos), "uv": b64(uv16), "idx": b64(idx),
        "ppos": D0["ppos"], "pcol": D0["pcol"],
        "nv": int(len(vpos)), "nt": int(len(F)), "np": int(D0["np"]),
        "scale": scale, "tex": "kolu_tex.jpg", "texSize": [crop.size[0], crop.size[1]],
        "source": {"faces_full": n0[1], "vertices_full": n0[0],
                   "atlas_rows": [r0, r1], "jpeg_quality": JPEG_Q,
                   "aligned_with": os.path.basename(ALIGN) if ALIGN else None},
    }
    with io.open(os.path.join(OUT, "packed.json"), "w", encoding="utf-8") as f:
        json.dump(D, f)
    # mid is baked into vpos; scale alone reconstructs metres per unit downstream
    log(f"packed.json {os.path.getsize(os.path.join(OUT, 'packed.json')) / 1e6:.1f} MB: "
        f"{D['nt']:,} tri, {D['nv']:,} corners, {D['np']:,} pts, scale {scale:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
