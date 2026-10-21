"""One-off 'Reorganise existing': plan moves for old folders under courses/ into the new tree.

Only produces a plan; Organiser.apply_items() performs it after the user approves.
Folders that are not plain category containers (e.g. a practical with a VM and a repo)
are moved whole, never split.
"""
import os
import re
from datetime import datetime
from pathlib import Path

from . import placer, rules
from .classify import classify
from .extract import ExtractError, extract

CONTAINERS = [
    ("Lectures", r"^(lec|lecs|lectures?|slides|lecture slides|lecture notes)$"),
    ("Practicals", r"^(pract|practs|practicals?|labs?|tutorials?|worksheets?|problem sheets?)$"),
    ("Solutions", r"^(solutions?|answers?)$"),
    ("Readings", r"^(readings?|papers|books?|resources)$"),
    ("Assessment", r"^(assessments?|coursework|assignments?|cw)$"),
    ("Exam Prep", r"^(exams?|exam prep|past papers|revision)$"),
]
TEXT_EXTS = {".pdf", ".pptx", ".docx", ".ipynb", ".py", ".c", ".txt", ".md", ".csv", ".html", ".htm", ".zip"}


def _container_category(name):
    n = rules.normalise(name)
    for cat, rx in CONTAINERS:
        if re.match(rx, n):
            return cat
    return None


def _file_text(p):
    if p.suffix.lower() not in TEXT_EXTS:
        return "", "", None
    try:
        text, title = extract(p)
        if p.suffix.lower() in (".html", ".htm"):
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text)
        return text, title, None
    except ExtractError as e:
        return "", "", str(e)[:200]


def _dir_text(d):
    """File listing plus the text of the most relevant document inside."""
    files = []
    for dirpath, dirnames, filenames in os.walk(d):
        dirnames[:] = [x for x in dirnames if x not in placer.SKIP_DIRS]
        for f in filenames:
            files.append(Path(dirpath) / f)
        if len(files) > 300:
            break
    listing = "\n".join(str(f.relative_to(d)) for f in files[:60])
    docs = [f for f in files if f.suffix.lower() in (".pdf", ".docx", ".pptx", ".md", ".txt")
            and f.relative_to(d).parts.__len__() <= 3]
    docs.sort(key=lambda f: (0 if f.name.lower().startswith("readme") else 1,
                             0 if f.suffix.lower() == ".pdf" else 1, len(f.relative_to(d).parts)))
    body, title = "", ""
    for doc in docs[:2]:
        t, ti, _ = _file_text(doc)
        if t:
            body, title = t[:2500], ti
            break
    return f"Folder '{d.name}' containing:\n{listing}\n\nMain document:\n{body}", title


def old_dirs(cfg):
    keep = {m.key for m in cfg.modules} | {"_Unsorted"}
    if not cfg.root_folder.is_dir():
        return []
    return sorted(d for d in cfg.root_folder.iterdir() if d.is_dir() and d.name not in keep)


def plan_migration(cfg, progress=None):
    items = []
    dirs = old_dirs(cfg)
    work = []
    for top in dirs:
        mod = rules.module_from_names(cfg, top.name) or rules.module_from_code(cfg, top.name)
        pmod, ppart = rules.module_from_prefix(cfg, top.name)
        if not mod and pmod:
            mod = pmod
        part_hint = ppart if pmod and pmod == mod else None
        _collect(top, top, mod, part_hint, None, work)
    for i, (src, top, mod, part_hint, cat_hint) in enumerate(work):
        if progress:
            progress(i, len(work), src.name)
        when = datetime.fromtimestamp(src.stat().st_mtime)
        if src.is_dir():
            text, title = _dir_text(src)
            error = None
        else:
            text, title, error = _file_text(src)
        c = classify(cfg, src.name, text, title, manual_module=mod, manual_part=part_hint,
                     error=error, when=when)
        if cat_hint and c.sources.get("category") not in ("filename",):
            c.category = cat_hint
            c.sources["category"] = "old folder"
            c.confidence = max(c.confidence, min(1.0, 0.85 if c.module else 0.0))
        items.append({"src": str(src), "kind": "dir" if src.is_dir() else "file", "action": "move",
                      "c": c.to_dict(), "text": text[:3000], "title": title, "cleanup": str(top),
                      "old_rel": str(src.relative_to(cfg.root_folder))})
    if progress:
        progress(len(work), len(work), "")
    _preview_dests(cfg, items)
    return items


def _collect(d, top, mod, part_hint, cat_hint, out):
    for child in sorted(d.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.is_dir():
            cat = _container_category(child.name)
            if cat:
                _collect(child, top, mod, part_hint, cat, out)
                continue
        out.append((child, top, mod, part_hint, cat_hint))


def _preview_dests(cfg, items):
    """Approximate destinations, simulating folders that earlier items will create."""
    from .classify import Classification
    planned = {}          # (module, part, number) -> practical folder
    counters = {}         # (folder, prefix) -> next number
    items.sort(key=lambda it: 0 if it["kind"] == "dir" else 1)
    for it in items:
        c = Classification.from_dict(it["c"])
        name = Path(it["src"]).name
        pl = placer.plan(cfg, c, name, is_dir=it["kind"] == "dir")
        dest = pl.dest
        if not pl.unsorted and c.category in placer.FOLDERED:
            folder = placer.category_dir(cfg, c)
            prefix = placer.FOLDERED[c.category]
            if c.number is None:  # successive unnumbered items get successive numbers
                key = (str(folder), prefix)
                n = counters.get(key) or placer.next_free_number(folder, prefix)
                for k, v in planned.items():
                    if k[:2] == (c.module, c.part) and prefix == "Practical":
                        n = max(n, k[2] + 1)
                counters[key] = n + 1
                c.number = n
                pl = placer.plan(cfg, c, name, is_dir=it["kind"] == "dir")
                dest = pl.dest
                it["c"]["number"] = n
            if c.category == "Practicals":
                k = (c.module, c.part, c.number)
                if it["kind"] == "dir":
                    planned.setdefault(k, dest)
                elif k in planned:
                    is_code = Path(name).suffix.lower() in rules.CODE_EXTS
                    dest = planned[k] / (name if is_code else f"Practical {c.number:02d} - {c.topic}{Path(name).suffix}")
                else:
                    planned[k] = dest.parent
        it["dest"] = str(dest)
        it["unsorted"] = pl.unsorted
