# -*- coding: utf-8 -*-
"""
Build the console: demo/console/index.html

The three pages this replaces were a walkthrough of one prepared run. This is the
product surface instead: every run the pipeline has produced, side by side, each
one read out of its own `run_manifest.json`. Nothing on the page is re-derived
here - the verdict strings, the units, the scale status and the codes are the
manifest's, which is the whole point. A run that says "not measurable" says it on
the page too.

    python tools/build_console.py

Inputs
    out/runs/*/run_manifest.json     one per run, written by src/tesseract
    out/<run>/viewer.html            packed geometry for the runs that have a mesh
    research/calibration/*.json      per-run metric scale
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

import scale_cal                                                  # noqa: E402
from build_gallery import packed                                  # noqa: E402
from tesseract import contracts as K                              # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_DIR = os.path.join(ROOT, "out", "runs")
OUT = os.path.join(ROOT, "demo", "console")
TOOLS = os.path.dirname(os.path.abspath(__file__))

TITLE = "Tesseract - reconstruction console"
DESC = ("Every run the single-pass drone-video-to-3D pipeline has produced, read out "
        "of each run's own manifest: what it may claim, what it cannot, and why.")

# Source clips this page may not publish, by the filename the manifest records.
# A run is dropped entirely when its source is here, not merely stripped of its mesh:
# the reconstruction is derived work and carries the same rights as the footage
# (`docs/16` L-8, finding F-4). Removing only the video would leave the geometry up.
WITHHELD = {
    "yt_short.mp4": "third-party YouTube Short, rights not cleared (docs/16 F-4, B-05)",
}

# Which packed geometry belongs to which run. A run without an entry has no mesh,
# and the Model tab says so rather than showing an empty canvas.
MODELS = {
    "kolu": [
        ("kolu_mvs", "kolumvs3d", "MVS rebuild",
         "Per-pixel photometric MVS at full keyframe resolution. The feed-forward "
         "model supplied the camera poses and the metric scale, nothing else."),
        ("kolu_base", "kolu3d", "Feed-forward",
         "The feed-forward baseline: one point map per view, fused. Faster, and it "
         "paints buildings onto a sheet where the rebuild resolves them."),
    ],
}

# Per-run prose that a manifest cannot carry: why the frame is what it is, what the
# codes meant for this clip, and what the timing does and does not show.
NOTES = {
    "bahai-rejected": {
        "frame": "no frame: the run never reached geometry",
        "codes": "A temple orbit, 59 percent sky. The screener refused it and the ladder "
                 "walked down to L5, where the refusal itself is the deliverable. This is "
                 "the intended behaviour, not a crash: R-C9 asks the system to say why a "
                 "clip is hard before spending inference on it.",
        "time": "Nothing ran past the screener.",
    },
    "kolu": {
        "frame": "local level frame: gravity is up, north is not known",
        "codes": "Two shots and no GNSS sidecar. The shot boundary bounds the pass "
                 "that was used; the missing telemetry is why this run is levelled "
                 "rather than georeferenced.",
        "time": "The dense stage was adopted from an earlier run rather than "
                "recomputed, so this figure is the orchestration, not the "
                "reconstruction. The recorded reconstruction took 34m 39s.",
    },
}
SYNTH_NOTES = {
    "frame": "projected: the fit put it in a real CRS",
    "codes": "",
    "time": "A generated scene whose ground truth is known, which is how the "
            "accuracy figure above can exist at all.",
}


def sources_sha() -> str:
    """A fingerprint of the template and the stylesheet, stamped into the page.

    The console build needs out/, which is not in the repo, so CI cannot rebuild it -
    it drives the committed page instead. Without this, editing the template and
    forgetting to rebuild would sail through a green CI and ship the stale page.
    tools/test_console.py recomputes this and refuses to run if it has moved.

    Line endings are normalised first. These files are committed with LF and checked
    out with CRLF on Windows, so hashing the raw bytes makes the stamp disagree with
    itself between the machine that built the page and the runner that checks it -
    which is exactly what happened on the first CI run after this guard landed.
    """
    h = hashlib.sha256()
    for name in ("console_template.html", "console_ds.css"):
        with io.open(os.path.join(TOOLS, name), encoding="utf-8", newline="") as f:
            h.update(f.read().replace("\r\n", "\n").encode("utf-8"))
    return h.hexdigest()[:12]


def jload(p):
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def verify(rundir: str, man: dict) -> dict:
    """The same checks `tesseract verify` runs, so the page cannot claim a pass the
    CLI would not give."""
    problems = K.validate_manifest(man)
    for name, art in (man.get("artefacts") or {}).items():
        full = os.path.join(rundir, art["path"])
        if not os.path.exists(full):
            problems.append(f"{name}: missing {art['path']}")
            continue
        if art.get("sha256") and K.file_sha256(full) != art["sha256"]:
            problems.append(f"{name}: {art['path']} changed since the run")
        if art.get("units") == K.Units.METRES and \
                (man.get("scale") or {}).get("status") == "unvalidated":
            problems.append(f"{name}: claims metres on an unvalidated scale")
    return {"ok": not problems, "problems": problems}


def host_line(h) -> str:
    """The manifest records the machine as a dict; a header wants one line of it."""
    if not isinstance(h, dict):
        return str(h or "not recorded")
    plat = (h.get("platform") or "").split("-")
    return " ".join(x for x in [plat[0] if plat else None,
                                "python " + h["python"] if h.get("python") else None,
                                f"{h['cpu_count']} cpu" if h.get("cpu_count") else None]
                    if x)


def flat_facts(facts: dict) -> dict:
    """Stage facts worth a chip: scalars only. A nested dict is a whole sub-report and
    belongs in the manifest, not in a row of the timeline."""
    out = {}
    for k, v in (facts or {}).items():
        if isinstance(v, (int, float, str, bool)) and not isinstance(v, bool):
            out[k] = v
        elif isinstance(v, bool):
            out[k] = "yes" if v else "no"
    return out


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    if not os.path.isdir(RUNS_DIR):
        sys.exit("no out/runs: produce a run first (python tesseract.py run synthetic)")

    # ---- packed geometry, once per model, for the view scale the A/B toggle shares
    halves, packs = {}, {}
    wanted = {(k, run) for ms in MODELS.values() for k, run, _, _ in ms}
    for key, run in sorted(wanted):
        D, half = packed(run)
        halves[key] = half
        packs[key] = {"nt": D["nt"], "np": D["np"]}
        print(f"  mesh   {key:11} <- out/{run:11} {D['nt']:>9,} tri  {D['np']:>9,} pts"
              f"   half-extent {half:6.2f}")

    runs = []
    for rid in sorted(os.listdir(RUNS_DIR)):
        mp = os.path.join(RUNS_DIR, rid, "run_manifest.json")
        if not os.path.exists(mp):
            continue
        man = jload(mp)
        clip = man.get("source", "").split(":", 1)[-1]
        if clip in WITHHELD:
            print(f"  skip   {rid:22} {WITHHELD[clip]}")
            continue
        v = verify(os.path.join(RUNS_DIR, rid), man)
        lvl = K.LEVELS[man.get("level", "L0")]
        sc = man.get("scale") or {}
        cal = scale_cal.load(man.get("scale", {}).get("run") or rid)

        georef = next((s for s in man.get("stages", [])
                       if s["id"] == "S5-georef"), {}) or {}
        crs = (georef.get("facts") or {}).get("crs")

        note = NOTES.get(rid) or SYNTH_NOTES
        models = []
        for key, _run, label, mnote in MODELS.get(rid, []):
            models.append({"key": key, "file": key + ".js", "label": label,
                           "note": mnote, "tri": packs[key]["nt"],
                           "pts": packs[key]["np"]})
        view_scale = round(max([halves[m["key"]] for m in models], default=1.0), 4)

        runs.append({
            "id": man["run_id"],
            "source": man["source"],
            "started": (man.get("started") or "").replace("T", " ").replace("Z", ""),
            "host": host_line(man.get("host")),
            "region": man.get("region"),
            "git": man.get("git_sha"),
            "cfg": (man.get("config_sha256") or "")[:12],
            "schema": man.get("schema"),
            "seconds": round(man.get("seconds", 0.0), 2),
            "budget": man.get("budget_s", 900),
            "within": man.get("within_budget", True),
            "level": man.get("level"),
            "quality": lvl.quality,
            "ladderDesc": lvl.description,
            "frame": man.get("frame"),
            "frameNote": note["frame"],
            "units": man.get("units"),
            "geo": bool(man.get("georeferenced")),
            "crs": crs,
            "codes": man.get("codes") or [],
            "codeNote": note["codes"],
            "timeNote": note["time"],
            "scale": {
                "status": sc.get("status", "unvalidated"),
                "factor": sc.get("factor", 1.0),
                "label": sc.get("label", "unvalidated (model units)"),
                "basis": sc.get("basis") or cal.get("summary")
                         or "no external ruler for this clip",
                "bracket": cal.get("bracket"),
            },
            "verdicts": man.get("verdicts") or {},
            "stages": [{
                "id": s["id"], "sec": round(s.get("seconds", 0.0), 3),
                "skipped": bool(s.get("skipped")),
                "cached": s.get("note") == "cached",
                "note": "" if s.get("note") == "cached" else (s.get("note") or ""),
                "codes": s.get("codes") or [],
                "facts": flat_facts(s.get("facts")),
            } for s in man.get("stages", [])],
            "arts": [{"name": n, "path": a["path"], "frame": a.get("frame"),
                      "units": a.get("units"), "bytes": a.get("bytes"),
                      "sha": a.get("sha256")}
                     for n, a in sorted((man.get("artefacts") or {}).items())],
            "inputs": [{"path": i.get("path"), "bytes": i.get("bytes"),
                        "sha": i.get("sha256")}
                       for i in (man.get("inputs") or [])],
            "dense": (next((st for st in man.get("stages", [])
                             if st["id"] == "S3-geometry"), {})
                      .get("facts") or {}).get("points"),
            "verify": v,
            "models": models,
            "viewScale": view_scale,
        })

    # the run that shows the most goes first; a refusal is still worth reading, last
    order = {"kolu": 0, "demo": 1, "synthetic-rtk": 2,
             "synthetic-consumer-120": 3, "bahai-rejected": 9}
    runs.sort(key=lambda r: (order.get(r["id"], 6), r["id"]))

    git = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip() or "unknown"
    built = subprocess.run(["git", "log", "-1", "--format=%cs"], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    data = {
        "build": {"git": git, "at": built,
                  "verified": sum(1 for r in runs if r["verify"]["ok"])},
        "ladder": [[k, v.quality, v.description] for k, v in K.LEVELS.items()],
        "meshDir": "../gallery/mesh/",
        "runs": runs,
    }

    tpl = io.open(os.path.join(TOOLS, "console_template.html"), encoding="utf-8").read()
    ds = io.open(os.path.join(TOOLS, "console_ds.css"), encoding="utf-8").read()
    faces = io.open(os.path.join(OUT, "fonts", "faces.css"), encoding="utf-8").read()
    page = (tpl.replace("__TITLE__", TITLE).replace("__DESC__", DESC)
               .replace("__QA__", "../qa/").replace("__FACES__", faces)
               .replace("__SRCSHA__", sources_sha())
               .replace("__DS__", ds)
               .replace("__DATA__", json.dumps(data, separators=(",", ":"))))

    out = os.path.join(OUT, "index.html")
    with io.open(out, "w", encoding="utf-8") as f:
        f.write(page)

    check(data, page)
    print(f"\n  runs      {len(runs)}   ({data['build']['verified']} pass the contracts)")
    print(f"  models    {sum(len(r['models']) for r in runs)}")
    print(f"  written   {os.path.relpath(out, ROOT)}   "
          f"{os.path.getsize(out)/1024:.0f} KB")
    return 0


def check(data, page):
    """Guardrails on what the page is allowed to say. The first two are the ones that
    would be a real lie rather than a typo."""
    bad = []
    for r in data["runs"]:
        if r["units"] == "metres" and r["scale"]["status"] == "unvalidated":
            bad.append(f"{r['id']}: metres on an unvalidated scale")
        if r["geo"] and r["frame"] not in ("F6", "F7"):
            bad.append(f"{r['id']}: georeferenced but frame {r['frame']}")
        for k, s in r["verdicts"].items():
            if k != "scale" and not s.startswith(("met", "not met", "not measurable")):
                bad.append(f"{r['id']}: verdict {k!r} reads {s!r}")
    for ch in ("—", "–"):
        if ch in page:
            bad.append(f"page contains {ch!r}")
    if "__" in page.split("<script>")[0]:
        bad.append("an unfilled template placeholder survived")
    if bad:
        for b in bad:
            print("  !", b)
        sys.exit(f"\n  {len(bad)} problem(s); page not trustworthy")
    print("\n  checks    manifest claims, frames, verdict vocabulary, typography")


if __name__ == "__main__":
    sys.exit(main())
