"""
texture_fill.py on a tiny OBJ: two textured faces and one that TextureMesh left unseen.

Run:  python src/pipeline/test_texture_fill.py
"""
from __future__ import annotations

import os
import sys
import tempfile

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from texture_fill import fill, fill_in_place, parse  # noqa: E402

FAILED: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def sample(folder: str, uv: np.ndarray) -> np.ndarray:
    name = next(ln.split()[1] for ln in open(os.path.join(folder, "scene_tex.mtl"))
                if ln.startswith("map_Kd"))
    atlas = cv2.imread(os.path.join(folder, name))
    h, w = atlas.shape[:2]
    return atlas[int((1 - uv[1]) * h), int(uv[0] * w)].astype(int)


def make(folder: str):
    atlas = np.zeros((64, 64, 3), np.uint8)
    atlas[:, :32] = (0, 200, 0)                 # green left half: face 1
    atlas[:, 32:] = (200, 0, 0)                 # blue right half: face 2
    atlas[0, 63] = (39, 129, 255)               # the empty-colour texel
    cv2.imwrite(os.path.join(folder, "scene_tex_material_00_map_Kd.png"), atlas)
    with open(os.path.join(folder, "scene_tex.mtl"), "w") as f:
        f.write("newmtl material_00\nmap_Kd scene_tex_material_00_map_Kd.png\n")
    with open(os.path.join(folder, "scene_tex.obj"), "w") as f:
        f.write("mtllib scene_tex.mtl\n")
        for v in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (5, 5, 0), (6, 5, 0), (5, 6, 0)):
            f.write(f"v {v[0]} {v[1]} {v[2]}\n")
        for t in ((0.1, 0.1), (0.4, 0.1), (0.1, 0.4), (0.6, 0.1), (0.9, 0.1), (0.6, 0.4),
                  (0.995, 0.995)):
            f.write(f"vt {t[0]} {t[1]}\n")
        f.write("usemtl material_00\n")
        f.write("f 1/1 2/2 3/3\n")
        f.write("f 1/4 2/5 3/6\n")
        f.write("f 4/7 5/7 6/7\n")              # unseen: all corners on one texel
    # Dense points: red around the unseen face, grey elsewhere.
    P = np.array([[5, 5, 0], [6, 5, 0], [5, 6, 0], [5.3, 5.3, 0], [0, 0, 0], [1, 1, 0]],
                 np.float32)
    C = np.array([[255, 0, 0]] * 4 + [[128, 128, 128]] * 2, np.uint8)
    np.save(os.path.join(folder, "points_fused.npy"), P)
    np.save(os.path.join(folder, "colors_fused.npy"), C)


print("\nT1: the unseen face gets its own cell, painted from the cloud")
with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as out:
    make(src)
    before = [sample(src, np.array(t)) for t in ((0.2, 0.2), (0.7, 0.2))]
    r = fill(src, out)
    check("one unseen face found", r["unseen_faces"] == 1, str(r))
    lines, V, VT, faces = parse(os.path.join(out, "scene_tex.obj"))
    t = VT[faces[2][2]]
    e1, e2 = t[1] - t[0], t[2] - t[0]
    check("its texture corners now span an area", abs(e1[0] * e2[1] - e1[1] * e2[0]) > 0)
    red = sample(out, t.mean(0))
    check("and the cell is red, from the points around it (BGR)",
          red[2] > 200 and red[0] < 40 and red[1] < 40, str(red))
    after = [sample(out, VT[faces[i][2]].mean(0)) for i in (0, 1)]
    check("the textured faces still sample their own colours",
          all(np.abs(a - b).max() <= 6 for a, b in zip(after, before)),
          f"{before} -> {after}")
    check("the input folder is untouched",
          open(os.path.join(src, "scene_tex.obj")).read().count("vt ") == 7)

print("\nT2: in place, the old atlas goes and the OBJ points at the new one")
with tempfile.TemporaryDirectory() as work:
    make(work)
    fill_in_place(work)
    names = sorted(os.listdir(work))
    check("one atlas left, the filled one",
          [n for n in names if "map_Kd" in n] == ["scene_tex_material_00_map_Kd_filled.jpg"],
          str(names))
    check("no temporary folder left", not any(n.startswith("fill-") for n in names), str(names))

print()
if FAILED:
    print(f"{len(FAILED)} TEST(S) FAILED: {FAILED}")
    sys.exit(1)
print("ALL PASS")
