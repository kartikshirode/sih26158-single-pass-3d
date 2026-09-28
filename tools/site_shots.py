"""
Screenshots of the web pages in headless Chrome, served from web/ on a local port.

Run:  python tools/site_shots.py <out dir> "<page?query>=<name.png>" ...
e.g.  python tools/site_shots.py out/shots "workspace.html?model=b3&demo=oblique,distance,height,area=measure.png"

workspace.html's ?demo= hook (src/workspace.js) places measurements at fixed screen spots,
so a capture needs no clicking. Each page gets 25 s to load its model before the shot, and
console errors are printed beside the file name. Needs Playwright and a Chrome install;
SHOTS_WEB points at another copy of the site.
"""
import functools
import http.server
import os
import sys
import threading
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    web = os.environ.get("SHOTS_WEB", os.path.join(ROOT, "web"))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=web)
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8765), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME if os.path.exists(CHROME) else None,
                              args=["--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist"])
        for spec in sys.argv[2:]:
            url, name = spec.rsplit("=", 1)
            pg = b.new_page(viewport={"width": 1600, "height": 1000})
            msgs = []
            pg.on("console", lambda m: msgs.append(f"{m.type}: {m.text}"))
            pg.on("pageerror", lambda e: msgs.append(f"pageerror: {e}"))
            pg.goto(f"http://127.0.0.1:8765/{url}", wait_until="load", timeout=180000)
            time.sleep(25)
            pg.screenshot(path=os.path.join(out, name), full_page=url.startswith("index"))
            print(name, [m for m in msgs if "error" in m.lower()][:6])
            pg.close()
        b.close()
    srv.shutdown()


if __name__ == "__main__":
    main()
