"""
mesh_export on a two-triangle textured OBJ: the vertices land where S5b puts the cloud,
UVs and faces survive, the GLB keeps its atlas, and FBX is written or its absence named.

Run:  python src/pipeline/test_mesh_export.py
"""
from __future__ import annotations

import os
import sys
import tempfile

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mesh_export import export_textured, to_frame  # noqa: E402

FAILED: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


print("T1: a textured OBJ carried into the levelled frame")
with tempfile.TemporaryDirectory() as tmp:
    V = np.array([[1.0, 2.0, 3.0], [4.0, 2.0, 3.0], [1.0, 5.0, 3.0], [4.0, 5.0, 4.0]])
    with open(os.path.join(tmp, "scene_tex.obj"), "w") as f:
        f.write("mtllib scene_tex.mtl\n")
        f.writelines(f"v {x} {y} {z}\n" for x, y, z in V)
        f.write("vt 0 0\nvt 1 0\nvt 0 1\nvt 1 1\nusemtl material_00\n"
                "f 1/1 2/2 3/3\nf 2/2 4/4 3/3\n")
    with open(os.path.join(tmp, "scene_tex.mtl"), "w") as f:
        f.write("newmtl material_00\nTr 1.000000\nmap_Kd atlas.jpg\n")
    cv2.imwrite(os.path.join(tmp, "atlas.jpg"), np.full((8, 8, 3), 128, np.uint8))

    # A level basis that is a proper rotation: rows [e1, up, e2].
    c, s = np.cos(0.3), np.sin(0.3)
    B = np.array([[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]])
    origin, k = np.array([2.0, 3.0, 3.0]), 2.5
    out = os.path.join(tmp, "export")
    paths, notes = export_textured(os.path.join(tmp, "scene_tex.obj"), out,
                                   lambda X: to_frame(X, B, origin, k))

    lines = open(paths["obj"]).read().splitlines()
    got = np.array([ln.split()[1:] for ln in lines if ln.startswith("v ")], float)
    want = ((V - origin) @ B.T)[:, [0, 2, 1]] * k
    check("vertices are transformed exactly as S5b transforms the cloud",
          np.allclose(got, want, atol=1e-4) and np.allclose(to_frame(V, B, origin, k), want),
          str(np.abs(got - want).max()))
    check("UVs and faces are copied unchanged",
          [ln for ln in lines if ln[:2] in ("vt", "f ")] ==
          ["vt 0 0", "vt 1 0", "vt 0 1", "vt 1 1", "f 1/1 2/2 3/3", "f 2/2 4/4 3/3"])
    mtl = open(os.path.join(out, "model.mtl")).read()
    check("the MTL points at the copied atlas and drops OpenMVS's Tr 1",
          "map_Kd model_Kd.jpg" in mtl and "Tr" not in mtl
          and os.path.isfile(os.path.join(out, "model_Kd.jpg")))
    import trimesh
    m = trimesh.load(paths["glb"], force="mesh")
    check("the GLB is Y-up and keeps its texture",
          m.visual.kind == "texture" and np.allclose(
              np.sort(m.vertices[:, 1]), np.sort(want[:, 2]), atol=1e-4))
    check("FBX is written, or its absence is named",
          "fbx" in paths or any(n.startswith("fbx") for n in notes), str(notes))

print()
if FAILED:
    print(f"{len(FAILED)} TEST(S) FAILED: {FAILED}")
    sys.exit(1)
print("ALL PASS")
