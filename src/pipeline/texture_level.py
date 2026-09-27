"""
Level the colour steps between texture patches of a finished textured mesh.

Run:  python src/pipeline/texture_level.py <geometry_dir> --out <new_dir>
                                            [--lambda-smooth 0.1] [--report <json>]
From code: level(geometry_dir, out_dir) writes a levelled copy; level_in_place(work)
replaces the atlases in a work folder, the way texture_fill.fill_in_place does;
local_gpu calls it right after the fill.

TextureMesh fills each texture patch from one photo, so the colour jumps where two
patches meet. OpenMVS's own levelling blackens the atlas in the Windows build, so this is
the global adjustment of Waechter, Moehrle and Goesele (2014, "Let There Be Color!")
done on the CPU after texturing:

- A patch is a connected set of faces whose shared edges have the same texture
  coordinates in the same material. Every (patch, mesh vertex) pair gets an RGB offset.
- Along each seam edge, the colour of each side is sampled a quarter texel inside its
  patch (deeper samples see different ground on the two sides and mostly measure
  texture detail, not the colour step). Per channel, the solve minimises the squared
  difference of the two adjusted colours at every sample, plus lambda times the squared
  difference of the offsets of neighbouring vertices inside a patch, plus a pull toward
  zero that keeps brightness from drifting across the model (tuned on B2 and B3).
- The offsets are interpolated across each triangle in texture space and spread into the
  gutter around each patch from the nearest patch texel, then added to the atlas and
  clipped to 0-255.

Faces no photo textured are left alone and are not anchors: TextureMesh's unseen faces
(all three texture corners on one texel) and the faces texture_fill moved into the strip
it appends under the atlas (their colours are estimates from the dense cloud). Their
texels keep their colours.

The OBJ and MTL are copied unchanged; only the atlases are rewritten, under their own
names and formats (JPEG at quality 97).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time

import cv2
import numpy as np
from scipy.sparse import coo_matrix, identity
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import splu

try:
    from numba import njit
except ImportError:  # the pure Python loop is slow but correct
    def njit(*a, **k):
        return (lambda f: f) if not (a and callable(a[0])) else a[0]

INSET = 0.25       # texels inside the patch where seam colours are sampled
SAMPLES = 8        # samples along each seam edge
PULL = 0.03        # weight of the pull toward zero on every offset
JPEG_QUALITY = 97
UV_TOL = 1e-6      # same tolerance as the seam metric
ROBUST_ITERS = 3   # reweighted solves when a robust scale is set
REACH = 3.0        # texels outside a triangle that take its own offsets


# Reading ------------------------------------------------------------------------------

def parse_obj(path: str) -> dict:
    """Texture coordinates, triangles (v and vt indices) and the material of each face."""
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    mtllib, vt, fv, ft, fm = None, [], [], [], []
    mats, cur, nv = [], -1, 0
    for ln in lines:
        if ln.startswith("v "):
            nv += 1
        elif ln.startswith("vt "):
            p = ln.split()
            vt.append((float(p[1]), float(p[2])))
        elif ln.startswith("f "):
            parts = [p.split("/") for p in ln.split()[1:]]
            vs = [int(p[0]) for p in parts]
            ts = [int(p[1]) if len(p) > 1 and p[1] else 0 for p in parts]
            vs = [v - 1 if v > 0 else nv + v for v in vs]
            ts = [t - 1 if t > 0 else (len(vt) + t if t < 0 else -1) for t in ts]
            for k in range(1, len(vs) - 1):         # fan for polygons
                fv.append((vs[0], vs[k], vs[k + 1]))
                ft.append((ts[0], ts[k], ts[k + 1]))
                fm.append(cur)
        elif ln.startswith("usemtl"):
            name = ln.split(None, 1)[1].strip() if len(ln.split()) > 1 else ""
            if name not in mats:
                mats.append(name)
            cur = mats.index(name)
        elif ln.startswith("mtllib") and mtllib is None:
            mtllib = ln.split(None, 1)[1].strip()
    return {"mtllib": mtllib, "materials": mats,
            "VT": np.asarray(vt, np.float64).reshape(-1, 2),
            "F": np.asarray(fv, np.int64).reshape(-1, 3),
            "FT": np.asarray(ft, np.int64).reshape(-1, 3),
            "M": np.asarray(fm, np.int64)}


def read_mtl(path: str) -> dict:
    atlases, cur = {}, None
    for ln in open(path, encoding="utf-8", errors="replace"):
        s = ln.strip()
        if s.startswith("newmtl"):
            cur = s.split(None, 1)[1].strip()
        elif s.startswith("map_Kd") and cur is not None:
            atlases[cur] = s.split(None, 1)[1].strip()
    return atlases


# The seam metric, copied unchanged from the saved-run audit (FINDINGS.md) ---------------

def seam_stat(faces, fuv, uv, atlas_path, max_pairs=16000):
    """Compare RGB steps just inside matched geometry edges.

    A seam edge has the same pair of vertex IDs in two faces but different UV
    endpoint IDs. The step is mean absolute RGB difference between atlas samples
    5% of a triangle altitude in from the shared edge on each side. The control
    uses the same sampling for continuous-UV interior edges. Units: 8-bit RGB.
    """
    n = len(faces)
    edge_key = np.empty(n*3, np.uint64)
    edge_face = np.empty(n*3, np.int32)
    edge_side = np.empty(n*3, np.uint8)
    for s in range(3):
        a, b = faces[:, s], faces[:, (s+1)%3]
        edge_key[s*n:(s+1)*n] = (np.minimum(a,b).astype(np.uint64)<<32) | np.maximum(a,b).astype(np.uint64)
        edge_face[s*n:(s+1)*n] = np.arange(n)
        edge_side[s*n:(s+1)*n] = s
    order = np.argsort(edge_key)
    key = edge_key[order]
    valid = np.flatnonzero(key[1:] == key[:-1])
    valid = valid[(valid == 0) | (key[np.maximum(valid-1,0)] != key[valid])]
    valid = valid[(valid+2 >= len(key)) | (key[np.minimum(valid+2,len(key)-1)] != key[valid])]
    a, b = order[valid], order[valid+1]
    fa, fb = edge_face[a], edge_face[b]
    sa, sb = edge_side[a], edge_side[b]
    ua = fuv[fa, sa]; va = fuv[fa, (sa+1)%3]
    ub = fuv[fb, sb]; vb = fuv[fb, (sb+1)%3]
    ea = faces[fa,sa] < faces[fa,(sa+1)%3]
    eb = faces[fb,sb] < faces[fb,(sb+1)%3]
    a0 = np.where(ea,ua,va); a1 = np.where(ea,va,ua)
    b0 = np.where(eb,ub,vb); b1 = np.where(eb,vb,ub)
    seam = (np.max(np.abs(uv[a0]-uv[b0]),axis=1)>1e-6) | (np.max(np.abs(uv[a1]-uv[b1]),axis=1)>1e-6)
    atlas = cv2.imread(str(atlas_path))
    if atlas is None:
        return {"error": "atlas unreadable"}
    h, w = atlas.shape[:2]
    rng = np.random.default_rng(7)
    result = {"face_count": int(n), "paired_edges": int(len(a)), "uv_seam_edges": int(seam.sum()), "boundary_edges": int(n*3-2*len(a))}
    cent = uv[fuv].mean(axis=1)
    cx = np.clip(np.rint(cent[:,0]*(w-1)).astype(int),0,w-1)
    cy = np.clip(np.rint((1-cent[:,1])*(h-1)).astype(int),0,h-1)
    face_rgb = atlas[cy,cx][:,::-1]
    empty = (face_rgb[:,0]>200) & (face_rgb[:,1]>70) & (face_rgb[:,1]<170) & (face_rgb[:,2]<90)
    result["orange_faces"] = int(empty.sum())
    result["orange_face_fraction"] = round(float(empty.mean()),4)
    for label, choose in (("seam", seam), ("interior", ~seam)):
        idx = np.flatnonzero(choose)
        if len(idx) > max_pairs:
            idx = rng.choice(idx, max_pairs, replace=False)
        def sample(f, s):
            p = .475*uv[fuv[f,s]] + .475*uv[fuv[f,(s+1)%3]] + .05*uv[fuv[f,(s+2)%3]]
            x = np.clip(np.rint(p[:,0]*(w-1)).astype(int), 0, w-1)
            y = np.clip(np.rint((1-p[:,1])*(h-1)).astype(int), 0, h-1)
            return atlas[y,x].astype(np.float32)
        d = np.abs(sample(fa[idx],sa[idx])-sample(fb[idx],sb[idx])).mean(axis=1)
        result[label+"_mean_rgb"] = round(float(d.mean()),3) if len(d) else None
        result[label+"_median_rgb"] = round(float(np.median(d)),3) if len(d) else None
        result[label+"_sample_n"] = int(len(d))
    i = result["interior_mean_rgb"]
    result["seam_to_interior_ratio"] = round(result["seam_mean_rgb"]/i,3) if i else None
    return result


def seam_summary(mesh: dict, atlas_path: str, keep=None) -> dict:
    """seam_stat on the whole mesh, or on the faces in keep (a bool mask)."""
    F, FT = mesh["F"], mesh["FT"]
    if keep is not None:
        F, FT = F[keep], FT[keep]
    ok = (FT >= 0).all(1)
    try:
        s = seam_stat(F[ok].astype(np.int32), FT[ok].astype(np.int32),
                      mesh["VT"].astype(np.float32), atlas_path)
    except (TypeError, ValueError, IndexError):     # no seam or no interior edge at all
        s = {}
    return {k: s.get(k) for k in ("seam_mean_rgb", "interior_mean_rgb",
                                  "seam_to_interior_ratio", "uv_seam_edges")}


# Which faces take part ----------------------------------------------------------------

def pixel_coords(VT: np.ndarray, h: int, w: int) -> np.ndarray:
    """Texel coordinates with texel centres at integers, as view_check samples them."""
    return np.column_stack([VT[:, 0] * (w - 1), (1.0 - VT[:, 1]) * (h - 1)])


def fill_top(mesh: dict, m: int, shape: tuple, name: str):
    """
    First atlas row of texture_fill's strip in material m, or None. texture_fill names the
    atlas *_filled and gives each face an 8 px cell with corners at (1, 1), (7, 1) and
    (1, 7) inside it, in pixels of x = u * W, y = (1 - v) * H.
    """
    if "_filled" not in os.path.splitext(name)[0]:
        return None
    h, w = shape[:2]
    sel = np.flatnonzero((mesh["M"] == m) & (mesh["FT"] >= 0).all(1))
    if not len(sel):
        return None
    t = mesh["VT"][mesh["FT"][sel]]                          # (n, 3, 2)
    x, y = t[..., 0] * w, (1.0 - t[..., 1]) * h
    xi, yi = np.rint(x), np.rint(y)
    on_grid = (np.abs(x - xi) < 0.05).all(1) & (np.abs(y - yi) < 0.05).all(1)
    shape_ok = ((xi[:, 1] - xi[:, 0] == 6) & (yi[:, 1] == yi[:, 0])
                & (xi[:, 2] == xi[:, 0]) & (yi[:, 2] - yi[:, 0] == 6)
                & ((xi[:, 0] - 1) % 8 == 0))
    cells = on_grid & shape_ok
    if not cells.any():
        return None
    top = int(yi[cells, 0].min() - 1)
    if ((yi[cells, 0] - 1 - top).astype(int) % 8).any():
        return None
    return top


def excluded_faces(mesh: dict, shapes: list, names: list):
    """Faces with no photo texture: no vt, no atlas, zero texture area, or in a fill strip."""
    F, FT, M, VT = mesh["F"], mesh["FT"], mesh["M"], mesh["VT"]
    bad = (FT < 0).any(1) | (M < 0)
    for m in range(len(shapes)):
        if shapes[m] is None:
            bad |= M == m
    t = VT[np.maximum(FT, 0)]
    e1, e2 = t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]
    unseen = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) < 1e-12
    tops = {}
    fill = np.zeros(len(F), bool)
    for m, shape in enumerate(shapes):
        if shape is None:
            continue
        top = fill_top(mesh, m, shape, names[m])
        if top is None:
            continue
        tops[m] = top
        h = shape[0]
        y = (1.0 - t[..., 1]) * h
        fill |= (M == m) & (y.min(1) >= top - 0.5)
    return bad | unseen | fill, unseen & ~bad, fill & ~bad, tops


# Patches and the solve ----------------------------------------------------------------

def paired_edges(F: np.ndarray, use: np.ndarray):
    """Geometry edges shared by exactly two used faces: (fa, sa, fb, sb)."""
    idx = np.flatnonzero(use)
    n = len(idx)
    f = F[idx]
    key = np.empty(3 * n, np.uint64)
    face = np.empty(3 * n, np.int64)
    side = np.empty(3 * n, np.int64)
    for s in range(3):
        a, b = f[:, s], f[:, (s + 1) % 3]
        key[s * n:(s + 1) * n] = ((np.minimum(a, b).astype(np.uint64) << np.uint64(32))
                                  | np.maximum(a, b).astype(np.uint64))
        face[s * n:(s + 1) * n] = idx
        side[s * n:(s + 1) * n] = s
    order = np.argsort(key, kind="stable")
    k = key[order]
    same = np.flatnonzero(k[1:] == k[:-1])
    lone = ((same == 0) | (k[np.maximum(same - 1, 0)] != k[same]))
    lone &= (same + 2 >= len(k)) | (k[np.minimum(same + 2, len(k) - 1)] != k[same])
    same = same[lone]
    a, b = order[same], order[same + 1]
    return face[a], side[a], face[b], side[b]


def corner_of(F, f, v):
    """Index (0, 1, 2) of geometry vertex v in face f, vectorised."""
    return np.argmax(F[f] == v[:, None], axis=1)


def bilinear(img: np.ndarray, xy: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    x = np.clip(xy[:, 0], 0, w - 1)
    y = np.clip(xy[:, 1], 0, h - 1)
    x0 = np.minimum(np.floor(x).astype(np.int64), w - 2 if w > 1 else 0)
    y0 = np.minimum(np.floor(y).astype(np.int64), h - 2 if h > 1 else 0)
    x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
    fx, fy = (x - x0)[:, None], (y - y0)[:, None]
    im = img.reshape(h, w, -1)
    top = im[y0, x0] * (1 - fx) + im[y0, x1] * fx
    bot = im[y1, x0] * (1 - fx) + im[y1, x1] * fx
    return top * (1 - fy) + bot * fy


def solve_offsets(mesh: dict, atlases: list, use: np.ndarray, lam: float,
                  robust=None, pull: float = PULL) -> dict:
    F, FT, M, VT = mesh["F"], mesh["FT"], mesh["M"], mesh["VT"]
    nf = len(F)
    fa, sa, fb, sb = paired_edges(F, use)
    va0, va1 = F[fa, sa], F[fa, (sa + 1) % 3]
    ca0, ca1 = sa, (sa + 1) % 3
    cb0, cb1 = corner_of(F, fb, va0), corner_of(F, fb, va1)
    ta0, ta1 = FT[fa, ca0], FT[fa, ca1]
    tb0, tb1 = FT[fb, cb0], FT[fb, cb1]
    cont = ((M[fa] == M[fb])
            & (np.abs(VT[ta0] - VT[tb0]).max(1) <= UV_TOL)
            & (np.abs(VT[ta1] - VT[tb1]).max(1) <= UV_TOL))
    # Patches: connected components of used faces joined across continuous edges.
    g = coo_matrix((np.ones(int(cont.sum())), (fa[cont], fb[cont])), shape=(nf, nf))
    _, patch = connected_components(g, directed=False)
    used = np.flatnonzero(use)
    _, patch_id = np.unique(patch[used], return_inverse=True)
    patch = np.full(nf, -1, np.int64)
    patch[used] = patch_id
    n_patch = int(patch_id.max()) + 1 if len(used) else 0
    # One unknown per (patch, vertex) pair.
    nv = int(F.max()) + 1
    key = patch[used, None] * nv + F[used]
    uk, inv = np.unique(key.ravel(), return_inverse=True)
    var = np.full((nf, 3), -1, np.int64)
    var[used] = inv.reshape(-1, 3)
    n = len(uk)
    # Seam colours, sampled along each seam edge a few texels inside each side.
    seam = ~cont & (patch[fa] != patch[fb])
    fa, sa, fb = fa[seam], sa[seam], fb[seam]
    ca0, ca1, cb0, cb1 = ca0[seam], ca1[seam], cb0[seam], cb1[seam]
    t = (np.arange(SAMPLES) + 0.5) / SAMPLES
    col = {}
    for side, (ff, c0, c1) in (("a", (fa, ca0, ca1)), ("b", (fb, cb0, cb1))):
        c2 = 3 - c0 - c1
        cols = np.zeros((len(ff), SAMPLES, 3))
        for m, img in enumerate(atlases):
            sel = np.flatnonzero(M[ff] == m)
            if img is None or not len(sel):
                continue
            h, w = img.shape[:2]
            P = pixel_coords(VT, h, w)
            p0 = P[FT[ff[sel], c0[sel]]]
            p1 = P[FT[ff[sel], c1[sel]]]
            q = P[FT[ff[sel], c2[sel]]]
            e = p1 - p0
            length = np.maximum(np.hypot(e[:, 0], e[:, 1]), 1e-9)
            alt = np.abs(e[:, 0] * (q - p0)[:, 1] - e[:, 1] * (q - p0)[:, 0]) / length
            s = np.clip(INSET / np.maximum(alt, 1e-9), 0.0, 0.45)
            pts = p0[:, None] + t[None, :, None] * e[:, None]
            pts = pts + s[:, None, None] * (q[:, None] - pts)
            cols[sel] = bilinear(img, pts.reshape(-1, 2)).reshape(len(sel), SAMPLES, 3)
        col[side] = cols
    d = col["a"] - col["b"]                                  # (e, S, 3)
    A0, A1 = var[fa, ca0], var[fa, ca1]
    B0, B1 = var[fb, cb0], var[fb, cb1]
    # Each sample at t along the edge sees the offset step (1 - t) s0 + t s1, where
    # s0 = gA0 - gB0 and s1 = gA1 - gB1 at the two ends; per edge the samples reduce
    # to the 2 x 2 moments below.
    ma = np.mean((1 - t) ** 2); mb = np.mean(t * (1 - t)); mc = np.mean(t ** 2)
    r0 = np.einsum("s,esc->ec", (1 - t) / SAMPLES, d)
    r1 = np.einsum("s,esc->ec", t / SAMPLES, d)
    dd = np.mean(d ** 2, axis=1)                             # (e, 3)
    ie = np.concatenate([var[used][:, [0, 1]], var[used][:, [1, 2]], var[used][:, [2, 0]]])
    ie = np.unique(np.sort(ie, 1), axis=0)
    u0 = (np.stack([A0, B0], 1), np.array([1.0, -1.0]))
    u1 = (np.stack([A1, B1], 1), np.array([1.0, -1.0]))

    def outer(u, v, coef):
        (iu, su), (iv, sv) = u, v
        r = np.repeat(iu, 2, axis=1).ravel()
        c = np.tile(iv, (1, 2)).ravel()
        val = (np.outer(su, sv).ravel()[None, :] * coef[:, None]).ravel()
        return r, c, val

    def solve(we):
        parts = [outer(u0, u0, we * ma), outer(u1, u1, we * mc),
                 outer(u0, u1, we * mb), outer(u1, u0, we * mb)]
        ls = np.full(len(ie), lam)
        rows = np.concatenate([p[0] for p in parts] + [ie[:, 0], ie[:, 1], ie[:, 0], ie[:, 1]])
        cols_ = np.concatenate([p[1] for p in parts] + [ie[:, 0], ie[:, 1], ie[:, 1], ie[:, 0]])
        vals = np.concatenate([p[2] for p in parts] + [ls, ls, -ls, -ls])
        Mx = coo_matrix((vals, (rows, cols_)), shape=(n, n)).tocsc()
        Mx = Mx + identity(n, format="csc") * pull
        rhs = np.zeros((n, 3))
        for idx, sgn, r in ((A0, -1, r0), (B0, 1, r0), (A1, -1, r1), (B1, 1, r1)):
            np.add.at(rhs, idx, sgn * we[:, None] * r)
        # The matrix is symmetric positive definite; without symmetric mode SuperLU
        # pivots off the diagonal and takes minutes instead of about a second on B1.
        return splu(Mx, permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0.0,
                    options={"SymmetricMode": True}).solve(rhs)

    def edge_rms(G):
        """Root mean square of the adjusted step over each edge's samples, per edge."""
        s0, s1 = G[A0] - G[B0], G[A1] - G[B1]
        e2 = dd + 2 * (r0 * s0 + r1 * s1) + ma * s0 ** 2 + 2 * mb * s0 * s1 + mc * s1 ** 2
        return np.sqrt(np.maximum(e2.mean(1), 0))

    we = np.ones(len(fa))
    G = np.zeros((n, 3))
    before = edge_rms(G)
    if n and len(fa):
        for _ in range(1 + ROBUST_ITERS):
            G = solve(we)
            if robust is None:
                break
            # Huber weights: a seam whose step stays large after levelling is more
            # likely a misplaced edge or a moving object than a colour difference.
            we = np.minimum(1.0, robust / np.maximum(edge_rms(G), 1e-9))
    after = edge_rms(G)
    rms = lambda x: round(float(np.sqrt(np.mean(x ** 2))), 3) if len(x) else 0.0
    return {"var": var, "G": G, "patches": n_patch, "unknowns": n,
            "seam_edges": int(len(fa)), "downweighted_edges": int((we < 1).sum()),
            "residual_before": rms(before), "residual_after": rms(after)}


# Applying the offsets -----------------------------------------------------------------

@njit(cache=True)
def _raster(P, O, off, dist, reach):
    """
    Offsets interpolated over each triangle. Texels up to reach texels outside a
    triangle take the offset of the nearest point on it, unless another triangle is
    closer, so the gutter between two patches follows the nearer patch.
    """
    h, w = dist.shape
    for f in range(P.shape[0]):
        x0, y0 = P[f, 0, 0], P[f, 0, 1]
        x1, y1 = P[f, 1, 0], P[f, 1, 1]
        x2, y2 = P[f, 2, 0], P[f, 2, 1]
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(den) < 1e-12:
            continue
        # Altitude onto the edge opposite each corner, in texels.
        l0 = np.hypot(x1 - x2, y1 - y2)
        l1 = np.hypot(x2 - x0, y2 - y0)
        l2 = np.hypot(x0 - x1, y0 - y1)
        a0 = abs(den) / max(l0, 1e-12)
        a1 = abs(den) / max(l1, 1e-12)
        a2 = abs(den) / max(l2, 1e-12)
        xa = max(0, int(np.floor(min(x0, x1, x2) - reach)))
        xb = min(w - 1, int(np.ceil(max(x0, x1, x2) + reach)))
        ya = max(0, int(np.floor(min(y0, y1, y2) - reach)))
        yb = min(h - 1, int(np.ceil(max(y0, y1, y2) + reach)))
        for y in range(ya, yb + 1):
            for x in range(xa, xb + 1):
                w0 = ((y1 - y2) * (x - x2) + (x2 - x1) * (y - y2)) / den
                w1 = ((y2 - y0) * (x - x2) + (x0 - x2) * (y - y2)) / den
                w2 = 1.0 - w0 - w1
                d = max(0.0, -w0 * a0, -w1 * a1, -w2 * a2)
                if d > reach or d >= dist[y, x]:
                    continue
                if d > 0.0:
                    w0 = max(w0, 0.0)
                    w1 = max(w1, 0.0)
                    w2 = max(w2, 0.0)
                    s = w0 + w1 + w2
                    w0 /= s
                    w1 /= s
                    w2 /= s
                for c in range(3):
                    off[y, x, c] = w0 * O[f, 0, c] + w1 * O[f, 1, c] + w2 * O[f, 2, c]
                dist[y, x] = d


@njit(cache=True)
def _cells(P, keep):
    """Mark the texels of excluded faces (and one texel around them) as fixed."""
    h, w = keep.shape
    for f in range(P.shape[0]):
        xa = max(0, int(np.floor(min(P[f, 0, 0], P[f, 1, 0], P[f, 2, 0]))) - 1)
        xb = min(w - 1, int(np.ceil(max(P[f, 0, 0], P[f, 1, 0], P[f, 2, 0]))) + 1)
        ya = max(0, int(np.floor(min(P[f, 0, 1], P[f, 1, 1], P[f, 2, 1]))) - 1)
        yb = min(h - 1, int(np.ceil(max(P[f, 0, 1], P[f, 1, 1], P[f, 2, 1]))) + 1)
        for y in range(ya, yb + 1):
            for x in range(xa, xb + 1):
                keep[y, x] = 1


def apply_offsets(img, P, O, P_fixed, top):
    """Offset image for one atlas: triangles, then nearest patch texel in the gutters."""
    h, w = img.shape[:2]
    off = np.zeros((h, w, 3), np.float32)
    dist = np.full((h, w), np.inf, np.float32)
    if len(P):
        _raster(P, O.astype(np.float32), off, dist, REACH)
    mask = (dist <= REACH).astype(np.uint8)
    tri = (dist == 0).astype(np.uint8)
    del dist
    fixed = np.zeros((h, w), np.uint8)
    if len(P_fixed):
        _cells(P_fixed, fixed)
    if top is not None:
        fixed[max(0, top - 1):] = 1
    mask[fixed > 0] = 0
    if mask.any() and not mask.all():
        _, labels = cv2.distanceTransformWithLabels(
            (mask == 0).astype(np.uint8), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
        ys, xs = np.nonzero(mask)
        lut = np.zeros((int(labels.max()) + 1, 2), np.int32)
        lut[labels[ys, xs]] = np.column_stack([ys, xs])
        src = lut[labels]
        gap = mask == 0
        off[gap] = off[src[gap][:, 0], src[gap][:, 1]]
        del labels, src
    off[fixed > 0] = 0
    new = img.astype(np.float32) + off
    clipped = ((new < -0.5) | (new > 255.5)).any(2)
    # Clipped texels among the photo triangle texels, where it would show.
    tri &= fixed == 0
    n_clip = int((clipped & (tri > 0)).sum())
    return np.clip(np.rint(new), 0, 255).astype(np.uint8), int(tri.sum()), n_clip


def write_image(path: str, img: np.ndarray):
    ext = os.path.splitext(path)[1].lower()
    params = [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY] if ext in (".jpg", ".jpeg") else []
    if not cv2.imwrite(path, img, params):
        raise OSError("could not write " + path)


# Entry points -------------------------------------------------------------------------

def level(geometry: str, out: str, lambda_smooth: float = 0.1, robust: float | None = None,
          pull: float = PULL, metric: bool = True) -> dict:
    """Write a levelled copy of geometry's scene_tex.obj, MTL and atlases into out."""
    t0 = time.perf_counter()
    if os.path.abspath(out) == os.path.abspath(geometry):
        raise ValueError("out must be a different folder; use level_in_place")
    obj = os.path.join(geometry, "scene_tex.obj")
    mesh = parse_obj(obj)
    mtl_name = mesh["mtllib"]
    by_name = read_mtl(os.path.join(geometry, mtl_name)) if mtl_name else {}
    names = [by_name.get(m) for m in mesh["materials"]]
    atlases = []
    for nm in names:
        img = cv2.imread(os.path.join(geometry, nm), cv2.IMREAD_COLOR) if nm else None
        atlases.append(img)
    shapes = [None if a is None else a.shape for a in atlases]
    skip, unseen, fill, tops = excluded_faces(mesh, shapes, names)
    use = ~skip
    report = {"geometry": geometry, "faces": int(len(mesh["F"])), "lambda_smooth": lambda_smooth,
              "robust": robust, "pull": pull,
              "materials": len(names), "unseen_faces": int(unseen.sum()),
              "fill_faces": int(fill.sum()), "fill_strip_top_row": tops,
              "fill_handling": "excluded from the solve and left unchanged"}
    first = next((os.path.join(geometry, n) for n in names if n), None)
    if metric and first:
        report["seam_before"] = seam_summary(mesh, first)
        report["seam_before_photo_faces"] = seam_summary(mesh, first, keep=use)
    t1 = time.perf_counter()
    sol = solve_offsets(mesh, atlases, use, lambda_smooth, robust, pull)
    report["solve_s"] = round(time.perf_counter() - t1, 2)
    for k in ("patches", "unknowns", "seam_edges", "downweighted_edges",
              "residual_before", "residual_after"):
        report[k] = sol[k]
    G = sol["G"]
    report["offset_abs_mean"] = round(float(np.abs(G).mean()), 3) if len(G) else 0.0
    report["offset_abs_p99"] = round(float(np.percentile(np.abs(G), 99)), 3) if len(G) else 0.0
    os.makedirs(out, exist_ok=True)
    covered = n_clip = 0
    FT, M, VT = mesh["FT"], mesh["M"], mesh["VT"]
    for m, img in enumerate(atlases):
        if img is None:
            continue
        h, w = img.shape[:2]
        Pm = pixel_coords(VT, h, w)
        sel = np.flatnonzero(use & (M == m))
        fx = np.flatnonzero(skip & (M == m) & (FT >= 0).all(1))
        P = Pm[FT[sel]]
        O = G[sol["var"][sel]] if len(sel) else np.zeros((0, 3, 3))
        new, cov, clip = apply_offsets(img, P, O, Pm[FT[fx]], tops.get(m))
        covered += cov
        n_clip += clip
        write_image(os.path.join(out, names[m]), new)
    report["clipped_texels"] = n_clip
    report["clipped_fraction"] = round(n_clip / max(covered, 1), 6)
    # The OBJ and MTL keep their bytes; atlases no material names are copied as they are.
    shutil.copyfile(obj, os.path.join(out, "scene_tex.obj"))
    if mtl_name:
        shutil.copyfile(os.path.join(geometry, mtl_name), os.path.join(out, mtl_name))
        for nm in set(by_name.values()) - set(n for n in names if n):
            src = os.path.join(geometry, nm)
            if os.path.exists(src) and not os.path.exists(os.path.join(out, nm)):
                shutil.copyfile(src, os.path.join(out, nm))
    sp = os.path.join(geometry, "sparse_txt")
    if os.path.isdir(sp) and not os.path.exists(os.path.join(out, "sparse_txt")):
        shutil.copytree(sp, os.path.join(out, "sparse_txt"))
    if metric and first:
        after_first = os.path.join(out, os.path.basename(first))
        report["seam_after"] = seam_summary(mesh, after_first)
        report["seam_after_photo_faces"] = seam_summary(mesh, after_first, keep=use)
    report["seconds"] = round(time.perf_counter() - t0, 2)
    return report


def level_in_place(work: str, lambda_smooth: float = 0.1, robust: float | None = None,
                   pull: float = PULL, metric: bool = False) -> dict:
    """level() into a temporary folder, then replace the work folder's atlases."""
    tmp = tempfile.mkdtemp(prefix="level-", dir=work)
    try:
        report = level(work, tmp, lambda_smooth, robust, pull, metric=metric)
        mesh = parse_obj(os.path.join(work, "scene_tex.obj"))
        names = read_mtl(os.path.join(work, mesh["mtllib"])).values() if mesh["mtllib"] else []
        for nm in set(names):
            src = os.path.join(tmp, nm)
            if os.path.exists(src):
                os.replace(src, os.path.join(work, nm))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("geometry")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lambda-smooth", type=float, default=0.1)
    ap.add_argument("--robust", type=float, help="Huber scale in RGB levels for the seam "
                    "steps (reweighted solve); off by default")
    ap.add_argument("--pull", type=float, default=PULL, help="weight pulling every offset "
                    "toward zero, which stops brightness drifting across the model")
    ap.add_argument("--report")
    a = ap.parse_args()
    if os.path.abspath(a.out) == os.path.abspath(a.geometry):
        ap.error("--out must be a new folder")
    r = level(a.geometry, a.out, a.lambda_smooth, a.robust, a.pull)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            json.dump(r, f, indent=2)
    print(json.dumps(r))


if __name__ == "__main__":
    main()
