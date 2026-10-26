"""The stages of Alt+L on a site's PDF viewer, each on fixed inputs (no timing involved).

    python -m tests.viewer_stages

Screenshots are built here with the pages at known places, so the expected answers are exact:
  S3 open:   the PDF downloads once and is reused; something that is not a PDF is refused.
  S4 pages:  page outlines found in a screenshot - one page centred, cut by the top or bottom of the viewer, two
             pages with the gap between them, pink/grey slides on a grey viewer, a dark viewer.
  S5 match:  which page of the PDF is on screen - right with no toolbar hint or a wrong one; with 50 near-identical
             slides it may say "don't know" but must never name a wrong page.
They run inside the extension's own reader page, where Alt+L's code is loaded (extension/clip.js stages).
Viewer detection (S1) and finding the file (S2) need a whole fake site: tests/bbviewer_smoke.py.
"""
import base64
import functools
import http.server
import io
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

import fitz
from PIL import Image
from playwright.sync_api import sync_playwright

from tests.clip_smoke import EXT

FIXTURE = Path(__file__).parent / "fixtures" / "math_slides.pdf"
REAL = Path.home() / "Downloads" / "Algs-04-SkipListsTreapsQS.pdf"
PORT = 8827
W, H = 1200, 900                     # the screen (CSS px = screenshot px here)
PW = 760                             # page width on screen
GREY, DARK = (232, 234, 237), (45, 47, 52)
hits = {}


class Files(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_GET(self):
        hits[self.path] = hits.get(self.path, 0) + 1
        super().do_GET()


def page_png(doc, n, width=PW):
    z = width / doc[n - 1].rect.width
    return Image.open(io.BytesIO(doc[n - 1].get_pixmap(matrix=fitz.Matrix(z, z)).tobytes("png"))).convert("RGB")


def shot(doc, placements, bg=GREY):
    """A screenshot of a viewer: pages (number, x, y) pasted at known places. Returns (data URL, page rects)."""
    img = Image.new("RGB", (W, H), bg)
    rects = {}
    for n, x, y in placements:
        p = page_png(doc, n)
        img.paste(p, (x, y))
        rects[n] = [x, y, p.width, p.height]
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), rects


def similar_pdf(path):
    """50 slides that differ only by the number in a corner."""
    src = fitz.open(FIXTURE)
    out = fitz.open()
    for k in range(50):
        p = out.new_page(width=src[1].rect.width, height=src[1].rect.height)
        p.show_pdf_page(p.rect, src, 1)
        p.insert_text((p.rect.width - 40, p.rect.height - 6), f"{k + 1}/50", fontsize=5)
    out.save(path)


# In the reader page: load a screenshot, then run one stage. Rects are [x, y, w, h].
RUN = """async ({ stage, shot, url, sel, region, pr, hint }) => {
  const S = globalThis.altoClip.stages;
  const R = (a) => DOMRect.fromRect({ x: a[0], y: a[1], width: a[2], height: a[3] });
  const r1 = (r) => [r.left, r.top, r.width, r.height].map(Math.round);
  if (stage === "open") { const pdf = await S.openPdf(url); return pdf ? pdf.numPages : 0; }
  const bmp = await createImageBitmap(await (await fetch(shot)).blob());
  const ctx = new OffscreenCanvas(bmp.width, bmp.height).getContext("2d", { willReadFrequently: true });
  ctx.drawImage(bmp, 0, 0);
  const pdf = await S.openPdf(url);
  if (!pdf) return { error: "openPdf gave nothing for " + url + ": " + S.openPdf.lastError };
  const vp = (await pdf.getPage(1)).getViewport({ scale: 1 });
  if (stage === "pages") {
    const hit = { el: { tagName: "IFRAME" }, rect: R(region) };
    return S.pageRects([R(sel)], [], hit, ctx, 1, vp.width / vp.height).map((p) => ({ full: r1(p.full), vis: r1(p.vis) }));
  }
  if (stage === "match") return S.whichPage(pdf, { full: R(pr.full), vis: R(pr.vis) }, ctx, 1, hint || 0);
}"""


def main():
    tmp = Path(tempfile.mkdtemp(prefix="viewer_stages_"))
    site = tmp / "site"
    site.mkdir()
    shutil.copy(FIXTURE, site / "slides.pdf")
    similar_pdf(site / "similar.pdf")
    (site / "notpdf.pdf").write_text("<html>login page</html>")
    have_real = REAL.exists()
    if have_real:
        shutil.copy(REAL, site / "real.pdf")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), functools.partial(Files, directory=str(site)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{PORT}"
    doc, sim = fitz.open(FIXTURE), fitz.open(site / "similar.pdf")
    ph = round(PW * doc[0].rect.height / doc[0].rect.width)
    checks = {}
    launch = lambda p: p.chromium.launch_persistent_context(str(tmp / "profile"), channel="chromium", headless=True,
        viewport={"width": W, "height": H}, device_scale_factor=1,
        args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
    try:
        with sync_playwright() as p:
            launch(p).close()
            prefs_file = tmp / "profile" / "Default" / "Preferences"
            prefs = json.loads(prefs_file.read_text(encoding="utf-8"))
            ext_id = (EXT / "EXTENSION_ID.txt").read_text().strip()
            prefs.setdefault("extensions", {}).setdefault("settings", {}).setdefault(ext_id, {})["newAllowFileAccess"] = True
            prefs_file.write_text(json.dumps(prefs), encoding="utf-8")
            ctx = launch(p)
            ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
            reader = ctx.new_page()
            reader.goto(f"chrome-extension://{ext_id}/vendor/pdfjs/web/viewer.html")
            reader.wait_for_function("() => globalThis.altoClip && globalThis.altoClip.stages", timeout=20000)
            run = lambda **q: reader.evaluate(RUN, {"shot": None, "url": None, "sel": None, "region": None, "pr": None, "hint": 0, **q})
            # the PDFs reach the page directly (blob URLs), no test server; fetch is watched to count downloads
            reader.evaluate("""() => { window.__fetches = {}; const f = window.fetch.bind(window);
              window.fetch = (u, o) => { window.__fetches[u] = (window.__fetches[u] || 0) + 1; return f(u, o); }; }""")
            def blob(path, kind="application/pdf"):
                b64 = base64.b64encode(Path(path).read_bytes()).decode()
                return reader.evaluate("([b, t]) => URL.createObjectURL(new Blob([Uint8Array.fromBase64(b)], { type: t }))", [b64, kind])
            url = {"slides": blob(site / "slides.pdf"), "similar": blob(site / "similar.pdf"), "notpdf": blob(site / "notpdf.pdf", "text/html")}
            if have_real:
                url["real"] = blob(site / "real.pdf")

            # S3: download once, reuse; refuse what is not a PDF
            n1 = run(stage="open", url=url["slides"])
            n2 = run(stage="open", url=url["slides"])
            checks["S3 opens the PDF"] = n1 == 3 and n2 == 3
            checks["S3 downloads it once, then reuses it"] = reader.evaluate("(u) => window.__fetches[u]", url["slides"]) == 1
            checks["S3 refuses a file that is not a PDF"] = run(stage="open", url=url["notpdf"]) == 0

            # S4 + S5 on screenshots with the pages at known places
            layouts = {
                "one page centred": ([(2, 220, 236)], GREY, 2),
                "page cut by the viewer's top": ([(2, 220, -200), (3, 220, ph - 200 + 16)], GREY, 3),
                "page cut by the viewer's bottom": ([(1, 220, 40), (2, 220, 40 + ph + 16)], GREY, 1),
                "two pages with the gap": ([(1, 220, -150), (2, 220, ph - 150 + 16)], GREY, 2),
                "dark viewer": ([(2, 220, 236)], DARK, 2),
            }
            for name, (places, bg, main_page) in layouts.items():
                data, rects = shot(doc, places, bg)
                x, y, w, h = rects[main_page]
                vy0, vy1 = max(0, y), min(H, y + h)
                sel = [x + 40, vy0 + 10, w - 80, max(20, vy1 - vy0 - 20)]
                found = run(stage="pages", shot=data, url=url["slides"], sel=sel, region=[0, 0, W, H])
                if isinstance(found, dict):                 # the stage failed: report it, keep going
                    print(f"  {name}: {found}")
                    checks[f"S4 {name}: page outlines exact"] = False
                    continue
                want = {n: r for n, r in rects.items() if r[1] < H and r[1] + r[3] > 0}
                ok = len(found) >= 1
                for f in found:   # every outline found is one of the placed pages, within 2 px
                    ok &= any(all(abs(a - b) <= 2 for a, b in zip(f["full"], r)) for r in want.values())
                checks[f"S4 {name}: page outlines exact"] = ok and any(
                    all(abs(a - b) <= 2 for a, b in zip(f["full"], rects[main_page])) for f in found)
                # S5: each found page is named right (or "don't know" for a sliver), never wrong
                names = []
                for f in found:
                    n_true = next((n for n, r in rects.items() if all(abs(a - b) <= 2 for a, b in zip(f["full"], r))), None)
                    wrong_hint = 1 if n_true != 1 else 2
                    for hint in (0, wrong_hint, n_true or 0):  # no toolbar, a wrong toolbar page, the right one
                        res = run(stage="match", shot=data, url=url["slides"], pr=f, hint=hint)
                        res = res if "n" in res else {"n": -1, "scores": res}
                        names.append((n_true, res["n"], f["vis"][3], res["scores"], hint))
                big = [t for t in names if t[2] > 0.5 * ph]
                alike = lambda t: len(t[3]) > 1 and t[3][0][1] - t[3][1][1] < 0.02   # the PDF has a look-alike page
                checks[f"S5 {name}: the main page is named right"] = bool(big) and all(
                    t[1] == t[0] or (t[1] == 0 and alike(t) and t[4] != t[0]) for t in big)
                checks[f"S5 {name}: never a wrong page"] = all(t[1] == 0 or t[1] == t[0] for t in names)
                if not checks[f"S5 {name}: the main page is named right"] or not checks[f"S4 {name}: page outlines exact"]:
                    print(f"  {name}: found {found} want {want} matches {names}")

            # S5 on 50 slides that differ only by a corner number: may not know, must not guess wrong
            data, rects = shot(sim, [(17, 220, 236)])
            pr = {"full": rects[17], "vis": rects[17]}
            res = run(stage="match", shot=data, url=url["similar"], pr=pr, hint=0)
            print("  similar:", res)
            res = res if "n" in res else {"n": -1}
            checks["S5 50 near-identical slides: never a wrong page"] = res["n"] in (0, 17)
            if have_real:                                    # the real lecture slides: page 11 of 51
                real = fitz.open(site / "real.pdf")
                data, rects = shot(real, [(11, 220, 236)])
                res = run(stage="match", shot=data, url=url["real"], pr={"full": rects[11], "vis": rects[11]}, hint=0)
                res = res if "n" in res else {"n": -1, "error": res}
                checks["S5 real lecture slides: page 11 of 51 found"] = res["n"] == 11
                if res["n"] != 11:
                    print("  real:", res)
            ctx.close()
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    for k, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {k}")
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
