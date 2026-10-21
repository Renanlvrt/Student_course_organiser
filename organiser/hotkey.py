"""Global hotkey via Win32 RegisterHotKey (no keyboard hook, works over elevated windows).

Falls back to the `keyboard` library hook if another app already owns the combination.
"""
import ctypes
import ctypes.wintypes as W
import logging
import threading

log = logging.getLogger("organiser.hotkey")

MODS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
NAMED_VK = {**{f"f{i}": 0x6F + i for i in range(1, 25)}, "space": 0x20, "tab": 0x09, "enter": 0x0D,
            "esc": 0x1B, "home": 0x24, "end": 0x23, "insert": 0x2D, "delete": 0x2E}


def parse(combo):
    mods, vk = 0, None
    for part in combo.lower().replace(" ", "").split("+"):
        if part in MODS:
            mods |= MODS[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part in NAMED_VK:
            vk = NAMED_VK[part]
        else:
            raise ValueError(f"unsupported key '{part}' in hotkey '{combo}'")
    if vk is None:
        raise ValueError(f"hotkey '{combo}' has no main key")
    return mods, vk


class Hotkey:
    def __init__(self, combo, callback):
        self.combo, self.callback = combo, callback
        self._thread_id = None
        self._fallback = False
        self.ok = threading.Event()
        self.error = None

    def start(self, timeout=3.0):
        threading.Thread(target=self._loop, daemon=True, name="hotkey").start()
        self.ok.wait(timeout)
        if self.error:
            log.warning("RegisterHotKey(%s) failed: %s - falling back to keyboard hook", self.combo, self.error)
            import keyboard
            keyboard.add_hotkey(self.combo, self.callback, suppress=False)
            self._fallback = True
        return "registered" if not self._fallback else "hook fallback"

    def _loop(self):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32")
        self._thread_id = kernel32.GetCurrentThreadId()
        try:
            mods, vk = parse(self.combo)
        except ValueError as e:
            self.error = str(e)
            self.ok.set()
            return
        if not user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk):
            self.error = f"Win32 error {ctypes.get_last_error()} (another app may own {self.combo})"
            self.ok.set()
            return
        self.ok.set()
        msg = W.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    try:
                        self.callback()
                    except Exception:
                        log.exception("hotkey callback failed")
        finally:
            user32.UnregisterHotKey(None, 1)

    def stop(self):
        if self._fallback:
            try:
                import keyboard
                keyboard.unhook_all()
            except Exception:
                pass
        elif self._thread_id:
            ctypes.WinDLL("user32").PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
