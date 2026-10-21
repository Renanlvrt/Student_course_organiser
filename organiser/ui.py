"""Tk dashboard, fix editor and preview windows. Runs on the main thread only.

Background threads talk to the UI exclusively through App.uiq (drained by Tk's after()).
"""
import os
import re
import subprocess
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from . import migrate, rules
from .classify import Classification

C = {
    "bg": "#1d1e22", "panel": "#26272d", "row": "#2c2d34", "row_hi": "#363844", "line": "#3a3c45",
    "fg": "#e9e9ec", "muted": "#9c9daa", "accent": "#5b8cff", "accent_dim": "#33456e",
    "ok": "#3fb950", "warn": "#e3a72f", "err": "#f2665b", "dup": "#8b8fa3", "off": "#6b6d78",
}
FONT = ("Segoe UI", 9)
FONT_B = ("Segoe UI Semibold", 9)
FONT_S = ("Segoe UI", 8)
FONT_H = ("Segoe UI Semibold", 10)
CAT_SHORT = {"Lectures": "Lec", "Practicals": "Prac", "Solutions": "Sol", "Readings": "Read",
             "Assessment": "Assess", "Exam Prep": "Exam", "Other": "Other"}
STATUS_COLOUR = {"sorted": C["ok"], "flagged": C["warn"], "duplicate": C["dup"], "skipped": C["dup"],
                 "error": C["err"], "undone": C["off"]}


def open_in_explorer(path):
    p = Path(path)
    if p.exists() and p.is_file():
        subprocess.Popen(["explorer", "/select,", str(p)])
    elif p.exists():
        os.startfile(str(p))
    elif p.parent.exists():
        os.startfile(str(p.parent))


def short(s, n):
    s = str(s or "")
    return s if len(s) <= n else s[: n - 1] + "…"


class FlatButton(tk.Label):
    """Small flat clickable label: looks consistent and supports a 'selected' state."""

    def __init__(self, master, text, command=None, bg=None, fg=None, font=FONT, padx=7, pady=3, **kw):
        self._bg = bg or C["row"]
        self._fg = fg or C["fg"]
        super().__init__(master, text=text, bg=self._bg, fg=self._fg, font=font, padx=padx, pady=pady,
                         cursor="hand2", **kw)
        self.command = command
        self.selected = False
        self.bind("<Enter>", lambda e: self.config(bg=C["row_hi"] if not self.selected else C["accent"]))
        self.bind("<Leave>", lambda e: self._paint())
        self.bind("<Button-1>", lambda e: self.command and self.command())

    def set_selected(self, sel):
        self.selected = sel
        self._paint()

    def _paint(self):
        self.config(bg=C["accent"] if self.selected else self._bg, fg="#ffffff" if self.selected else self._fg)


class Dashboard:
    """Three sections: Needs a look (amber) / Where files went (tree) / Left in Downloads (muted)."""
    W, H = 450, 640

    def __init__(self, app):
        self.app = app
        self.core = app.core
        self.cfg = app.core.cfg
        s = app.scale
        self.s = s
        self.W, self.H = int(self.W * s), int(self.H * s)
        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=C["line"])
        self._drag = None
        self._row_drag = None
        self._ghost = None
        self._hover_target = None
        self._refresh_pending = False
        self._summary_text = ""
        self.collapsed = set()
        self.view = None            # "session" | "today"; None = pick automatically
        self.targets = []
        self._build()

    # ------------------------------------------------------------------ layout
    def _build(self):
        outer = tk.Frame(self.win, bg=C["bg"])
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(outer, bg=C["bg"])
        head.pack(fill="x", padx=12, pady=(10, 2))
        self.dot = tk.Label(head, text="●", bg=C["bg"], fg=C["off"], font=FONT_H, cursor="hand2")
        self.dot.pack(side="left")
        self.onoff = tk.Label(head, text="Off", bg=C["bg"], fg=C["muted"], font=FONT_H, cursor="hand2")
        self.onoff.pack(side="left", padx=(4, 0))
        for w in (self.dot, self.onoff):
            w.bind("<Button-1>", lambda e: self.app.set_active(not self.core.active))
        FlatButton(head, "×", self.hide, bg=C["bg"], fg=C["muted"], font=FONT_H, padx=6).pack(side="right")
        FlatButton(head, "⋯", self._menu, bg=C["bg"], fg=C["muted"], font=FONT_H, padx=6).pack(side="right")
        self.pick_btn = FlatButton(head, "Auto ▾", self._pick_menu, bg=C["bg"], fg=C["fg"], font=FONT)
        self.pick_btn.pack(side="right", padx=(0, 4))
        for w in (head,):
            w.bind("<ButtonPress-1>", self._start_move)
            w.bind("<B1-Motion>", self._on_move)
            w.bind("<ButtonRelease-1>", self._end_move)

        bar = tk.Frame(outer, bg=C["bg"])
        bar.pack(fill="x", padx=12, pady=(4, 8))
        self.tab_session = self._tab(bar, "This session", "session")
        self.tab_today = self._tab(bar, "Today", "today")
        self.summary = tk.Label(bar, text="", bg=C["bg"], fg=C["muted"], font=FONT_S)
        self.summary.pack(side="right")
        tk.Frame(outer, bg=C["line"], height=1).pack(fill="x")

        body = tk.Frame(outer, bg=C["bg"])
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, bg=C["bg"], highlightthickness=0, bd=0)
        self.rows = tk.Frame(self.canvas, bg=C["bg"])
        self.rows.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._rows_win = self.canvas.create_window((0, 0), window=self.rows, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._rows_win, width=e.width))
        self.canvas.pack(fill="both", expand=True)
        self.win.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

    def _tab(self, parent, text, view):
        t = tk.Label(parent, text=text, bg=C["bg"], fg=C["muted"], font=FONT, cursor="hand2", padx=0)
        t.pack(side="left", padx=(0, 14))
        t.bind("<Button-1>", lambda e: self._set_view(view))
        return t

    def _set_view(self, view):
        self.view = view
        self.refresh()

    # ------------------------------------------------------------------ window move
    def _start_move(self, e):
        self._drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _on_move(self, e):
        if self._drag:
            self.win.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _end_move(self, e):
        if self._drag:
            self._drag = None
            self.core.state.set("dash_pos", [self.win.winfo_x(), self.win.winfo_y()])

    def _place_window(self):
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        pos = self.core.state.get("dash_pos")
        if pos and 0 <= pos[0] <= sw - 60 and 0 <= pos[1] <= sh - 60:
            x, y = pos
        else:
            x, y = sw - self.W - 14, sh - self.H - int(56 * self.app.scale)
        self.win.geometry(f"{self.W}x{self.H}+{x}+{max(0, y)}")

    # ------------------------------------------------------------------ show / state
    def show(self):
        self._place_window()
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)
        self.update_state()
        self.refresh()

    def hide(self):
        self.win.withdraw()

    @property
    def visible(self):
        return self.win.winfo_viewable()

    def update_state(self):
        on = self.core.active
        self.dot.config(fg=C["ok"] if on else C["off"])
        self.onoff.config(text="On" if on else "Off", fg=C["fg"] if on else C["muted"])
        mod, part = self.core.pick_module, self.core.pick_part
        label = mod or "Auto"
        if mod and part is not None:
            label += f" · {short(self.cfg.module(mod).parts[part], 12)}"
        self.pick_btn.config(text=label + " ▾")
        self.refresh()

    def _pick_menu(self):
        m = self._new_menu()
        m.add_command(label="Auto (detect module)", command=lambda: self._pick(None, None))
        m.add_separator()
        for mod in self.cfg.modules:
            sub = self._new_menu(m)
            sub.add_command(label="Detect part", command=lambda k=mod.key: self._pick(k, None))
            for i, p in enumerate(mod.parts):
                sub.add_command(label=p, command=lambda k=mod.key, ix=i: self._pick(k, ix))
            m.add_cascade(label=f"{mod.key}  ·  {mod.name}", menu=sub)
        m.tk_popup(*self.win.winfo_pointerxy())

    def _pick(self, key, part):
        if not self.core.active:
            self.app.set_active(True, module=key)
        self.core.set_pick(key, part)

    def _new_menu(self, parent=None):
        return tk.Menu(parent or self.win, tearoff=0, bg=C["panel"], fg=C["fg"], activebackground=C["accent"],
                       activeforeground="white", font=FONT, bd=0)

    # ------------------------------------------------------------------ data
    def _entries(self):
        today = time.strftime("%Y-%m-%d")
        all_ = [e for e in self.core.log.recent(300) if e.get("kind") in ("download", "existing", None)
                or e["status"] == "flagged"]
        session = [e for e in all_ if self.core.session_start and e["time"] >= self.core.session_start]
        view = self.view or ("session" if session else "today")
        self.tab_session.config(fg=C["fg"] if view == "session" else C["muted"],
                                font=FONT_B if view == "session" else FONT)
        self.tab_today.config(fg=C["fg"] if view == "today" else C["muted"],
                              font=FONT_B if view == "today" else FONT)
        return session if view == "session" else [e for e in all_ if e["time"].startswith(today)]

    def _rel(self, path):
        try:
            return Path(path).relative_to(self.cfg.root_folder).parts
        except ValueError:
            return None

    def _target_for(self, parts):
        """What dropping a file on this folder means (mirrors the folder layout)."""
        mod = self.cfg.module(parts[0]) if parts else None
        if not mod:
            return None
        if len(parts) == 1:
            return {"module": mod.key}
        if parts[1] == "Other":
            return {"module": mod.key, "part": None, "category": "Other"}
        if parts[1] == "Lectures" and "Readings" in parts[2:4]:
            part = mod.parts.index(parts[2]) if len(parts) >= 3 and parts[2] in mod.parts else None
            return {"module": mod.key, "part": part, "category": "Readings"}
        if parts[1] in ("Lectures", "Practicals") and len(parts) >= 3 and parts[2] in mod.parts:
            t = {"module": mod.key, "part": mod.parts.index(parts[2]), "category": parts[1]}
            m = len(parts) >= 4 and re.match(r"(Lecture|Practical) (\d+)", parts[3])
            if m:
                t["number"] = int(m.group(2))
            return t
        return None

    # ------------------------------------------------------------------ render
    def refresh(self):
        if self._refresh_pending:
            return
        self._refresh_pending = True
        self.win.after(60, self._do_refresh)

    def _do_refresh(self):
        self._refresh_pending = False
        y = self.canvas.yview()[0]
        for w in self.rows.winfo_children():
            w.destroy()
        entries = self._entries()
        flagged = [e for e in entries if e["status"] == "flagged"]
        placed = [e for e in entries if e["status"] == "sorted" and self._rel(e["current_path"])]
        left = [e for e in entries if e["status"] in ("duplicate", "skipped", "undone", "error")]
        bits = [f"{len(placed)} sorted"]
        if flagged:
            bits.append(f"{len(flagged)} to check")
        if left:
            bits.append(f"{len(left)} left")
        self._summary_text = " · ".join(bits) if entries else ""
        self.summary.config(text=self._summary_text)
        if not entries:
            msg = "Waiting for downloads…" if self.core.active else "Press Alt+O, then download."
            tk.Label(self.rows, text=msg, bg=C["bg"], fg=C["muted"], font=FONT).pack(pady=(40, 4))
            tk.Label(self.rows, text="Each file will appear here, in the folder it went to.", bg=C["bg"],
                     fg=C["off"], font=FONT_S).pack()
            return
        if flagged:
            self._section("NEEDS A LOOK", len(flagged), C["warn"])
            for e in flagged:
                self._flag_card(e)
        if placed:
            self._section("WHERE FILES WENT", len(placed), C["muted"])
            self._tree(placed)
        if left:
            self._section("LEFT IN DOWNLOADS", len(left), C["muted"])
            for e in left:
                self._left_row(e)
        tk.Frame(self.rows, bg=C["bg"], height=12).pack()
        self.win.after(10, lambda: self.canvas.yview_moveto(y))

    def _section(self, title, n, colour):
        f = tk.Frame(self.rows, bg=C["bg"])
        f.pack(fill="x", padx=12, pady=(12, 4))
        tk.Label(f, text=title, bg=C["bg"], fg=colour, font=FONT_S).pack(side="left")
        tk.Label(f, text=str(n), bg=C["bg"], fg=C["off"], font=FONT_S).pack(side="left", padx=(6, 0))

    # -- needs a look
    def _flag_card(self, e):
        c = Classification.from_dict(e.get("classification"))
        card = tk.Frame(self.rows, bg=C["row"])
        card.pack(fill="x", padx=12, pady=2)
        tk.Frame(card, bg=C["warn"], width=3).pack(side="left", fill="y")
        body = tk.Frame(card, bg=C["row"])
        body.pack(side="left", fill="x", expand=True, padx=9, pady=6)
        name = tk.Label(body, text=short(e["original_name"], 48), bg=C["row"], fg=C["fg"], font=FONT_B,
                        anchor="w", cursor="hand2")
        name.pack(fill="x")
        name.bind("<Button-1>", lambda ev: open_in_explorer(e["current_path"]))
        guess = self._where(c)
        why = e.get("message") or "Not sure where it goes"
        tk.Label(body, text=why, bg=C["row"], fg=C["warn"], font=FONT_S, anchor="w").pack(fill="x")
        if guess:
            tk.Label(body, text="Best guess:  " + guess, bg=C["row"], fg=C["muted"], font=FONT_S, anchor="w",
                     justify="left", wraplength=int(380 * self.s)).pack(fill="x")
        acts = tk.Frame(body, bg=C["row"])
        acts.pack(fill="x", pady=(5, 0))
        if c.module and c.category:
            FlatButton(acts, "✓ Accept", lambda: self.app.run_fix(e["id"], None), bg=C["accent_dim"],
                       font=FONT_S).pack(side="left")
        FlatButton(acts, "Move…", lambda: self.open_editor(e["id"]), bg=C["panel"], font=FONT_S).pack(
            side="left", padx=(6, 0))
        self._make_draggable([card, body, name], e["id"], e["original_name"])

    # -- tree
    def _tree(self, placed):
        root = {"kids": {}, "files": [], "path": ()}
        for e in placed:
            rel = self._rel(e["current_path"])
            node = root
            for i, name in enumerate(rel[:-1]):
                node = node["kids"].setdefault(name, {"kids": {}, "files": [], "path": rel[:i + 1]})
            node["files"].append(e)
        for name in sorted(root["kids"]):
            self._node(name, root["kids"][name], 0)

    def _count(self, node):
        return len(node["files"]) + sum(self._count(k) for k in node["kids"].values())

    def _node(self, label, node, depth):
        # Collapse single-child chains below the module: "Lectures › Algorithmic Game Theory".
        while depth > 0 and not node["files"] and len(node["kids"]) == 1:
            (name, child), = node["kids"].items()
            label, node = f"{label} › {name}", child
        key = node["path"]
        if depth > 1 and not node["kids"] and len(node["files"]) == 1:
            return self._file(node["files"][0], depth, folder=None)   # one-file folder: one row
        open_ = key not in self.collapsed
        row = tk.Frame(self.rows, bg=C["bg"])
        row.pack(fill="x", padx=(12 + int(16 * depth * self.s), 12), pady=(3 if depth == 0 else 1, 0))
        arrow = tk.Label(row, text="▾" if open_ else "▸", bg=C["bg"], fg=C["muted"], font=FONT, width=2,
                         cursor="hand2")
        arrow.pack(side="left")
        if depth == 0:
            mod = self.cfg.module(label)
            lab = tk.Label(row, text=label, bg=C["bg"], fg=C["fg"], font=FONT_H, cursor="hand2")
            lab.pack(side="left")
            if mod:
                tk.Label(row, text=short(mod.name, 34), bg=C["bg"], fg=C["off"], font=FONT_S).pack(
                    side="left", padx=(8, 0))
        else:
            lab = tk.Label(row, text="📁 " + short(label, 60 - 3 * depth), bg=C["bg"], fg=C["fg"],
                           font=FONT_B if depth == 1 else FONT, cursor="hand2", anchor="w")
            lab.pack(side="left")
        tk.Label(row, text=str(self._count(node)), bg=C["bg"], fg=C["off"], font=FONT_S).pack(side="right")
        for w in (arrow, lab):
            w.bind("<Button-1>", lambda ev, k=key: self._toggle(k))
        target = self._target_for(list(key))
        if target:
            for w in (row, lab):
                w._drop = target
            self.targets.append(lab)
        lab.bind("<Double-Button-1>", lambda ev, k=key: os.startfile(str(self.cfg.root_folder.joinpath(*k))))
        if not open_:
            return
        for name in sorted(node["kids"]):
            self._node(name, node["kids"][name], depth + 1)
        for e in sorted(node["files"], key=lambda x: Path(x["current_path"]).name.lower()):
            self._file(e, depth + 1, folder=key[-1] if key else None)

    def _toggle(self, key):
        self.collapsed.symmetric_difference_update({key})
        self.refresh()

    def _file(self, e, depth, folder=None):
        row = tk.Frame(self.rows, bg=C["bg"])
        row.pack(fill="x", padx=(12 + int(16 * depth * self.s) + int(18 * self.s), 12), pady=0)
        name = Path(e["current_path"]).name
        shown = name
        m = folder and re.match(r"((?:Lecture|Practical) \d+) - ", folder)
        if m and name.startswith(m.group(1) + " - "):
            shown = name[len(m.group(1)) + 3:]              # folder already says "Lecture 01"
        lab = tk.Label(row, text="• " + short(shown, 60 - 3 * depth), bg=C["bg"], fg=C["fg"], font=FONT,
                       anchor="w", cursor="hand2")
        lab.pack(side="left")
        lab.bind("<Button-1>", lambda ev: open_in_explorer(e["current_path"]))
        acts = tk.Frame(row, bg=C["bg"])
        self._link(acts, "move", lambda: self.open_editor(e["id"]), C["accent"])
        self._link(acts, "undo", lambda: self.core.submit(self.core.undo, e["id"]), C["muted"])
        self._hover(row, acts)
        tip = f"was: {e['original_name']}"
        lab.bind("<Enter>", lambda ev: self.summary.config(text=short(tip, 48)), add="+")
        lab.bind("<Leave>", lambda ev: self.summary.config(text=self._summary_text), add="+")
        self._make_draggable([row, lab], e["id"], name)

    # -- left in downloads
    def _left_row(self, e):
        st = e["status"]
        row = tk.Frame(self.rows, bg=C["bg"])
        row.pack(fill="x", padx=12, pady=1)
        target = e.get("duplicate_of") if st == "duplicate" else e.get("current_path")
        lab = tk.Label(row, text="• " + short(e["original_name"], 40), bg=C["bg"], fg=C["off"], font=FONT,
                       anchor="w", cursor="hand2")
        lab.pack(side="left")
        lab.bind("<Button-1>", lambda ev: open_in_explorer(target))
        if st == "duplicate":
            rel = self._rel(e.get("duplicate_of") or "")
            why = "already have it" + (f" in {rel[0]}" if rel else "")
        elif st == "skipped":
            why = "not course material"
        elif st == "undone":
            why = "you undid it"
        else:
            why = e.get("message") or st
        tk.Label(row, text=why, bg=C["bg"], fg=C["off"], font=FONT_S).pack(side="right")
        if st == "skipped":
            self._make_draggable([row, lab], e["id"], e["original_name"])

    # -- helpers
    def _where(self, c):
        mod = self.cfg.module(c.module) if c.module else None
        if not mod:
            return ""
        if c.category in ("Lectures", "Practicals"):
            parts = [mod.key, c.category] + ([short(mod.parts[c.part], 34)] if c.part is not None and mod.parts else [])
        elif c.category == "Readings":
            parts = [mod.key, "Lectures"] + ([short(mod.parts[c.part], 34)] if c.part is not None and mod.parts
                                             else []) + ["Readings"]
        elif c.category == "Solutions" and c.number and c.part is not None:
            home = "Lectures" if c.relates_to == "Lectures" else "Practicals"
            parts = [mod.key, home, short(mod.parts[c.part], 18), f"{home[:-1]} {c.number:02d}"]
        else:
            parts = [mod.key, "Other"]
        return " › ".join(parts)

    def _link(self, parent, text, cmd, fg):
        l = tk.Label(parent, text=text, bg=C["bg"], fg=fg, font=FONT_S, cursor="hand2", padx=4)
        l.pack(side="left")
        l.bind("<Button-1>", lambda e: cmd())
        return l

    def _hover(self, row, acts):
        def inside():
            w = self.win.winfo_containing(*self.win.winfo_pointerxy())
            while w is not None:
                if w is row:
                    return True
                w = w.master
            return False

        def enter(_):
            if not acts.winfo_ismapped():
                acts.pack(side="right")

        def leave(_):
            row.after(40, lambda: acts.winfo_exists() and not inside() and acts.pack_forget())

        for w in [row] + list(row.winfo_children()):
            w.bind("<Enter>", enter, add="+")
            w.bind("<Leave>", leave, add="+")

    # ------------------------------------------------------------------ drag & drop
    def _make_draggable(self, widgets, entry_id, title):
        for w in widgets:
            w.bind("<ButtonPress-1>", lambda ev: self._row_press(ev, entry_id, title), add="+")
            w.bind("<B1-Motion>", self._row_motion, add="+")
            w.bind("<ButtonRelease-1>", self._row_release, add="+")

    def _row_press(self, ev, entry_id, title):
        self._row_drag = {"id": entry_id, "x": ev.x_root, "y": ev.y_root, "title": title, "active": False}

    def _row_motion(self, ev):
        d = self._row_drag
        if not d:
            return
        if not d["active"] and abs(ev.x_root - d["x"]) + abs(ev.y_root - d["y"]) > 8:
            d["active"] = True
            g = tk.Toplevel(self.win)
            g.overrideredirect(True)
            g.attributes("-topmost", True)
            g.attributes("-alpha", 0.9)
            tk.Label(g, text="⇢ " + short(d["title"], 36), bg=C["accent"], fg="white", font=FONT,
                     padx=8, pady=3).pack()
            self._ghost = g
        if d["active"]:
            self._ghost.geometry(f"+{ev.x_root + 12}+{ev.y_root + 8}")
            tgt = self._target_at(ev.x_root, ev.y_root)
            if tgt is not self._hover_target:
                if self._hover_target is not None and self._hover_target.winfo_exists():
                    self._hover_target.config(bg=C["bg"], fg=C["fg"])
                if tgt is not None:
                    tgt.config(bg=C["accent"], fg="white")
                self._hover_target = tgt

    def _target_at(self, x, y):
        w = self.win.winfo_containing(x, y)
        while w is not None:
            if hasattr(w, "_drop") and isinstance(w, tk.Label):
                return w
            if hasattr(w, "_drop"):
                lab = next((c for c in w.winfo_children() if hasattr(c, "_drop")), None)
                return lab
            w = w.master
        return None

    def _row_release(self, ev):
        d, self._row_drag = self._row_drag, None
        if self._ghost is not None:
            self._ghost.destroy()
            self._ghost = None
        if self._hover_target is not None and self._hover_target.winfo_exists():
            self._hover_target.config(bg=C["bg"], fg=C["fg"])
        self._hover_target = None
        if not d or not d["active"]:
            return
        tgt = self._target_at(ev.x_root, ev.y_root)
        if tgt is not None:
            self.app.run_fix(d["id"], dict(tgt._drop))

    # ------------------------------------------------------------------ move picker / menu
    def open_editor(self, entry_id, preset=None, message=""):
        MovePicker(self.app, entry_id, preset or {}, message)

    def _menu(self):
        m = self._new_menu()
        m.add_command(label="Sort files already in Downloads…", command=self.app.open_sort_existing)
        m.add_command(label="Reorganise old course folders…", command=self.app.open_migration)
        m.add_separator()
        m.add_command(label="Expand all", command=lambda: (self.collapsed.clear(), self.refresh()))
        m.add_command(label="Open courses folder", command=lambda: os.startfile(str(self.cfg.root_folder)))
        m.add_command(label="Open _Unsorted", command=lambda: os.startfile(str(self.cfg.unsorted_dir)))
        m.add_separator()
        m.add_command(label="Quit organiser", command=self.app.quit)
        m.tk_popup(*self.win.winfo_pointerxy())


class MovePicker:
    """One small panel: Module / Part / Type chips (+ name). Current placement preselected."""

    def __init__(self, app, entry_id, preset, message=""):
        self.app, self.core, self.cfg = app, app.core, app.core.cfg
        self.entry_id = entry_id
        e = self.core.log.get(entry_id)
        if not e:
            return
        c = Classification.from_dict(e.get("classification"))
        for k, v in preset.items():
            setattr(c, k, v)
        self.mod = c.module
        self.part = c.part
        self.cat = c.category if c.category else None
        self.topic0 = c.topic or ""
        w = self.w = tk.Toplevel(app.root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=C["line"])
        self.inner = tk.Frame(w, bg=C["bg"], padx=10, pady=8)
        self.inner.pack(padx=1, pady=1)
        head = tk.Frame(self.inner, bg=C["bg"])
        head.pack(fill="x")
        tk.Label(head, text=short(e["original_name"], 40), bg=C["bg"], fg=C["fg"], font=FONT_B).pack(side="left")
        FlatButton(head, "×", w.destroy, bg=C["bg"], fg=C["muted"], font=FONT_H, padx=4).pack(side="right")
        self.msg = tk.Label(self.inner, text=message, bg=C["bg"], fg=C["warn"], font=FONT_S, anchor="w")
        if message:
            self.msg.pack(fill="x")
        self.body = tk.Frame(self.inner, bg=C["bg"])
        self.body.pack(fill="x")
        self.v_topic = tk.StringVar(value=self.topic0)
        foot = tk.Frame(self.inner, bg=C["bg"])
        foot.pack(fill="x", pady=(8, 0))
        ent = tk.Entry(foot, textvariable=self.v_topic, bg=C["row"], fg=C["fg"], insertbackground=C["fg"],
                       relief="flat", font=FONT, width=28)
        ent.pack(side="left", ipady=3, fill="x", expand=True)
        FlatButton(foot, "Move", self._apply, bg=C["accent"], fg="white").pack(side="right", padx=(6, 0))
        w.bind("<Return>", lambda ev: self._apply())
        w.bind("<Escape>", lambda ev: w.destroy())
        self._render()
        w.update_idletasks()
        x = app.root.winfo_pointerx() - w.winfo_width() + 40
        y = app.root.winfo_pointery() - w.winfo_height() - 10
        w.geometry(f"+{max(0, x)}+{max(0, y)}")
        w.focus_force()

    def _chips(self, label, options, selected, on_pick, cols=4):
        tk.Label(self.body, text=label, bg=C["bg"], fg=C["muted"], font=FONT_S).pack(anchor="w", pady=(6, 1))
        f = tk.Frame(self.body, bg=C["bg"])
        f.pack(fill="x")
        for i, (value, text) in enumerate(options):
            b = FlatButton(f, text, lambda v=value: on_pick(v), font=FONT_S, padx=5)
            b.grid(row=i // cols, column=i % cols, padx=1, pady=1, sticky="we")
            b.set_selected(value == selected)
        for col in range(cols):
            f.columnconfigure(col, weight=1)

    def _render(self):
        for wdg in self.body.winfo_children():
            wdg.destroy()
        self._chips("Module", [(m.key, m.key) for m in self.cfg.modules], self.mod, self._set_mod, cols=3)
        mod = self.cfg.module(self.mod) if self.mod else None
        if mod:
            opts = [(i, short(p, 22)) for i, p in enumerate(mod.parts)] + [(None, "Whole module")]
            self._chips("Part", opts, self.part, self._set_part, cols=3)
            cats = self.cfg.module_categories if self.part is None else self.cfg.part_categories
            if self.cat not in cats:
                self.cat = None
            self._chips("Type", [(c, c) for c in cats], self.cat, self._set_cat, cols=4)

    def _set_mod(self, v):
        if v != self.mod:
            self.mod, self.part = v, (0 if self.cfg.module(v).parts else None)
        self._render()

    def _set_part(self, v):
        self.part = v
        self._render()

    def _set_cat(self, v):
        self.cat = v
        self._render()

    def _apply(self):
        if not self.mod or not self.cat:
            self.msg.config(text="Pick a module and a type")
            self.msg.pack(fill="x", before=self.body)
            return
        changes = {"module": self.mod, "part": self.part, "category": self.cat}
        topic = rules.clean_topic(self.v_topic.get())
        if topic and topic != self.topic0:
            changes["topic"] = topic
        self.app.run_fix(self.entry_id, changes)
        self.w.destroy()


class PreviewWindow:
    """Two-phase window: (optional) pick files -> classify -> review plan -> apply."""

    def __init__(self, app, mode):
        self.app, self.core, self.cfg, self.mode = app, app.core, app.core.cfg, mode
        self.items = []
        self.include = {}
        w = self.w = tk.Toplevel(app.root)
        w.title("Sort files already in Downloads" if mode == "existing" else "Reorganise old course folders")
        w.configure(bg=C["bg"])
        s = app.scale
        w.geometry(f"{int(980 * s)}x{int(560 * s)}")
        w.attributes("-topmost", True)
        w.after(400, lambda: w.attributes("-topmost", False))
        style = ttk.Style(w)
        style.theme_use("clam")
        style.configure("Treeview", background=C["row"], fieldbackground=C["row"], foreground=C["fg"],
                        rowheight=int(22 * s), font=FONT, borderwidth=0)
        style.configure("Treeview.Heading", background=C["panel"], foreground=C["muted"], font=FONT_S)
        style.map("Treeview", background=[("selected", C["accent_dim"])])
        self.info = tk.Label(w, text="", bg=C["bg"], fg=C["fg"], font=FONT, anchor="w", justify="left")
        self.info.pack(fill="x", padx=10, pady=(8, 4))
        frame = tk.Frame(w, bg=C["bg"])
        frame.pack(fill="both", expand=True, padx=10)
        self.tree = ttk.Treeview(frame, show="headings", selectmode="none")
        vs = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._toggle)
        self.tree.tag_configure("off", foreground=C["off"])
        self.tree.tag_configure("warn", foreground=C["warn"])
        self.bar = tk.Frame(w, bg=C["bg"])
        self.bar.pack(fill="x", padx=10, pady=8)
        if mode == "existing":
            self._phase_pick()
        else:
            self._classify(None)

    # phase 1 (existing only)
    def _phase_pick(self):
        files = self.core.list_downloads()
        self.files = files
        self.info.config(text=f"{len(files)} course-type files are in Downloads. Tick the ones to sort "
                              f"(click a row), then Classify. Nothing moves until you approve the plan.")
        self.tree.config(columns=("on", "name", "date", "size"))
        for col, txt, wd in (("on", "✓", 40), ("name", "File", 560), ("date", "Modified", 160), ("size", "Size", 90)):
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=int(wd * self.app.scale), stretch=col == "name", anchor="w")
        for i, f in enumerate(files):
            self.include[str(i)] = False
            self.tree.insert("", "end", iid=str(i), values=("", f["name"], time.strftime("%Y-%m-%d %H:%M", time.localtime(f["mtime"])),
                                                           f"{f['size'] // 1024} KB"), tags=("off",))
        for w in self.bar.winfo_children():
            w.destroy()
        FlatButton(self.bar, "Last 24 h", lambda: self._select_recent(1)).pack(side="left", padx=2)
        FlatButton(self.bar, "Last 7 days", lambda: self._select_recent(7)).pack(side="left", padx=2)
        FlatButton(self.bar, "None", lambda: self._select_recent(0)).pack(side="left", padx=2)
        tk.Label(self.bar, text="  Treat as:", bg=C["bg"], fg=C["muted"], font=FONT).pack(side="left")
        self.v_mod = tk.StringVar(value="Auto")
        ttk.Combobox(self.bar, textvariable=self.v_mod, state="readonly", width=12,
                     values=["Auto"] + [m.key for m in self.cfg.modules]).pack(side="left", padx=4)
        FlatButton(self.bar, "Cancel", self.w.destroy).pack(side="right", padx=2)
        FlatButton(self.bar, "Classify selected →", self._start_classify, bg=C["accent_dim"]).pack(side="right", padx=2)

    def _select_recent(self, days):
        cutoff = time.time() - days * 86400
        for i, f in enumerate(self.files):
            self._set(str(i), days > 0 and f["mtime"] >= cutoff)

    def _set(self, iid, on):
        self.include[iid] = on
        vals = list(self.tree.item(iid, "values"))
        vals[0] = "✓" if on else ""
        tags = () if on else ("off",)
        if on and self.items and self.items[int(iid)].get("unsorted"):
            tags = ("warn",)
        self.tree.item(iid, values=vals, tags=tags)

    def _toggle(self, ev):
        iid = self.tree.identify_row(ev.y)
        if iid and iid in self.include:
            self._set(iid, not self.include[iid])
            self._update_apply_label()
        return "break"

    def _start_classify(self):
        paths = [self.files[int(i)]["path"] for i, on in self.include.items() if on]
        if not paths:
            self.info.config(text="Tick at least one file first.")
            return
        mod = self.v_mod.get()
        self._classify(paths, (None if mod == "Auto" else mod, None))

    # phase 2
    def _classify(self, paths, pick=(None, None)):
        for w in self.bar.winfo_children():
            w.destroy()
        self.tree.delete(*self.tree.get_children())
        self.include = {}
        self.info.config(text="Classifying… (AI may take a few seconds per file)")
        uiq = self.app.uiq

        def progress(i, n, name):
            uiq.put(("call", lambda: self.info.config(text=f"Classifying {i}/{n}  {short(name, 70)}")))

        def job():
            if self.mode == "existing":
                items = self.core.preview_files(paths, pick, progress)
            else:
                items = migrate.plan_migration(self.cfg, progress)
            uiq.put(("call", lambda: self._show_plan(items)))

        self.core.submit(job)

    def _rel(self, p):
        try:
            return str(Path(p).relative_to(self.cfg.root_folder))
        except ValueError:
            return str(Path(p).name) if self.mode == "existing" else str(p)

    def _show_plan(self, items):
        if not self.w.winfo_exists():
            return
        self.items = items
        self.tree.config(columns=("on", "src", "dest", "conf", "note"))
        for col, txt, wd in (("on", "✓", 36), ("src", "From", 300), ("dest", "→ To (courses\\…)", 470),
                             ("conf", "Conf", 50), ("note", "Note", 150)):
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=int(wd * self.app.scale), stretch=col in ("src", "dest"), anchor="w")
        for i, it in enumerate(items):
            c = it.get("c") or {}
            on = it["action"] == "move"
            note = {"duplicate": "already have it", "skip": "not course material"}.get(it["action"], "")
            if it.get("unsorted"):
                note = "→ _Unsorted (unsure)"
            src = it.get("old_rel") or Path(it["src"]).name
            if it.get("kind") == "dir":
                src += "\\  (whole folder)"
            dest = self._rel(it["dest"]) if it.get("dest") else "(stays)"
            self.tree.insert("", "end", iid=str(i), values=("✓" if on else "", src, dest,
                                                            f"{int(c.get('confidence', 0) * 100)}%" if c else "", note),
                             tags=(("warn",) if it.get("unsorted") else ()) if on else ("off",))
            self.include[str(i)] = on
        for w in self.bar.winfo_children():
            w.destroy()
        n_dup = sum(1 for it in items if it["action"] == "duplicate")
        extra = f" {n_dup} duplicates stay put." if n_dup else ""
        if not items:
            self.info.config(text="Nothing to do: no old folders found." if self.mode == "migration" else "Nothing to do.")
        else:
            self.info.config(text="Review the plan. Click a row to include/exclude it. Amber = unsure, goes to "
                                  "_Unsorted for a one-click fix later. Numbers are final when applied." + extra)
        FlatButton(self.bar, "Cancel", self.w.destroy).pack(side="right", padx=2)
        self.apply_btn = FlatButton(self.bar, "", self._apply, bg=C["accent_dim"])
        self.apply_btn.pack(side="right", padx=2)
        self._update_apply_label()

    def _update_apply_label(self):
        if hasattr(self, "apply_btn") and self.items:
            n = sum(1 for i, on in self.include.items() if on and self.items[int(i)]["action"] == "move")
            self.apply_btn.config(text=f"Apply {n} move{'s' if n != 1 else ''}")

    def _apply(self):
        chosen = [it for i, it in enumerate(self.items) if self.include.get(str(i)) and it["action"] == "move"]
        kind = "migration" if self.mode == "migration" else "existing"
        uiq = self.app.uiq

        def job():
            done = self.core.apply_items(chosen, kind=kind)
            uiq.put(("call", lambda: self.app.toast("Done", f"Moved {len(done)} item(s)")))

        self.core.submit(job)
        self.w.destroy()
        self.app.dashboard.show()
