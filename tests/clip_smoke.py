"""Smoke test for Alt+L (extension/clip.js) and the built-in PDF reader, in headless Chromium.

    python -m tests.clip_smoke

Drags boxes on a local web page and a generated PDF, then reads the clipboard back. Also checks that a PDF sent
as an attachment (how Blackboard serves files) still downloads instead of opening in the reader.
Headless Chromium has its own clipboard, so your Windows clipboard is not touched.
"""
import functools
import http.server
import shutil
import sys
import tempfile
import threading
from pathlib import Path

import json

import fitz
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"
PAGE = """<!doctype html><html><head><title>Clip test</title><style>
body{font-family:Georgia,serif;margin:40px;color:#222} h2{color:#0a5} .hl{background:#ff0}
td{border:1px solid #888;padding:4px} table{border-collapse:collapse}</style></head><body>
<h2 id=h>Key exchange</h2>
<p id=p>Alice and <b>Bob</b> agree on a <span class=hl>prime p</span> and generator <i>g</i>. Outside words here.</p>
<ul><li>First item</li><li>Second item</li></ul>
<svg id=svg width=200 height=100><rect width=200 height=100 fill="#36c"/><circle cx=100 cy=50 r=30 fill="#fc0"/></svg>
<p>Middle paragraph not wanted.</p>
<table id=t><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr></table>
</body></html>"""
READ_CLIPBOARD = """async () => { const out = {};
  for (const it of await navigator.clipboard.read()) for (const t of it.types) {
    const b = await it.getType(t); out[t] = t.startsWith('image/') ? b.size : await b.text(); }
  return out; }"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def guess_type(self, path):
        return "application/pdf" if str(path).endswith(".pdf") else super().guess_type(path)

    def end_headers(self):
        if self.path.startswith("/attach.pdf"):
            self.send_header("Content-Disposition", 'attachment; filename="attach.pdf"')
        super().end_headers()


def make_site(folder):
    (folder / "index.html").write_text(PAGE)
    doc = fitz.open()
    page = doc.new_page(width=720, height=540)
    page.insert_text((60, 80), "Theorem 1 (Diffie-Hellman)", fontsize=28, fontname="hebo")
    page.insert_text((60, 130), "Shared secret g^ab mod p is never sent.", fontsize=18, fontname="helv")
    page.draw_circle((500, 330), 80, color=(0.1, 0.3, 0.9), fill=(0.8, 0.9, 1))
    page.insert_text((440, 335), "vector", fontsize=20, fontname="helv")
    doc.save(folder / "slides.pdf")
    shutil.copy(folder / "slides.pdf", folder / "attach.pdf")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="clip_smoke_"))
    site = tmp / "site"
    site.mkdir()
    make_site(site)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8796), functools.partial(Handler, directory=str(site)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:8796"
    results = {}
    launch = lambda p: p.chromium.launch_persistent_context(
        str(tmp / "profile"), channel="chromium", headless=True, viewport={"width": 1100, "height": 800},
        accept_downloads=True, permissions=["clipboard-read", "clipboard-write"],
        args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
    try:
        with sync_playwright() as p:
            launch(p).close()                                      # first run creates the profile...
            prefs_file = tmp / "profile" / "Default" / "Preferences"
            prefs = json.loads(prefs_file.read_text(encoding="utf-8"))
            ext_id = (EXT / "EXTENSION_ID.txt").read_text().strip()
            prefs.setdefault("extensions", {}).setdefault("settings", {}).setdefault(ext_id, {})["newAllowFileAccess"] = True
            prefs_file.write_text(json.dumps(prefs), encoding="utf-8")  # ...then "Allow access to file URLs" is on
            ctx = launch(p)
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
            shortcuts = sw.evaluate("chrome.commands.getAll().then(c => Object.fromEntries(c.map(x => [x.name, x.shortcut])))")

            def clip(pg, url_glob, a, b=None, key=None, more=()):
                sw.evaluate(f"async () => {{ const [t] = await chrome.tabs.query({{ url: '{url_glob}' }}); await startClip(t); }}")
                pg.wait_for_selector("alto-clip", state="attached", timeout=5000)
                if key:
                    pg.keyboard.press(key)
                for m1, m2 in more:                                # earlier boxes, kept with Shift
                    pg.keyboard.down("Shift")
                    pg.mouse.move(*m1)
                    pg.mouse.down()
                    pg.mouse.move(*m2, steps=6)
                    pg.mouse.up()
                    pg.keyboard.up("Shift")
                pg.mouse.move(*a)
                if b:                                              # drag
                    pg.mouse.down()
                    pg.mouse.move(*b, steps=6)
                else:                                              # click a block / page
                    pg.mouse.move(a[0] + 1, a[1] + 1)
                    pg.mouse.down()
                pg.mouse.up()
                pg.wait_for_timeout(700)
                data = pg.evaluate(READ_CLIPBOARD)
                pg.evaluate("() => navigator.clipboard.writeText('')")
                pg.wait_for_function("() => !document.querySelector('alto-clip')", timeout=10000)  # toast gone
                return data

            page = ctx.new_page()
            page.goto(base + "/index.html")
            h, svg = page.locator("#h").bounding_box(), page.locator("#svg").bounding_box()
            results["web default"] = clip(page, base + "/*", (h["x"], h["y"]), (h["x"] + 300, h["y"] + 80))
            results["web image"] = clip(page, base + "/*", (h["x"], h["y"]), (h["x"] + 300, h["y"] + 80), key="i")
            results["web text"] = clip(page, base + "/*", (h["x"] - 5, h["y"] - 5),
                                       (svg["x"] + svg["width"] + 5, svg["y"] + svg["height"] + 5), key="t")
            t = page.locator("#t").bounding_box()
            results["web table"] = clip(page, base + "/*", (t["x"] + 5, t["y"] + 5))
            # several boxes: the heading (Shift+drag), then the table; everything between stays out
            heading = ((h["x"] - 4, h["y"] - 4), (h["x"] + 200, h["y"] + h["height"] + 4))
            table = ((t["x"] - 4, t["y"] - 4), (t["x"] + t["width"] + 4, t["y"] + t["height"] + 4))
            results["web multi"] = clip(page, base + "/*", *table, more=[heading])
            results["web multi image"] = clip(page, base + "/*", *table, key="i", more=[heading])

            pdf = ctx.new_page()
            pdf.goto(base + "/slides.pdf")
            pdf.wait_for_url("chrome-extension://**", timeout=10000)
            pdf.wait_for_selector(".page[data-page-number='1'] canvas", timeout=15000)
            pdf.wait_for_timeout(800)
            c = pdf.locator(".page[data-page-number='1'] .canvasWrapper").bounding_box()
            k = c["width"] / 720
            at = lambda x, y: (c["x"] + x * k, c["y"] + y * k)
            results["pdf text"] = clip(pdf, "chrome-extension://*/*", at(40, 40), at(600, 145), key="t")
            results["pdf image"] = clip(pdf, "chrome-extension://*/*", at(380, 230), at(600, 430), key="i")
            results["pdf multi"] = clip(pdf, "chrome-extension://*/*", at(430, 315), at(560, 345), key="t",
                                        more=[(at(40, 40), at(600, 95))])

            local = ctx.new_page()                                # a PDF on disk opens in the reader too
            local.goto((site / "slides.pdf").as_uri())
            local.wait_for_url("chrome-extension://**", timeout=10000)
            local.wait_for_selector(".page[data-page-number='1'] canvas", timeout=15000)
            local_title = local.title()

            with pdf.expect_download(timeout=10000) as dl:        # attachment: downloads, no reader
                try:
                    pdf.goto(base + "/attach.pdf")
                except Exception:
                    pass                                          # navigation is aborted by the download
            attachment_downloaded = dl.value.suggested_filename == "attach.pdf"
            ctx.close()
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    wd, wi, wt, tb, pt, pi = (results[k] for k in ("web default", "web image", "web text", "web table", "pdf text", "pdf image"))
    wm, wmi, pm = results["web multi"], results["web multi image"], results["pdf multi"]
    checks = {
        "shortcuts Alt+L / Alt+Shift+L": shortcuts.get("clip-region") == "Alt+L" and shortcuts.get("save-page") == "Alt+Shift+L",
        "default is editable text": "text/html" in wd and "Key exchange" in wd.get("text/plain", ""),
        "image mode is PNG only": set(wi) == {"image/png"} and wi["image/png"] > 1000,
        "several boxes: both parts, in page order": wm.get("text/plain", "").replace("\r", "") == "Key exchange\na\tb\n1\t2",
        "several boxes: nothing between them": "Middle" not in wm.get("text/html", "") and "Alice" not in wm.get("text/html", ""),
        "several boxes, image mode: one stacked PNG": set(wmi) == {"image/png"} and wmi["image/png"] > 500,
        "text mode keeps formatting": all(s in wt.get("text/html", "") for s in ("color:rgb(0, 170, 85)", "<b", "background-color:rgb(255, 255, 0)", "<li>")),
        "headings state their look (no h1-h6 for OneNote)": "<h2" not in wt.get("text/html", "x") and "font-size:24px" in wt.get("text/html", ""),
        "tables carry the border attribute (OneNote)": '<table border="1"' in tb.get("text/html", ""),
        "gaps become spacer paragraphs (OneNote)": "&nbsp;</p>" in wt.get("text/html", ""),
        "text mode cuts at the box edge": "Outside words" not in wt.get("text/plain", "x"),
        "visuals become exact images": "<img" in wt.get("text/html", "") and "data:image/png;base64," in wt.get("text/html", ""),
        "click picks the whole table": tb.get("text/plain", "").replace("\r", "") == "a\tb\n1\t2",
        "PDF opens in the reader": True,
        "PDF text exact, bold kept": pt.get("text/plain", "").replace("\r", "") == "Theorem 1 (Diffie-Hellman)\nShared secret g^ab mod p is never sent."
                                    and "font-weight:bold\">Theorem 1" in pt.get("text/html", "")
                                    and "font-size:28pt" in pt.get("text/html", ""),
        "PDF image is PNG only": set(pi) == {"image/png"} and pi["image/png"] > 1000,
        "PDF several boxes": pm.get("text/plain", "").replace("\r", "") == "Theorem 1 (Diffie-Hellman)\n\nvector",
        "PDF on disk opens in the reader": local_title == "slides.pdf",
        "attachment PDFs still download": attachment_downloaded,
    }
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
