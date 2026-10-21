"""Wiring: Tk main loop + hotkey + tray + localhost server + engine."""
import ctypes
import logging
import os
import queue
import sys
import time
import tkinter as tk
from logging.handlers import RotatingFileHandler

from .config import load_config
from .core import Organiser
from .server import AlreadyRunning, make_server

log = logging.getLogger("organiser")


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.uiq = queue.Queue()
        self.core = Organiser(cfg)
        self._last_toggle = 0.0
        self._quitting = False

    def run(self):
        from . import ui
        from .tray import Tray
        try:
            self.server = make_server(self.core, self.cfg.port)
        except AlreadyRunning:
            log.warning("Another instance is already running (port %s busy); exiting.", self.cfg.port)
            return 1
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        self.root = tk.Tk()
        self.root.withdraw()
        self.scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        self.tray = Tray(self.uiq, self.cfg.hotkey)
        self.core.notify = self.toast
        self.core.on_tagged = lambda e: self.uiq.put(("tagged",))
        self.core.on_show = lambda: self.uiq.put(("show",))
        self.core.state_listeners.append(lambda: self.uiq.put(("state",)))
        self.core.log.listeners.append(lambda e: self.uiq.put(("entry",)))
        self.core.start()
        self.dashboard = ui.Dashboard(self)
        self.tray.start()
        self._register_hotkey()
        self.root.after(100, self._poll)
        log.info("Organiser started. Root=%s Downloads=%s", self.cfg.root_folder, self.cfg.downloads_folder)
        self.root.mainloop()
        return 0

    def _register_hotkey(self):
        from .hotkey import Hotkey
        self.hotkey = Hotkey(self.cfg.hotkey, lambda: self.uiq.put(("toggle",)))
        try:
            mode = self.hotkey.start()
            self.core.hotkey_mode = mode
            log.info("Hotkey %s: %s", self.cfg.hotkey, mode)
        except Exception:
            log.exception("Could not register hotkey %s", self.cfg.hotkey)
            self.toast("Hotkey problem", f"Could not register {self.cfg.hotkey}; use the tray icon.")

    # ------------------------------------------------------------------ UI queue
    def _poll(self):
        if self._quitting:
            return
        try:
            while not self._quitting:
                msg = self.uiq.get_nowait()
                try:
                    self._handle(msg)
                except Exception:
                    log.exception("UI handler failed for %s", msg[0])
        except queue.Empty:
            pass
        if not self._quitting:
            self.root.after(100, self._poll)

    def _handle(self, msg):
        kind = msg[0]
        if kind == "toggle":
            if time.time() - self._last_toggle < 0.4:   # key repeat / double fire
                return
            self._last_toggle = time.time()
            self.set_active(not self.core.active)
        elif kind == "show":
            self.dashboard.show()
        elif kind == "state":
            self.dashboard.update_state()
            label = self.core.pick_module or "Auto"
            self.tray.set_active(self.core.active, label)
        elif kind == "entry":
            if self.dashboard.visible:
                self.dashboard.refresh()
        elif kind == "tagged":  # extension download sorted: show where it went, even when Alt+O is off
            if not self.dashboard.visible:
                self.dashboard.show()
            self.dashboard.refresh()
        elif kind == "call":
            msg[1]()
        elif kind == "fix_result":
            entry_id, res, changes = msg[1], msg[2], msg[3]
            if res == "need_part":
                self.dashboard.open_editor(entry_id, changes or {}, "Which part does it belong to?")
            elif res == "need_module":
                self.dashboard.open_editor(entry_id, changes or {}, "Pick a module")
        elif kind == "sort_existing":
            self.open_sort_existing()
        elif kind == "migration":
            self.open_migration()
        elif kind == "open_root":
            os.startfile(str(self.cfg.root_folder))
        elif kind == "open_log":
            os.startfile(str(self.cfg.data_dir / "log.json")) if (self.cfg.data_dir / "log.json").exists() \
                else os.startfile(str(self.cfg.data_dir))
        elif kind == "quit":
            self.quit()

    # ------------------------------------------------------------------ actions
    def set_active(self, on, module=None):
        if on:
            self.core.activate(module, None)
            self.dashboard.show()
            self.toast("Organiser ON", "Pick a module on the dashboard (Auto = AI decides)")
        else:
            self.core.deactivate()
            self.dashboard.hide()
            self.toast("Organiser OFF", "Downloads are no longer sorted")

    def run_fix(self, entry_id, changes):
        def job():
            if changes is None:
                res = self.core.accept(entry_id)
            else:
                res = self.core.reassign(entry_id, **changes)
            self.uiq.put(("fix_result", entry_id, res if isinstance(res, str) else None, changes))
        self.core.submit(job)

    def toast(self, title, msg):
        if hasattr(self, "tray"):
            self.tray.notify(title, msg)

    def open_sort_existing(self):
        from .ui import PreviewWindow
        PreviewWindow(self, "existing")

    def open_migration(self):
        from .ui import PreviewWindow
        PreviewWindow(self, "migration")

    def quit(self):
        self._quitting = True
        if hasattr(self, "hotkey"):
            self.hotkey.stop()
        self.core.shutdown()
        self.server.shutdown()
        self.tray.stop()
        self.root.destroy()


def setup_logging(cfg):
    handler = RotatingFileHandler(cfg.data_dir / "organiser.log", maxBytes=1_000_000, backupCount=2,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr is not None:
        root.addHandler(logging.StreamHandler())


def main():
    cfg = load_config()
    setup_logging(cfg)
    try:
        return App(cfg).run()
    except Exception:
        log.exception("Fatal error")
        raise
