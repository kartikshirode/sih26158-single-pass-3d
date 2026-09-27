"""
The S3b gate in mvs_job/run_mvs.py, against real and broken analyzer output.

Run:  python mvs_job/test_ba_gate.py

No COLMAP needed: ba_gate only reads the dict reproj_error parses. The passing cases are
the three recorded Kolu runs in research/run-evidence/, so the gate is proven not to
refuse the reconstructions the project already publishes.
"""

from __future__ import annotations

import glob
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from run_mvs import ba_gate                                              # noqa: E402

FAIL = 0


def check(name, cond, detail=""):
    global FAIL
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))
    FAIL += 0 if cond else 1


evidence = sorted(glob.glob(os.path.join(HERE, "..", "research", "run-evidence",
                                         "*mvs_result.json")))
check("recorded MVS runs are available to test against", len(evidence) >= 1,
      f"{len(evidence)} files")
for p in evidence:
    d = json.load(io.open(p, encoding="utf-8"))
    got = ba_gate(d["sparse_after_bundle_adjustment"], d["n_images"])
    check(f"the published run passes: {os.path.basename(p)}", got == [], str(got))

good = {"Registered images": "45", "Mean reprojection error": "0.366012px"}
lost = ba_gate(dict(good, **{"Registered images": "35"}), 45)
check("a lost view fails the gate", any("35 of 45" in s for s in lost), str(lost))
drift = ba_gate(dict(good, **{"Mean reprojection error": "4.0px"}), 45)
check("4 px after BA fails the gate", any("4.000 px" in s for s in drift), str(drift))
check("an analyzer that printed nothing fails, not passes", len(ba_gate({}, 45)) == 2)
check("the threshold is the caller's to loosen",
      ba_gate(dict(good, **{"Mean reprojection error": "1.2px"}), 45, max_px=1.5) == [])

print(f"\n{'ALL PASS' if not FAIL else f'{FAIL} FAILED'}")
sys.exit(1 if FAIL else 0)
