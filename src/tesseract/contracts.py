"""
The contracts every stage is held to: frames, units, artefacts, codes, manifest.

This is `docs/09-interface-contracts.md` as code. The document exists because the old
pipeline carried its agreements in prose and in habit, and two of them turned out to be
wrong in ways nothing could catch: an export frame labelled ENU whose horizontal axes
are arbitrary, and lengths printed as metres when the scale behind them was 5.5x off
(docs/08). Both are now properties an artefact carries, so a stage cannot quietly assume
either one.

Nothing here does work. It says what the work must produce.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_RUN_MANIFEST = "sih26158/run-manifest/1"
SCHEMA_STATE = "sih26158/run-state/1"

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# --------------------------------------------------------------------------- frames
class Frame:
    """Every array in the system is in exactly one of these (docs/09 section 1)."""

    F0_SOURCE_PX = "F0"        # full decoded frame, pixels
    F1_MODEL_PX = "F1"         # the model's cropped/resized grid, pixels
    F2_CAMERA = "F2"           # OpenCV camera frame, model units
    F3_MODEL_WORLD = "F3"      # feed-forward world; not gravity aligned
    F4_REFINED_WORLD = "F4"    # same gauge, bundle-adjusted
    F5_LLF = "F5"              # local level frame: gravity up, heading arbitrary
    F6_ENU = "F6"              # true east/north/up, metres, geodetic reference
    F7_PROJECTED = "F7"        # projected CRS + orthometric height

    METRIC = (F5_LLF, F6_ENU, F7_PROJECTED)

    @staticmethod
    def is_georeferenced(frame: str) -> bool:
        return frame in (Frame.F6_ENU, Frame.F7_PROJECTED)


# --------------------------------------------------------------------------- units
class Units:
    """
    What a number means. `MODEL` is the trap docs/08 documents: the reconstruction's
    own units look like metres, print like metres, and on Kolu were 5.5x too small.
    """

    MODEL = "model units"
    METRES = "metres"


SCALE_STATUS = ("unvalidated", "calibrated", "gnss", "gnss+rtk")


def units_for(scale_status: str) -> str:
    if scale_status not in SCALE_STATUS:
        raise ValueError(f"unknown scale status {scale_status!r}")
    return Units.MODEL if scale_status == "unvalidated" else Units.METRES


# --------------------------------------------------------------------------- codes
class Code:
    """Machine-readable outcomes (docs/09 section 6). An operator reads these."""

    ADM_HORIZON = "ADM-HORIZON"
    ADM_SKY = "ADM-SKY"
    ADM_SHOTS = "ADM-SHOTS"
    ADM_OVERLAY = "ADM-OVERLAY"
    ING_NOGNSS = "ING-NOGNSS"
    ING_SCHEMA = "ING-SCHEMA"
    GEO_UNREG = "GEO-UNREG"
    GEO_REPROJ = "GEO-REPROJ"
    MVS_RC = "MVS-RC"
    REF_BALLPARK = "REF-BALLPARK"
    REF_7DOF = "REF-7DOF"
    EXP_FORMAT = "EXP-FORMAT"
    STAGE_UNAVAILABLE = "STAGE-UNAVAILABLE"   # a tool or artefact this host lacks
    BUDGET = "BUDGET"                          # predicted cost exceeds what is left


class StageError(RuntimeError):
    """A stage failing in a way the orchestrator can act on."""

    def __init__(self, code: str, message: str, *, fatal: bool = False):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.fatal = fatal          # fatal => no ladder step will help


# --------------------------------------------------------------------------- ladder
@dataclass(frozen=True)
class Level:
    key: str
    label: str
    quality: str
    description: str


LADDER = (
    Level("L0", "full", "measured",
          "dense set at full resolution, mesh, texture"),
    Level("L1", "half-res", "measured, reduced resolution",
          "densify at resolution level 1 (~4x faster)"),
    Level("L2", "half-set", "measured, sparse coverage",
          "dense set halved"),
    Level("L3", "feed-forward", "coarse - patch-limited",
          "no MVS: fused feed-forward point maps (docs/05: ~14 px information floor)"),
    Level("L4", "sparse", "sparse",
          "sparse points and a DSM only"),
    Level("L5", "screen-only", "not reconstructable",
          "the admissibility report and its codes"),
)
LEVELS = {lv.key: lv for lv in LADDER}


def step_down(level: str) -> str | None:
    keys = [lv.key for lv in LADDER]
    i = keys.index(level)
    return keys[i + 1] if i + 1 < len(keys) else None


# --------------------------------------------------------------------------- artefacts
@dataclass
class Artefact:
    """
    A file a stage produced, with the two facts the old pipeline left implicit.

    `frame` and `units` travel with the data. A consumer that needs metres asserts on
    `units`; a consumer that needs a gravity-aligned frame asserts on `frame`. Neither
    is inferred from a file extension or a directory name ever again.
    """

    path: str
    kind: str
    frame: str | None = None
    units: str | None = None
    sha256: str | None = None
    bytes: int | None = None

    def stamp(self, root: str = "") -> "Artefact":
        full = os.path.join(root, self.path) if root else self.path
        if os.path.exists(full):
            self.bytes = os.path.getsize(full)
            self.sha256 = file_sha256(full)
        return self


@dataclass
class StageResult:
    stage: str
    seconds: float
    outputs: dict[str, Artefact] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)      # numbers for the manifest
    codes: list[str] = field(default_factory=list)
    skipped: bool = False
    note: str = ""


# --------------------------------------------------------------------------- hashing
def file_sha256(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def config_sha256(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def git_sha() -> str | None:
    try:
        r = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None
    except Exception:
        return None


# --------------------------------------------------------------------------- manifest
@dataclass
class RunManifest:
    """
    One file per run, the single place a reviewer looks (docs/09 section 4, R-NF3).

    It records what went in, what ran, in which frame and units the result is, and what
    the run is allowed to claim. `verdicts` is deliberately three-valued: a target can be
    met, missed, or not measurable, and the third is not a softer way of saying missed.
    """

    run_id: str
    source: str
    schema: str = SCHEMA_RUN_MANIFEST
    git_sha: str | None = field(default_factory=git_sha)
    config_sha256: str | None = None
    host: dict[str, Any] = field(default_factory=lambda: {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
    })
    region: str | None = None
    inputs: list[dict[str, Any]] = field(default_factory=list)
    stages: list[dict[str, Any]] = field(default_factory=list)
    artefacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    frame: str | None = None
    units: str | None = None
    scale: dict[str, Any] | None = None
    georeferenced: bool = False
    level: str = "L0"
    quality: str = ""
    codes: list[str] = field(default_factory=list)
    verdicts: dict[str, str] = field(default_factory=dict)
    seconds: float = 0.0
    budget_s: float = 900.0
    started: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                              time.gmtime()))

    def add(self, res: StageResult) -> None:
        self.stages.append({
            "id": res.stage, "seconds": round(res.seconds, 3),
            "skipped": res.skipped, "codes": res.codes,
            "outputs": sorted(res.outputs), "facts": res.facts,
            **({"note": res.note} if res.note else {}),
        })
        for name, art in res.outputs.items():
            self.artefacts[name] = {k: v for k, v in asdict(art).items() if v is not None}
        for c in res.codes:
            if c not in self.codes:
                self.codes.append(c)
        self.seconds += res.seconds

    def write(self, path: str) -> str:
        d = asdict(self)
        d["within_budget"] = self.seconds <= self.budget_s
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
        return path


def validate_manifest(d: dict) -> list[str]:
    """Return the problems with a manifest. Empty list means it satisfies docs/09."""
    bad = []
    if d.get("schema") != SCHEMA_RUN_MANIFEST:
        bad.append(f"schema is {d.get('schema')!r}, expected {SCHEMA_RUN_MANIFEST!r}")
    for k in ("run_id", "source", "stages", "level"):
        if not d.get(k):
            bad.append(f"missing {k}")
    if d.get("level") not in LEVELS:
        bad.append(f"unknown ladder level {d.get('level')!r}")
    sc = d.get("scale") or {}
    if sc.get("status") not in SCALE_STATUS:
        bad.append(f"scale.status is {sc.get('status')!r}")
    elif d.get("units") != units_for(sc["status"]):
        bad.append(f"units {d.get('units')!r} contradict scale status {sc['status']!r}")
    if d.get("georeferenced") and d.get("frame") not in (Frame.F6_ENU, Frame.F7_PROJECTED):
        bad.append("georeferenced=true but the frame is not F6/F7")
    if not d.get("georeferenced") and Frame.is_georeferenced(d.get("frame") or ""):
        bad.append("frame claims georeferencing but georeferenced=false")
    for st in d.get("stages", []):
        for c in st.get("codes", []):
            if not isinstance(c, str) or not c.isupper() and "-" not in c:
                bad.append(f"stage {st.get('id')}: odd code {c!r}")
    return bad


if __name__ == "__main__":
    # A contract file that cannot be inspected is a contract nobody reads.
    print("frames  :", " ".join(v for k, v in vars(Frame).items() if k.startswith("F")))
    print("ladder  :", " ".join(f"{lv.key}={lv.label}" for lv in LADDER))
    print("codes   :", " ".join(v for k, v in vars(Code).items() if k.isupper()))
    print("git     :", git_sha())
    sys.exit(0)
