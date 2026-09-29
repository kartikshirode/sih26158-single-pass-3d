"""Shared paths for the reproduction scripts in tools/repro (README.md there).

Every script scores on the demonstration clip's keyframes from the final clean run,
out/runs/night-b1-final, with every tenth keyframe held out of dense and texture.
"""
import os
import shutil
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUN = os.path.join(ROOT, "out", "runs", "night-b1-final")
EXP = os.path.join(ROOT, "out", "exp")
for p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "src", "pipeline"), os.path.join(ROOT, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)


def tool(env: str) -> str:
    """A tool path from the same variables the pipeline reads (SIH_COLMAP, SIH_OPENMVS)."""
    p = os.environ.get(env)
    if not p:
        raise SystemExit(f"set {env} first (see tools/repro/README.md)")
    return p


def demo_keyframes() -> str:
    """out/exp/kf: the final run's keyframes plus its ingest.json, copied once."""
    kf = os.path.join(EXP, "kf")
    if not os.path.exists(os.path.join(kf, "ingest.json")):
        shutil.copytree(os.path.join(RUN, "keyframes"), kf, dirs_exist_ok=True)
        shutil.copyfile(os.path.join(RUN, "ingest.json"), os.path.join(kf, "ingest.json"))
    return kf
