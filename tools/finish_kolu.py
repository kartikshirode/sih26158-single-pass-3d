"""
Pull the reconstruction off GCS and take it all the way to a viewer.

One command, so the whole downstream half is reproducible from the raw model output
without re-running inference: filter -> fuse -> mesh -> render -> pack.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "out", "kolu_raw")
OUT = os.path.join(ROOT, "out", "kolu3d")
PY311 = r"C:\Users\Mandar\AppData\Local\Programs\Python\Python311\python.exe"


def sh(*a):
    print("  $", " ".join(str(x) for x in a[:4]), "...")
    r = subprocess.run([str(x) for x in a], capture_output=True, text=True)
    if r.stdout.strip():
        print("\n".join("    " + l for l in r.stdout.strip().splitlines()))
    if r.returncode:
        print(r.stderr[-2500:])
        sys.exit(f"failed: {a[0]}")
    return r.stdout


def main():
    os.makedirs(RAW, exist_ok=True)
    sh("gsutil", "-m", "cp", "gs://sih26158-mumbai/mapanything/kolu_out/*", RAW)

    res = json.load(open(os.path.join(RAW, "mapanything_result.json")))
    print("\nmodel run:")
    for k in ("n_views", "params_B", "load_s", "inference_s",
              "seconds_per_view_cpu", "torch_threads", "points", "bbox_extent"):
        if k in res:
            print(f"  {k:22s} {res[k]}")

    print("\nfilter / fuse / mesh:")
    log = sh(PY311, os.path.join(ROOT, "src", "pipeline", "fuse_mesh.py"), RAW, "--out", OUT)

    print("\nrender:")
    sh(PY311, os.path.join(ROOT, "src", "pipeline", "render_views.py"), OUT,
       "--out", os.path.join(OUT, "render.png"))

    # Pull the funnel numbers straight out of the stage's own log, so the viewer can
    # never disagree with what the pipeline actually printed.
    def grab(prefix):
        for line in log.splitlines():
            if line.strip().startswith(prefix):
                for tok in line.split():
                    t = tok.replace(",", "")
                    if t.isdigit():
                        return int(t)
                return line.split()[-1]
        return None

    ing = json.load(open(os.path.join(ROOT, "out", "kf_kolu", "ingest.json")))["stats"]
    stats = {
        "ingest": [
            ["frames decoded", f"{ing['frames_decoded']:,}"],
            ["shots detected", str(ing["shots_detected"])],
            ["rejected: horizon", f"{ing['rejected_horizon']:,}"],
            ["rejected: sky / flare", f"{ing['rejected_sky']:,}"],
            ["rejected: motion blur", f"{ing['rejected_blur']:,}"],
            ["keyframes", str(ing["keyframes_selected"])],
        ],
        "funnel": [
            ["raw per-view", grab("raw")],
            ["finite + valid", grab("finite")],
            ["confidence gate", grab("confidence")],
            ["outlier removal", grab("outlier")],
            ["voxel fusion", grab("voxel")],
        ],
        "geom": [
            ["model", "MapAnything (Apache)"],
            ["inference", f"{res.get('inference_s', 0):.0f} s CPU"],
            ["per view", f"{res.get('seconds_per_view_cpu', 0):.1f} s"],
        ],
        "caveat": ("<b>No GPS in this clip</b>, so the model is metric-relative, not "
                   "georeferenced. The problem statement lists GPS as a mandatory input "
                   "because without it the &le;1 m absolute requirement cannot be "
                   "measured at all."),
    }
    sp = os.path.join(OUT, "viewer_stats.json")
    json.dump(stats, open(sp, "w"), indent=1)

    print("\npack:")
    sh(PY311, os.path.join(ROOT, "tools", "build_viewer.py"), OUT,
       "--stats", sp, "--out", os.path.join(OUT, "viewer.html"))
    print("\ndone ->", OUT)


if __name__ == "__main__":
    main()
