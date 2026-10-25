"""Alt+L outside Chrome, in desktop PDF viewers (Acrobat, Foxit, SumatraPDF...).

Alt+L is registered with RegisterHotKey only while one of those viewers is the foreground window (a
SetWinEventHook on foreground changes registers / unregisters it), so Alt+L keeps reaching Chrome and every other
app untouched, and no keyboard hook is needed. The overlay is a frozen screenshot of the viewer's monitor where
boxes are drawn like in the extension; pdfclip turns them into formatted text from the PDF itself.
"""
import ctypes
import ctypes.wintypes as W
import json
import logging
import threading

from PIL import Image, ImageEnhance, ImageGrab, ImageTk

log = logging.getLogger("organiser.desktop_clip")

PDF_APPS = {"acrobat.exe", "acrord32.exe", "foxitpdfreader.exe", "foxitreader.exe", "foxitphantompdf.exe",
            "foxitpdfeditor.exe", "sumatrapdf.exe", "pdfxedit.exe", "pdfxcview.exe", "nitropdf.exe"}
HOTKEY_ID = 0xA17                   # Alt+O uses id 1
MOD_ALT, MOD_NOREPEAT, VK_L = 0x0001, 0x4000, 0x4C
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
EVENT_SYSTEM_FOREGROUND, WINEVENT_OUTOFCONTEXT = 0x0003, 0x0000
WINEVENTPROC = ctypes.WINFUNCTYPE(None, W.HANDLE, W.DWORD, W.HWND, W.LONG, W.LONG, W.DWORD, W.DWORD)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.SetWinEventHook.restype = W.HANDLE
user32.SetWinEventHook.argtypes = [W.DWORD, W.DWORD, W.HMODULE, WINEVENTPROC, W.DWORD, W.DWORD, W.DWORD]


def exe_of(hwnd):
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)            # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf, size = ctypes.create_unicode_buffer(520), W.DWORD(520)
        ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        return buf.value.rsplit("\\", 1)[-1].lower() if ok else ""
    finally:
        kernel32.CloseHandle(h)


def title_of(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


class ForegroundHotkey:
    """Alt+L while a PDF viewer is in front; calls on_hotkey(hwnd, title) on that thread."""

    def __init__(self, on_hotkey):
        self.on_hotkey = on_hotkey
        self._tid = None
        self._registered = False
        self._fg = None

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="pdf-hotkey").start()

    def _update(self, hwnd):
        self._fg = hwnd
        want = bool(hwnd) and exe_of(hwnd) in PDF_APPS
        if want and not self._registered:
            self._registered = bool(user32.RegisterHotKey(None, HOTKEY_ID, MOD_ALT | MOD_NOREPEAT, VK_L))
            if not self._registered:
                log.warning("RegisterHotKey(Alt+L) failed: %s", ctypes.get_last_error())
        elif not want and self._registered:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            self._registered = False

    def _loop(self):
        self._tid = kernel32.GetCurrentThreadId()
        self._proc = WINEVENTPROC(lambda hook, ev, hwnd, obj, child, thread, t: self._update(hwnd))   # keep a reference
        hook = user32.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None, self._proc, 0, 0,
                                      WINEVENT_OUTOFCONTEXT)
        self._update(user32.GetForegroundWindow())
        msg = W.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID and self._fg:
                    try:
                        self.on_hotkey(self._fg, title_of(self._fg))
                    except Exception:
                        log.exception("Alt+L callback failed")
        finally:
            if self._registered:
                user32.UnregisterHotKey(None, HOTKEY_ID)
            if hook:
                user32.UnhookWinEvent(hook)

    def stop(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT), ("dwFlags", W.DWORD)]


def monitor_rect(hwnd):
    mon = user32.MonitorFromWindow(hwnd, 2)                        # MONITOR_DEFAULTTONEAREST
    mi = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
    user32.GetMonitorInfoW(mon, ctypes.byref(mi))
    r = mi.rcMonitor
    return r.left, r.top, r.right, r.bottom


def stack(images, gap=12):
    if len(images) == 1:
        return images[0]
    out = Image.new("RGB", (max(i.width for i in images), sum(i.height for i in images) + gap * (len(images) - 1)), "white")
    y = 0
    for i in images:
        out.paste(i, (0, y))
        y += i.height + gap
    return out


class ClipOverlay:
    """Frozen screenshot of the viewer's monitor; drag boxes (Shift = several), Enter/release copies, Esc cancels."""

    def __init__(self, app, hwnd, title):
        import tkinter as tk
        self.app, self.title = app, title
        self.mode_file = app.cfg.data_dir / "clip_mode.json"
        try:
            self.mode = json.loads(self.mode_file.read_text())["mode"]
        except Exception:
            self.mode = "text"
        l, t, r, b = monitor_rect(hwnd)
        self.origin = (l, t)
        self.shot = ImageGrab.grab(bbox=(l, t, r, b), all_screens=True)
        self.boxes, self.start, self.drag = [], None, None
        top = self.top = tk.Toplevel(app.root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.geometry(f"{r - l}x{b - t}+{l}+{t}")
        c = self.canvas = tk.Canvas(top, width=r - l, height=b - t, highlightthickness=0, cursor="crosshair")
        c.pack(fill="both", expand=True)
        self._dim = ImageTk.PhotoImage(ImageEnhance.Brightness(self.shot).enhance(0.62))
        self._crops = []
        c.create_image(0, 0, image=self._dim, anchor="nw")
        self.bar = None
        self._paint_bar()
        c.bind("<ButtonPress-1>", self._down)
        c.bind("<B1-Motion>", self._move)
        c.bind("<ButtonRelease-1>", self._up)
        c.bind("<ButtonPress-3>", lambda e: self.close())
        for key, fn in (("<Escape>", lambda e: self.close()), ("<Return>", lambda e: self.done()),
                        ("<BackSpace>", lambda e: self._undo()), ("t", lambda e: self._set("text")),
                        ("i", lambda e: self._set("image"))):
            top.bind(key, fn)
        top.after(30, top.focus_force)
        top.after(200, top.focus_force)

    # -- drawing
    def _paint_bar(self):
        c = self.canvas
        if self.bar:
            for item in self.bar:
                c.delete(item)
        n = len(self.boxes)
        hint = (f"{n} box{'es' if n != 1 else ''} · Shift+drag adds · Enter copies · Backspace undo · Esc" if n
                else "Drag a box · Shift = several · Esc")
        label = f"  Editable text (T)  {'●' if self.mode == 'text' else '○'}    Exact image (I)  {'●' if self.mode == 'image' else '○'}    {hint}  "
        x = int(c.winfo_reqwidth()) // 2
        txt = c.create_text(x, 30, text=label, fill="#e2e8f0", font=("Segoe UI", 11))
        x0, y0, x1, y1 = c.bbox(txt)
        bg = c.create_rectangle(x0 - 10, y0 - 8, x1 + 10, y1 + 8, fill="#0f172a", outline="#334155")
        c.tag_raise(txt)
        self.bar = (bg, txt)

    def _show_box(self, box, color):
        l, t, r, b = box
        crop = ImageTk.PhotoImage(self.shot.crop(box))
        self._crops.append(crop)
        self.canvas.create_image(l, t, image=crop, anchor="nw")
        self.canvas.create_rectangle(l, t, r, b, outline=color, width=2)
        self.canvas.create_text(l + 6, t + 4, text=str(len(self.boxes)), anchor="nw", fill="white", font=("Segoe UI", 9, "bold"))
        self._paint_bar()

    def _set(self, mode):
        self.mode = mode
        try:
            self.mode_file.write_text(json.dumps({"mode": mode}))
        except Exception:
            pass
        self._paint_bar()

    # -- mouse
    def _down(self, e):
        self.start = (e.x, e.y)

    def _move(self, e):
        if not self.start:
            return
        if self.drag:
            self.canvas.delete(self.drag)
        self.drag = self.canvas.create_rectangle(*self.start, e.x, e.y, outline="white", width=2)

    def _up(self, e):
        if not self.start:
            return
        (x0, y0), self.start = self.start, None
        if self.drag:
            self.canvas.delete(self.drag)
            self.drag = None
        box = (min(x0, e.x), min(y0, e.y), max(x0, e.x), max(y0, e.y))
        if box[2] - box[0] >= 6 and box[3] - box[1] >= 6:
            self.boxes.append(box)
            self._show_box(box, "#22c55e")
        if not (e.state & 0x0001):                # Shift not held: copy now
            self.done()

    def _undo(self):
        if self.boxes:
            self.boxes.pop()
            boxes, self.boxes = self.boxes, []
            self.canvas.delete("all")
            self.canvas.create_image(0, 0, image=self._dim, anchor="nw")
            self.bar = None
            for bx in boxes:
                self.boxes.append(bx)
                self._show_box(bx, "#22c55e")
            self._paint_bar()

    def close(self):
        try:
            self.top.destroy()
        except Exception:
            pass

    def done(self):
        if not self.boxes:
            return
        boxes, shot, mode, title = sorted(self.boxes, key=lambda b: (b[1], b[0])), self.shot, self.mode, self.title
        self.close()
        dirs = [self.app.cfg.root_folder, self.app.cfg.downloads_folder]
        threading.Thread(target=self._work, args=(shot, boxes, mode, title, dirs), daemon=True).start()

    def _work(self, shot, boxes, mode, title, dirs):
        try:
            msg = process(shot, boxes, mode, title, dirs)
            self.app.toast("Alt+L", msg)
        except Exception as e:
            log.exception("desktop clip failed")
            self.app.toast("Alt+L", f"Couldn't copy: {e}")


def process(shot, boxes, mode, title, search_dirs=()):
    """Clipboard content for the boxes; returns the confirmation message."""
    import fitz
    from . import pdfclip
    image = stack([shot.crop(b) for b in boxes])
    if mode == "image":
        pdfclip.set_clipboard(image=image)
        return "Copied the exact image · Ctrl+V"
    pdf = pdfclip.find_open_pdf(title, search_dirs)
    if not pdf:
        pdfclip.set_clipboard(image=image)
        return "Copied the exact image (couldn't tell which PDF file is open)"
    doc = fitz.open(str(pdf))
    htmls, texts, pages = [], [], []
    for b in boxes:
        m = pdfclip.locate(pdf, shot, b)
        if not m:
            pdfclip.set_clipboard(image=image)
            return "Copied the exact image (couldn't line the box up with the PDF)"
        html, text = pdfclip.rich(doc[m.page], m.rect)
        htmls.append(html)
        texts.append(text)
        pages.append(m.page + 1)
    pdfclip.set_clipboard(html="".join(htmls), text="\n\n".join(t for t in texts if t), image=image)
    where = f"page {pages[0]}" if len(set(pages)) == 1 else "pages " + ", ".join(map(str, sorted(set(pages))))
    return f"Copied text from {where} · Ctrl+V"
