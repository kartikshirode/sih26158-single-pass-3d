"""
Where a run's input comes from, and what it can honestly promise.

Two sources, because the project has exactly two kinds of input and they support
different claims:

  SyntheticSource   a scene whose ground truth we know exactly. Valid for
                    georeferencing, CRS and geoid handling, scoring, timing and
                    coverage geometry - and NOT for judging a learned model, because
                    the domain gap to real imagery is too wide (EXP-10). It is what
                    lets the whole chain be tested in seconds with no GPU.

  VideoSource       a real clip. Everything downstream is then as good as the clip:
                    no GNSS means no georeferencing, and no ruler means no metres.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from . import contracts as K


@dataclass
class Source:
    def describe(self) -> str:                       # pragma: no cover - interface
        raise NotImplementedError

    def inputs(self) -> list[dict[str, Any]]:        # pragma: no cover - interface
        raise NotImplementedError


@dataclass
class VideoSource(Source):
    """A real video file, optionally with a telemetry sidecar."""

    path: str
    telemetry: str | None = None

    def describe(self) -> str:
        return f"video:{os.path.basename(self.path)}"

    def inputs(self) -> list[dict[str, Any]]:
        out = []
        for p in (self.path, self.telemetry):
            if p and os.path.exists(p):
                out.append({"path": os.path.relpath(p, K.ROOT).replace(os.sep, "/"),
                            "bytes": os.path.getsize(p), "sha256": K.file_sha256(p)})
            elif p:
                out.append({"path": p, "missing": True})
        return out


@dataclass
class SyntheticSource(Source):
    """
    A single-pass flight over a known scene, with a physically-motivated GNSS error.

    Every number it hands downstream is one we can score against, which is the point:
    the orchestrator, the ladder, the georeferencing and the manifest can all be
    exercised end to end in seconds, on any machine, with no model and no GPU.
    """

    seed: int = 7
    n_frames: int = 240
    pitch_deg: float = 60.0
    gnss: str = "consumer"                 # consumer | sbas | rtk
    site: tuple[float, float, float] = (28.6139, 77.2090, 250.0)
    _cache: dict[str, Any] = field(default_factory=dict, repr=False)

    def describe(self) -> str:
        return f"synthetic:seed={self.seed},frames={self.n_frames},gnss={self.gnss}"

    def inputs(self) -> list[dict[str, Any]]:
        return [{"path": "(synthetic)", "seed": self.seed, "frames": self.n_frames,
                 "gnss_class": self.gnss, "pitch_deg": self.pitch_deg}]

    # ---- the world, built once per process
    def world(self) -> dict[str, Any]:
        if self._cache:
            return self._cache
        import sys

        import numpy as np
        sys.path.insert(0, os.path.join(K.ROOT, "src"))
        import trimesh
        from eval3d.gnss import (CONSUMER_GNSS, RTK_GNSS, SBAS_GNSS,
                                 simulate_gnss_error)
        from simscene.scene import Camera, SceneSpec, build_scene, single_pass

        spec = {"consumer": CONSUMER_GNSS, "sbas": SBAS_GNSS, "rtk": RTK_GNSS}[self.gnss]
        rng = np.random.default_rng(self.seed)
        scene = build_scene(SceneSpec(seed=self.seed))
        pos, R = single_pass(scene, n_frames=self.n_frames, alt=110.0,
                             pitch_deg=self.pitch_deg)
        gps = pos + simulate_gnss_error(self.n_frames, 600.0 / self.n_frames, spec, rng)
        # 2% wild fixes, as real receivers produce (R-C5)
        nbad = max(1, int(self.n_frames * 0.02))
        gps[rng.choice(self.n_frames, nbad, replace=False)] += rng.normal(0, 25.0, (nbad, 3))

        gt, gt_fidx = trimesh.sample.sample_surface(scene.mesh, 60_000, seed=1)
        occ, _ = trimesh.sample.sample_surface(scene.mesh, 400_000, seed=2)
        self._cache = {
            "scene": scene, "pos": pos, "R": R, "gps": gps, "cam": Camera(),
            "gt": np.asarray(gt), "gt_fidx": gt_fidx, "occ": np.asarray(occ),
            "gnss_spec": spec, "rng": rng, "site": self.site,
        }
        return self._cache
