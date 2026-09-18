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

    def estimate(self, ctx: Context) -> float:
        return 1.0

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

    The key is the stage id plus the config plus the hashes of its inputs. Change a
    threshold and only the stages downstream of it re-run; change nothing and the whole
    pipeline is a no-op that still writes a manifest.
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

    def key(self, stage: Stage, ctx: Context) -> str:
        inputs = {n: (ctx.artefacts[n].sha256 if n in ctx.artefacts else None)
                  for n in stage.needs}
        return K.config_sha256({"stage": stage.id,
                                "version": getattr(stage, "version", "1"),
                                "level": ctx.level,
                                "config": ctx.config, "inputs": inputs})

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

        i = 0
        while i < len(self.stages):
            st = self.stages[i]
            if ctx.level not in st.levels:
                ctx.log(f"  {st.id:<12} skipped at {ctx.level}")
                man.add(StageResult(stage=st.id, seconds=0.0, skipped=True,
                                    note=f"not part of {ctx.level}"))
                i += 1
                continue

            key = state.key(st, ctx)
            hit = state.cached(st, key, ctx.workdir) if resume else None
            if hit is not None:
                ctx.log(f"  {st.id:<12} cached")
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

            ctx.log(f"  {st.id:<12} {res.seconds:6.2f}s"
                    + (f"  [{' '.join(res.codes)}]" if res.codes else ""))
            state.record(st, key, res)
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
