"""System tray icon (pystray) on its own thread. Menu actions are forwarded to the UI queue."""
import threading

import pystray
from PIL import Image, ImageDraw


def _icon(active):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    colour = (63, 185, 80, 255) if active else (120, 122, 134, 255)
    d.rounded_rectangle((4, 14, 60, 54), radius=7, fill=colour)
    d.rounded_rectangle((4, 8, 28, 20), radius=5, fill=colour)
    d.rectangle((10, 26, 54, 30), fill=(255, 255, 255, 230))
    d.rectangle((10, 36, 44, 40), fill=(255, 255, 255, 230))
    return img


class Tray:
    def __init__(self, uiq, hotkey):
        self.uiq = uiq
        put = lambda *msg: (lambda icon, item: uiq.put(msg))
        self.icon = pystray.Icon(
            "alt-o-organiser", _icon(False), "Organiser (off)",
            menu=pystray.Menu(
                pystray.MenuItem(f"On / Off  ({hotkey})", put("toggle"), default=True),
                pystray.MenuItem("Open dashboard", put("show")),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Sort files already in Downloads…", put("sort_existing")),
                pystray.MenuItem("Reorganise old course folders…", put("migration")),
                pystray.MenuItem("Automation Status (Ctrl+Alt+O)", put("status_window")),
                pystray.MenuItem("Open courses folder", put("open_root")),
                pystray.MenuItem("Open log", put("open_log")),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", put("quit")),
            ),
        )

    def start(self):
        threading.Thread(target=self.icon.run, daemon=True, name="tray").start()

    def set_active(self, active, label=""):
        try:
            self.icon.icon = _icon(active)
            self.icon.title = f"Organiser ({'ON · ' + label if active else 'off'})"[:120]
        except Exception:
            pass

    def notify(self, title, msg):
        try:
            self.icon.notify(msg[:240], title[:60])
        except Exception:
            pass

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass
