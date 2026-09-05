"""
Push the keyframes and the notebook to Kaggle and run them, without the browser.

The Kaggle notebook EDITOR renders zero cells in this environment - reproduced on
two separate notebooks, including one whose saved version demonstrably has content -
so every browser-driven run risks saving a blank draft over a working notebook. The
API path has no such failure mode and is also reproducible, which the click path is
not.

Needs ~/.kaggle/kaggle.json (Kaggle -> Settings -> API -> Create New Token). The
token never passes through this script; the CLI reads it from disk.
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER = "mandarwagh9"
DATA_SLUG   = f"{USER}/kolu-drone-keyframes-sih26158"
KERNEL_SLUG = f"{USER}/sih26158-kolu-video-3d"
STAGE       = os.path.join(ROOT, "out", "kaggle_push")


def sh(*a, **kw):
    print("  $", " ".join(a))
    return subprocess.run(a, check=True, capture_output=True, text=True, **kw).stdout


def push_kernel():
    shutil.rmtree(STAGE, ignore_errors=True)
    os.makedirs(STAGE)
    shutil.copy(os.path.join(ROOT, "notebooks", "kaggle_video_to_3d.ipynb"),
                os.path.join(STAGE, "sih26158-kolu-video-3d.ipynb"))
    json.dump({
        "id": KERNEL_SLUG,
        "title": "SIH26158 Kolu video to 3D",
        "code_file": "sih26158-kolu-video-3d.ipynb",
        "language": "python",
        "kernel_type": "notebook",
        "is_private": True,
        "enable_gpu": True,
        "enable_internet": True,           # MapAnything weights come from HF
        "dataset_sources": [DATA_SLUG],
        "competition_sources": [],
        "kernel_sources": [],
    }, open(os.path.join(STAGE, "kernel-metadata.json"), "w"), indent=2)
    print(sh("kaggle", "kernels", "push", "-p", STAGE))


def wait(poll: int = 30, limit_s: int = 3600):
    t0 = time.time()
    while time.time() - t0 < limit_s:
        out = subprocess.run(["kaggle", "kernels", "status", KERNEL_SLUG],
                             capture_output=True, text=True).stdout.strip()
        print(f"  [{int(time.time()-t0):>5}s] {out}")
        if "complete" in out.lower() or "error" in out.lower():
            return out
        time.sleep(poll)
    return "TIMEOUT"


def pull_output(dst="out/kolu3d"):
    os.makedirs(dst, exist_ok=True)
    print(sh("kaggle", "kernels", "output", KERNEL_SLUG, "-p", dst))
    for f in sorted(os.listdir(dst)):
        print(f"  {f:28s} {os.path.getsize(os.path.join(dst,f))/1e6:8.2f} MB")


if __name__ == "__main__":
    if not os.path.exists(os.path.expanduser("~/.kaggle/kaggle.json")):
        sys.exit("Missing ~/.kaggle/kaggle.json - Kaggle > Settings > API > "
                 "Create New Token, then drop the file there.")
    push_kernel()
    print(wait())
    pull_output()
