"""
tesseract - single-pass drone video to a metric 3D model.

    tesseract screen  <video>...                 admissibility, before any compute
    tesseract run     <video|synthetic> [opts]   the pipeline, with the ladder
    tesseract calibrate <run> --length A B M     scale from a length you know
    tesseract report  <rundir>                   the QA report for a finished run
    tesseract verify  <rundir>                   check a run against the contracts

The CLI is the product (docs/13 section 8): everything a person needs to do with the
system is one of these five verbs, and each prints what it did rather than leaving the
answer in a file.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys

from . import contracts as K
from . import scale as scale_svc
from .pipeline import Context, Pipeline
from .report import write_report
from .sources import SyntheticSource, VideoSource
from .stages import DEFAULT_STAGES


def _run_dir(name: str) -> str:
    return os.path.join(K.ROOT, "out", "runs", name)


def cmd_screen(a) -> int:
    sys.path.insert(0, os.path.join(K.ROOT, "src"))
    from ingest.screen import screen

    bad = 0
    for p in a.videos:
        v = screen(p)
        print(f"\n=== {v['file']}  [{v['verdict']}] ===")
        for k in ("resolution", "fps", "duration_s", "shots_detected", "longest_shot_s",
                  "median_sky", "horizon_frac", "static_overlay_px_frac"):
            print(f"  {k:24s} {v[k]}")
        for r in v["reasons"]:
            print(f"  ! {r}")
        bad += v["verdict"] == "REJECT"
    return 1 if bad and a.strict else 0


def cmd_run(a) -> int:
    if a.source == "synthetic":
        src = SyntheticSource(seed=a.seed, n_frames=a.frames, gnss=a.gnss)
        run_id = a.name or f"synthetic-{a.gnss}-{a.frames}"
    else:
        if not os.path.exists(a.source):
            print(f"no such video: {a.source}")
            return 2
        src = VideoSource(a.source, telemetry=a.telemetry)
        run_id = a.name or os.path.splitext(os.path.basename(a.source))[0]

    cfg = {
        "dense_views": a.dense_views,
        "region": a.region,
        "force": a.force,
        "ingest": {"target_keyframes": a.keyframes,
                   "horizon_policy": a.horizon,
                   "skip_start_s": a.skip, "end_s": a.end},
    }
    if a.adopt:
        cfg["adopt"] = a.adopt
    if a.calibration_run:
        cfg["calibration_run"] = a.calibration_run
    if a.config:
        with io.open(a.config, encoding="utf-8") as f:
            cfg.update(json.load(f))

    ctx = Context(run_id=run_id, workdir=_run_dir(run_id), source=src, config=cfg,
                  level=a.level, budget_s=a.budget)
    print(f"\n  run {run_id}   source {src.describe()}   level {a.level}   "
          f"budget {a.budget:.0f}s")
    man = Pipeline(DEFAULT_STAGES).run(ctx, resume=not a.no_resume)

    print(f"\n  level      {man.level}  ({K.LEVELS[man.level].quality})")
    print(f"  frame      {man.frame}   units {man.units}")
    if man.scale:
        print(f"  scale      {man.scale.get('label')}")
    for k, v in (man.verdicts or {}).items():
        print(f"  {k:<26} {v}")
    print(f"  wall clock {man.seconds:.1f}s of {man.budget_s:.0f}s")
    print(f"  manifest   {os.path.relpath(ctx.path('run_manifest.json'), K.ROOT)}")
    rp = write_report(ctx.workdir)
    print(f"  report     {os.path.relpath(rp, K.ROOT)}")
    return 0


def cmd_calibrate(a) -> int:
    """
    Write a calibration from a length the operator knows (docs/08 S8).

    Two points in the model and what the distance between them really is. That is the
    whole interface, because on the day the scene itself is the only ruler available.
    """
    import numpy as np

    p1, p2 = np.array(a.points[:3], float), np.array(a.points[3:], float)
    model = float(np.linalg.norm(p1 - p2))
    if model <= 0:
        print("the two points are identical")
        return 2
    factor = a.length / model
    tol = a.tolerance
    cal = {
        "schema": "sih26158/scale-calibration/1",
        "runs": [a.run] + list(a.also or []),
        "factor": round(factor, 4),
        "bracket": [round(factor * (1 - tol), 4), round(factor * (1 + tol), 4)],
        "status": "calibrated",
        "method": "known-length",
        "summary": a.what or "an operator-supplied known length",
        "references": [{"object": a.what or "known length", "model_m": round(model, 4),
                        "real_m": [a.length], "source": a.source or "operator"}],
        "measured_by": "tesseract calibrate",
        "date": __import__("time").strftime("%Y-%m-%d"),
    }
    out = os.path.join(K.ROOT, "research", "calibration", f"{a.run}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with io.open(out, "w", encoding="utf-8") as f:
        json.dump(cal, f, indent=2)
    print(f"  {model:.4f} model units = {a.length} m  ->  x{factor:.3f} "
          f"(±{tol:.0%})\n  wrote {os.path.relpath(out, K.ROOT)}")
    print("  re-run the pipeline (or the demo build) to apply it")
    return 0


def cmd_report(a) -> int:
    p = write_report(a.rundir)
    print(io.open(p, encoding="utf-8").read())
    return 0


def cmd_verify(a) -> int:
    """Check a finished run against the contracts. This is what a gate calls."""
    mp = os.path.join(a.rundir, "run_manifest.json")
    if not os.path.exists(mp):
        print(f"no run_manifest.json in {a.rundir}")
        return 2
    with io.open(mp, encoding="utf-8") as f:
        man = json.load(f)
    problems = K.validate_manifest(man)

    # artefacts must still be there, and still be what the manifest says they are
    for name, art in man.get("artefacts", {}).items():
        full = os.path.join(a.rundir, art["path"])
        if not os.path.exists(full):
            problems.append(f"{name}: missing {art['path']}")
            continue
        if art.get("sha256") and K.file_sha256(full) != art["sha256"]:
            problems.append(f"{name}: {art['path']} changed since the run")
        if art.get("units") == K.Units.METRES and (man.get("scale") or {}) \
                .get("status") == "unvalidated":
            problems.append(f"{name}: claims metres on an unvalidated scale")
    for p in problems:
        print("  !", p)
    print(f"\n  {'FAIL' if problems else 'PASS'} - {len(problems)} problem(s) in "
          f"{os.path.basename(a.rundir)}")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tesseract", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("screen", help="admissibility verdict for one or more clips")
    s.add_argument("videos", nargs="+")
    s.add_argument("--strict", action="store_true", help="exit 1 if any clip is rejected")
    s.set_defaults(fn=cmd_screen)

    r = sub.add_parser("run", help="run the pipeline")
    r.add_argument("source", help="a video path, or the word 'synthetic'")
    r.add_argument("--name")
    r.add_argument("--telemetry", help="SRT/CSV sidecar")
    r.add_argument("--adopt", help="out/<run> whose geometry to adopt")
    r.add_argument("--calibration-run", help="which calibration file applies")
    r.add_argument("--level", default="L0", choices=[lv.key for lv in K.LADDER])
    r.add_argument("--budget", type=float, default=900.0)
    r.add_argument("--keyframes", type=int, default=600)
    r.add_argument("--dense-views", type=int, default=300)
    r.add_argument("--horizon", default="reject", choices=["reject", "crop"])
    r.add_argument("--skip", type=float, default=0.0)
    r.add_argument("--end", type=float, default=None)
    r.add_argument("--frames", type=int, default=240, help="synthetic: flight frames")
    r.add_argument("--gnss", default="consumer", choices=["consumer", "sbas", "rtk"])
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--region", default=None, help="records where this ran (R-NF8)")
    r.add_argument("--config", help="JSON file merged into the run config")
    r.add_argument("--force", action="store_true", help="run even if screening rejects")
    r.add_argument("--no-resume", action="store_true")
    r.set_defaults(fn=cmd_run)

    c = sub.add_parser("calibrate", help="write a scale calibration from a known length")
    c.add_argument("run")
    c.add_argument("--points", type=float, nargs=6, required=True,
                   metavar=("X1", "Y1", "Z1", "X2", "Y2", "Z2"))
    c.add_argument("--length", type=float, required=True, help="the true distance, m")
    c.add_argument("--what", help="what was measured, e.g. 'lane width'")
    c.add_argument("--source", help="where the true length comes from")
    c.add_argument("--also", nargs="*", help="other runs sharing this frame")
    c.add_argument("--tolerance", type=float, default=0.05)
    c.set_defaults(fn=cmd_calibrate)

    q = sub.add_parser("report", help="print the QA report for a run")
    q.add_argument("rundir")
    q.set_defaults(fn=cmd_report)

    v = sub.add_parser("verify", help="check a run against the contracts")
    v.add_argument("rundir")
    v.set_defaults(fn=cmd_verify)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
