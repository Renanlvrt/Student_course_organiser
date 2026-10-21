"""Automation Status: one window showing the organiser's health and everything that runs automatically.

Separate from the organiser on purpose, so it still works (and can start it) when the organiser is down.
"""
import ctypes
import json
import os
import subprocess
import threading
import time
import tkinter as tk
import urllib.request
import winreg
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
APPDATA = Path(os.environ.get("APPDATA", ""))
STARTUP_DIR = APPDATA / r"Microsoft\Windows\Start Menu\Programs\Startup"
COMMON_STARTUP = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs\StartUp"
LNK = STARTUP_DIR / "Alt+O Organiser.lnk"
NO_WINDOW = 0x08000000

C = {"bg": "#1d1e22", "panel": "#26272d", "row": "#2c2d34", "line": "#3a3c45", "fg": "#e9e9ec", "muted": "#9c9daa",
     "off": "#6b6d78", "ok": "#3fb950", "warn": "#e3a72f", "err": "#f2665b", "accent": "#5b8cff"}
F, FB, FS, FH = ("Segoe UI", 10), ("Segoe UI Semibold", 10), ("Segoe UI", 9), ("Segoe UI Semibold", 12)


def port():
    try:
        return json.loads((PROJECT / "config.json").read_text(encoding="utf-8")).get("port", 47821)
    except (OSError, ValueError):
        return 47821


def http(path, timeout=3, post=False):
    req = urllib.request.Request(f"http://127.0.0.1:{port()}{path}", method="POST" if post else "GET",
                                 data=b"{}" if post else None, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def ps_json(script, timeout=40):
    """Run a PowerShell snippet that prints JSON; return the parsed list."""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                             timeout=timeout, creationflags=NO_WINDOW).stdout.strip()
        data = json.loads(out) if out else []
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def ago(ts):
    if not ts:
        return "never"
    s = int(time.time() - ts)
    if s < 90:
        return f"{s}s ago"
    if s < 5400:
        return f"{s // 60} min ago"
    if s < 172800:
        return f"{s // 3600} h ago"
    return f"{s // 86400} days ago"


# ------------------------------------------------------------------ data collection
def startup_approved(kind):
    """name -> enabled?, from Task Manager's 'Startup apps' switches."""
    out = {}
    for hive, path in ((winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\{kind}"),
                       (winreg.HKEY_LOCAL_MACHINE, rf"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\{kind}")):
        try:
            with winreg.OpenKey(hive, path) as k:
                for i in range(winreg.QueryInfoKey(k)[1]):
                    name, val, _ = winreg.EnumValue(k, i)
                    out[name.lower()] = not (isinstance(val, bytes) and val[:1] and val[0] & 1)
        except OSError:
            pass
    return out


def autostart_items():
    items = []
    folder_ok = startup_approved("StartupFolder")
    for d, where in ((STARTUP_DIR, "Startup folder (you)"), (COMMON_STARTUP, "Startup folder (all users)")):
        for f in sorted(d.glob("*")) if d.is_dir() else []:
            if f.name.lower() == "desktop.ini":
                continue
            items.append({"name": f.stem, "where": where, "enabled": folder_ok.get(f.name.lower(), True),
                          "detail": f.name})
    run_ok = {**startup_approved("Run"), **startup_approved("Run32")}
    for hive, hname, path in ((winreg.HKEY_CURRENT_USER, "Registry (you)", r"Software\Microsoft\Windows\CurrentVersion\Run"),
                              (winreg.HKEY_LOCAL_MACHINE, "Registry (all users)", r"Software\Microsoft\Windows\CurrentVersion\Run"),
                              (winreg.HKEY_LOCAL_MACHINE, "Registry (all users, 32-bit)",
                               r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run")):
        try:
            with winreg.OpenKey(hive, path) as k:
                for i in range(winreg.QueryInfoKey(k)[1]):
                    name, val, _ = winreg.EnumValue(k, i)
                    items.append({"name": name, "where": hname, "enabled": run_ok.get(name.lower(), True),
                                  "detail": str(val)})
        except OSError:
            pass
    return items


def scheduled_tasks():
    rows = ps_json("Get-ScheduledTask | Where-Object { $_.TaskPath -notlike '\\Microsoft*' } | "
                   "Select-Object TaskName, TaskPath, @{n='State';e={[string]$_.State}}, "
                   "@{n='Action';e={($_.Actions | ForEach-Object { \"$($_.Execute) $($_.Arguments)\" }) -join ' ; '}} | "
                   "ConvertTo-Json -Compress")
    return [r for r in rows if r]


def background_scripts():
    rows = ps_json("Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|pythonw|node)(3[\\d.]*)?\\.exe$' } | "
                   "Select-Object ProcessId, Name, CommandLine, CreationDate | ConvertTo-Json -Compress")
    out, seen = [], set()
    for r in rows:
        cmd = r.get("CommandLine") or ""
        if not cmd or "status.pyw" in cmd:
            continue
        # The Store Python starts a stub + the real interpreter for each script: show it once.
        key = cmd.replace("pythonw3.13.exe", "pythonw.exe").replace("python3.13.exe", "python.exe")
        script = next((p for p in reversed(cmd.replace('"', " ").split()) if p.lower().endswith((".py", ".pyw", ".js"))), "")
        k2 = script or key
        if k2 in seen:
            continue
        seen.add(k2)
        out.append({"pid": r.get("ProcessId"), "script": script or cmd[:120], "cmd": cmd})
    return out


def organiser_checks():
    checks = []
    st = None
    try:
        st = http("/status")
    except Exception:
        pass
    if st:
        checks.append(("ok", "Organiser is running", f"since {ago(st.get('started_at'))} · pid {st.get('pid')} · "
                                                     f"Alt+O watching: {'ON' if st.get('active') else 'off'}"))
    else:
        checks.append(("err", "Organiser is NOT running", "Click Start. The Chrome extension also starts it automatically."))
    enabled = startup_approved("StartupFolder").get(LNK.name.lower(), True)
    if LNK.exists() and enabled:
        checks.append(("ok", "Starts automatically at login", "Startup shortcut present and enabled"))
    elif LNK.exists():
        checks.append(("err", "Startup is DISABLED", "Task Manager > Startup apps > enable 'Alt+O Organiser'"))
    else:
        checks.append(("err", "No startup shortcut", "Run scripts\\install_startup.ps1"))
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\NativeMessagingHosts\com.alto.organiser") as k:
            mpath = Path(winreg.QueryValue(k, None))
        good = mpath.exists() and (PROJECT / "native" / "organiser_host.bat").exists()
        checks.append(("ok" if good else "err", "Chrome can start the organiser" if good else "Chrome launcher broken",
                       "native launcher registered" if good else "Run scripts\\install_native_host.ps1"))
    except OSError:
        checks.append(("err", "Chrome launcher not registered", "Run scripts\\install_native_host.ps1"))
    if st:
        seen = st.get("extension_seen")
        checks.append(("ok" if seen and time.time() - seen < 86400 else "warn", "Chrome extension",
                       f"last contact {ago(seen)}" if seen else "not seen since the organiser started (open the popup once)"))
        hk = st.get("hotkey_mode")
        checks.append(("ok" if hk == "registered" else "warn" if hk else "err", f"Hotkey {st.get('hotkey', 'alt+o').upper()}",
                       {"registered": "registered", "hook fallback": "works via keyboard hook (another app owns it)"}.get(hk, "not registered")))
        ai = st.get("ai_last") or {}
        if not st.get("ai_key"):
            checks.append(("warn", "AI (Gemini)", "no GEMINI_API_KEY: sorting uses rules only"))
        elif ai.get("error_at") and (not ai.get("ok_at") or ai["error_at"] > ai["ok_at"]):
            checks.append(("warn", "AI (Gemini)", f"last call failed {ago(ai['error_at'])}: {ai.get('error', '')[:80]}"))
        else:
            checks.append(("ok", "AI (Gemini)", f"working · last answer {ago(ai.get('ok_at'))}" if ai.get("ok_at")
                           else "key set · not used yet since start"))
        try:
            t = http("/selftest", timeout=10)
            bad = [k for k, v in t.items() if not v.get("ok")]
            checks.append(("err" if bad else "ok", "Antivirus / file access",
                           "can create and move files in courses and Downloads" if not bad else
                           f"BLOCKED in {', '.join(bad)}: {t[bad[0]].get('error')} - allow pythonw3.13.exe in your antivirus"))
        except Exception as ex:
            checks.append(("warn", "Antivirus / file access", f"self-test failed to run: {ex}"))
        last = st.get("last_entry")
        checks.append(("ok", "Last file handled", f"{last['name']} · {last['status']} · {last['time']}" if last else "none yet"))
    return checks


# ------------------------------------------------------------------ window
class StatusWindow:
    def __init__(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        self.root = tk.Tk()
        self.root.title("Automation Status")
        self.root.configure(bg=C["bg"])
        s = max(1.0, self.root.winfo_fpixels("1i") / 96)
        self.wrap = int(640 * s)
        self.root.geometry(f"{int(760 * s)}x{int(780 * s)}")
        ico = PROJECT / "assets" / "status.ico"
        if ico.exists():
            self.root.iconbitmap(str(ico))
        head = tk.Frame(self.root, bg=C["bg"])
        head.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(head, text="Automation Status", bg=C["bg"], fg=C["fg"], font=("Segoe UI Semibold", 15)).pack(side="left")
        self.updated = tk.Label(head, text="", bg=C["bg"], fg=C["muted"], font=FS)
        self.updated.pack(side="left", padx=12)
        self._btn(head, "↻ Refresh", self.refresh).pack(side="right")
        canvas = tk.Canvas(self.root, bg=C["bg"], highlightthickness=0)
        sb = tk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        self.body = tk.Frame(canvas, bg=C["bg"])
        self.body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=self.body, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(16, 0))
        sb.pack(side="right", fill="y")
        self.root.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        self.sections = {}
        for key, title in (("org", "ALT+O ORGANISER"), ("auto", "STARTS AUTOMATICALLY WITH WINDOWS"),
                           ("tasks", "SCHEDULED TASKS (yours)"), ("bg", "BACKGROUND SCRIPTS RUNNING NOW")):
            tk.Label(self.body, text=title, bg=C["bg"], fg=C["muted"], font=FS).pack(anchor="w", pady=(14, 4))
            f = tk.Frame(self.body, bg=C["panel"])
            f.pack(fill="x", padx=(0, 12))
            self.sections[key] = f
            tk.Label(f, text="checking…", bg=C["panel"], fg=C["muted"], font=FS).pack(anchor="w", padx=10, pady=8)
        self.refresh()
        self.root.after(15000, self._auto)
        self.root.mainloop()

    def _btn(self, parent, text, cmd, bg=None):
        b = tk.Label(parent, text=text, bg=bg or C["row"], fg=C["fg"], font=FS, padx=9, pady=4, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        return b

    def _clear(self, key):
        for w in self.sections[key].winfo_children():
            w.destroy()
        return self.sections[key]

    def _row(self, parent, colour, title, detail="", detail_fg=None):
        r = tk.Frame(parent, bg=C["panel"])
        r.pack(fill="x", padx=10, pady=3)
        tk.Label(r, text="●", bg=C["panel"], fg=colour, font=FS).pack(side="left", anchor="n", pady=2)
        box = tk.Frame(r, bg=C["panel"])
        box.pack(side="left", fill="x", expand=True, padx=(6, 0))
        tk.Label(box, text=title, bg=C["panel"], fg=C["fg"], font=FB, anchor="w").pack(fill="x")
        if detail:
            tk.Label(box, text=detail, bg=C["panel"], fg=detail_fg or C["muted"], font=FS, anchor="w", justify="left",
                     wraplength=self.wrap).pack(fill="x")
        return r

    def _auto(self):
        self.refresh(only_org=True)
        self.root.after(15000, self._auto)

    def refresh(self, only_org=False):
        self.updated.config(text="refreshing…")

        def work():
            data = {"org": organiser_checks()}
            if not only_org:
                data["auto"] = autostart_items()
                data["tasks"] = scheduled_tasks()
                data["bg"] = background_scripts()
            self.root.after(0, lambda: self._render(data))
        threading.Thread(target=work, daemon=True).start()

    def _render(self, data):
        colours = {"ok": C["ok"], "warn": C["warn"], "err": C["err"]}
        f = self._clear("org")
        for level, title, detail in data["org"]:
            self._row(f, colours[level], title, detail, C["err"] if level == "err" else None)
        bar = tk.Frame(f, bg=C["panel"])
        bar.pack(fill="x", padx=10, pady=(6, 10))
        running = data["org"][0][0] == "ok"
        if running:
            self._btn(bar, "Open dashboard", lambda: self._safe(lambda: http("/show", post=True))).pack(side="left")
            self._btn(bar, "Restart", self.restart).pack(side="left", padx=6)
        else:
            self._btn(bar, "▶ Start organiser", self.start, bg=C["accent"]).pack(side="left")
        self._btn(bar, "Open log", lambda: os.startfile(PROJECT / "data" / "organiser.log")).pack(side="left", padx=6)
        self._btn(bar, "Open courses", self.open_courses).pack(side="left")
        if "auto" in data:
            f = self._clear("auto")
            for it in data["auto"]:
                ours = "organiser" in it["name"].lower()
                self._row(f, C["ok"] if it["enabled"] else C["off"],
                          ("★ " if ours else "") + it["name"] + ("" if it["enabled"] else "   (disabled)"),
                          f"{it['where']} · {it['detail'][:150]}")
            if not data["auto"]:
                self._row(f, C["off"], "Nothing")
            f = self._clear("tasks")
            for t in data["tasks"]:
                self._row(f, C["ok"] if t.get("State") in ("Ready", "Running") else C["off"],
                          f"{t.get('TaskName')}   ({t.get('State')})", (t.get("Action") or "")[:160])
            if not data["tasks"]:
                self._row(f, C["off"], "None")
            f = self._clear("bg")
            for p in data["bg"]:
                ours = "Desktop_organiser" in p["cmd"]
                self._row(f, C["accent"] if ours else C["ok"], ("★ " if ours else "") + Path(p["script"]).name,
                          f"pid {p['pid']} · {p['script']}")
            if not data["bg"]:
                self._row(f, C["off"], "No Python / Node scripts running")
        self.updated.config(text="updated " + time.strftime("%H:%M:%S"))

    def _safe(self, fn):
        try:
            fn()
        except Exception:
            pass

    def start(self):
        subprocess.Popen(["explorer.exe", str(LNK)])
        self.root.after(5000, lambda: self.refresh(only_org=True))

    def restart(self):
        try:
            pid = http("/status")["pid"]
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=NO_WINDOW)
        except Exception:
            pass
        self.root.after(1500, self.start)

    def open_courses(self):
        try:
            os.startfile(json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))["root_folder"])
        except Exception:
            pass


if __name__ == "__main__":
    StatusWindow()
