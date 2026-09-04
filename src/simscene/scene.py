"""
Synthetic urban scene + single-pass flight generator for SIH26158.

Purpose: produce GROUND TRUTH without a drone, a GPU, or a public dataset.

No public dataset provides "single-pass 10-minute drone video + per-frame GPS +
ground-truth 3D model", so the only defensible route to an accuracy/completeness
number before the finale is to build a scene whose truth we know exactly, fly a
simulated single pass over it, and measure what that pass can and cannot recover.

This module is deliberately CPU-only (trimesh + numpy).

Scene contents map onto the PS's required content classes:
    R-F1 terrain/structures, R-F2 facades+rooftops, R-F3 roads, R-F4 vegetation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh


# --------------------------------------------------------------------------------------
# Scene construction
# --------------------------------------------------------------------------------------

@dataclass
class SceneSpec:
    extent: float = 400.0          # metres, half-width of the site
    n_buildings: int = 26
    building_h: tuple[float, float] = (6.0, 40.0)
    road_width: float = 12.0
    n_trees: int = 40
    terrain_relief: float = 8.0
    seed: int = 7


@dataclass
class Scene:
    mesh: trimesh.Trimesh
    labels: np.ndarray             # per-face semantic label
    spec: SceneSpec
    parts: dict = field(default_factory=dict)

    LABELS = ("terrain", "building", "road", "vegetation")

    def face_label_mask(self, name: str) -> np.ndarray:
        return self.labels == self.LABELS.index(name)

    def sample_surface(self, n: int, rng=None):
        """Uniform-area samples with labels - this is the ground-truth point cloud."""
        rng = rng or np.random.default_rng(0)
        pts, fidx = trimesh.sample.sample_surface(self.mesh, n, seed=int(rng.integers(1 << 30)))
        return np.asarray(pts), self.labels[fidx]


def _terrain(extent: float, relief: float, n: int = 60) -> trimesh.Trimesh:
    """Gently rolling ground plane as a regular grid."""
    xs = np.linspace(-extent, extent, n)
    ys = np.linspace(-extent, extent, n)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    Z = (relief * 0.5 * np.sin(X / 180.0) * np.cos(Y / 150.0)
         + relief * 0.2 * np.sin(X / 70.0 + 1.3))
    verts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    faces = []
    for i in range(n - 1):
        for j in range(n - 1):
            a, b = i * n + j, i * n + j + 1
            c, d = (i + 1) * n + j, (i + 1) * n + j + 1
            faces.append([a, c, b])
            faces.append([b, c, d])
    return trimesh.Trimesh(vertices=verts, faces=np.asarray(faces), process=False)


def _terrain_height(mesh: trimesh.Trimesh, xy: np.ndarray) -> np.ndarray:
    """Height of the terrain at given XY by nearest-vertex lookup (adequate here)."""
    from scipy.spatial import cKDTree
    tree = cKDTree(mesh.vertices[:, :2])
    _, idx = tree.query(np.atleast_2d(xy))
    return mesh.vertices[idx, 2]


def build_scene(spec: SceneSpec | None = None) -> Scene:
    """Assemble terrain + buildings + roads + trees into one labelled mesh."""
    spec = spec or SceneSpec()
    rng = np.random.default_rng(spec.seed)

    ground = _terrain(spec.extent, spec.terrain_relief)
    meshes = [ground]
    labels = [np.zeros(len(ground.faces), dtype=np.int64)]   # 0 = terrain

    # --- roads: two flat strips, slightly proud of the terrain so they are visible
    for axis in (0, 1):
        z = float(np.mean(ground.vertices[:, 2])) + 0.15
        if axis == 0:
            box = trimesh.creation.box(extents=[2 * spec.extent, spec.road_width, 0.3])
        else:
            box = trimesh.creation.box(extents=[spec.road_width, 2 * spec.extent, 0.3])
        box.apply_translation([0, 0, z])
        meshes.append(box)
        labels.append(np.full(len(box.faces), 2, dtype=np.int64))   # 2 = road

    # --- buildings: boxes on a loose grid, avoiding the road corridors
    placed = []
    tries = 0
    while len(placed) < spec.n_buildings and tries < spec.n_buildings * 60:
        tries += 1
        cx, cy = rng.uniform(-spec.extent * 0.85, spec.extent * 0.85, 2)
        if abs(cy) < spec.road_width or abs(cx) < spec.road_width:
            continue                                   # keep roads clear
        w, d = rng.uniform(12, 42, 2)
        if any(abs(cx - px) < (w + pw) / 2 + 6 and abs(cy - py) < (d + pd) / 2 + 6
               for px, py, pw, pd in placed):
            continue                                   # no overlaps
        h = float(rng.uniform(*spec.building_h))
        z0 = float(_terrain_height(ground, np.array([[cx, cy]]))[0])
        box = trimesh.creation.box(extents=[w, d, h])
        box.apply_translation([cx, cy, z0 + h / 2])
        meshes.append(box)
        labels.append(np.full(len(box.faces), 1, dtype=np.int64))   # 1 = building
        placed.append((cx, cy, w, d))

    # --- vegetation: crude tree = trunk cylinder + canopy icosphere
    for _ in range(spec.n_trees):
        cx, cy = rng.uniform(-spec.extent * 0.9, spec.extent * 0.9, 2)
        if any(abs(cx - px) < pw / 2 + 4 and abs(cy - py) < pd / 2 + 4
               for px, py, pw, pd in placed):
            continue
        z0 = float(_terrain_height(ground, np.array([[cx, cy]]))[0])
        h = float(rng.uniform(4, 11))
        r = float(rng.uniform(1.8, 3.6))
        trunk = trimesh.creation.cylinder(radius=0.28, height=h, sections=6)
        trunk.apply_translation([cx, cy, z0 + h / 2])
        crown = trimesh.creation.icosphere(subdivisions=1, radius=r)
        crown.apply_translation([cx, cy, z0 + h + r * 0.6])
        for m in (trunk, crown):
            meshes.append(m)
            labels.append(np.full(len(m.faces), 3, dtype=np.int64))  # 3 = vegetation

    combined = trimesh.util.concatenate(meshes)
    all_labels = np.concatenate(labels)
    assert len(all_labels) == len(combined.faces), "label/face mismatch"

    return Scene(mesh=combined, labels=all_labels, spec=spec,
                 parts={"n_buildings": len(placed)})


# --------------------------------------------------------------------------------------
# Flight and camera
# --------------------------------------------------------------------------------------

@dataclass
class Camera:
    width: int = 3840
    height: int = 2160
    hfov_deg: float = 84.0          # typical drone wide lens

    @property
    def fx(self) -> float:
        return (self.width / 2.0) / np.tan(np.radians(self.hfov_deg) / 2.0)

    @property
    def K(self) -> np.ndarray:
        f = self.fx
        return np.array([[f, 0, self.width / 2.0],
                         [0, f, self.height / 2.0],
                         [0, 0, 1.0]])


def single_pass(scene: Scene, n_frames: int = 600, alt: float = 110.0,
                pitch_deg: float = 90.0, heading_deg: float = 0.0,
                offset: float = 0.0):
    """
    A single straight pass across the scene - the PS's defining constraint (R-C1).

    pitch_deg: 90 = straight down (nadir); 45 = oblique.
    Returns (positions (N,3), rotations (N,3,3) cam->world).
    """
    e = scene.spec.extent
    hd = np.radians(heading_deg)
    fwd = np.array([np.cos(hd), np.sin(hd), 0.0])
    left = np.array([-np.sin(hd), np.cos(hd), 0.0])

    s = np.linspace(-e * 1.15, e * 1.15, n_frames)
    pos = s[:, None] * fwd[None, :] + offset * left[None, :]
    pos[:, 2] = alt

    # Camera looks along -Z of its own frame. Build cam->world.
    p = np.radians(pitch_deg)
    view = -(np.sin(p) * np.array([0, 0, 1.0]) + np.cos(p) * (-fwd))
    view = view / np.linalg.norm(view)
    right = np.cross(view, np.array([0, 0, 1.0]))
    if np.linalg.norm(right) < 1e-8:
        right = left.copy()
    right /= np.linalg.norm(right)
    down = np.cross(view, right)
    R = np.stack([right, down, view], axis=1)
    return pos, np.repeat(R[None, ...], n_frames, axis=0)
