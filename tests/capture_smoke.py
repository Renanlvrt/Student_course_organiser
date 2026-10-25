"""Smoke test for Alt+Shift+L (extension/capture.js) in headless Chromium with the unpacked extension.

    python -m tests.capture_smoke

Serves two local sites (so images, CSS and an iframe are cross-origin), saves the page twice (the second save
re-injects the library) and checks that the saved .html holds everything. The Save As dialog is skipped.
"""
import functools
import http.server
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c63f8cfc0f01f0005010201a5f9ad5e0000000049454e44ae426082")
PAGE = """<!doctype html><html><head><title>Test Page: Deadlines</title>
<link rel=stylesheet href="http://127.0.0.1:8792/style.css"></head><body>
<h1 class=x>Hello capture</h1>
<img src="http://127.0.0.1:8792/img.png"><img src="local.png">
<div style="height:3000px"></div>
<img loading=lazy src="http://127.0.0.1:8792/img.png?lazy">
<iframe src="http://127.0.0.1:8792/frame.html"></iframe>
<div id=js></div><script>document.getElementById('js').textContent='RENDERED BY JS'</script>
</body></html>"""


def serve(folder, port):
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(folder))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def main():
    tmp = Path(tempfile.mkdtemp(prefix="capture_smoke_"))
    a, b = tmp / "a", tmp / "b"
    a.mkdir(); b.mkdir()
    (a / "index.html").write_text(PAGE)
    (a / "local.png").write_bytes(PNG)
    (b / "img.png").write_bytes(PNG)
    (b / "style.css").write_text(".x{color:rgb(1,2,3);background:url(img.png)} .unused{color:red}")
    (b / "frame.html").write_text("<html><body><p>FRAME CONTENT 42</p><img src='img.png'></body></html>")
    serve(a, 8791)
    serve(b, 8792)
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(tmp / "profile"), channel="chromium", headless=True, accept_downloads=True,
                args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
            page = ctx.new_page()
            page.goto("http://127.0.0.1:8791/index.html")
            page.wait_for_load_state("networkidle")
            shortcut = sw.evaluate("chrome.commands.getAll().then(c => c.find(x => x.name === 'save-page').shortcut)")
            out = sw.evaluate("""async () => {
              const orig = chrome.downloads.download;
              let asked = null;
              chrome.downloads.download = (o) => { asked = o; return orig({ ...o, saveAs: false }); };
              const [tab] = await chrome.tabs.query({ url: "http://127.0.0.1:8791/*" });
              await savePage(tab);
              const t0 = Date.now();
              await savePage(tab);
              const ms = Date.now() - t0;
              chrome.downloads.download = orig;
              const [it] = await chrome.downloads.search({ orderBy: ["-startTime"], limit: 1 });
              return { ms, asked, file: it && it.filename, state: it && it.state, left: captureUrls.size };
            }""")
            html = Path(out["file"]).read_text(encoding="utf-8")
            ctx.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    checks = {
        "shortcut is Alt+Shift+L": shortcut == "Alt+Shift+L",
        "Save As dialog requested": out["asked"]["saveAs"] is True,
        "file name from title": out["asked"]["filename"].startswith("Test Page_ Deadlines ("),
        "download complete": out["state"] == "complete",
        "blob URLs released": out["left"] == 0,
        "text": "Hello capture" in html,
        "JS-rendered DOM kept": "RENDERED BY JS" in html,
        "cross-origin iframe": "FRAME CONTENT 42" in html,
        "cross-origin CSS": "rgb(1,2,3)" in html,
        "images inlined": "data:image/png" in html and 'src="http://127.0.0.1:8792/img.png"' not in html,
        "scripts removed": "<script>document" not in html,
        "source URL noted": "127.0.0.1:8791/index.html" in html,
    }
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f"saved {len(html)} bytes in {out['ms']} ms")
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
