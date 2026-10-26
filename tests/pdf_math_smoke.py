"""Alt+L on slides with mathematics, in the built-in reader (headless Chromium).

    python -m tests.pdf_math_smoke

tests/fixtures/math_slides.pdf is Beamer, typeset like the department's lecture slides: sans-serif text (CMSS),
maths in CMSSI letters with CMMI/CMSY symbols, fractions and scripts on their own small baselines, bullets drawn
as shapes and pink blocks. If the real lecture PDF from the bug report is in Downloads it is checked as well
(copied to a temp folder, never committed).

What a paste must be: the prose as editable text, once, in reading order, in a sans font with bullets; every
formula as a complete typeset picture in its place (inline in the sentence, nothing cut, nothing swallowing the
words around it); the block's colour kept.
"""
import base64
import functools
import html as htmlmod
import http.server
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

from tests.clip_smoke import EXT, READ_CLIPBOARD, Handler

FIXTURE = Path(__file__).parent / "fixtures" / "math_slides.pdf"
REAL = Path.home() / "Downloads" / "Algs-04-SkipListsTreapsQS.pdf"
PORT = 8823

# (file, page, box as fractions of the page, prose fragments in reading order, prose that must appear once)
CASES = {
    "fixture proof": ("slides.pdf", 2, (0.05, 0.27, 0.985, 0.875),
                      ["Proof.", "Let", "be the tower height of key", "and", "A key reaches level", "only after",
                       "heads in a row, so", "The tower is tall when one key is tall:", "By the union bound",
                       "for any events", "we get:", "For any", "with", "we have"],
                      ["By the union bound", "we get:", "For any", "heads in a row", "The tower is tall"]),
    "fixture theorem": ("slides.pdf", 2, (0.05, 0.09, 0.985, 0.24),
                        ["Theorem", "The height of a random tower over", "keys is", "with high probability."],
                        ["The height of a random tower over"]),
    "fixture title slide": ("slides.pdf", 1, (0.0, 0.0, 1.0, 1.0),
                            ["Height bound", "Every search halves the remaining keys, so after", "levels we reach the bottom."],
                            ["Every search halves"]),
    "real proof": ("real.pdf", 11, (0.012, 0.265, 0.99, 0.835),
                   ["Proof.", "Let", "be height of stack for element", "In order for a search key", "heads in a row",
                    "when it was inserted, so", "We have at least", "levels if and only if", "search keys:",
                    "Using the union bound", "for any random events", "we can simplify this as follows:", "For any", "we have"],
                   ["Using the union bound", "we can simplify", "For any", "heads in a row"]),
}


class RangeHandler(Handler):
    """Static files with HTTP byte ranges, which PDF.js uses (the plain handler made loads flaky)."""
    def send_head(self):
        rng = self.headers.get("Range")
        path = Path(self.translate_path(self.path))
        if not rng or not path.is_file():
            return super().send_head()
        data = path.read_bytes()
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        a = int(m.group(1)) if m.group(1) else 0
        b = int(m.group(2)) if m.group(2) else len(data) - 1
        part = data[a:b + 1]
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {a}-{a + len(part) - 1}/{len(data)}")
        self.send_header("Content-Length", str(len(part)))
        self.end_headers()
        return io.BytesIO(part)

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass                                          # PDF.js cancels the first full download on purpose


def images(html):
    """(alt, width, height, PIL image) of every pasted picture."""
    out = []
    for m in re.finditer(r'<img src="data:image/png;base64,([^"]+)"([^>]*)>', html):
        attrs = m.group(2)
        alt = htmlmod.unescape((re.search(r'alt="([^"]*)"', attrs) or [None, ""])[1])
        w = int((re.search(r'width="(\d+)"', attrs) or [None, 0])[1])
        h = int((re.search(r'height="(\d+)"', attrs) or [None, 0])[1])
        out.append((alt, w, h, Image.open(io.BytesIO(base64.b64decode(m.group(1)))).convert("RGB")))
    return out


def cut(img):
    """True when glyph ink touches an edge of the picture (part of the formula is missing)."""
    w, h = img.size
    px = img.load()
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    bg = max(set(corners), key=corners.count)
    ink = lambda p: sum(abs(a - b) for a, b in zip(p, bg)) > 160
    edges = [(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)] + [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)]
    return sum(ink(px[x, y]) for x, y in edges) > 2


def words(html):
    """The editable text of the paste (pictures removed)."""
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", html)))


def run():
    tmp = Path(tempfile.mkdtemp(prefix="pdf_math_"))
    site = tmp / "site"
    site.mkdir()
    shutil.copy(FIXTURE, site / "slides.pdf")
    have_real = REAL.exists()
    if have_real:
        shutil.copy(REAL, site / "real.pdf")
    got = {}
    launch = lambda p: p.chromium.launch_persistent_context(str(tmp / "profile"), channel="chromium", headless=True,
        viewport={"width": 1400, "height": 1000}, permissions=["clipboard-read", "clipboard-write"],
        args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
    try:
        with sync_playwright() as p:
            # PDFs open from disk (file://), as in clip_smoke: no test server between PDF.js and the file
            launch(p).close()
            prefs_file = tmp / "profile" / "Default" / "Preferences"
            prefs = json.loads(prefs_file.read_text(encoding="utf-8"))
            ext_id = (EXT / "EXTENSION_ID.txt").read_text().strip()
            prefs.setdefault("extensions", {}).setdefault("settings", {}).setdefault(ext_id, {})["newAllowFileAccess"] = True
            prefs_file.write_text(json.dumps(prefs), encoding="utf-8")
            ctx = launch(p)
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
            pages = {}
            for name, (file, page_no, fr, *_ ) in CASES.items():
                if file == "real.pdf" and not have_real:
                    continue
                pg = pages.get(file)
                if not pg:
                    pg = pages[file] = ctx.new_page()
                    for attempt in range(3):                  # the reader's redirect rule is set when the worker starts
                        try:
                            pg.goto((site / file).as_uri())
                            pg.wait_for_url("chrome-extension://**", timeout=8000)
                            break
                        except Exception:
                            print("not redirected:", pg.url)
                            if attempt == 2:
                                raise
                    log = []
                    pg.on("console", lambda m, log=log: log.append(m.text[:200]))
                    pg.on("requestfailed", lambda r, log=log: log.append(f"request failed {r.url[:80]} {r.failure}"))
                    try:
                        pg.wait_for_selector(".page[data-page-number='1'] canvas", timeout=60000)
                    except Exception:
                        print("reader did not render:", pg.url, *log, sep="\n  ")
                        raise
                pg.bring_to_front()
                pg.evaluate(f"() => PDFViewerApplication.page = {page_no}")
                pg.wait_for_selector(f".page[data-page-number='{page_no}'] canvas", timeout=30000)
                pg.wait_for_timeout(1000)
                c = pg.locator(f".page[data-page-number='{page_no}'] .canvasWrapper").bounding_box()
                a = (c["x"] + fr[0] * c["width"] + 1, c["y"] + fr[1] * c["height"] + 1)
                b = (c["x"] + fr[2] * c["width"] - 1, c["y"] + fr[3] * c["height"] - 1)
                sw.evaluate("async () => { const ts = await chrome.tabs.query({ url: 'chrome-extension://*/*', active: true }); await startClip(ts[0]); }")
                pg.wait_for_selector("alto-clip", state="attached", timeout=5000)
                pg.keyboard.press("t")
                pg.mouse.move(*a)
                pg.mouse.down()
                pg.mouse.move(*b, steps=6)
                pg.mouse.up()
                pg.wait_for_function("() => document.querySelector('alto-clip .toast, alto-clip')", timeout=5000)
                pg.wait_for_timeout(2500)
                got[name] = pg.evaluate(READ_CLIPBOARD)
                pg.evaluate("() => navigator.clipboard.writeText('')")
                pg.wait_for_function("() => !document.querySelector('alto-clip')", timeout=15000)
            ctx.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return got, have_real


def main():
    got, have_real = run()
    dump = os.environ.get("CLIP_DEBUG_DIR")                  # set it to look at what each case pasted
    if dump:
        for name, data in got.items():
            Path(dump, name.replace(" ", "_") + ".html").write_text(data.get("text/html", ""), encoding="utf-8")
            Path(dump, name.replace(" ", "_") + ".txt").write_text(data.get("text/plain", ""), encoding="utf-8")
    checks = {}
    for name, (file, _, _, order, once) in CASES.items():
        if name not in got:
            continue
        html, text = got[name].get("text/html", ""), got[name].get("text/plain", "").replace("\r", "")
        prose, imgs = words(html), images(html)
        pos, in_order = 0, True
        for frag in order:
            k = prose.find(frag, pos)
            in_order &= k >= 0
            pos = k + 1 if k >= 0 else pos
        checks[f"{name}: prose is text, in reading order"] = in_order
        checks[f"{name}: no sentence pasted twice"] = all(prose.count(f) == 1 for f in once)
        checks[f"{name}: no picture swallows words"] = not any(f.lower() in alt.lower() for alt, *_ in imgs for f in once)
        checks[f"{name}: no formula picture is cut"] = not any(cut(im) for *_, im in imgs)
        checks[f"{name}: sans text stays sans (no Times)"] = "Times New Roman" not in html
        if "proof" in name:
            line_px = 10.9 * 4 / 3
            checks[f"{name}: formulas are inline pictures, one line high"] = len(imgs) >= 8 and all(h <= line_px * 2.6 for _, _, h, _ in imgs)
            checks[f"{name}: bullets kept"] = text.count("•") == 5
            checks[f"{name}: block colour kept"] = bool(re.search(r"(bgcolor|background(-color)?)[=:]\s*\"?(#f[0-9a-f]{5}|rgb\(2[45]\d, ?2[0-4]\d, ?2[0-4]\d\))", html, re.I))
            checks[f"{name}: plain text reads the formulas"] = re.search(r"Pr\((H|L) ?≥ ?(k|ℓ)\)", text) is not None
        if "theorem" in name:
            checks[f"{name}: italic statement stays italic text"] = "font-style:italic" in html and "The height of a random tower over" in prose
            red = r"(rgb\((1[5-9]\d|2\d\d), ?\d{1,2}, ?\d{1,2}\)|#[89a-f][0-9a-f][0-5][0-9a-f][0-5][0-9a-f])"   # red, any notation
            checks[f"{name}: block title keeps its colour"] = bool(re.search(r"color:" + red + r"[^>]*>Theorem", html, re.I))
    if not have_real:
        print("(real lecture PDF not in Downloads: its cases skipped)")
    for k, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {k}")
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
