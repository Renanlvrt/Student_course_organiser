"""Persistent move log (data/log.json) and small UI state (data/state.json)."""
import json
import os
import threading
import time
import uuid
from pathlib import Path


def _atomic_write(path, data):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class Log:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.listeners = []
        try:
            self.entries = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.entries = []

    def _save(self):
        _atomic_write(self.path, self.entries)

    def add(self, **fields):
        e = {"id": uuid.uuid4().hex[:12], "time": time.strftime("%Y-%m-%d %H:%M:%S"), "extras": [], **fields}
        with self._lock:
            self.entries.append(e)
            self._save()
        self._notify(e)
        return e

    def update(self, entry_id, **fields):
        with self._lock:
            e = self.get(entry_id)
            if e is None:
                return None
            e.update(fields)
            self._save()
        self._notify(e)
        return e

    def get(self, entry_id):
        with self._lock:
            return next((e for e in self.entries if e["id"] == entry_id), None)

    def recent(self, n=40):
        with self._lock:
            return list(reversed(self.entries[-n:]))

    def repath(self, old_prefix, new_prefix):
        """A folder was renamed: fix every stored path below it."""
        old_prefix, new_prefix = str(old_prefix), str(new_prefix)
        with self._lock:
            for e in self.entries:
                for k in ("current_path",):
                    v = e.get(k) or ""
                    if v == old_prefix or v.startswith(old_prefix + os.sep):
                        e[k] = new_prefix + v[len(old_prefix):]
                e["extras"] = [new_prefix + x[len(old_prefix):] if x.startswith(old_prefix + os.sep) else x
                               for x in e.get("extras", [])]
            self._save()

    def _notify(self, e):
        for cb in list(self.listeners):
            try:
                cb(e)
            except Exception:
                pass


class State:
    def __init__(self, path):
        self.path = Path(path)
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def get(self, k, default=None):
        return self.data.get(k, default)

    def set(self, k, v):
        self.data[k] = v
        _atomic_write(self.path, self.data)
