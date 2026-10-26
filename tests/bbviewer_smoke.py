"""Alt+L on a PDF shown inside Blackboard's own file viewer (headless Chromium, fake Blackboard).

    python -m tests.bbviewer_smoke

Blackboard Ultra documents list their files ("Algs-01-Cuckoo.pdf", "Algs-04-SkipListsTreapsQS.pdf"...); expanding
one opens a viewer under it (Page N of M, zoom, download) that shows the pages as pictures. Alt+L there must read
the real PDF - the file named above the viewer, found through Blackboard's REST API like the scanner does - work out
which page and where the box is from the screenshot, and paste the same thing as the built-in reader would.

The viewer is faked three ways (page images in the page, canvases in a same-origin iframe, a cross-origin iframe)
because Blackboard's own markup is not public and can change.
"""
import functools
import http.server
import io
import json
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import fitz
from playwright.sync_api import sync_playwright

from tests.clip_smoke import EXT, READ_CLIPBOARD

FIXTURE = Path(__file__).parent / "fixtures" / "math_slides.pdf"
PORT, OTHER = 8825, 8826                      # Blackboard, and another origin for the cross-origin viewer
C = "/learn/api/public"
WIDTH = 760                                   # page width on screen, CSS px
PROOF = (0.05, 0.27, 0.985, 0.875)            # the proof box on page 2, fractions of the page
hits = {}


def cuckoo_pdf():
    doc = fitz.open()
    for k in range(3):
        p = doc.new_page(width=453.5, height=255.1)
        p.insert_text((40, 80), f"Cuckoo hashing, slide {k + 1}", fontsize=20)
    return doc.tobytes()


def viewer_html(variant, n_pages, toolbar_page):
    pages = "".join(f'<div class="pg"><img src="/render/p{k}.png" width="{WIDTH}"></div>' for k in range(1, n_pages + 1))
    if variant == "canvas":
        body = f'<iframe id="vf" src="/viewer-frame?n={n_pages}" style="width:100%;height:620px;border:0"></iframe>'
    elif variant == "xorigin":
        body = f'<iframe id="vf" src="http://127.0.0.1:{OTHER}/viewer-frame?n={n_pages}" style="width:100%;height:620px;border:0"></iframe>'
    else:
        body = f'<div id="scroller" class="scroller">{pages}</div>'
    return f"""<div class="viewer"><div class="bar">‹ Page <input value="{toolbar_page}" size=2> of {n_pages} ›
      <span>− + ⛶</span></div>{body}</div>"""


def page_html(variant, toolbar_page, icon="▤", loaded=False):
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Lecture Slides</title><style>
      body{{font-family:Segoe UI,Arial;margin:0;background:#fff}} .row{{display:flex;gap:12px;padding:18px 24px;background:#f7f7f7;margin:8px 20px;font-weight:600}}
      .viewer{{margin:0 20px;background:#e8eaed}} .bar{{background:#262b33;color:#fff;padding:12px 20px}}
      .scroller{{height:620px;overflow:auto}} .pg{{width:{WIDTH}px;margin:16px auto;background:#fff;box-shadow:0 1px 4px #0004}}
      .pg img{{display:block}}</style></head><body>
      <h2 style="margin:16px 24px;color:#c00">Lecture Slides</h2>
      <div class="row">{icon} Algs-01-Cuckoo.pdf</div>
      <div class="row">{icon} Algs-04-SkipListsTreapsQS.pdf <span style="margin-left:auto">⌃</span></div>
      {viewer_html(variant, 3, toolbar_page)}
      <div style="height:400px"></div>
      {"<script>fetch('/bbcswebdav/xid-14_1')</script>" if loaded else ""}</body></html>"""


NEWS = """<!doctype html><html><head><title>News</title></head><body style="font-family:Georgia;margin:40px">
  <h1>Campus news</h1><p>A photo from the open day.</p><img id="photo" src="/render/p2.png" width="760"></body></html>"""


def frame_html(n):
    pages = "".join(f'<div class="pg"><canvas id="c{k}"></canvas></div>' for k in range(1, n + 1))
    draw = "".join(f"""{{const i=new Image();i.onload=()=>{{const c=document.getElementById('c{k}');c.width=i.width;c.height=i.height;
      c.style.width='{WIDTH}px';c.getContext('2d').drawImage(i,0,0);}};i.src='http://127.0.0.1:{PORT}/render/p{k}.png';}}""" for k in range(1, n + 1))
    return f"""<!doctype html><html><head><style>body{{margin:0;background:#e8eaed}}
      .pg{{width:{WIDTH}px;margin:16px auto;background:#fff}} canvas{{display:block}}</style></head>
      <body>{pages}<script>{draw}</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    renders = {}
    pdfs = {}

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype, extra=()):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(data)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        path = u.path
        hits[path] = hits.get(path, 0) + 1
        m = re.match(r"/ultra/courses/(_\d+_1)/document/(_\d+_1)$", path)
        if m:
            return self._send(200, page_html(q.get("v", ["img"])[0], q.get("page", ["2"])[0], q.get("icon", ["▤"])[0],
                                             q.get("loaded", ["0"])[0] == "1"), "text/html")
        if path == "/news":
            return self._send(200, NEWS, "text/html")
        if path == "/viewer-frame":
            return self._send(200, frame_html(int(q["n"][0])), "text/html")
        m = re.match(r"/render/p(\d+)\.png$", path)
        if m:
            return self._send(200, self.renders[int(m.group(1))], "image/png")
        if path.startswith("/bbcswebdav/"):
            name = path.rsplit("/", 1)[-1]
            if name in self.pdfs:
                return self._send(200, self.pdfs[name], "application/pdf")
            return self._send(404, "", "text/plain")
        api = {
            f"{C}/v3/courses/_1_1": {"courseId": "COMP3811_2026", "name": "Algorithms"},
            f"{C}/v1/courses/_1_1/contents/_5_1": {"id": "_5_1", "title": "Lecture Slides", "contentHandler": {"id": "resource/x-bb-document"}},
            f"{C}/v1/courses/_1_1/contents/_5_1/children": {"results": [
                {"id": "_6_1", "title": "ultraDocumentBody", "contentHandler": {"id": "resource/x-bb-document"}}]},
            f"{C}/v1/courses/_1_1/contents/_6_1": {"id": "_6_1", "title": "ultraDocumentBody", "contentHandler": {"id": "resource/x-bb-document"},
                "body": '<p><a href="@X@EmbeddedFile.requestUrlStub@X@bbcswebdav/xid-11_1" data-bbfile=\'{"linkName":"Algs-01-Cuckoo.pdf"}\'>Algs-01-Cuckoo.pdf</a></p>'
                        '<p><a href="@X@EmbeddedFile.requestUrlStub@X@bbcswebdav/xid-14_1" data-bbfile=\'{"linkName":"Algs-04-SkipListsTreapsQS.pdf"}\'>Algs-04-SkipListsTreapsQS.pdf</a></p>'},
            # a course whose files can't be found anywhere
            f"{C}/v3/courses/_2_1": {"courseId": "COMP9999_2026", "name": "Nowhere"},
            f"{C}/v3/courses/_3_1": {"courseId": "COMP3811_2026", "name": "Algorithms"},
            f"{C}/v1/courses/_3_1/contents/_8_1": {"id": "_8_1", "title": "Slides", "contentHandler": {"id": "resource/x-bb-document"}, "body": ""},
            f"{C}/v1/courses/_2_1/contents/_7_1": {"id": "_7_1", "title": "Slides", "contentHandler": {"id": "resource/x-bb-document"}, "body": ""},
        }
        if path in api:
            return self._send(200, json.dumps(api[path]), "application/json")
        if path.startswith(C) and (path.endswith("/children") or path.endswith("/attachments")):
            return self._send(200, json.dumps({"results": []}), "application/json")
        return self._send(404, "{}", "application/json")


class Server(http.server.ThreadingHTTPServer):
    """The default queue holds 5 pending connections; on Windows, Chrome's parallel requests beyond that are reset,
    so pictures failed to load at random. A longer queue makes the fake site dependable."""
    request_queue_size = 128
    daemon_threads = True


# Positions the viewer deterministically: waits until every page picture/canvas is drawn, then sets the scroll so
# the page (or the gap between two pages) is in the middle of the viewer. Returns the pages' screen rectangles.
SHOW = """async (root, [first, last, selector, scroller]) => {
  const doc = root.ownerDocument;
  const pages = [...doc.querySelectorAll(selector)];
  const drawn = (p) => (p.tagName === "IMG" ? p.complete && p.naturalWidth > 0 : p.width > 300);
  for (let k = 0; k < 200 && !pages.every(drawn); k++) await new Promise((r) => setTimeout(r, 50));   // up to 10 s
  const sc = scroller ? doc.querySelector(scroller) : doc.scrollingElement;
  const base = sc === doc.scrollingElement ? 0 : sc.getBoundingClientRect().top;
  const top = (el) => el.getBoundingClientRect().top - base + sc.scrollTop;
  const a = pages[first - 1], b = pages[last - 1];
  sc.scrollTop = first === last ? top(a) + a.offsetHeight / 2 - sc.clientHeight / 2 : top(b) - sc.clientHeight / 2;
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
}"""


def show(pg, variant, first, last):
    if variant == "img":
        pg.locator("html").evaluate(SHOW, [first, last, "#scroller .pg img", "#scroller"])
        return [pg.locator(f"#scroller .pg:nth-child({n}) img").bounding_box() for n in (first, last)]
    frame = pg.frame_locator("#vf")
    frame.locator("html").evaluate(SHOW, [first, last, "canvas", None])
    return [frame.locator(f"#c{n}").bounding_box() for n in (first, last)]


def clip(pg, sw, base, a, b):
    sw.evaluate(f"async () => {{ const [t] = await chrome.tabs.query({{ url: '{base}/*' }}); await startClip(t); }}")
    pg.wait_for_selector("alto-clip", state="attached", timeout=5000)
    pg.mouse.move(*a)
    pg.mouse.down()
    pg.mouse.move(*b, steps=6)
    pg.mouse.up()
    pg.wait_for_selector("alto-clip[data-message]", state="attached", timeout=60000)   # the clip is done
    toast = pg.evaluate("() => document.querySelector('alto-clip[data-message]').dataset.message")
    trace = json.loads(pg.evaluate("() => document.querySelector('alto-clip[data-message]').dataset.trace || 'null'"))
    data = pg.evaluate(READ_CLIPBOARD)
    pg.evaluate("() => navigator.clipboard.writeText('')")
    pg.wait_for_function("() => !document.querySelector('alto-clip')", timeout=15000)
    data["toast"] = toast
    data["trace"] = trace
    return data


def main():
    doc = fitz.open(FIXTURE)
    zoom = 2 * WIDTH / doc[0].rect.width          # page pictures at twice the screen size, like a viewer would
    Handler.renders = {k + 1: doc[k].get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png") for k in range(doc.page_count)}
    Handler.pdfs = {"xid-14_1": FIXTURE.read_bytes(), "xid-11_1": cuckoo_pdf()}
    servers = [Server(("127.0.0.1", port), Handler) for port in (PORT, OTHER)]
    for s in servers:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{PORT}"
    tmp = Path(tempfile.mkdtemp(prefix="bbviewer_"))
    got = {}
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(str(tmp / "profile"), channel="chromium", headless=True,
                viewport={"width": 1200, "height": 900}, permissions=["clipboard-read", "clipboard-write"],
                args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
            pg = ctx.new_page()
            pg.on("console", lambda m: print("  console:", m.text[:300]) if "Alt+L" in m.text else None)
            pg.add_init_script("document.addEventListener('DOMContentLoaded', () => document.documentElement.dataset.altoDebug = '1')")

            def run(name, variant="img", toolbar=2, course="_1_1", item="_5_1", frs=PROOF, pages=(2,), reload=True, extra=""):
                if reload:
                    pg.goto(f"{base}/ultra/courses/{course}/document/{item}?v={variant}&page={toolbar}{extra}")
                    pg.wait_for_timeout(1500)
                if "loaded=1" in extra:                 # the page's own download of the PDF has finished
                    pg.wait_for_function("() => performance.getEntriesByType('resource').some((e) => /xid-14_1/.test(e.name) && e.responseEnd > 0)")
                first, last = show(pg, variant, pages[0], pages[-1])
                for b in (first, last):                 # a page not drawn is the test's fault, never Alt+L's
                    if not b or b["height"] < 100:
                        raise RuntimeError(f"{name}: the viewer's page is not drawn ({b})")
                a = (first["x"] + frs[0] * first["width"], first["y"] + frs[1] * first["height"])
                b = (last["x"] + frs[2] * last["width"], last["y"] + frs[3] * last["height"])
                got[name] = clip(pg, sw, base, a, b)

            run("page images")
            fetched = hits.get("/bbcswebdav/xid-14_1", 0)
            run("page images again (cached)", reload=False)   # a second Alt+L on the same slides
            refetched = hits.get("/bbcswebdav/xid-14_1", 0) - fetched
            run("toolbar shows the wrong page", toolbar=1)
            run("canvases in an iframe", variant="canvas")
            run("cross-origin viewer", variant="xorigin")
            run("no PDF to be found", course="_2_1", item="_7_1")
            # a box from the bottom of slide 1 to the middle of slide 2's theorem, across the gap between pages
            run("across two pages", frs=(0.03, 0.25, 0.98, 0.22), pages=(1, 2))
            run("file name with an emoji", extra="&icon=%F0%9F%93%84")
            run("PDF only among what the page loaded", course="_3_1", item="_8_1", extra="&loaded=1")
            # an ordinary page with a big photo: not a viewer, so no PDF note and the usual web clip
            pg.goto(f"{base}/news")
            pg.wait_for_function("() => document.getElementById('photo').complete")
            ph = pg.locator("#photo").bounding_box()
            got["ordinary page with a photo"] = clip(pg, sw, base, (ph["x"] + 20, ph["y"] + 20), (ph["x"] + ph["width"] - 20, ph["y"] + ph["height"] - 20))
            ctx.close()
    finally:
        for s in servers:
            s.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    def prose(name):
        return re.sub(r"\s+", " ", got[name].get("text/plain", ""))
    proof = ["By the union bound", "for any events", "we get:", "For any", "we have"]
    checks = {}
    for name in ("page images", "toolbar shows the wrong page", "canvases in an iframe", "cross-origin viewer"):
        html = got[name].get("text/html", "")
        checks[f"{name}: the slide's text, from the PDF"] = all(f in prose(name) for f in proof)
        checks[f"{name}: formulas as pictures, bullets kept"] = len(re.findall(r"<img ", html)) >= 8 and prose(name).count("•") == 5
        checks[f"{name}: right file (not the other PDF listed)"] = "Cuckoo" not in prose(name)
        checks[f"{name}: says which page"] = "page 2" in got[name]["toast"]
    checks["the PDF is downloaded once, then reused"] = fetched == 1 and refetched == 0 and all(f in prose("page images again (cached)") for f in proof)
    nf = got["no PDF to be found"]
    checks["no PDF to be found: still copies the picture, says why"] = nf.get("image/png", 0) > 1000 and re.search(r"PDF", nf["toast"]) is not None
    for name in ("file name with an emoji", "PDF only among what the page loaded"):
        checks[f"{name}: the slide's text, from the PDF"] = all(f in prose(name) for f in proof)
    tr = got["page images"]["trace"] or {}
    checks["trace: viewer, file chosen by the name above it, page 2 by matching"] = tr.get("viewer") == "img" and         (tr.get("file") or {}).get("name") == "Algs-04-SkipListsTreapsQS.pdf" and (tr.get("match") or {}).get("page") == 2
    checks["trace: no PDF to be found stops at the file stage"] = (got["no PDF to be found"]["trace"] or {}).get("failed") == "file"
    op = got["ordinary page with a photo"]
    checks["ordinary page with a photo: not a viewer, no PDF note"] = (op["trace"] or {}).get("viewer") is None and "PDF" not in op["toast"]
    two = prose("across two pages")
    checks["across two pages: both pages, in order"] = "reach the bottom" in two and "The height of a random tower" in two and \
        two.find("reach the bottom") < two.find("The height of a random tower")
    for name, data in got.items():
        print(f"[{name}] toast: {data.get('toast', '')[:200]!r}")
        print(f"    trace: {json.dumps(data.get('trace'))[:600]}")
    for k, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {k}")
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
