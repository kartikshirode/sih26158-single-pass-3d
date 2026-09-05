"""
Pack the reconstruction into a single self-contained HTML viewer.

Decimates the mesh to a web-sized budget, quantises positions to int16 about the
model centre, and inlines everything as base64 - no network fetches, because the
artifact CSP blocks them and because a viewer that needs a server is not a
deliverable.
"""
from __future__ import annotations
import argparse, base64, json, os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def pack(d: str, tri_budget: int = 160_000, pt_budget: int = 220_000):
    import open3d as o3d
    P = np.load(f"{d}/points_fused.npy").astype(np.float64)
    C = np.load(f"{d}/colors_fused.npy")

    m = o3d.io.read_triangle_mesh(f"{d}/model.ply")
    if len(m.triangles) > tri_budget:
        m = m.simplify_quadric_decimation(tri_budget)
        m.remove_degenerate_triangles(); m.remove_unreferenced_vertices()
    V = np.asarray(m.vertices); F = np.asarray(m.triangles)
    VC = (np.asarray(m.vertex_colors) * 255).astype(np.uint8)

    # One frame for both payloads: model Y is down, so flip to a Y-up viewer.
    flip = np.array([1.0, -1.0, 1.0])
    V, P = V * flip, P * flip
    mid = (V.max(0) + V.min(0)) / 2.0
    scale = float((V.max(0) - V.min(0)).max()) / 2.0
    q = lambda A: np.clip(np.round((A - mid) / scale * 32000), -32768, 32767).astype(np.int16)

    if len(P) > pt_budget:
        sel = np.random.default_rng(0).choice(len(P), pt_budget, replace=False)
        P, C = P[sel], C[sel]

    b64 = lambda a: base64.b64encode(a.tobytes()).decode()
    return {
        "vpos": b64(q(V)), "vcol": b64(VC.astype(np.uint8)),
        "idx":  b64(F.astype(np.uint32)),
        "ppos": b64(q(P)), "pcol": b64(C.astype(np.uint8)),
        "nv": int(len(V)), "nt": int(len(F)), "np": int(len(P)),
        "scale": scale,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("indir")
    ap.add_argument("--stats", default=None, help="JSON of pipeline counters")
    ap.add_argument("--out", default="out/kolu3d/viewer.html")
    a = ap.parse_args()

    D = pack(a.indir)
    stats = json.load(open(a.stats)) if a.stats and os.path.exists(a.stats) else {}
    tpl = open(os.path.join(HERE, "viewer_template.html"), encoding="utf-8").read()
    html = (tpl.replace("__DATA__", json.dumps(D))
               .replace("__STATS__", json.dumps(stats)))
    html = "".join(c if ord(c) < 128 else f"&#{ord(c)};" for c in html)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(html)
    print(f"{D['nv']:,} verts / {D['nt']:,} tris / {D['np']:,} pts -> "
          f"{os.path.getsize(a.out)/1e6:.1f} MB  {a.out}")
