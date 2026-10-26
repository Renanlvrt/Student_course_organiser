"""Smoke test for the Blackboard "Scan sections" collector (extension/content.js + bbparse.js), against a fake
Blackboard REST API that reproduces the ways files hide in Ultra courses.

    python -m tests.scan_smoke

Every one of these must be found: a file item, a document whose file sits in its hidden "ultraDocumentBody"
child, a file embedded in a document body behind Ultra's @X@ placeholder, an extension-less link that is really a
PDF, a text-only page (saved as .html), a link to another item of the course, and the Assessment section.
"""
import functools
import http.server
import json
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"
PORT = 8811
C = "/learn/api/public"
LONG = "<p>" + "Clone the practical repository, build with make and run each exercise under gdb. " * 3 + "</p>"
FOLDER, DOC, FILE, LINK, COURSELINK = ("resource/x-bb-folder", "resource/x-bb-document", "resource/x-bb-file",
                                       "resource/x-bb-externallink", "resource/x-bb-courselink")
LESSON = "resource/x-bb-lesson"
API = {
    f"{C}/v3/courses/_1_1": {"courseId": "COMP3761_2026", "name": "Applied Security"},
    f"{C}/v1/courses/_1_1/contents": {"results": [
        {"id": "_10_1", "title": "Teaching Materials", "hasChildren": True, "contentHandler": {"id": FOLDER}},
        {"id": "_20_1", "title": "Assessment", "hasChildren": True, "contentHandler": {"id": FOLDER}}]},
    f"{C}/v1/courses/_1_1/contents/_10_1/children": {"results": [
        {"id": "_11_1", "title": "Lecture slides (term 1)", "hasChildren": True, "contentHandler": {"id": FOLDER}},
        {"id": "_12_1", "title": "Practical 1 - 3: Buffer overflows and fuzzing", "hasChildren": False, "contentHandler": {"id": DOC}},
        {"id": "_13_1", "title": "Repository for practicals", "hasChildren": False, "contentHandler": {"id": LINK, "url": f"http://127.0.0.1:{PORT}/web/repo"}},
        {"id": "_14_1", "title": "Reading guidance", "hasChildren": False, "contentHandler": {"id": DOC}},
        {"id": "_15_1", "title": "Exam notes", "hasChildren": False, "contentHandler": {"id": LINK, "url": f"http://127.0.0.1:{PORT}/files/notes"}},
        {"id": "_16_1", "title": "Shortcut to the coversheet", "hasChildren": False, "contentHandler": {"id": COURSELINK, "targetId": "_21_1"}}]},
    f"{C}/v1/courses/_1_1/contents/_11_1/children": {"results": [
        {"id": "_111_1", "title": "week12-buffer-overflows.pdf", "hasChildren": False, "contentHandler": {"id": FILE}}]},
    f"{C}/v1/courses/_1_1/contents/_111_1/attachments": {"results": [{"id": "_a1_1", "fileName": "week12.pdf"}]},
    f"{C}/v1/courses/_1_1/contents/_12_1": {"id": "_12_1", "title": "Practical 1 - 3: Buffer overflows and fuzzing", "contentHandler": {"id": DOC},
        "body": '<p>Sheet: <a href="@X@EmbeddedFile.requestUrlStub@X@bbcswebdav/xid-555_1" data-bbfile=\'{"linkName":"practical1.pdf"}\'>practical1.pdf</a></p>'},
    f"{C}/v1/courses/_1_1/contents/_12_1/children": {"results": [{"id": "_121_1", "title": "ultraDocumentBody", "hasChildren": False, "contentHandler": {"id": DOC}}]},
    f"{C}/v1/courses/_1_1/contents/_121_1/attachments": {"results": [{"id": "_a2_1", "fileName": "practical-sheet.pdf"}]},
    f"{C}/v1/courses/_1_1/contents/_14_1": {"id": "_14_1", "title": "Reading guidance", "contentHandler": {"id": DOC}, "body": LONG},
    f"{C}/v1/courses/_1_1/contents/_20_1/children": {"results": [
        {"id": "_21_1", "title": "COMP3761 Security In-year test Coversheet.pdf", "hasChildren": False, "contentHandler": {"id": FILE}}]},
    f"{C}/v1/courses/_1_1/contents/_21_1": {"id": "_21_1", "title": "COMP3761 Security In-year test Coversheet.pdf", "hasChildren": False, "contentHandler": {"id": FILE}},
    f"{C}/v1/courses/_1_1/contents/_21_1/attachments": {"results": [{"id": "_a3_1", "fileName": "coversheet.pdf"}]},
    # A second layout: terms > weeks > learning modules, practicals in their own section, a file at the top level.
    f"{C}/v3/courses/_2_1": {"courseId": "COMP2221_2026", "name": "Programming Paradigms"},
    f"{C}/v1/courses/_2_1/contents": {"results": [
        {"id": "_30_1", "title": "Announcements", "hasChildren": False, "contentHandler": {"id": DOC}},
        {"id": "_31_1", "title": "Term1 [Functional]", "hasChildren": True, "contentHandler": {"id": FOLDER}},
        {"id": "_32_1", "title": "Epiphany term", "hasChildren": True, "contentHandler": {"id": FOLDER}},
        {"id": "_33_1", "title": "Practicals", "hasChildren": True, "contentHandler": {"id": FOLDER}},
        {"id": "_34_1", "title": "Module handbook.pdf", "hasChildren": False, "contentHandler": {"id": FILE}}]},
    f"{C}/v1/courses/_2_1/contents/_31_1/children": {"results": [
        {"id": "_311_1", "title": "Week 3", "hasChildren": True, "contentHandler": {"id": FOLDER}}]},
    f"{C}/v1/courses/_2_1/contents/_311_1/children": {"results": [
        {"id": "_3111_1", "title": "Lecture 5: Monads", "hasChildren": True, "contentHandler": {"id": LESSON}}]},
    f"{C}/v1/courses/_2_1/contents/_3111_1/children": {"results": [
        {"id": "_31111_1", "title": "Slides", "hasChildren": False, "contentHandler": {"id": FILE}}]},
    f"{C}/v1/courses/_2_1/contents/_31111_1/attachments": {"results": [{"id": "_b1_1", "fileName": "monads.pdf"}]},
    f"{C}/v1/courses/_2_1/contents/_32_1/children": {"results": [
        {"id": "_321_1", "title": "Lecture 12 (no file, written page)", "hasChildren": False, "contentHandler": {"id": DOC}}]},
    f"{C}/v1/courses/_2_1/contents/_321_1": {"id": "_321_1", "title": "Lecture 12 (no file, written page)", "contentHandler": {"id": DOC}, "body": LONG},
    f"{C}/v1/courses/_2_1/contents/_33_1/children": {"results": [
        {"id": "_331_1", "title": "Practical 2", "hasChildren": True, "contentHandler": {"id": FOLDER}}]},
    f"{C}/v1/courses/_2_1/contents/_331_1/children": {"results": [
        {"id": "_3311_1", "title": "Exercises", "hasChildren": False, "contentHandler": {"id": DOC}}]},
    f"{C}/v1/courses/_2_1/contents/_3311_1/attachments": {"results": [{"id": "_b2_1", "fileName": "prac2.zip"}]},
    f"{C}/v1/courses/_2_1/contents/_34_1/attachments": {"results": [{"id": "_b3_1", "fileName": "handbook.pdf"}]},
}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/course":
            return self._send(200, "<html><body>COMP3761 course page</body></html>", "text/html")
        if path == "/files/notes":
            return self._send(200, b"%PDF-1.4 fake", "application/pdf")
        if path == "/web/repo":
            return self._send(200, "<html><body>a git repository web page</body></html>", "text/html")
        if path in API:
            return self._send(200, json.dumps(API[path]), "application/json")
        if path.startswith(C) and (path.endswith("/children") or path.endswith("/attachments")):
            return self._send(200, json.dumps({"results": []}), "application/json")
        if path.startswith(C + "/v1/courses/_1_1/contents/"):
            cid = path.rsplit("/", 1)[-1]
            return self._send(200, json.dumps({"id": cid, "title": cid, "contentHandler": {"id": DOC}}), "application/json")
        return self._send(404, "{}", "application/json")


def main():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{PORT}"
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(tempfile.mkdtemp(), channel="chromium", headless=True,
                args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
            page = ctx.new_page()
            page.goto(base + "/course")
            res, res2 = sw.evaluate(f"""async () => {{
              const [t] = await chrome.tabs.query({{ url: '{base}/*' }});
              await chrome.scripting.executeScript({{ target: {{ tabId: t.id }}, files: ['bbparse.js', 'content.js'] }});
              const go = (courseId, sectionIds) => chrome.tabs.sendMessage(t.id, {{ type: 'collect', courseId, sectionIds }}, {{ frameId: 0 }});
              return [await go('_1_1', ['_10_1', '_20_1']), await go('_2_1', ['_31_1', '_32_1', '_33_1', '_34_1'])];
            }}""")
            ctx.close()
    finally:
        srv.shutdown()
    names = sorted(f["fileName"] for f in res.get("files", []))
    print("found:", names)
    print("skipped:", [k["text"] for k in res.get("skipped", [])])
    by_name = {f["fileName"]: f for f in res2.get("files", [])}
    print("layout 2:", {n: f["ctx"]["chain"] for n, f in by_name.items()})
    checks = {
        "file item (lecture slides)": "week12.pdf" in names,
        "document's hidden ultraDocumentBody attachment": "practical-sheet.pdf" in names,
        "file behind Ultra's @X@ placeholder link": "practical1.pdf" in names,
        "extension-less link that is a PDF, named with .pdf": "Exam notes.pdf" in names,
        "text-only page kept as .html": "Reading guidance.html" in names,
        "Assessment section": "coversheet.pdf" in names,
        "placeholder link resolved to the real address": any("/bbcswebdav/xid-555_1" in f["url"] and "@X@" not in f["url"]
                                                           for f in res.get("files", [])),
        "web pages are still listed as skipped, not lost": any("Repository" in k["text"] or "repo" in k.get("href", "") for k in res.get("skipped", [])),
        "terms > weeks > learning module: file found": "monads.pdf" in by_name,
        "  ... with its folder path (for Term 1 / Lecture 5)": by_name.get("monads.pdf", {}).get("ctx", {}).get("chain", [])[-1:] == ["Term1 [Functional]"],
        "practicals-only section": "prac2.zip" in by_name and "Practical 2" in by_name["prac2.zip"]["ctx"]["chain"],
        "file sitting at the top level": "handbook.pdf" in by_name,
        "written lecture page in a term folder": any(n.startswith("Lecture 12") and n.endswith(".html") for n in by_name),
        "no duplicates": len(names) == len(set(f["key"] for f in res.get("files", []))),
    }
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
