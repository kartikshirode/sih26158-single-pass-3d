"""
The per-run QA report (docs/14 section 3.3).

One page that answers what a reviewer actually asks: what was this run, what may it
claim, what kind of metre is it printing, and where did each number come from. The
demo's Q&A page is the prototype; this is the version a run generates for itself.

Every line traces to the run manifest. The report invents nothing - if a number is not
in the manifest it does not appear here, which is why the manifest is written first.
"""

from __future__ import annotations

import io
import json
import os

from . import contracts as K


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    if isinstance(v, dict):
        return ", ".join(f"{k}={_fmt(x)}" for k, x in v.items())
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v)


def render(man: dict) -> str:
    lv = K.LEVELS.get(man.get("level", "L0"))
    sc = man.get("scale") or {}
    out: list[str] = []
    w = out.append

    w(f"# QA report - {man['run_id']}")
    w("")
    w(f"Source **{man['source']}**, {man.get('started', '')}, "
      f"git `{man.get('git_sha')}`, config `{(man.get('config_sha256') or '')[:12]}`.")
    w("")
    w("## What this run may claim")
    w("")
    w("| | |")
    w("|---|---|")
    w(f"| Ladder level | **{lv.key} - {lv.quality}** ({lv.description}) |")
    w(f"| Frame | {man.get('frame')} |")
    w(f"| Units | **{man.get('units')}** |")
    w(f"| Scale | {sc.get('label', 'unvalidated')}"
      + (f" - {sc.get('basis')}" if sc.get("basis") else "") + " |")
    w(f"| Georeferenced | {'yes' if man.get('georeferenced') else 'no'} |")
    w(f"| Region | {man.get('region') or 'not recorded'} |")
    w(f"| Codes | {', '.join(man.get('codes') or []) or 'none'} |")
    w("")

    if man.get("verdicts"):
        w("## The PS targets")
        w("")
        w("| Target | Standing |")
        w("|---|---|")
        for k, v in man["verdicts"].items():
            w(f"| {k} | {v} |")
        w("")

    w("## Stages")
    w("")
    w("| Stage | Seconds | Outcome | Facts |")
    w("|---|---:|---|---|")
    for st in man.get("stages", []):
        state = "cached" if st.get("note") == "cached" else \
                ("skipped" if st.get("skipped") else "ran")
        facts = {k: v for k, v in (st.get("facts") or {}).items()
                 if not isinstance(v, (dict, list))}
        w(f"| `{st['id']}` | {st['seconds']:.2f} | {state}"
          + (f" ({', '.join(st['codes'])})" if st.get("codes") else "")
          + f" | {_fmt(facts) if facts else ''} |")
    w("")
    w(f"Total **{man.get('seconds', 0):.1f} s** against a {man.get('budget_s', 0):.0f} s "
      f"budget - {'within' if man.get('within_budget') else 'OVER'}.")
    w("")

    if man.get("artefacts"):
        w("## Artefacts")
        w("")
        w("| Name | Path | Frame | Units | Bytes |")
        w("|---|---|---|---|---:|")
        for name, a in sorted(man["artefacts"].items()):
            w(f"| {name} | `{a['path']}` | {a.get('frame') or ''} | "
              f"{a.get('units') or ''} | {a.get('bytes') or ''} |")
        w("")

    w("## Provenance")
    w("")
    w("Every figure above is read from this run's `run_manifest.json`; the inputs are "
      "checksummed at intake and the artefacts are checksummed on write, so "
      "`tesseract verify` can tell whether the files still match the run that claimed "
      "them. What the run may *say* is bounded by the two lines that matter: the ladder "
      "level, and the scale status.")
    if (man.get("scale") or {}).get("status") == "unvalidated":
        w("")
        w("> **This run has no external ruler.** Its lengths are model units. They may "
          "not be printed as metres, and they are not comparable with another run's "
          "(docs/08).")
    return "\n".join(out) + "\n"


def write_report(rundir: str) -> str:
    mp = os.path.join(rundir, "run_manifest.json")
    with io.open(mp, encoding="utf-8") as f:
        man = json.load(f)
    out = os.path.join(rundir, "qa_report.md")
    with io.open(out, "w", encoding="utf-8") as f:
        f.write(render(man))
    return out


if __name__ == "__main__":
    import sys
    print(render(json.load(open(os.path.join(sys.argv[1], "run_manifest.json")))))
