#!/usr/bin/env python3
"""Browser smoke test: every example renders in both views and both themes with no console errors,
the expected number of steps/cards appears, and the verdict matches the outcome. Saves screenshots.

Needs Playwright for Python (pip install playwright && playwright install chromium).
Run from the repo root:  python3 tests/render_smoke.py [--shots docs/img]
"""
import http.server, json, os, socketserver, sys, threading
from functools import partial
from playwright.sync_api import sync_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else os.path.join(ROOT, "tests", ".shots")
os.makedirs(SHOTS, exist_ok=True)

Handler = partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
Handler.log_message = lambda *a: None
srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

index = json.load(open(os.path.join(ROOT, "examples", "journeys", "index.json")))
failures = []
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    for theme in ("dark", "light"):
        ctx = b.new_context(viewport={"width": 1280, "height": 1000}, device_scale_factor=2,
                            color_scheme=theme, reduced_motion="reduce")
        pg = ctx.new_page()
        errors = []
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        for it in index:
            j = json.load(open(os.path.join(ROOT, "examples", "journeys", it["file"])))
            name = it["file"][:-5]
            pg.goto(f"http://127.0.0.1:{port}/examples/?t={theme}&n={name}#{name}")   # query forces a real reload per example
            for view in ("technical", "narrative"):
                pg.wait_for_selector(".tj .tj-views")
                pg.click(f".tj-views button:has-text('{view.capitalize()}')")
                pg.wait_for_selector(".tj-verdict.show", timeout=15000)   # verdict appears when the build-out finishes
                state = pg.evaluate("""() => ({
                    view: document.querySelector('.tj').dataset.view,
                    rows: document.querySelectorAll('.tj-svg .tj-g').length,
                    cards: document.querySelectorAll('.tj-narr').length,
                    verdict: document.querySelector('.tj-verdict').className,
                    err: !!document.querySelector('.tj-error') })""")
                exp_rows = len(j["steps"]); exp_cards = sum(1 for s in j["steps"] if s.get("story"))
                ok_cls = "ok" if j["outcome"]["status"] == "allow" else "no"
                problems = []
                if state["err"]: problems.append("validation error shown")
                if state["view"] != view: problems.append(f"view is {state['view']}")
                if view == "technical" and state["rows"] != exp_rows: problems.append(f"rows {state['rows']} != {exp_rows}")
                if view == "narrative" and state["cards"] != exp_cards: problems.append(f"cards {state['cards']} != {exp_cards}")
                if ok_cls not in state["verdict"].split(): problems.append(f"verdict class {state['verdict']!r}, expected {ok_cls}")
                if problems: failures.append(f"{theme}/{name}/{view}: " + "; ".join(problems))
                pg.locator("#viewer .tj").screenshot(path=os.path.join(SHOTS, f"{name}-{view}-{theme}.png"))
        if errors: failures.append(f"{theme}: console errors: {errors[:5]}")
        ctx.close()
    b.close()
srv.shutdown()
print(f"rendered {len(index)} journeys x 2 views x 2 themes; screenshots in {os.path.relpath(SHOTS, ROOT)}")
if failures:
    print("FAILURES:\n  " + "\n  ".join(failures)); sys.exit(1)
print("ALL PASS")
