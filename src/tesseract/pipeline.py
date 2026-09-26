"""
The orchestrator: a stage DAG with resume, a cost budget, and the degradation ladder.

Three rules from docs/13, and each one exists because of something that happened:

  Every stage is a pure function of its inputs.  A run that dies in densification after
  32 minutes should not re-do ingest and pose. Outputs are content-addressed, so a
  re-run with the same inputs does no work and says so.

  Always return something labelled.  A budget overrun or a missing tool steps DOWN the
  ladder (L0 -> L5) instead of ending in a traceback. The level is written into the
  manifest and onto every output, because "coarse, patch-limited" and "measured" must
  never look alike.

  The orchestrator knows nothing about geometry.  It schedules, caches, budgets and
  records. Every claim about the world is made by a stage and carried in its facts.
"""

from __future__ import annotations

import io
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from . import contracts as K
from .contracts import Artefact, Code, LEVELS, RunManifest, StageError, StageResult


# --------------------------------------------------------------------------- context
@dataclass
class Context:
    """What a stage is given: where to work, what it may assume, what came before."""

    run_id: str
    workdir: str
    source: Any                                   # sources.Source
    config: dict[str, Any] = field(default_factory=dict)
    level: str = "L0"
    budget_s: float = 900.0
    spent_s: float = 0.0
    artefacts: dict[str, Artefact] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)
    # Stages this invocation took from the cache. A cached stage adds 0 s to spent_s, so
    # a resumed run's wall clock is not a measurement of the pipeline (audit F-09).
    cached: list[str] = field(default_factory=list)
    log: Callable[[str], None] = print

    def path(self, *parts: str) -> str:
        p = os.path.join(self.workdir, *parts)
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        return p

    def remaining(self) -> float:
        return max(0.0, self.budget_s - self.spent_s)

    def need(self, name: str) -> Artefact:
        if name not in self.artefacts:
            raise StageError(Code.STAGE_UNAVAILABLE,
                             f"no upstream artefact {name!r}", fatal=True)
        return self.artefacts[name]


class Stage(Protocol):
    id: str
    version: str
    needs: tuple[str, ...]
    produces: tuple[str, ...]
    levels: tuple[str, ...]          # ladder levels at which this stage runs

    def estimate(self, ctx: Context) -> float: ...
    def key_extra(self, ctx: Context) -> Any: ...
    def run(self, ctx: Context) -> StageResult: ...


@dataclass
class BaseStage:
    """Defaults every stage shares. Subclasses override `execute`."""

    id: str = "stage"
    # Bump when a stage's behaviour changes. The cache key includes it, so editing a
    # stage invalidates its own cached outputs - without this, a code change is
    # silently ignored on a resumed run, which is the worst kind of stale result.
    version: str = "1"
    needs: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    levels: tuple[str, ...] = ("L0", "L1", "L2", "L3", "L4", "L5")
    # A stage that reads the run's accumulated facts rather than declared artefacts
    # cannot be keyed on its inputs, so it must run every time or it replays an old
    # answer about new facts. S8 is the case: its key would be only its config.
    cacheable: bool = True
    # Only a stage whose output depends on the ladder level keys on it. Keying every
    # stage on it made each ladder step re-run S0 and S1 from scratch: on a 20 s clip
    # that stepped L0 to L5, four of five ingest passes (about 90 of 124 s) repeated
    # identical work, and on a 10-minute clip each repeat is minutes of R-O2's budget.
    level_sensitive: bool = False

    def estimate(self, ctx: Context) -> float:
        return 1.0

    def key_extra(self, ctx: Context) -> Any:
        """
        Anything outside the run directory that this stage reads, as JSON-able data.

        The cache key sees declared artefacts, config, the source and the stages
        upstream. A stage that also reads a file of its own choosing (a calibration, an
        adopted run) must report that file's content here, or a changed file is
        silently ignored on resume.
        """
        return None

    def execute(self, ctx: Context) -> StageResult:      # pragma: no cover - abstract
        raise NotImplementedError

    def run(self, ctx: Context) -> StageResult:
        t0 = time.perf_counter()
        res = self.execute(ctx)
        res.seconds = time.perf_counter() - t0
        res.stage = self.id
        return res


# --------------------------------------------------------------------------- state
class State:
    """
    The resume record: which stages ran, with what key, and what they produced.

    The key is the stage id, version, config (and the level, for a stage whose
    output depends on it), the hashes of its declared
    inputs, the source's own fingerprint, whatever else the stage says it reads
    (`key_extra`), and the key of the stage before it. Change a threshold and only the
    stages downstream of it re-run; change nothing and the whole pipeline is a no-op
    that still writes a manifest.

    The source and the chain were added after audit F-01. Without the source, a
    different clip under the same run name resumed on the old clip's keyframes, since
    S0 and S1 declare no inputs. Without the chain, a stage that reads an upstream
    stage's facts rather than its files (S5b reads S4's scale factor) kept its old
    output after a recalibration. The chain costs one thing: a downstream stage re-runs
    even when an upstream re-run happened to produce identical files.
    """

    def __init__(self, path: str):
        self.path = path
        self.data = {"schema": K.SCHEMA_STATE, "stages": {}}
        if os.path.exists(path):
            try:
                with io.open(path, encoding="utf-8") as f:
                    d = json.load(f)
                if d.get("schema") == K.SCHEMA_STATE:
                    self.data = d
            except json.JSONDecodeError:
                pass                                   # a corrupt cache is not a failure

    def key(self, stage: Stage, ctx: Context, *, source: str | None = None,
            upstream: str = "") -> str:
        # Pipeline.run hashes the source once and passes it in; a video's sha256 is not
        # something to recompute per stage. Any other caller gets it computed here, so
        # no key is ever blind to the source.
        if source is None:
            source = K.config_sha256(ctx.source.inputs())
        inputs = {n: (ctx.artefacts[n].sha256 if n in ctx.artefacts else None)
                  for n in stage.needs}
        extra = stage.key_extra(ctx) if hasattr(stage, "key_extra") else None
        return K.config_sha256({"stage": stage.id,
                                "version": getattr(stage, "version", "1"),
                                "level": (ctx.level if getattr(stage, "level_sensitive",
                                                               False) else None),
                                "config": ctx.config, "inputs": inputs,
                                "source": source, "extra": extra,
                                "upstream": upstream})

    def cached(self, stage: Stage, key: str, workdir: str) -> StageResult | None:
        rec = self.data["stages"].get(stage.id)
        if not rec or rec.get("key") != key:
            return None
        outs = {}
        for name, a in rec.get("outputs", {}).items():
            art = Artefact(**a)
            full = os.path.join(workdir, art.path)
            if not os.path.exists(full):
                return None                            # the cache lies; re-run
            outs[name] = art
        return StageResult(stage=stage.id, seconds=0.0, outputs=outs,
                           facts=rec.get("facts", {}), codes=rec.get("codes", []),
                           skipped=True, note="cached")

    def record(self, stage: Stage, key: str, res: StageResult) -> None:
        self.data["stages"][stage.id] = {
            "key": key,
            "outputs": {n: {k: v for k, v in vars(a).items() if v is not None}
                        for n, a in res.outputs.items()},
            "facts": res.facts, "codes": res.codes,
            "seconds": round(res.seconds, 3),
        }
        with io.open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)


# --------------------------------------------------------------------------- pipeline
class Pipeline:
    def __init__(self, stages: list[Stage]):
        self.stages = stages
        self._check_wiring()

    def _check_wiring(self) -> None:
        """A stage may not need what nothing produces. Caught here, not at runtime."""
        made: set[str] = set()
        for st in self.stages:
            missing = [n for n in st.needs if n not in made]
            if missing:
                raise ValueError(f"stage {st.id!r} needs {missing}, which no earlier "
                                 f"stage produces")
            made |= set(st.produces)

    def run(self, ctx: Context, *, resume: bool = True) -> RunManifest:
        state = State(ctx.path("state.json"))
        man = RunManifest(run_id=ctx.run_id, source=ctx.source.describe(),
                          budget_s=ctx.budget_s,
                          config_sha256=K.config_sha256(ctx.config))
        man.inputs = ctx.source.inputs()
        source_key = K.config_sha256(man.inputs)

        i = 0
        upstream = ""
        made_here: set[str] = set()     # keys of results this invocation computed
        while i < len(self.stages):
            st = self.stages[i]
            if i == 0:
                upstream = ""                           # a ladder restart re-plans
            if ctx.level not in st.levels:
                ctx.log(f"  {st.id:<12} skipped at {ctx.level}")
                man.add(StageResult(stage=st.id, seconds=0.0, skipped=True,
                                    note=f"not part of {ctx.level}"))
                i += 1
                continue

            key = state.key(st, ctx, source=source_key, upstream=upstream)
            upstream = key
            reuse = resume and getattr(st, "cacheable", True)
            hit = state.cached(st, key, ctx.workdir) if reuse else None
            if hit is not None and key in made_here:
                # Computed earlier in this same invocation, before the ladder stepped
                # down. Its time is already in spent_s, so it is not a resume and must
                # not make R-O2 unmeasurable the way a resumed stage does.
                ctx.log(f"  {st.id:<12} reused")
                hit.note = "reused from this run's earlier attempt"
                self._absorb(ctx, man, hit)
                i += 1
                continue
            if hit is not None:
                ctx.log(f"  {st.id:<12} cached")
                ctx.cached.append(st.id)
                self._absorb(ctx, man, hit)
                i += 1
                continue

            want = st.estimate(ctx)
            if want > ctx.remaining():
                ctx.log(f"  {st.id:<12} needs ~{want:.0f}s, {ctx.remaining():.0f}s left")
                if self._degrade(ctx, man, Code.BUDGET,
                                 f"{st.id} needs ~{want:.0f}s"):
                    i = 0                               # re-plan from the top
                    continue
                break

            try:
                res = st.run(ctx)
            except StageError as e:
                ctx.log(f"  {st.id:<12} {e}")
                man.add(StageResult(stage=st.id, seconds=0.0, codes=[e.code],
                                    skipped=True, note=str(e)))
                if e.fatal or not self._degrade(ctx, man, e.code, str(e)):
                    break
                i = 0
                continue
            except Exception as e:
                # Anything else (a ValueError from a file reader, an empty cloud reaching
                # the DSM) used to end the process with no manifest at all. A finale clip
                # must leave a labelled result, so it is a failed stage like any other,
                # and the ladder may still find a level that works.
                msg = f"unexpected {type(e).__name__}: {e}"[:800]
                ctx.log(f"  {st.id:<12} {msg}")
                man.add(StageResult(stage=st.id, seconds=0.0, codes=[Code.STAGE_UNAVAILABLE],
                                    skipped=True, note=msg))
                if not self._degrade(ctx, man, Code.STAGE_UNAVAILABLE, msg):
                    break
                i = 0
                continue

            ctx.log(f"  {st.id:<12} {res.seconds:6.2f}s"
                    + (f"  [{' '.join(res.codes)}]" if res.codes else ""))
            state.record(st, key, res)
            made_here.add(key)
            self._absorb(ctx, man, res)
            i += 1

        lv = LEVELS[ctx.level]
        man.level, man.quality = lv.key, lv.quality
        man.frame = ctx.facts.get("frame")
        # No scale stage, or one that never resolved: that is `unvalidated`, not absent.
        # A manifest without a scale status would let a reader assume metres.
        man.scale = ctx.facts.get("scale") or {
            "factor": 1.0, "status": "unvalidated",
            "label": "unvalidated (model units)",
            "basis": "no scale stage resolved this run"}
        man.units = ctx.facts.get("units") or K.units_for(man.scale["status"])
        man.georeferenced = bool(ctx.facts.get("georeferenced"))
        man.region = ctx.config.get("region")
        man.verdicts = ctx.facts.get("verdicts", {})
        man.write(ctx.path("run_manifest.json"))
        return man

    def _absorb(self, ctx: Context, man: RunManifest, res: StageResult) -> None:
        ctx.artefacts.update(res.outputs)
        ctx.facts.update(res.facts)
        ctx.spent_s += res.seconds
        man.add(res)

    def _degrade(self, ctx: Context, man: RunManifest, code: str, why: str) -> bool:
        """Step down one level. False when there is nowhere left to go."""
        nxt = K.step_down(ctx.level)
        if nxt is None:
            return False
        ctx.log(f"  ladder       {ctx.level} -> {nxt}  ({code}: {why})")
        ctx.level = nxt
        if code not in man.codes:
            man.codes.append(code)
        return True
