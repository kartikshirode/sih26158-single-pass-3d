# -*- coding: utf-8 -*-
"""
Drive demo/console/ in a real browser and check what it says.

    python tools/test_console.py [--shots DIR]

check_design.py and check_wiring.py read the built HTML. They cannot see whether the
WebGL workspace actually renders, whether a measurement on a calibrated clip prints
metres while the same tool on an unvalidated one prints units, or whether a tab throws
once it has data in it. Those are exactly the claims the console exists to make, so
they are checked here against a headless Chromium with a served copy of demo/.

It drives the COMMITTED page, not a fresh build: build_console.py needs out/, which is
not in the repo, so CI cannot rebuild the console. A fingerprint of the template and the
stylesheet is stamped into the page, and this refuses to run when they have moved, so a
stale committed page cannot sail through a green gate.

Needs playwright (`pip install playwright && playwright install chromium`). Skips with
a clear message rather than failing when it is not installed, because the rest of the
build gate does not depend on it.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import io
import os
import re
import socket
import socketserver
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "demo")
GRID = [(0.20 + 0.04 * i, 0.22 + 0.04 * j) for i in range(16) for j in range(15)]


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):        # the build log is not an access log
        pass


def serve(directory: str):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    handler = functools.partial(Quiet, directory=directory)
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{port}/console/"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", help="write screenshots here")
    a = ap.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  SKIP - playwright is not installed; the console was not driven")
        return 0
    page_path = os.path.join(DEMO, "console", "index.html")
    if not os.path.exists(page_path):
        print("  no demo/console/index.html: run tools/build_console.py first")
        return 2
    # The console build needs out/, which is not in the repo, so CI drives the
    # committed page rather than rebuilding it. That is only safe if the committed
    # page is current, which is what the stamp proves.
    from build_console import sources_sha
    with io.open(page_path, encoding="utf-8") as f:
        head = f.read(4096)
    m = re.search(r'name="tesseract-sources" content="([0-9a-f]+)"', head)
    if not m or m.group(1) != sources_sha():
        print(f"  FAIL the committed console is stale: built from "
              f"{m.group(1) if m else 'an unstamped template'}, "
              f"sources are now {sources_sha()}")
        print("       run tools/build_console.py and commit demo/console/index.html")
        return 1

    skipped = []
    shots = a.shots and os.path.abspath(a.shots)
    if shots:
        os.makedirs(shots, exist_ok=True)
    httpd, base = serve(DEMO)
    fails, errs = [], []

    def ck(name, ok, detail=""):
        print(("  PASS " if ok else "  FAIL ") + name + ("   " + detail if detail else ""))
        if not ok:
            fails.append(name)

    def skip(name, why):
        print(f"  SKIP {name}   {why}")
        skipped.append(name)

    def shot(page, name):
        if shots:
            page.screenshot(path=os.path.join(shots, name))

    try:
        with sync_playwright() as p:
            # SwiftShader: the CI runner has no GPU, and WebGL2 is the thing under test
            b = p.chromium.launch(args=["--enable-unsafe-swiftshader"])
            pg = b.new_page(viewport={"width": 1440, "height": 900}, color_scheme="dark")
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("console",
                  lambda m: errs.append("console: " + m.text) if m.type == "error"
                  else None)

            pg.goto(base, wait_until="load")
            pg.wait_for_timeout(900)
            runs = pg.evaluate("RUNS.map(function(r){return r.id})")
            ck("every run reaches the rail",
               pg.locator("#runs .run").count() == len(runs), f"{len(runs)} runs")

            broke = []
            for rid in runs:
                for tab in ("overview", "stages", "artefacts", "contracts"):
                    pg.evaluate(f"location.hash = '#/{rid}/{tab}'")
                    pg.wait_for_timeout(100)
                    if pg.evaluate("document.querySelector('#main').innerText.length") < 120:
                        broke.append(f"{rid}/{tab}")
            ck(f"all {len(runs) * 4} run/tab views render", not broke, ", ".join(broke))

            # what the page is allowed to say, per run, read back off the rendered text
            def text(rid, tab="overview"):
                pg.evaluate(f"location.hash = '#/{rid}/{tab}'")
                pg.wait_for_timeout(260)
                return pg.evaluate("document.querySelector('#main').innerText")

            t = text("kolu")
            ck("a calibrated run names its factor and its evidence",
               "calibrated x5.54" in t and "lane width" in t)
            ck("an unmeasurable target says so rather than passing",
               "NOT MEASURABLE" in t.upper())
            shot(pg, "1-overview.png")

            # An unvalidated run is one with a mesh and no ruler. The clip that used to
            # provide it was withdrawn for rights (B-05), and restoring the check needs a
            # reconstruction of a clip the team holds, which is Phase 1 work.
            unval = next((r for r in runs
                          if pg.evaluate(f"BY['{r}'].scale.status") == "unvalidated"
                          and pg.evaluate(f"BY['{r}'].models.length") > 0), None)
            if unval:
                t = text(unval)
                ck("an unvalidated run is not given metres",
                   "unvalidated" in t and "model units" in t and "metres" not in t)
            else:
                skip("an unvalidated run is not given metres",
                     "no run has a mesh and an unvalidated scale - reconstruct a clip "
                     "with clear rights (B-05 replacement) to restore this")

            refused = next((r for r in runs
                            if pg.evaluate(f"BY['{r}'].level") == "L5"), None)
            t = text(refused)
            ck("a refused clip reports the refusal as the result",
               "L5" in t and "not reconstructable" in t and "Nothing to read" in t)
            shot(pg, "5-refused.png")

            t = text("demo")
            ck("a georeferenced run reaches a projected frame",
               "F7" in t and "metres" in t and "EPSG" in t)

            pg.evaluate("location.hash = '#/kolu/stages'")
            pg.wait_for_timeout(260)
            ck("the timeline has one row per stage",
               pg.locator(".tl .row").count() == pg.evaluate("BY['kolu'].stages.length"))
            shot(pg, "2-stages.png")

            pg.evaluate("location.hash = '#/kolu/artefacts'")
            pg.wait_for_timeout(260)
            ck("every artefact is listed with its frame and units",
               pg.locator("tbody tr").count() == pg.evaluate("BY['kolu'].arts.length"))
            shot(pg, "4-artefacts.png")

            pg.evaluate("location.hash = '#/kolu/contracts'")
            pg.wait_for_timeout(260)
            ck("the contract check is reported",
               "PASS" in pg.evaluate("document.querySelector('#main').innerText"))
            shot(pg, "6-contracts.png")

            # ---- the workspace, which no static check can see
            pg.evaluate("location.hash = '#/kolu/model'")
            pg.wait_for_function("window.active && window.curMVP", timeout=90000)
            pg.wait_for_timeout(1600)
            ck("the workspace renders geometry", pg.evaluate("!!active"))
            ck("rendering never sees the calibration factor",
               abs(pg.evaluate("active.uScale * active.viewScale / "
                               "(window.__MESH[active.key].scale * 32767 / 32000)")
                   - 1) < 1e-9)
            # The textured model is the first Kolu model: its atlas must arrive over
            # the same path as the mesh, and the page must say so in the HUD.
            if pg.evaluate("!!active.vaoT"):
                pg.wait_for_function("active.texReady || active.texError", timeout=60000)
                ck("the textured model's atlas loads",
                   pg.evaluate("active.texReady") and not pg.evaluate("active.texError"),
                   pg.evaluate("document.querySelector('#hud').textContent"))
                pg.wait_for_timeout(400)
                shot(pg, "3b-textured.png")
                ck("the HUD reports the texture",
                   "textured" in pg.evaluate("document.querySelector('#hud').textContent"))
                # Switch to the per-vertex rebuild so the measurement checks below run
                # on the same model they always did.
                pg.click("[data-m='1']")
                pg.wait_for_function("window.active && window.active.key === 'kolu_mvs'",
                                     timeout=90000)
                pg.wait_for_timeout(800)
            else:
                skip("the textured model's atlas loads", "no textured model on the page")
            shot(pg, "3-model.png")

            box = pg.locator("#gl").bounding_box()

            def measure():
                for fx, fy in sorted(GRID, key=lambda q: q[0] + q[1]):
                    pg.mouse.click(box["x"] + box["width"] * fx,
                                   box["y"] + box["height"] * fy)
                    pg.wait_for_timeout(80)
                    if pg.evaluate("marks.length") >= 1:
                        break
                for fx, fy in sorted(GRID, key=lambda q: -(q[0] + q[1])):
                    pg.mouse.click(box["x"] + box["width"] * fx,
                                   box["y"] + box["height"] * fy)
                    pg.wait_for_timeout(80)
                    if pg.evaluate("marks.length") >= 2:
                        break
                pg.wait_for_timeout(350)
                return pg.evaluate("document.querySelector('#ovl .m-txt') && "
                                   "document.querySelector('#ovl .m-txt').textContent")

            pg.click("#bMeasure")
            ck("an active tool reads as pressed",
               pg.evaluate("getComputedStyle(document.querySelector('#bMeasure'))"
                           ".backgroundColor")
               != pg.evaluate("getComputedStyle(document.querySelector('#bClear'))"
                              ".backgroundColor"))
            lab = measure()
            ck("measuring a calibrated run prints metres",
               bool(lab) and lab.endswith(" m"), repr(lab))
            shot(pg, "3b-measure.png")

            if unval:
                pg.evaluate(f"location.hash = '#/{unval}/model'")
                pg.wait_for_function("window.active && window.curMVP", timeout=90000)
                pg.wait_for_timeout(1400)
                box = pg.locator("#gl").bounding_box()
                if pg.evaluate("!measuring"):
                    pg.click("#bMeasure")
                lab = measure()
                ck("the same tool on an unvalidated run prints units",
                   bool(lab) and lab.endswith(" units"), repr(lab))
                shot(pg, "7-unvalidated-model.png")
            else:
                skip("the same tool on an unvalidated run prints units",
                     "same cause as above")

            pg.evaluate(f"location.hash = '#/{refused}/model'")
            pg.wait_for_timeout(350)
            ck("a run with no mesh cannot open the workspace",
               pg.evaluate("curTab") == "overview")

            # ---- shell
            pg.evaluate("location.hash = '#/kolu/overview'")
            pg.wait_for_timeout(260)
            before = pg.evaluate("getComputedStyle(document.body).backgroundColor")
            pg.click("#bTheme")
            pg.wait_for_timeout(350)
            ck("the theme toggle flips the console",
               before != pg.evaluate("getComputedStyle(document.body).backgroundColor"))
            shot(pg, "8-light.png")
            pg.click("#bTheme")
            pg.wait_for_timeout(250)

            pg.keyboard.press("j")
            pg.wait_for_timeout(250)
            ck("j steps to the next run", pg.evaluate("cur") == runs[1])
            pg.fill("#q", "synthetic")
            pg.wait_for_timeout(250)
            want = pg.evaluate("RUNS.filter(function(r){"
                               "return (r.id+' '+r.source).indexOf('synthetic')>=0}).length")
            n = pg.locator("#runs .run").count()
            ck("the filter narrows the rail", n == want and n < len(runs), f"{n} of {len(runs)}")

            ph = b.new_page(viewport={"width": 390, "height": 844},
                            device_scale_factor=2, is_mobile=True, has_touch=True,
                            color_scheme="dark")
            ph.goto(base + "#/kolu/overview", wait_until="load")
            ph.wait_for_timeout(1100)
            sw = ph.evaluate("document.documentElement.scrollWidth")
            cw = ph.evaluate("document.documentElement.clientWidth")
            ck("no sideways scroll on a phone", sw <= cw + 1, f"{sw} vs {cw}")
            shot(ph, "9-phone.png")

            ck("nothing threw", not errs, "; ".join(errs)[:300])
            b.close()
    finally:
        httpd.shutdown()

    print("\n  " + ("FAIL - " + ", ".join(fails) if fails
                    else "PASS - the console says what the manifests say"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
