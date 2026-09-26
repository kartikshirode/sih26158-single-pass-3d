"""
Tests for the rebuilt pipeline: contracts, scale, orchestrator, and one end to end.

Run:  python src/tesseract/test_tesseract.py

Written in the same style as src/eval3d/test_metrics.py - plain asserts, no framework,
and each check named for the behaviour it protects rather than the function it calls.
The ones that matter most are the two that encode findings: a run may not print metres
on an unvalidated scale (docs/08), and RTK reaches the accuracy target where consumer
GNSS cannot (EXP-05).
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from tesseract import contracts as K                                    # noqa: E402
from tesseract import scale as scale_svc                                # noqa: E402
from tesseract.contracts import (Artefact, Code, Frame, StageError,     # noqa: E402
                                 StageResult, Units)
from tesseract.pipeline import BaseStage, Context, Pipeline             # noqa: E402
from tesseract.report import render                                     # noqa: E402
from tesseract.sources import SyntheticSource                           # noqa: E402
from tesseract.stages import DEFAULT_STAGES, Ingest                     # noqa: E402

PASS = FAIL = SKIP = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"   {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}   {detail}")


def skip(name, why):
    """
    A skip is reported and counted, never silent.

    `out/` is gitignored, so the checks that need a real run cannot run on a clean
    checkout or in CI. That is acceptable; a skip that reads like a pass is not - it is
    the sky_fraction-capped-at-0.60 failure in test form.
    """
    global SKIP
    SKIP += 1
    print(f"  [SKIP] {name}   {why}")


def section(t):
    print(f"\n=== {t} ===")


# ---------------------------------------------------------------- a stage for testing
class Toy(BaseStage):
    def __init__(self, sid, produces=(), needs=(), cost=1.0, fail=None,
                 levels=("L0", "L1", "L2", "L3", "L4", "L5"), version="1"):
        super().__init__(id=sid, needs=tuple(needs), produces=tuple(produces),
                         levels=tuple(levels), version=version)
        self.cost, self.fail, self.calls = cost, fail, 0

    def estimate(self, ctx):
        return self.cost

    def execute(self, ctx):
        self.calls += 1
        if self.fail:
            raise self.fail
        outs = {}
        for p in self.produces:
            path = ctx.path(f"{p}.txt")
            with io.open(path, "w", encoding="utf-8") as f:
                f.write(f"{self.id}:{p}")
            outs[p] = Artefact(f"{p}.txt", "text").stamp(ctx.workdir)
        return StageResult(self.id, 0.0, outputs=outs, facts={f"{self.id}_ran": True})


def ctx_for(tmp, source=None, **kw):
    return Context(run_id="t", workdir=tmp, source=source or SyntheticSource(n_frames=8),
                   log=lambda *_: None, **kw)


# ---------------------------------------------------------------- T1 contracts
def t_contracts():
    section("T1: the contracts say what a number means")
    check("unvalidated scale means model units",
          K.units_for("unvalidated") == Units.MODEL)
    check("a calibrated scale means metres", K.units_for("calibrated") == Units.METRES)
    check("an unknown status is refused",
          _raises(lambda: K.units_for("probably-fine"), ValueError))

    base = {"schema": K.SCHEMA_RUN_MANIFEST, "run_id": "r", "source": "s",
            "stages": [{"id": "x"}], "level": "L0",
            "scale": {"status": "calibrated"}, "units": "metres",
            "frame": Frame.F5_LLF, "georeferenced": False}
    check("a consistent manifest validates", K.validate_manifest(base) == [])

    bad = dict(base, units=Units.METRES, scale={"status": "unvalidated"})
    check("metres on an unvalidated scale is caught",
          any("contradict" in p for p in K.validate_manifest(bad)),
          K.validate_manifest(bad)[:1])

    bad2 = dict(base, georeferenced=True)
    check("georeferenced with a local frame is caught",
          any("F6/F7" in p for p in K.validate_manifest(bad2)))

    bad3 = dict(base, frame=Frame.F7_PROJECTED)
    check("a projected frame that claims no georeferencing is caught",
          any("georeferenc" in p for p in K.validate_manifest(bad3)))

    check("the ladder steps down and then stops",
          [K.step_down(x) for x in ("L0", "L4", "L5")] == ["L1", "L5", None])


def _raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


# ---------------------------------------------------------------- T2 scale service
def t_scale():
    section("T2: the scale service, and the check that would have caught EXP-14")
    un = scale_svc.load("no-such-run-anywhere")
    check("an unknown run is unvalidated at factor 1",
          un["status"] == "unvalidated" and un["factor"] == 1.0)
    check("an unvalidated run is labelled, not silently metric",
          "model units" in scale_svc.for_page(un)["label"])

    kolu = scale_svc.load("kolumvs3d")
    if kolu["status"] == "unvalidated":
        check("kolu calibration present", False, "research/calibration/kolu.json missing")
        return
    check("kolu resolves to its measured factor",
          5.3 <= kolu["factor"] <= 5.8, f"x{kolu['factor']}")
    check("the calibration names its evidence",
          len(kolu.get("references", [])) >= 2 and kolu["source"],
          kolu["source"])

    # The real numbers: f=1450.5 px on a 1920 px frame, camera 10.59 model units up.
    # The clip demonstrably shows a four-lane highway - far more than 40 m of ground.
    pre = scale_svc.footprint_check(1450.547, 1920, 10.59, 1.0, content_span_m=40.0)
    post = scale_svc.footprint_check(1450.547, 1920, 10.59, kolu["factor"],
                                     content_span_m=40.0)
    check("the footprint check rejects the pre-calibration scale", not pre["ok"],
          f"{pre['footprint_m']:.1f} m of ground for a four-lane highway")
    check("the footprint check passes the calibrated scale", post["ok"],
          f"{post['footprint_m']:.1f} m")
    implied = scale_svc.implied_factor(1450.547, 1920, 10.59, 40.0)
    check("the implied factor from the footprint is in the right region",
          2.5 <= implied <= 6.0, f"x{implied:.2f} for a 40 m span")

    g = scale_svc.from_gnss(1.002, rtk=True, residual_m=0.09)
    check("a GNSS fit yields a gnss+rtk status", g["status"] == "gnss+rtk")


# ---------------------------------------------------------------- T3 orchestration
def t_pipeline():
    section("T3: the orchestrator caches, versions, budgets and degrades")
    tmp = tempfile.mkdtemp(prefix="tess-")
    try:
        a, b = Toy("A", produces=("x",)), Toy("B", needs=("x",), produces=("y",))
        p = Pipeline([a, b])
        man = p.run(ctx_for(tmp))
        check("a clean run executes every stage", (a.calls, b.calls) == (1, 1))
        check("the manifest validates", K.validate_manifest(json.loads(
            io.open(os.path.join(tmp, "run_manifest.json"), encoding="utf-8").read())
        ) == [], "")

        p.run(ctx_for(tmp))
        check("a second run is a no-op", (a.calls, b.calls) == (1, 1))

        a2 = Toy("A", produces=("x",), version="2")
        Pipeline([a2, b]).run(ctx_for(tmp))
        check("bumping a stage version re-runs it", a2.calls == 1)

        # wiring
        check("a stage needing what nothing produces is refused at construction",
              _raises(lambda: Pipeline([Toy("Z", needs=("ghost",))]), ValueError))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # budget -> ladder
    tmp = tempfile.mkdtemp(prefix="tess-")
    try:
        cheap = Toy("cheap", produces=("x",), cost=1.0)
        dear = Toy("dear", needs=("x",), cost=10_000.0, levels=("L0",))
        man = Pipeline([cheap, dear]).run(ctx_for(tmp, budget_s=5.0))
        check("an unaffordable stage steps the ladder down",
              man.level != "L0" and Code.BUDGET in man.codes, f"level {man.level}")
        check("the stage that could not be afforded did not run", dear.calls == 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # failure -> ladder, and fatal -> stop
    tmp = tempfile.mkdtemp(prefix="tess-")
    try:
        soft = Toy("soft", produces=("x",), fail=StageError(Code.MVS_RC, "rc=1"),
                   levels=("L0",))
        after = Toy("after", cost=0.1)
        man = Pipeline([soft, after]).run(ctx_for(tmp))
        check("a non-fatal stage failure degrades instead of crashing",
              man.level == "L1" and Code.MVS_RC in man.codes, f"level {man.level}")
        check("the run continues past the failure", after.calls == 1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # A ladder step re-plans from the top. Stages whose output does not depend on the
    # level (screen, ingest) must not redo their work, and reusing them is not a resume.
    tmp = tempfile.mkdtemp(prefix="tess-")
    try:
        first = Toy("first", produces=("x",))
        plan = Toy("plan", needs=("x",), produces=("p",))
        plan.level_sensitive = True
        soft = Toy("soft", needs=("p",), fail=StageError(Code.MVS_RC, "rc=1"),
                   levels=("L0",))
        ctx = ctx_for(tmp)
        man = Pipeline([first, plan, soft]).run(ctx)
        check("a ladder step reuses a stage that does not depend on the level",
              first.calls == 1 and man.level == "L1", f"calls {first.calls}, {man.level}")
        check("and re-runs one that does", plan.calls == 2, f"calls {plan.calls}")
        check("reuse within one run is not counted as a resumed stage", ctx.cached == [],
              str(ctx.cached))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp(prefix="tess-")
    try:
        fatal = Toy("fatal", fail=StageError(Code.REF_7DOF, "refused", fatal=True))
        after = Toy("after", cost=0.1)
        man = Pipeline([fatal, after]).run(ctx_for(tmp))
        check("a fatal refusal stops the run", after.calls == 0)
        check("the refusal is recorded as a code", Code.REF_7DOF in man.codes)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # A stage that judges accumulated facts has no inputs to key on, so a resumed run
    # would replay its old answer. It has to run every time, and the run has to know
    # which stages it did not actually time.
    tmp = tempfile.mkdtemp(prefix="tess-")
    try:
        a, judge = Toy("A", produces=("x",)), Toy("judge")
        judge.cacheable = False
        Pipeline([a, judge]).run(ctx_for(tmp))
        ctx = ctx_for(tmp)
        Pipeline([a, judge]).run(ctx)
        check("an uncacheable stage runs again on resume", judge.calls == 2)
        check("the run records which stages came from the cache", ctx.cached == ["A"],
              str(ctx.cached))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    t_resume_keys()


class _Reads(Toy):
    """A toy stage that reads a file outside the run, and says so in its key."""

    def __init__(self, sid, path, **kw):
        super().__init__(sid, **kw)
        self.src = path

    def key_extra(self, ctx):
        return io.open(self.src, encoding="utf-8").read()


def t_resume_keys():
    """Audit F-01: resume must notice every change that would change the answer."""
    tmp = tempfile.mkdtemp(prefix="tess-")
    try:
        a, b = Toy("A", produces=("x",)), Toy("B")
        Pipeline([a, b]).run(ctx_for(tmp, source=SyntheticSource(n_frames=8, seed=1)))
        Pipeline([a, b]).run(ctx_for(tmp, source=SyntheticSource(n_frames=8, seed=2)))
        check("a different source under the same run re-runs every stage",
              (a.calls, b.calls) == (2, 2), f"calls {(a.calls, b.calls)}")
        Pipeline([a, b]).run(ctx_for(tmp, source=SyntheticSource(n_frames=8, seed=2)))
        check("the same source again is still a no-op", (a.calls, b.calls) == (2, 2))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp(prefix="tess-")
    try:
        # B reads A's facts, not A's files: only the chain can tell it A changed.
        src = os.path.join(tmp, "calibration.txt")
        with io.open(src, "w", encoding="utf-8") as f:
            f.write("x5.54")
        a, b = _Reads("A", src), Toy("B")
        Pipeline([a, b]).run(ctx_for(tmp))
        with io.open(src, "w", encoding="utf-8") as f:
            f.write("x5.60")
        Pipeline([a, b]).run(ctx_for(tmp))
        check("a changed outside file re-runs its stage", a.calls == 2)
        check("and every stage after it, files or no files", b.calls == 2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # The two real stages that read outside the run directory.
    from tesseract.pipeline import State
    from tesseract.stages import Geometry, Scale

    tmp = tempfile.mkdtemp(prefix="tess-")
    old = scale_svc.CAL_DIR
    try:
        scale_svc.CAL_DIR = tmp
        cal = {"runs": ["r"], "factor": 5.54, "bracket": [5.3, 5.8],
               "status": "calibrated", "method": "known-object", "summary": "s"}
        with io.open(os.path.join(tmp, "r.json"), "w", encoding="utf-8") as f:
            json.dump(cal, f)
        ctx = ctx_for(tmp, config={"calibration_run": "r"})
        st = State(os.path.join(tmp, "state.json"))
        k1 = st.key(Scale(), ctx)
        with io.open(os.path.join(tmp, "r.json"), "w", encoding="utf-8") as f:
            json.dump(dict(cal, factor=5.60), f)
        check("recalibrating changes the scale stage's key", st.key(Scale(), ctx) != k1)
    finally:
        scale_svc.CAL_DIR = old
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp(prefix="tess-")
    try:
        np.save(os.path.join(tmp, "points_fused.npy"), np.zeros((4, 3), np.float32))
        ctx = ctx_for(tmp, config={"adopt": tmp})
        st = State(os.path.join(tmp, "state.json"))
        k1 = st.key(Geometry(), ctx)
        np.save(os.path.join(tmp, "points_fused.npy"), np.ones((4, 3), np.float32))
        check("re-running the adopted reconstruction changes the geometry key",
              st.key(Geometry(), ctx) != k1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- T3b verdicts
class _Clip:
    """A stand-in video source: the verdicts only ask whether it has a path."""
    path = "clip.mp4"


def t_verdicts():
    section("T3b: a verdict says met only about what it measured")
    from tesseract.stages import _verdict_formats, _verdict_time

    three = _verdict_formats(["ply", "las", "geotiff"])
    check("three of the six PS formats is not met (audit F-02)",
          three.startswith("not met") and "obj" in three and "fbx" in three, three)
    check("all six is met, and GLB answers the glTF row",
          _verdict_formats(["obj", "ply", "las", "geotiff", "glb", "fbx"]) == "met")

    def verdict(source, spent, facts, cached=()):
        c = Context(run_id="v", workdir=".", source=source, budget_s=900.0,
                    spent_s=spent, facts=facts, log=lambda *_: None)
        c.cached = list(cached)
        return _verdict_time(c)

    ten_min = {"screen": {"duration_s": 600.0}}
    cases = {
        "synthetic": verdict(SyntheticSource(n_frames=8), 100, {}),
        "short clip": verdict(_Clip(), 100, {"screen": {"duration_s": 52.0}}),
        "adopted": verdict(_Clip(), 100, dict(ten_min, geometry_provider="adopt")),
        "cached": verdict(_Clip(), 100, ten_min, cached=["S0-screen"]),
        "timed, inside": verdict(_Clip(), 800, ten_min),
        "timed, over": verdict(_Clip(), 1200, ten_min),
    }
    check("a synthetic scene cannot meet R-O2 (audit F-09)",
          cases["synthetic"].startswith("not measurable"), cases["synthetic"])
    check("a clip shorter than ten minutes cannot meet R-O2",
          cases["short clip"].startswith("not measurable"), cases["short clip"])
    check("adopted geometry is not timed",
          cases["adopted"].startswith("not measurable"), cases["adopted"])
    check("a resumed run's wall clock is not a measurement",
          cases["cached"].startswith("not measurable"), cases["cached"])
    check("a timed ten-minute clip is judged on its wall clock",
          cases["timed, inside"] == "met" and cases["timed, over"] == "not met",
          f"{cases['timed, inside']} / {cases['timed, over']}")
    from tesseract.stages import _verdict_coverage
    easy = {"recall_at_1m_observable": 0.95, "recall_at_1m_whole_scene": 0.40}
    cov = {
        "easy surface": _verdict_coverage(dict(easy, geometry_provider="adopt")),
        "short": _verdict_coverage({"recall_at_1m_observable": 0.60,
                                    "recall_at_1m_whole_scene": 0.30}),
        "sensed": _verdict_coverage(dict(easy, geometry_provider="sense")),
        "no truth": _verdict_coverage({}),
    }
    check("R-O4 met on the observable surface still prints the whole-scene 40% (audit F-08)",
          cov["easy surface"].startswith("met") and "whole scene 40%" in cov["easy surface"],
          cov["easy surface"])
    check("R-O4 below 90% observable is not met", cov["short"].startswith("not met"),
          cov["short"])
    check("synthetic sensing cannot meet R-O4: its coverage is the mask it was built from",
          cov["sensed"].startswith("not measurable"), cov["sensed"])
    check("no ground truth, no R-O4", cov["no truth"].startswith("not measurable"))

    vocab = ("met", "not met", "not measurable")
    check("every verdict keeps the console's three-word vocabulary",
          all(s.startswith(vocab) for s in list(cases.values()) + list(cov.values()) + [three]))


def t_level_units():
    section("T3c: a levelled length names its own unit")
    from tesseract.stages import Level

    rng = np.random.default_rng(0)
    ground = np.column_stack([rng.uniform(-50, 50, 4000), rng.uniform(-20, 20, 4000),
                              rng.normal(0, 0.05, 4000)])
    cams = np.column_stack([np.linspace(-40, 40, 20), np.zeros(20), np.full(20, 30.0)])
    for status, factor in (("unvalidated", 1.0), ("calibrated", 2.0)):
        tmp = tempfile.mkdtemp(prefix="tess-")
        try:
            np.save(os.path.join(tmp, "points.npy"), ground.astype(np.float32))
            np.save(os.path.join(tmp, "cameras.npy"), cams)
            units = K.units_for(status)
            ctx = Context(run_id="lv", workdir=tmp, source=SyntheticSource(n_frames=8),
                          facts={"scale": {"factor": factor, "status": status},
                                 "units": units},
                          artefacts={"points": Artefact("points.npy", "point-cloud")
                                     .stamp(tmp),
                                     "cameras": Artefact("cameras.npy", "array")
                                     .stamp(tmp)},
                          log=lambda *_: None)
            f = Level().execute(ctx).facts
            keys = set(f) | set(f.get("gravity", {}))
            want = "extent_m" if units == Units.METRES else "extent_model"
            metre_named = sorted(k for k in keys if k.endswith("_m"))
            if units == Units.METRES:
                check("a calibrated run reports its extent in metres",
                      want in f and abs(max(f[want]) - 200.0) < 20.0, str(f.get(want)))
            else:
                check("an unvalidated run names no length in metres (audit F-06)",
                      want in f and not metre_named, f"metre-named: {metre_named}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- T4 end to end
def t_end_to_end():
    section("T4: the whole chain on a scene whose truth we know")
    out = {}
    for gnss in ("rtk", "consumer"):
        tmp = tempfile.mkdtemp(prefix=f"tess-{gnss}-")
        try:
            src = SyntheticSource(n_frames=60, gnss=gnss, seed=7)
            ctx = Context(run_id=f"t-{gnss}", workdir=tmp, source=src,
                          config={"dense_views": 40}, log=lambda *_: None)
            man = Pipeline(DEFAULT_STAGES).run(ctx)
            d = json.loads(io.open(os.path.join(tmp, "run_manifest.json"),
                                   encoding="utf-8").read())
            out[gnss] = (man, d, ctx)
            check(f"{gnss}: the run reaches a georeferenced frame",
                  d["georeferenced"] and d["frame"] == Frame.F7_PROJECTED,
                  f"{d['frame']}, units {d['units']}")
            check(f"{gnss}: the manifest satisfies the contracts",
                  K.validate_manifest(d) == [], str(K.validate_manifest(d))[:120])
            check(f"{gnss}: every export exists and is checksummed",
                  all(os.path.exists(os.path.join(tmp, a["path"])) and a.get("sha256")
                      for n, a in d["artefacts"].items() if n.startswith("export_")))
            rep = render(d)
            check(f"{gnss}: the report states the level and the scale",
                  "Ladder level" in rep and "Scale" in rep and d["units"] in rep)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # EXP-05, reproduced through the pipeline rather than asserted in prose
    rtk_err = out["rtk"][0].stages
    get = lambda man, k: next((s["facts"].get(k) for s in man.stages
                               if k in (s.get("facts") or {})), None)
    r, c = get(out["rtk"][0], "accuracy_absolute_rmse_m"), \
        get(out["consumer"][0], "accuracy_absolute_rmse_m")
    check("RTK reaches the 1 m target where consumer GNSS cannot",
          r is not None and c is not None and r <= 1.0 < c,
          f"rtk {r} m, consumer {c} m")
    check("the verdicts follow the measurement, not the hope",
          out["rtk"][0].verdicts["R-O3 spatial accuracy"] == "met"
          and out["consumer"][0].verdicts["R-O3 spatial accuracy"] == "not met")
    check("scale comes from the fit when there is GNSS",
          out["rtk"][0].scale["status"] == "gnss+rtk")
    v = out["rtk"][0].verdicts
    check("a synthetic run does not claim the processing-time target",
          v["R-O2 processing time"].startswith("not measurable"), v["R-O2 processing time"])
    check("S6's three files do not claim the six-format target",
          v["R-O5 formats"].startswith("not met"), v["R-O5 formats"])
    check("a synthetic end-to-end run does not claim R-O4 (audit F-08)",
          v["R-O4 coverage"].startswith("not measurable") and "whole scene" in v["R-O4 coverage"],
          v["R-O4 coverage"])
    g = get(out["rtk"][0], "gravity") or {}
    up = g.get("up") or [0, 0, 1]
    check("the synthetic gauge is no longer secretly level (audit F-07)",
          abs(up[2]) < 0.999, f"recovered up {np.round(up, 3).tolist()}")
    # The flight is at 110 m. S5 measures gravity on the raw gauge (scaled 0.1-2x), so
    # a metre-named height has to come out near 110 whatever that gauge's scale was.
    h = g.get("camera_above_ground_m")
    check("S5's metre-named camera height is in metres, not the gauge's units",
          h is not None and 80.0 < h < 140.0, f"camera_above_ground_m {h}")


def t_georef_fit():
    section("T3d: a straight track gives yaw and slope; gravity gives only the roll")
    from eval3d.gnss import track_sim3, yaw_only_sim3
    from eval3d.metrics import apply_transform

    rng = np.random.default_rng(3)
    s_ = np.linspace(-450, 450, 60)
    truth_cams = np.column_stack([s_, np.zeros(60), 110 + 0.02 * s_])   # a gentle climb
    truth_scene = np.column_stack([rng.uniform(-450, 450, 3000),
                                   rng.uniform(-300, 300, 3000), rng.uniform(0, 30, 3000)])
    # The reconstruction: scaled, yawed, and levelled with a 0.7 deg error along the
    # track, the size of the ground-plane error measured on the synthetic pass.
    a, yaw, sc = np.radians(0.7), np.radians(40), 0.2
    tilt = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    Rz = np.array([[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]])
    fwd = lambda X: apply_transform(X, Rz @ tilt, np.array([5.0, -3, 2]), sc)
    src_c, src_s = fwd(truth_cams), fwd(truth_scene)
    err = lambda R, t, s: float(np.sqrt(np.mean(np.sum(
        (apply_transform(src_s, R, t, s) - truth_scene) ** 2, axis=1))))
    e_yaw, e_trk = err(*yaw_only_sim3(src_c, truth_cams)), err(*track_sim3(src_c, truth_cams))
    check("a levelling error along the track survives a yaw-only fit",
          e_yaw > 1.0, f"{e_yaw:.2f} m")
    check("the track's own slope removes it (ADR-026)", e_trk < 0.05, f"{e_trk:.4f} m")

    tmp = tempfile.mkdtemp(prefix="tess-")
    try:
        from tesseract.stages import _write_ply_f64
        P = np.array([[500000.123, 3000000.456, 210.789], [500001.5, 3000002.5, 211.0]])
        p = os.path.join(tmp, "c.ply")
        _write_ply_f64(p, P)
        raw = open(p, "rb").read()
        body = np.frombuffer(raw[raw.index(b"end_header\n") + 11:], "<f8").reshape(-1, 3)
        check("a projected PLY keeps its coordinates to the millimetre (audit F-03)",
              np.abs(body - P).max() < 1e-6, f"max diff {np.abs(body - P).max():.2e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- T5 a real run
def t_real_run():
    section("T5: the Kolu run, if it has been produced on this machine")
    d = os.path.join(K.ROOT, "out", "runs", "kolu", "run_manifest.json")
    if not os.path.exists(d):
        skip("the Kolu run (6 checks)",
             "out/runs/kolu absent - LOCAL ONLY: python tesseract.py run "
             "data/cand/kolu.webm --adopt out/kolumvs3d --calibration-run kolumvs3d")
        return
    man = json.loads(io.open(d, encoding="utf-8").read())
    check("the real run validates", K.validate_manifest(man) == [],
          str(K.validate_manifest(man))[:160])
    check("it is calibrated, not georeferenced",
          man["scale"]["status"] == "calibrated" and not man["georeferenced"],
          man["scale"]["label"])
    check("the absence of GNSS is recorded as a code", Code.ING_NOGNSS in man["codes"])
    lvl = next(s for s in man["stages"] if s["id"] == "S5b-level")
    ext = lvl["facts"]["extent_m"]
    check("the levelled extent matches the calibrated reference export",
          abs(ext[0] - 105.9) < 1.0 and abs(ext[1] - 133.5) < 1.0, str(ext))
    g = lvl["facts"]["gravity"]
    check("the vertical was checked against the roll constraint, not assumed",
          g.get("residual_roll_deg", 9) < 1.0, f"residual roll {g.get('residual_roll_deg')} deg")
    check("camera height is reported in the files' own units",
          50 < g.get("camera_above_ground_m", 0) < 70,
          f"{g.get('camera_above_ground_m')} m")

    # The horizon remedy: --horizon crop has to survive S0, or the flag the CLI
    # offers is unreachable and the clip is refused before ingest can crop it.
    v = os.path.join(K.ROOT, "out", "runs", "village", "run_manifest.json")
    rj = os.path.join(K.ROOT, "out", "runs", "village-rejected", "run_manifest.json")
    if not (os.path.exists(v) and os.path.exists(rj)):
        skip("the horizon remedy (2 checks)",
             "out/runs/village absent - LOCAL ONLY: python tesseract.py run "
             "data/cand/yt_short.mp4 --horizon crop --adopt out/ytdmvs3d "
             "--calibration-run ytdmvs3d --name village")
        return
    cropped = json.loads(io.open(v, encoding="utf-8").read())
    refused = json.loads(io.open(rj, encoding="utf-8").read())
    s0 = next(s for s in cropped["stages"] if s["id"] == "S0-screen")
    check("a croppable horizon is remedied rather than refused",
          cropped["level"] == "L0" and Code.ADM_HORIZON in cropped["codes"]
          and s0["facts"].get("remedied_by_crop") is True,
          f"{cropped['level']}, codes {cropped['codes']}")
    check("the same clip under the default policy is still refused",
          refused["level"] == "L5" and not refused.get("artefacts"),
          refused["level"])


def t_local_provider():
    section("T3e: the local GPU provider's failures step the ladder, once")
    import types
    from tesseract.stages import Geometry

    calls = []

    class SparseError(RuntimeError):
        pass

    def make(exc):
        def run(images, work, **kw):
            calls.append(sorted(kw["dense_names"]))
            raise exc
        mod = types.ModuleType("local_gpu")
        mod.SparseError, mod.run = SparseError, run
        mod.frame_order = lambda n: (int(n[3:].split("_")[0]), n)
        return mod

    tmp = tempfile.mkdtemp(prefix="tess-")
    saved = sys.modules.get("local_gpu")
    try:
        kf = os.path.join(tmp, "keyframes")
        os.makedirs(kf)
        for i in (0, 1, 2, 1000):
            open(os.path.join(kf, f"kf_{i:03d}_f{i:05d}.jpg"), "wb").close()
        with io.open(os.path.join(tmp, "ingest.json"), "w", encoding="utf-8") as f:
            json.dump({"stats": {"overlay_crop_trbl": [0, 0, 0, 0]}}, f)
        np.save(os.path.join(tmp, "dense_index.npy"), np.array([0, 3]))

        def ctx(level):
            c = ctx_for(tmp, source=_Clip(), config={"geometry": "local"}, level=level)
            c.artefacts["plan"] = Artefact("dense_index.npy", "array")
            return c

        g = Geometry()
        sys.modules["local_gpu"] = make(SparseError("S3b gate failed: 4.0 px"))
        e1 = _raises_as(lambda: g.execute(ctx("L0")))
        check("a failed S3b gate is GEO_REPROJ, not fatal",
              e1 is not None and e1.code == Code.GEO_REPROJ and not e1.fatal, repr(e1))
        check("the dense set follows the keyframes' time order, past 999",
              calls and calls[0] == ["kf_000_f00000.jpg", "kf_1000_f01000.jpg"], str(calls))
        e2 = _raises_as(lambda: g.execute(ctx("L1")))
        check("at L1 the same sparse failure is replayed, not recomputed",
              len(calls) == 1 and e2 is not None and e2.code == Code.GEO_REPROJ, str(calls))
        g2 = Geometry()
        sys.modules["local_gpu"] = make(SystemExit("principal point is 12% off"))
        e3 = _raises_as(lambda: g2.execute(ctx("L0")))
        check("a SystemExit from colmap_export becomes a StageError, not an exit",
              e3 is not None and e3.code == Code.MVS_RC, repr(e3))
        reused = []

        def dense_fails(images, work, **kw):
            reused.append(kw.get("sparse_from"))
            os.makedirs(work, exist_ok=True)
            with io.open(os.path.join(work, "local_gpu_result.json"), "w",
                         encoding="utf-8") as f:
                json.dump({"n_views": 4, "ba_gate": {"passed": True}}, f)
            raise RuntimeError("DensifyPointCloud exited 3221225477")
        g3 = Geometry()
        sys.modules["local_gpu"] = make(RuntimeError())
        sys.modules["local_gpu"].run = dense_fails
        e5 = _raises_as(lambda: g3.execute(ctx("L0")))
        e6 = _raises_as(lambda: g3.execute(ctx("L1")))
        check("a dense failure is MVS_RC and L1 reuses the poses that passed the gate",
              e5 is not None and e5.code == Code.MVS_RC and e6 is not None
              and reused[0] is None and reused[1] is not None
              and os.path.samefile(reused[1], os.path.join(tmp, "geometry")), str(reused))
        reused = []

        def dense_fails(images, work, **kw):
            reused.append(kw.get("sparse_from"))
            os.makedirs(work, exist_ok=True)
            with io.open(os.path.join(work, "local_gpu_result.json"), "w",
                         encoding="utf-8") as f:
                json.dump({"n_views": 4, "ba_gate": {"passed": True}}, f)
            raise RuntimeError("DensifyPointCloud exited 3221225477")
        g3 = Geometry()
        sys.modules["local_gpu"] = make(RuntimeError())
        sys.modules["local_gpu"].run = dense_fails
        e5 = _raises_as(lambda: g3.execute(ctx("L0")))
        e6 = _raises_as(lambda: g3.execute(ctx("L1")))
        check("a dense failure is MVS_RC and L1 reuses the poses that passed the gate",
              e5 is not None and e5.code == Code.MVS_RC and e6 is not None
              and reused[0] is None and reused[1] is not None
              and os.path.samefile(reused[1], os.path.join(tmp, "geometry")), str(reused))
        def some_unregistered(images, work, **kw):
            os.makedirs(work, exist_ok=True)
            rng = np.random.default_rng(3)
            P = np.column_stack([rng.uniform(-50, 50, (2000, 2)), rng.normal(0, 0.2, 2000)])
            np.save(os.path.join(work, "points_fused.npy"), P.astype(np.float32))
            cams = np.repeat(np.eye(4)[None], 4, 0)
            cams[:, :3, :3] = np.diag([1.0, -1.0, -1.0])      # looking straight down
            cams[:, :3, 3] = [[x, 0.0, 60.0] for x in (-30, -10, 10, 30)]
            cams[2] = np.nan
            np.save(os.path.join(work, "cameras.npy"), cams)
            return {"n_views": 4, "unregistered": ["kf_002_f00002.jpg"], "total_seconds": 1}
        sys.modules["local_gpu"] = make(RuntimeError())
        sys.modules["local_gpu"].run = some_unregistered
        r7 = Geometry().execute(ctx("L0"))
        check("views the mapper could not place are flagged GEO_UNREG, not a failure",
              Code.GEO_UNREG in r7.codes and r7.facts.get("registered_views") == 3,
              f"{r7.codes} {r7.facts.get('registered_views')}")
        from tesseract.stages import _level_basis
        B, _, _ = _level_basis(np.load(os.path.join(tmp, "points.npy")),
                               np.load(os.path.join(tmp, "cameras.npy")))
        check("levelling skips the unregistered camera's NaN row",
              np.isfinite(B).all() and abs(abs(B[1] @ [0, 0, 1.0]) - 1) < 0.05, str(B))
        c0, c1 = ctx("L0"), ctx("L1")
        for cc in (c0, c1):
            cc.facts.update(pose_views=600, dense_views=300)
        est0, est1 = Geometry().estimate(c0), Geometry().estimate(c1)
        check("the local estimate is lower at L1, whose densify now runs a level lower",
              est1 < est0, f"L0 {est0:.0f} s, L1 {est1:.0f} s")
        e4 = _raises_as(lambda: Geometry().execute(ctx("L3")))
        check("levels the provider has no mode for are STAGE_UNAVAILABLE",
              e4 is not None and e4.code == Code.STAGE_UNAVAILABLE)
    finally:
        if saved is not None:
            sys.modules["local_gpu"] = saved
        else:
            sys.modules.pop("local_gpu", None)
        shutil.rmtree(tmp, ignore_errors=True)


def _raises_as(fn):
    try:
        fn()
    except StageError as e:
        return e
    return None


def t_srt_georef():
    section("T3g: a real clip's SRT track georeferences it to F6 (GAP C-3)")
    from eval3d.gnss import geodetic_to_enu
    from eval3d.metrics import apply_transform
    from tesseract.stages import Export, Georeference, _enu_to_geodetic

    rng = np.random.default_rng(11)
    n, hd = 40, np.radians(30)
    fwd, right = np.array([np.sin(hd), np.cos(hd), 0.0]), np.array([np.cos(hd), -np.sin(hd), 0])
    s_ = np.linspace(0, 400, n)
    cams_enu = s_[:, None] * fwd + [0, 0, 100.0]
    ground = np.column_stack([rng.uniform(-150, 550, 4000), rng.uniform(-150, 550, 4000),
                              rng.uniform(0, 3, 4000)])
    # The reconstruction's gauge: rotated, scaled and shifted, as a mapper leaves it.
    a = np.radians([25, -40, 70])
    Rx = np.array([[1, 0, 0], [0, np.cos(a[0]), -np.sin(a[0])], [0, np.sin(a[0]), np.cos(a[0])]])
    Ry = np.array([[np.cos(a[1]), 0, np.sin(a[1])], [0, 1, 0], [-np.sin(a[1]), 0, np.cos(a[1])]])
    Rz = np.array([[np.cos(a[2]), -np.sin(a[2]), 0], [np.sin(a[2]), np.cos(a[2]), 0], [0, 0, 1]])
    Rf, tf_, sf = Rz @ Ry @ Rx, np.array([3.0, -7, 1]), 0.04
    down = np.array([0, 0, -1.0])
    R_cam = np.stack([right, np.cross(down, right), down], axis=1)   # x right, z down
    cams = np.repeat(np.eye(4)[None], n, 0)
    cams[:, :3, :3] = Rf @ R_cam
    cams[:, :3, 3] = apply_transform(cams_enu, Rf, tf_, sf)
    cams[7] = np.nan                                  # a view the mapper did not place
    lat, lon, h = _enu_to_geodetic(cams_enu, 28.6, 77.2, 0.0)
    tel = [{"latitude": float(la), "longitude": float(lo), "height": float(z), "flags": []}
           for la, lo, z in zip(lat, lon, cams_enu[:, 2])]
    tel[3] = {}                                       # a keyframe with no fix

    tmp = tempfile.mkdtemp(prefix="tess-")
    try:
        with io.open(os.path.join(tmp, "ingest.json"), "w", encoding="utf-8") as f:
            json.dump({"stats": {}, "telemetry": tel}, f)
        np.save(os.path.join(tmp, "points.npy"), apply_transform(ground, Rf, tf_, sf))
        np.save(os.path.join(tmp, "cameras.npy"), cams)
        c = ctx_for(tmp, source=_Clip(), facts={"has_telemetry": True})
        c.artefacts["points"] = Artefact("points.npy", "point-cloud")
        c.artefacts["cameras"] = Artefact("cameras.npy", "array")
        r = Georeference().execute(c)
        check("S5 georeferences a video with an SRT track, in F6 metres",
              not r.skipped and r.facts.get("frame") == Frame.F6_ENU
              and r.facts.get("units") == Units.METRES and r.facts.get("georeferenced"),
              r.note)
        gl = _enu_to_geodetic(ground, 28.6, 77.2, 0.0)
        want = np.asarray(geodetic_to_enu(*gl, float(lat[0]), float(lon[0]), 0.0))
        got = np.load(os.path.join(tmp, "points_geo.npy"))
        rms = float(np.sqrt(np.mean(np.sum((got - want) ** 2, axis=1))))
        check("the ground lands where the GNSS says, heights above take-off",
              rms < 0.5, f"{rms:.3f} m RMS over {len(got)} points")
        check("fixes without a pose or without a fix are left out",
              r.facts.get("gnss_fixes_used") == n - 2, str(r.facts.get("gnss_fixes_used")))
        check("the vertical is labelled for what it is",
              "take-off" in r.facts.get("vertical", ""))
        c.artefacts.update(r.outputs)
        c.facts.update(r.facts)
        e = Export().execute(c)
        import laspy
        import rasterio
        with rasterio.open(os.path.join(tmp, "export", "dsm.tif")) as ds:
            tif_crs = ds.crs
        las_crs = laspy.read(os.path.join(tmp, "export", "cloud.las")).header.parse_crs()
        check("the GeoTIFF and the LAS carry a CRS a GIS can place",
              tif_crs is not None and las_crs is not None and e.facts["frame"] == "F6",
              f"{tif_crs}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_srt_pitch_focal():
    section("T3h: the gimbal pitch undoes a focal length the mapper got wrong")
    from eval3d.gnss import geodetic_to_enu
    from eval3d.metrics import apply_transform
    from tesseract.stages import Georeference, _apply_frame_json, _enu_to_geodetic

    rng = np.random.default_rng(12)
    n, hd, pitch, k = 60, np.radians(30), np.radians(60), 1.12
    fwd = np.array([np.sin(hd), np.cos(hd), 0.0])
    up = np.array([0, 0, 1.0])
    view = np.cos(pitch) * fwd - np.sin(pitch) * up
    right = np.cross(view, up)
    right /= np.linalg.norm(right)
    R_cam = np.stack([right, np.cross(view, right), view], axis=1)   # x right, y down
    cams_enu = np.linspace(0, 500, n)[:, None] * fwd + [0, 0, 110.0]
    ground = np.column_stack([rng.uniform(-200, 700, 6000), rng.uniform(-200, 700, 6000),
                              rng.uniform(0, 3, 6000)])
    # A straight pass at one attitude cannot tell a focal length k times too long from
    # a scene stretched k times along the view axis: both reproject the same. This is
    # the model a mapper leaves with that focal length, in its own gauge.
    o = ground.mean(0)

    def stretch(X):
        return X + (k - 1) * ((X - o) @ view)[:, None] * view

    a = np.radians([-20, 35, 110])
    Rx = np.array([[1, 0, 0], [0, np.cos(a[0]), -np.sin(a[0])], [0, np.sin(a[0]), np.cos(a[0])]])
    Rz = np.array([[np.cos(a[2]), -np.sin(a[2]), 0], [np.sin(a[2]), np.cos(a[2]), 0], [0, 0, 1]])
    Ry = np.array([[np.cos(a[1]), 0, np.sin(a[1])], [0, 1, 0], [-np.sin(a[1]), 0, np.cos(a[1])]])
    Rf, tf_, sf = Rz @ Ry @ Rx, np.array([-4.0, 2, 9]), 0.03
    cams = np.repeat(np.eye(4)[None], n, 0)
    cams[:, :3, :3] = Rf @ R_cam
    cams[:, :3, 3] = apply_transform(stretch(cams_enu), Rf, tf_, sf)
    lat, lon, h = _enu_to_geodetic(cams_enu, 28.6, 77.2, 0.0)
    gl = _enu_to_geodetic(ground, 28.6, 77.2, 0.0)
    want = np.asarray(geodetic_to_enu(*gl, float(lat[0]), float(lon[0]), 0.0))

    def run(with_pitch):
        tel = [{"latitude": float(la), "longitude": float(lo), "height": float(z),
                "flags": [], **({"gb_pitch": -60.0} if with_pitch else {})}
               for la, lo, z in zip(lat, lon, cams_enu[:, 2])]
        tmp = tempfile.mkdtemp(prefix="tess-")
        try:
            with io.open(os.path.join(tmp, "ingest.json"), "w", encoding="utf-8") as f:
                json.dump({"stats": {}, "telemetry": tel}, f)
            np.save(os.path.join(tmp, "points.npy"),
                    apply_transform(stretch(ground), Rf, tf_, sf))
            np.save(os.path.join(tmp, "cameras.npy"), cams)
            c = ctx_for(tmp, source=_Clip(),
                        facts={"has_telemetry": True,
                               "local_gpu": {"focal_after_mapper_px": [1194.0]}})
            c.artefacts["points"] = Artefact("points.npy", "point-cloud")
            c.artefacts["cameras"] = Artefact("cameras.npy", "array")
            r = Georeference().execute(c)
            got = np.load(os.path.join(tmp, "points_geo.npy"))
            tf = json.load(io.open(os.path.join(tmp, "georef.json"), encoding="utf-8"))
            again = _apply_frame_json(np.load(os.path.join(tmp, "points.npy")), tf)
            return r, got, float(np.abs(again - got).max())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    r, got, drift = run(with_pitch=False)
    dz = float(np.median(got[:, 2] - want[:, 2]))
    fp = r.facts.get("focal_from_pitch") or {}
    check("without a gimbal pitch the stretch stays in and is not corrected",
          abs(dz) > 3 and not fp.get("applied"), f"ground {dz:+.2f} m, {fp.get('reason')}")
    r, got, drift = run(with_pitch=True)
    fp = r.facts.get("focal_from_pitch") or {}
    rms = float(np.sqrt(np.mean(np.sum((got - want) ** 2, axis=1))))
    check("the gimbal pitch finds the focal length's error",
          fp.get("applied") and abs(fp.get("k", 0) - k) < 0.005, str(fp))
    check("and the ground lands where it is, to centimetres", rms < 0.1,
          f"{rms:.3f} m RMS over {len(got)} points")
    check("the implied focal length is the true one",
          abs(fp.get("focal_implied_px", 0) - 1194.0 / k) < 3, str(fp.get("focal_implied_px")))
    check("georef.json reproduces points_geo, stretch included", drift < 1e-6, f"{drift:.2e}")


def t_unexpected_failure_manifest():
    section("T3i: an unexpected exception in a stage still leaves a manifest")
    with tempfile.TemporaryDirectory() as tmp:
        stages = [Toy("A", produces=["a"]),
                  Toy("B", needs=["a"], produces=["b"], fail=ValueError("empty cloud"),
                      levels=("L0",))]
        Pipeline(stages).run(ctx_for(tmp), resume=False)
        path = os.path.join(tmp, "run_manifest.json")
        check("the run still writes its manifest", os.path.isfile(path))
        if os.path.isfile(path):
            man = json.load(open(path, encoding="utf-8"))
            check("the failure is named with its exception",
                  any(s["id"] == "B" and "ValueError: empty cloud" in s.get("note", "")
                      for s in man["stages"]), str([s.get("note") for s in man["stages"]]))
            check("and carries a code", Code.STAGE_UNAVAILABLE in man["codes"])


def t_ingest_failure_manifest():
    section("T3f: an ingest rejection leaves a manifest")
    from unittest.mock import patch

    class VideoStub:
        path = "not-opened.mp4"
        telemetry = None

        def describe(self):
            return "video stub"

        def inputs(self):
            return ["video stub"]

    with tempfile.TemporaryDirectory() as tmp:
        with patch("ingest.video_ingest.ingest_video",
                   side_effect=RuntimeError("every frame rejected")):
            Pipeline([Ingest()]).run(ctx_for(tmp, source=VideoStub()), resume=False)
        path = os.path.join(tmp, "run_manifest.json")
        check("ingest failure still writes a run manifest", os.path.isfile(path))
        if os.path.isfile(path):
            man = json.load(open(path, encoding="utf-8"))
            check("ingest failure is labelled", any(
                s["id"] == "S1-ingest" and s.get("skipped") and
                "every frame rejected" in s.get("note", "") for s in man["stages"]))
            check("ingest failure has its own code", Code.ING_REJECT in man["codes"])


if __name__ == "__main__":
    print("=" * 62)
    print("tesseract - contracts, scale, orchestration, end to end")
    print("=" * 62)
    t_contracts()
    t_scale()
    t_pipeline()
    t_verdicts()
    t_level_units()
    t_georef_fit()
    t_local_provider()
    t_ingest_failure_manifest()
    t_unexpected_failure_manifest()
    t_srt_georef()
    t_srt_pitch_focal()
    t_end_to_end()
    t_real_run()
    print("\n" + "=" * 62)
    print(f"{PASS} passed, {FAIL} failed, {SKIP} skipped")
    print("=" * 62)
    sys.exit(1 if FAIL else 0)
