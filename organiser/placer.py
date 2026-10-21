"""Where a classified file goes, what it is called, and moving it safely.

Never deletes or overwrites: clashes get ' (2)', ' (3)', ...
"""
import hashlib
import os
import re
import shutil
import threading
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .classify import part_needed
from .rules import CODE_EXTS, clean_stem, is_junk_title

PREFIX = {"Lectures": "Lecture", "Practicals": "Practical", "Solutions": "Solutions"}
FOLDERED = {"Lectures": "Lecture", "Practicals": "Practical"}
ATTACHED = {"Solutions": "Solutions"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__"}


@dataclass
class Placement:
    dest: Path
    unsorted: bool
    rename_folder: tuple = None   # (old_dir, new_dir) for a bare "Practical NN" folder


def unique_path(p):
    p = Path(p)
    if not p.exists():
        return p
    stem, ext = (p.stem, p.suffix) if p.is_file() else (p.name, "")
    i = 2
    while True:
        cand = p.with_name(f"{stem} ({i}){ext}")
        if not cand.exists():
            return cand
        i += 1


def category_dir(cfg, c):
    """Module/Lectures/<Part>, Module/Practicals/<Part>, Module/Lectures/<Part>/Readings;
    everything else lives in Module/Other."""
    mod = cfg.module(c.module)
    base = cfg.root_folder / mod.key
    if c.category in FOLDERED or c.category == "Readings":
        base = base / ("Lectures" if c.category == "Readings" else c.category)
        if c.part is not None and mod.parts:
            base = base / mod.parts[c.part]
        return base / "Readings" if c.category == "Readings" else base
    return base / "Other"


def is_confident(cfg, c):
    return bool(c.module and c.category and c.confidence >= cfg.confidence_threshold
                and not (part_needed(cfg, c) and c.part is None) and not c.not_course)


def next_free_number(folder, prefix):
    rx = re.compile(rf"^{re.escape(prefix)} (\d+)\b", re.I)
    nums = [int(m.group(1)) for e in (os.listdir(folder) if Path(folder).is_dir() else [])
            if (m := rx.match(e))]
    return max(nums, default=0) + 1


def find_numbered_folder(folder, prefix, n):
    if not Path(folder).is_dir():
        return None
    rx = re.compile(rf"^{prefix} 0*{n}(?!\d)", re.I)
    for e in sorted(os.listdir(folder)):
        if rx.match(e) and (Path(folder) / e).is_dir():
            return Path(folder) / e
    return None


def _needs_name(prefix, name):
    """'Practical 03' (created by a code file) or 'Lecture 01 - ultraDocumentBody Copy' get the real topic."""
    m = re.fullmatch(rf"{prefix} \d+(?: - (.*))?", name)
    return bool(m) and (m.group(1) is None or is_junk_title(m.group(1)))


def find_practical_folder(folder, n):
    return find_numbered_folder(folder, "Practical", n)


def plan(cfg, c, src_name, is_dir=False, bundle_hint=None):
    """Return a Placement. Low-confidence results go to _Unsorted under the original name."""
    if not is_confident(cfg, c):
        return Placement(unique_path(cfg.unsorted_dir / src_name), True)
    folder = category_dir(cfg, c)
    ext = "" if is_dir else Path(src_name).suffix.lower()
    orig_ext = "" if is_dir else Path(src_name).suffix
    is_code = ext in CODE_EXTS
    topic = c.topic

    if c.category in FOLDERED:
        # One folder per lecture / practical: "Lecture 03 - Topic\" holds slides, notes, code...
        prefix = FOLDERED[c.category]
        n = c.number
        pfolder = find_numbered_folder(folder, prefix, n) if n else None
        if pfolder is None and not n and c.category == "Practicals" and bundle_hint                 and Path(bundle_hint).is_dir() and Path(bundle_hint).parent == folder:
            pfolder = Path(bundle_hint)
        if pfolder is None and not n:
            n = next_free_number(folder, prefix)
        if is_dir:
            if pfolder is not None:  # already a folder for this number: keep both, nest it
                return Placement(unique_path(pfolder / src_name), False)
            return Placement(unique_path(folder / f"{prefix} {n:02d} - {topic}"), False)
        rename = None
        if pfolder is None:
            pfolder = folder / (f"{prefix} {n:02d}" if is_code else f"{prefix} {n:02d} - {topic}")
        elif not is_code and _needs_name(prefix, pfolder.name):
            num0 = int(re.match(rf"{prefix} (\d+)", pfolder.name).group(1))
            new_dir = unique_path(pfolder.with_name(f"{prefix} {num0:02d} - {topic}"))
            rename = (pfolder, new_dir)
            pfolder = new_dir
        num = int(re.match(rf"{prefix} (\d+)", pfolder.name).group(1))
        name = src_name if is_code else f"{prefix} {num:02d} - {topic}{orig_ext}"
        return Placement(unique_path(pfolder / name), False, rename)

    if c.category in ATTACHED and c.number and c.part is not None:
        # Answers live inside the lecture or practical they belong to.
        home = "Lectures" if c.relates_to == "Lectures" else "Practicals"
        prefix, label, n = FOLDERED[home], ATTACHED[c.category], c.number
        mod = cfg.module(c.module)
        folder = cfg.root_folder / mod.key / home / mod.parts[c.part]
        pfolder = find_numbered_folder(folder, prefix, n) or folder / f"{prefix} {n:02d}"
        name = src_name if is_dir else (f"{label} {n:02d} - {src_name}" if is_code else f"{label} {n:02d} - {topic}{orig_ext}")
        return Placement(unique_path(pfolder / name), False)

    if is_dir or is_code:
        return Placement(unique_path(folder / src_name), False)
    return Placement(unique_path(folder / f"{topic}{orig_ext}"), False)


def move(src, dest):
    dest = unique_path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return dest


def apply_folder_rename(rename):
    """Rename a bare 'Practical NN' / 'Lecture NN' folder once its document (with topic) arrives."""
    old, new = rename
    if old.is_dir() and not new.exists():
        old.rename(new)
        return True
    return False


def remove_if_empty_practical(folder):
    folder = Path(folder)
    try:
        if folder.is_dir() and folder.name.startswith(("Practical ", "Lecture ")) and not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        pass


def extract_zip(zip_path, max_bytes=3 * 1024 ** 3):
    """Extract next to the zip into '<stem>/'. Guards against path traversal."""
    zip_path = Path(zip_path)
    target = unique_path(zip_path.with_name(clean_stem(zip_path.name)))
    with zipfile.ZipFile(zip_path) as z:
        if sum(i.file_size for i in z.infolist()) > max_bytes:
            raise ValueError("zip too large to auto-extract")
        target.mkdir(parents=True)
        root = target.resolve()
        for info in z.infolist():
            out = (target / info.filename).resolve()
            if not str(out).startswith(str(root)):
                continue
            z.extract(info, target)
    # Single top-level folder of the same name inside? Leave as is: never reshuffle user content.
    return target


def file_hash(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


class DupIndex:
    """Size -> paths index of everything under root; hashes only on size collisions."""

    def __init__(self, root):
        self.root = Path(root)
        self.by_size = defaultdict(set)
        self._hashes = {}
        self._lock = threading.Lock()
        self.ready = threading.Event()

    def build(self):
        by_size = defaultdict(set)
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for f in filenames:
                p = os.path.join(dirpath, f)
                try:
                    by_size[os.path.getsize(p)].add(p)
                except OSError:
                    pass
        with self._lock:
            self.by_size = by_size
        self.ready.set()

    def _hash(self, p):
        st = os.stat(p)
        key = (p, st.st_mtime, st.st_size)
        if key not in self._hashes:
            self._hashes[key] = file_hash(p)
        return self._hashes[key]

    def find(self, path):
        self.ready.wait(timeout=30)
        try:
            size = os.path.getsize(path)
        except OSError:
            return None
        if size == 0:
            return None
        with self._lock:
            cands = list(self.by_size.get(size, ()))
        if not cands:
            return None
        h = file_hash(path)
        for cand in cands:
            try:
                if os.path.exists(cand) and os.path.normcase(cand) != os.path.normcase(str(path)) and self._hash(cand) == h:
                    return cand
            except OSError:
                continue
        return None

    def add(self, path):
        path = str(path)
        try:
            if os.path.isdir(path):
                for dirpath, _, filenames in os.walk(path):
                    for f in filenames:
                        self.add(os.path.join(dirpath, f))
                return
            with self._lock:
                self.by_size[os.path.getsize(path)].add(path)
        except OSError:
            pass

    def remove(self, path):
        path = str(path)
        with self._lock:
            for s in self.by_size.values():
                s.discard(path)
