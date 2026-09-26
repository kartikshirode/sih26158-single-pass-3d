"""
The textured mesh from S3 in the export frame, as OBJ, GLB and FBX (R-O5).

OpenMVS TextureMesh writes geometry/scene_tex.obj in the reconstruction's own frame
(F4). The cloud leaves S5b levelled and scaled (F5), or S5 georeferenced (F6), so the mesh
gets the same transform, read from level.json or georef.json rather than refitted, and
the three files overlay the PLY and LAS of the same run.

  OBJ  vertices rewritten, UVs and faces copied line for line; a clean MTL (OpenMVS
       writes `Tr 1`, which some readers take as fully transparent)
  GLB  trimesh, with the atlas embedded. glTF is Y-up, so Z-up is turned to Y-up
  FBX  assimp (BSD-3) through pyassimp, from a Y-up copy of the OBJ. The library is
       found through SIH_ASSIMP (its folder or the DLL), else on PATH. No FBX without it
"""
from __future__ import annotations

import os
import shutil

import numpy as np


def to_frame(V: np.ndarray, basis_rows: np.ndarray, origin: np.ndarray,
             scale: float) -> np.ndarray:
    """F4 to F5 exactly as S5b does it: rows [e1, up, e2], reordered to Z up."""
    return ((np.asarray(V, np.float64) - origin) @ np.asarray(basis_rows).T)[:, [0, 2, 1]] \
        * scale


def z_up_to_y_up(V: np.ndarray) -> np.ndarray:
    return np.column_stack([V[:, 0], V[:, 2], -V[:, 1]])


def _read(obj: str):
    lines = open(obj, encoding="utf-8", errors="replace").read().splitlines()
    vi = [i for i, ln in enumerate(lines) if ln.startswith("v ")]
    V = np.array([ln.split()[1:4] for ln in (lines[i] for i in vi)], np.float64)
    mtl = next((ln.split(None, 1)[1].strip() for ln in lines if ln.startswith("mtllib")),
               None)
    tex = None
    if mtl and os.path.isfile(os.path.join(os.path.dirname(obj), mtl)):
        for ln in open(os.path.join(os.path.dirname(obj), mtl), encoding="utf-8"):
            if ln.strip().startswith("map_Kd"):
                tex = os.path.join(os.path.dirname(obj), ln.split(None, 1)[1].strip())
    return lines, vi, V, tex


def _write(path: str, lines: list, vi: list, V: np.ndarray, mtl: str | None):
    rows = iter(V)
    at = set(vi)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for i, ln in enumerate(lines):
            if i in at:
                x, y, z = next(rows)
                f.write(f"v {x:.5f} {y:.5f} {z:.5f}\n")
            elif ln.startswith("mtllib"):
                if mtl:
                    f.write(f"mtllib {mtl}\n")
            else:
                f.write(ln + "\n")


def _assimp():
    """pyassimp with the assimp library loaded, or None and why not."""
    where = os.environ.get("SIH_ASSIMP")
    if where:
        d = where if os.path.isdir(where) else os.path.dirname(where)
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    try:
        import pyassimp
        return pyassimp, None
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:          # ImportError, or AssimpError (a BaseException)
        return None, f"fbx: no assimp library ({type(e).__name__}); set SIH_ASSIMP"


def export_textured(obj: str, out: str, transform) -> tuple[dict, list]:
    """
    Write model.obj/.mtl/_Kd.jpg, model.glb and model.fbx into `out`. `transform`
    maps the OBJ's F4 vertices (N, 3) into the export frame, Z up.
    """
    os.makedirs(out, exist_ok=True)
    lines, vi, V, tex = _read(obj)
    F5 = np.asarray(transform(V), np.float64)
    paths, notes = {}, []

    mtl = None
    if tex and os.path.isfile(tex):
        shutil.copyfile(tex, os.path.join(out, "model_Kd" + os.path.splitext(tex)[1]))
        mtl = "model.mtl"
        with open(os.path.join(out, mtl), "w", encoding="utf-8", newline="\n") as f:
            f.write("newmtl material_00\nKa 1 1 1\nKd 1 1 1\nKs 0 0 0\nd 1\nillum 1\n"
                    f"map_Kd model_Kd{os.path.splitext(tex)[1]}\n")
    else:
        notes.append("mesh has no texture atlas; exported untextured")
    _write(os.path.join(out, "model.obj"), lines, vi, F5, mtl)
    paths["obj"] = os.path.join(out, "model.obj")

    try:
        import trimesh
        m = trimesh.load(paths["obj"], force="mesh", process=False)
        m.vertices = z_up_to_y_up(np.asarray(m.vertices))
        m.export(os.path.join(out, "model.glb"))
        paths["glb"] = os.path.join(out, "model.glb")
    except Exception as e:
        notes.append(f"glb failed: {type(e).__name__}: {e}"[:200])

    pa, why = _assimp()
    if pa is None:
        notes.append(why)
    else:
        yup = os.path.join(out, "_model_yup.obj")
        try:
            _write(yup, lines, vi, z_up_to_y_up(F5), mtl)
            with pa.load(yup) as scene:
                pa.export(scene, os.path.join(out, "model.fbx"), file_type="fbx")
            paths["fbx"] = os.path.join(out, "model.fbx")
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as e:      # pyassimp raises AssimpError, a BaseException
            notes.append(f"fbx failed: {type(e).__name__}: {e}"[:200])
        finally:
            if os.path.exists(yup):
                os.remove(yup)
    return paths, notes
