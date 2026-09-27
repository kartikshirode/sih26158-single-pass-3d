"""Checks for texture_level.py on small synthetic meshes. Run: python src/pipeline/test_texture_level.py"""

import os
import shutil
import sys
import tempfile

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import texture_level as T  # noqa: E402

N = 4            # quads per side of the grid, about the size of a real patch
S = 48           # texels per quad side
W = H = 256
ORIGIN = {"L": (16, 32), "R": (144, 32), "ALL": (16, 32)}
FAILS = []


def check(ok, msg):
    print(("PASS: " if ok else "FAIL: ") + msg)
    if not ok:
        FAILS.append(msg)


def scene(X, Y):
    """Smooth ground truth colour (BGR) at grid position (X, Y)."""
    return np.stack([80 + 6 * X + 3 * Y, 120 - 4 * X + 5 * Y, 60 + 2 * X + 2 * Y], -1)


def island(p):
    """Grid columns of patch p and the texel position of grid point (i, j)."""
    i0, i1 = (0, N // 2) if p == "L" else (N // 2, N) if p == "R" else (0, N)
    ox, oy = ORIGIN[p]
    return i0, i1, lambda i, j: (ox + (i - i0) * S, oy + (N - j) * S)


def paint(img, p, offset):
    """Paint patch p's island and a 4 texel margin with scene + offset(X, Y)."""
    i0, i1, _ = island(p)
    ox, oy = ORIGIN[p]
    ys, xs = np.mgrid[oy - 4:oy + N * S + 5, ox - 4:ox + (i1 - i0) * S + 5]
    X = np.clip(i0 + (xs - ox) / S, i0, i1)
    Y = np.clip(N - (ys - oy) / S, 0, N)
    img[ys, xs] = np.clip(np.rint(scene(X, Y) + offset(X, Y)), 0, 255)


def write_mesh(d, split, offsets, materials=False, fmt=".png"):
    """
    An N x N grid of quads in the plane z = 0. split=True cuts it into a left and a right
    patch with separate texture islands (one atlas, or one per material); split=False
    keeps one island. offsets[p](X, Y) is added to the scene colour of patch p.
    """
    os.makedirs(d, exist_ok=True)
    patches = ["L", "R"] if split else ["ALL"]
    lines = ["mtllib scene_tex.mtl"]
    for j in range(N + 1):
        for i in range(N + 1):
            lines.append(f"v {i:.1f} {j:.1f} 0.0")
    vt, faces = [], {p: [] for p in patches}
    for j in range(N):
        for i in range(N):
            p = patches[0] if not split else ("L" if i < N // 2 else "R")
            _, _, px = island(p)
            for tri in (((i, j), (i + 1, j), (i + 1, j + 1)), ((i, j), (i + 1, j + 1), (i, j + 1))):
                f = []
                for a, b in tri:
                    x, y = px(a, b)
                    vt.append((x / (W - 1), 1 - y / (H - 1)))
                    f.append((b * (N + 1) + a + 1, len(vt)))
                faces[p].append(f)
    lines += [f"vt {u:.8f} {v:.8f}" for u, v in vt]
    mats = {p: ("mat_" + p if materials else "material_00") for p in patches}
    for p in patches:
        lines.append("usemtl " + mats[p])
        lines += ["f " + " ".join(f"{a}/{b}" for a, b in f) for f in faces[p]]
    with open(os.path.join(d, "scene_tex.obj"), "w", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    images = {}
    for p in patches:
        name = f"scene_tex_{mats[p]}_map_Kd{fmt}"
        img = images.setdefault(name, np.full((H, W, 3), 40, np.uint8))
        paint(img, p, offsets.get(p, lambda X, Y: 0))
    for name, img in images.items():
        cv2.imwrite(os.path.join(d, name), img)
    with open(os.path.join(d, "scene_tex.mtl"), "w", newline="\n") as fh:
        for m in dict.fromkeys(mats.values()):
            fh.write(f"newmtl {m}\nKd 1 1 1\nmap_Kd scene_tex_{m}_map_Kd{fmt}\n")
    return mats


def seam_step(d, mats):
    """Mean absolute RGB step across the cut at X = N / 2, sampled along the seam."""
    Y = np.linspace(0.05, N - 0.05, 60)
    sides = []
    for p, dx in (("L", -0.25), ("R", 0.25)):
        img = cv2.imread(os.path.join(d, f"scene_tex_{mats[p]}_map_Kd.png"))
        _, _, px = island(p)
        x0, _ = px(N // 2, 0)
        pts = np.column_stack([np.full_like(Y, x0 + dx), ORIGIN[p][1] + (N - Y) * S])
        sides.append(T.bilinear(img, pts))
    return float(np.abs(sides[0] - sides[1]).mean())


tmp = tempfile.mkdtemp(prefix="level-test-")
try:
    # 1. Constant and linear offsets between two patches are removed to within 1 level.
    # The default pull toward zero keeps about 5% of a step on a patch this large, so
    # the exact check uses a weaker pull and the default is checked for 90% removed.
    cases = {
        "constant": {"R": lambda X, Y: np.stack([30 + 0 * X, -20 + 0 * X, 12 + 0 * X], -1)},
        "linear": {"R": lambda X, Y: np.stack([10 + 3 * Y, -6 - 2 * Y, 4 + Y], -1)},
    }
    for label, off in cases.items():
        src, dst = os.path.join(tmp, label), os.path.join(tmp, label + "_out")
        mats = write_mesh(src, True, off)
        before = seam_step(src, mats)
        rep = T.level(src, dst, pull=0.01)
        after = seam_step(dst, mats)
        T.level(src, dst + "_default")
        default = seam_step(dst + "_default", mats)
        check(default <= 0.1 * before,
              f"{label} offset at the default pull: {before:.2f} -> {default:.2f} levels")
        check(rep["patches"] == 2, f"{label}: two patches found ({rep['patches']})")
        check(before > 10 and after <= 1.0,
              f"{label} offset: seam step {before:.2f} -> {after:.2f} levels (<= 1)")
        check(open(os.path.join(src, "scene_tex.obj")).read()
              == open(os.path.join(dst, "scene_tex.obj")).read(), f"{label}: OBJ unchanged")

    # 2. A mesh with no seam is left unchanged.
    src, dst = os.path.join(tmp, "one"), os.path.join(tmp, "one_out")
    mats = write_mesh(src, False, {})
    rep = T.level(src, dst)
    a = cv2.imread(os.path.join(src, "scene_tex_material_00_map_Kd.png"))
    b = cv2.imread(os.path.join(dst, "scene_tex_material_00_map_Kd.png"))
    check(rep["patches"] == 1 and np.array_equal(a, b), "no seam: one patch, atlas unchanged")

    # 3. Two materials keep both atlases, and the seam between them is levelled.
    src, dst = os.path.join(tmp, "two"), os.path.join(tmp, "two_out")
    mats = write_mesh(src, True, cases["constant"], materials=True)
    before = seam_step(src, mats)
    rep = T.level(src, dst, pull=0.01)
    names = sorted(x for x in os.listdir(dst) if x.endswith(".png"))
    check(names == ["scene_tex_mat_L_map_Kd.png", "scene_tex_mat_R_map_Kd.png"],
          f"two materials: both atlases written ({names})")
    check(open(os.path.join(src, "scene_tex.mtl")).read()
          == open(os.path.join(dst, "scene_tex.mtl")).read(), "two materials: MTL unchanged")
    after = seam_step(dst, mats)
    check(after <= 1.0, f"two materials: seam step {before:.2f} -> {after:.2f} levels")

    # 4. Faces texture_fill moved into its strip are not anchors and keep their colours.
    import texture_fill  # noqa: E402
    src = os.path.join(tmp, "fill_in")
    mats = write_mesh(src, True, cases["constant"], fmt=".jpg")
    lines = open(os.path.join(src, "scene_tex.obj")).read().splitlines()
    k = next(i for i, ln in enumerate(lines) if ln.startswith("f "))
    first_vt = int(lines[k].split()[1].split("/")[1])
    lines[k] = "f " + " ".join(f"{p.split('/')[0]}/{first_vt}" for p in lines[k].split()[1:])
    with open(os.path.join(src, "scene_tex.obj"), "w", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")                  # one face with no photo
    np.save(os.path.join(src, "points_fused.npy"), np.array([[0.0, 0, 0], [1, 1, 0], [0, 1, 0]]))
    np.save(os.path.join(src, "colors_fused.npy"), np.full((3, 3), 250, np.uint8))
    filled = os.path.join(tmp, "fill")
    texture_fill.fill(src, filled)
    rep = T.level(filled, os.path.join(tmp, "fill_out"))
    atlas = [x for x in os.listdir(filled) if x.endswith("_filled.jpg")][0]
    a = cv2.imread(os.path.join(filled, atlas)).astype(int)
    b = cv2.imread(os.path.join(tmp, "fill_out", atlas)).astype(int)
    check(rep["fill_faces"] == 1 and rep["fill_strip_top_row"] == {0: H},
          f"fill strip found at row {rep['fill_strip_top_row']}, {rep['fill_faces']} face")
    strip = np.abs(a[H:] - b[H:])
    check(strip.mean() <= 0.5 and strip.max() <= 6,
          f"fill strip kept (mean change {strip.mean():.2f}, largest {strip.max()}, "
          "both JPEG re-encoding)")
    check(np.abs(a[:H] - b[:H]).max() > 5, "photo patches above the strip were levelled")

    # 5. level_in_place replaces the atlas in the work folder and leaves no temp folder.
    work = os.path.join(tmp, "work")
    shutil.copytree(os.path.join(tmp, "constant"), work)
    rep = T.level_in_place(work, pull=0.01)
    mats = {"L": "material_00", "R": "material_00"}
    left = sorted(os.listdir(work))
    check(seam_step(work, mats) <= 1.0 and not any(x.startswith("level-") for x in left),
          f"in place: seam levelled, folder holds {left}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if FAILS:
    print(f"{len(FAILS)} check(s) failed")
    sys.exit(1)
print("all texture_level checks passed")
