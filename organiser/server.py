"""Localhost endpoint for the Chrome extension. Binding the port doubles as the single-instance lock."""
import json
import logging
import socket
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import rules

log = logging.getLogger("organiser.server")


class AlreadyRunning(Exception):
    pass


class _ExclusiveServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR lets a second process bind the same port; we need the opposite.
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(core, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _allowed(self):
            origin = self.headers.get("Origin", "")
            return origin == "" or origin.startswith("chrome-extension://")

        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            origin = self.headers.get("Origin", "")
            if origin.startswith("chrome-extension://"):
                self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            if not self._allowed():
                return self._send(403, {"error": "origin"})
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", ""))
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            if not self._allowed():
                return self._send(403, {"error": "origin"})
            if self.path.startswith("/status"):
                core.extension_seen = time.time()
                return self._send(200, {"app": "alt-o-organiser", "active": core.active,
                                        "module": core.pick_module})
            if self.path.startswith("/recent"):
                return self._send(200, {"entries": [_entry_view(core, e) for e in core.log.recent(80)]})
            if self.path.startswith("/taxonomy"):
                cfg = core.cfg
                return self._send(200, {
                    "modules": [{"key": m.key, "name": m.name, "parts": m.parts} for m in cfg.modules],
                    "part_categories": cfg.part_categories, "module_categories": cfg.module_categories})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._allowed():
                return self._send(403, {"error": "origin"})
            try:
                n = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(min(n, 1_000_000)) or b"{}")
            except ValueError:
                return self._send(400, {"error": "bad json"})
            if self.path == "/context":
                core.add_context(_clean_ctx(data))
                return self._send(200, {"ok": True, "active": core.active})
            if self.path == "/already":
                # Same original name already sorted into the same module (week1.pdf repeats across modules).
                names = {str(n).lower() for n in data.get("names", [])}
                module = rules.module_from_code(core.cfg, str(data.get("course_code", "")))
                have = set()
                for e in core.log.entries:
                    if e.get("status") in ("sorted", "flagged", "duplicate") and \
                            e.get("original_name", "").lower() in names and \
                            (e.get("classification") or {}).get("module") == module:
                        have.add(e["original_name"].lower())
                return self._send(200, {"have": sorted(have)})
            if self.path == "/move":
                # Same code path as the dashboard: one worker thread does every file move.
                done, box = threading.Event(), {}
                changes = {k: data[k] for k in ("module", "part", "category", "number", "topic") if k in data}

                def job():
                    try:
                        box["r"] = core.reassign(str(data.get("id", "")), **changes)
                    finally:
                        done.set()
                core.submit(job)
                if not done.wait(60):
                    return self._send(504, {"error": "timed out"})
                r = box.get("r")
                if isinstance(r, str) or r is None:
                    return self._send(200, {"ok": False, "error": r or "not found"})
                return self._send(200, {"ok": True, "entry": _entry_view(core, r)})
            if self.path == "/undo":
                done, box = threading.Event(), {}

                def job():
                    try:
                        box["r"] = core.undo(str(data.get("id", "")))
                    finally:
                        done.set()
                core.submit(job)
                done.wait(60)
                return self._send(200, {"ok": bool(box.get("r"))})
            self._send(404, {"error": "not found"})

    try:
        srv = _ExclusiveServer(("127.0.0.1", port), Handler)
    except OSError as e:
        raise AlreadyRunning(str(e)) from e
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True, name="http").start()
    return srv


def _clean_ctx(d):
    def s(v, n=300):
        return str(v or "")[:n]
    return {
        "path": s(d.get("path"), 1000),
        "url": s(d.get("url"), 1000),
        "course_code": s(d.get("course_code"), 80),
        "course_name": s(d.get("course_name"), 200),
        "chain": [s(x, 200) for x in (d.get("chain") or [])][:12],
        "prev_chain": [s(x, 200) for x in (d.get("prev_chain") or [])][:12],
        "item_title": s(d.get("item_title"), 200),
        "link_text": s(d.get("link_text"), 120),
        "source": s(d.get("source"), 20),
    }


def _entry_view(core, e):
    """What the extension needs to draw one file in the recap tree."""
    c = e.get("classification") or {}
    cur = e.get("current_path", "")
    try:
        rel = list(Path(cur).relative_to(core.cfg.root_folder).parts)
    except ValueError:
        rel = None                       # still in Downloads (duplicate / skipped / undone)
    return {"id": e["id"], "time": e.get("time"), "original_path": e.get("original_path"),
            "original_name": e.get("original_name"), "name": Path(cur).name if cur else "",
            "rel": rel, "status": e.get("status"), "message": e.get("message", ""),
            "where": core.short_dest(cur), "module": c.get("module"), "part": c.get("part"),
            "category": c.get("category"), "number": c.get("number"), "topic": c.get("topic")}
