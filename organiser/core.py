"""The organiser engine: watching, classifying, moving, undo/fix. No UI code here.

Threads: watchdog observer -> pending dict -> stabiliser thread -> job queue ->
ONE worker thread (all classification and file moves happen there, sequentially).
"""
import logging
import os
import queue
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from . import placer, rules
from .classify import Classification, classify, part_needed
from . import notebooks
from .config import ensure_skeleton
from .extract import ExtractError, extract
from .store import Log, State

log = logging.getLogger("organiser.core")

TEMP_EXTS = {".crdownload", ".tmp", ".part", ".partial", ".download", ".opdownload"}
BUNDLE_WINDOW = 15 * 60


def norm(p):
    return os.path.normcase(os.path.abspath(str(p)))


class _Handler(FileSystemEventHandler):
    def __init__(self, core):
        self.core = core

    def on_created(self, event):
        if not event.is_directory:
            self.core._seen(event.src_path)

    def on_moved(self, event):  # Chrome/Edge: .crdownload -> final name
        if not event.is_directory:
            self.core._seen(event.dest_path)

    def on_modified(self, event):
        if not event.is_directory:
            self.core._seen(event.src_path, touch_only=True)


class Organiser:
    def __init__(self, cfg):
        self.cfg = cfg
        self.log = Log(cfg.data_dir / "log.json")
        self.state = State(cfg.data_dir / "state.json")
        self.dups = placer.DupIndex(cfg.root_folder)
        self.active = False
        self.pick_module = None
        self.pick_part = None
        self.session_start = None      # "YYYY-mm-dd HH:MM:SS" of the last Alt+O on
        self.state_listeners = []
        self.notify = lambda title, msg: None
        self.on_tagged = lambda entry: None
        self._observer = None
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._inflight = set()        # detected by the watcher, queued for the worker
        self._suppress = {}
        self._contexts = {}
        self._ctx_lock = threading.Lock()
        self.extension_seen = 0.0
        self._last_practical = {}
        self._jobs = queue.Queue()
        self._stop = threading.Event()

    # ---------------------------------------------------------------- lifecycle
    def start(self):
        ensure_skeleton(self.cfg)
        threading.Thread(target=self.dups.build, daemon=True, name="dup-index").start()
        threading.Thread(target=self._worker, daemon=True, name="worker").start()
        threading.Thread(target=self._stabiliser, daemon=True, name="stabiliser").start()

    def shutdown(self):
        self.deactivate()
        self._stop.set()
        self._jobs.put(None)

    def submit(self, fn, *args, **kwargs):
        self._jobs.put((fn, args, kwargs))

    def _worker(self):
        while True:
            job = self._jobs.get()
            if job is None:
                return
            fn, args, kwargs = job
            try:
                fn(*args, **kwargs)
            except Exception:
                log.exception("job %s failed", getattr(fn, "__name__", fn))

    def _emit_state(self):
        for cb in list(self.state_listeners):
            try:
                cb()
            except Exception:
                pass

    # ---------------------------------------------------------------- on / off
    def activate(self, module=None, part=None):
        self.pick_module, self.pick_part = module, part
        if not self.active:
            self.session_start = time.strftime("%Y-%m-%d %H:%M:%S")
            self.cfg.downloads_folder.mkdir(parents=True, exist_ok=True)
            obs = Observer()
            obs.schedule(_Handler(self), str(self.cfg.downloads_folder), recursive=False)
            obs.start()
            self._observer = obs
            self.active = True
        self._emit_state()

    def set_pick(self, module, part):
        self.pick_module, self.pick_part = module, part
        self._emit_state()

    def deactivate(self):
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=3)
            self._observer = None
        self.active = False
        with self._pending_lock:
            self._pending.clear()
        self._emit_state()

    def toggle(self):
        if self.active:
            self.deactivate()
        else:
            self.activate()
        return self.active

    # ---------------------------------------------------------------- detection
    def is_candidate(self, path):
        p = Path(path)
        name = p.name
        if name.startswith(("~$", ".~", "~")) or name.lower() in ("desktop.ini", "thumbs.db"):
            return False
        ext = p.suffix.lower()
        if ext in TEMP_EXTS:
            return False
        return ext in self.cfg.file_types

    def _seen(self, path, touch_only=False):
        if not self.active or not self.is_candidate(path):
            return
        if Path(path).parent != self.cfg.downloads_folder and norm(Path(path).parent) != norm(self.cfg.downloads_folder):
            return
        key = norm(path)
        until = self._suppress.get(key)
        if until and until > time.time():
            return
        with self._pending_lock:
            if key in self._pending:
                self._pending[key]["changed"] = time.time()
            elif not touch_only:  # edits to files that were already there are not downloads
                now = time.time()
                self._pending[key] = {"path": path, "first": now, "changed": now, "size": -1,
                                      "pick": (self.pick_module, self.pick_part)}

    def _stabiliser(self):
        while not self._stop.is_set():
            time.sleep(0.5)
            now = time.time()
            ready = []
            with self._pending_lock:
                for key, info in list(self._pending.items()):
                    p = info["path"]
                    try:
                        size = os.path.getsize(p)
                    except OSError:
                        del self._pending[key]       # renamed away / deleted
                        continue
                    if size != info["size"]:
                        info["size"], info["changed"] = size, now
                        continue
                    if now - info["changed"] < 1.5 or now - info["first"] < 3.0:
                        continue
                    if size == 0 and now - info["first"] < 8:
                        continue
                    try:
                        with open(p, "rb"):
                            pass
                    except OSError:
                        info["changed"] = now        # still locked by the writer
                        continue
                    ready.append(info)
                    del self._pending[key]
            for info in ready:
                self._inflight.add(norm(info["path"]))
                self.submit(self.process_download, info["path"], info["pick"])

    def suppress(self, path, seconds=20):
        self._suppress[norm(path)] = time.time() + seconds

    # ---------------------------------------------------------------- extension context
    def add_context(self, ctx):
        self.extension_seen = time.time()
        path = ctx.get("path")
        if not path:
            return
        with self._ctx_lock:
            self._contexts[norm(path)] = (time.time(), ctx)
            cutoff = time.time() - 900
            for k in [k for k, (t, _) in self._contexts.items() if t < cutoff]:
                del self._contexts[k]
        late = next((e for e in reversed(self.log.entries[-30:])
                     if norm(e.get("original_path", "")) == norm(path) and not e.get("context")
                     and e.get("kind") == "download" and e["status"] in ("sorted", "flagged")), None)
        if late:
            self.submit(self._apply_late_context, late["id"], ctx)
            return
        with self._pending_lock:
            watched = norm(path) in self._pending or norm(path) in self._inflight
        if not watched:  # not something the Alt+O watcher is already handling
            self.submit(self._process_tagged, path, ctx)

    def _process_tagged(self, path, ctx):
        """A download started from the extension is an explicit 'organise this': sort it even when Alt+O is off."""
        src = Path(path)
        if not self.is_candidate(src) or norm(src.parent) != norm(self.cfg.downloads_folder):
            return
        last, since, end = -1, time.time(), time.time() + 60
        while True:                                  # wait until the file exists and stops growing
            try:
                size = src.stat().st_size
            except OSError:
                size = None
                if self._handled(src):
                    return                           # the watcher already sorted it
            if size is not None and size == last and time.time() - since >= 1.5:
                break
            if size != last:
                last, since = size, time.time()
            if time.time() > end:
                return
            time.sleep(0.3)
        with self._pending_lock:
            if norm(src) in self._pending or norm(src) in self._inflight:
                return
        if any(norm(e.get("current_path", "")) == norm(src) for e in self.log.entries[-200:]):
            return                                   # this exact file is already tracked (duplicate/undone/...)
        pick = (self.pick_module, self.pick_part) if self.active else (None, None)
        e = self.process_file(src, pick, ctx, kind="download")
        if e:
            self.on_tagged(e)

    def _handled(self, src):
        cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 300))
        return any(norm(e.get("original_path", "")) == norm(src) and e["time"] >= cutoff
                   for e in self.log.entries[-50:])

    def _apply_late_context(self, entry_id, ctx):
        """Context arrived after the file was already sorted: re-place it using Blackboard's answer."""
        e = self.log.get(entry_id)
        if not e or e["status"] not in ("sorted", "flagged"):
            return
        c = classify(self.cfg, e["original_name"], e.get("text", ""), e.get("title", ""), context=ctx)
        self.log.update(entry_id, context=ctx)
        if c.sources.get("module") != "blackboard":
            return
        old = Classification.from_dict(e.get("classification"))
        if (c.module, c.part, c.category) == (old.module, old.part, old.category) and e["status"] == "sorted":
            return
        changes = {"module": c.module, "part": c.part, "category": c.category or "Other"}
        if c.number:
            changes["number"] = c.number
        if c.topic:
            changes["topic"] = c.topic
        self.reassign(entry_id, **changes)

    def get_context(self, path, wait=0.0):
        deadline = time.time() + wait
        while True:
            with self._ctx_lock:
                hit = self._contexts.get(norm(path))
                if not hit:
                    base = Path(path).name.lower()
                    hit = next((v for k, v in self._contexts.items()
                                if Path(k).name == base and time.time() - v[0] < 180), None)
            if hit or time.time() >= deadline:
                return hit[1] if hit else None
            time.sleep(0.25)

    # ---------------------------------------------------------------- processing
    def process_download(self, path, pick=(None, None)):
        try:
            return self._process_download(path, pick)
        finally:
            self._inflight.discard(norm(path))

    def _process_download(self, path, pick):
        if not self.active:
            return None                              # switched off after detection: do nothing
        src = Path(path)
        if not src.exists():
            return None
        # The extension pings /status when a Blackboard download starts; give its context time to arrive.
        wait = 6.0 if time.time() - self.extension_seen < 60 else 0.0
        ctx = self.get_context(src, wait=wait)
        return self.process_file(src, pick, ctx, kind="download")

    def in_layout(self, path):
        """True if path is a proper new-layout location (Module/Lectures|Practicals|Other|Website/...)."""
        try:
            rel = Path(path).relative_to(self.cfg.root_folder).parts
        except ValueError:
            return False
        return len(rel) >= 3 and self.cfg.module(rel[0]) is not None and \
            rel[1] in ("Lectures", "Practicals", "Other", "Website")

    def process_file(self, src, pick=(None, None), ctx=None, kind="download", when=None):
        src = Path(src)
        src = self._repair_notebook(src, ctx)
        text, title, error = "", "", None
        try:
            text, title = extract(src)
        except ExtractError as ex:
            error = str(ex)[:200]
        if when is None:
            when = datetime.now() if kind == "download" else datetime.fromtimestamp(src.stat().st_mtime)
        c = classify(self.cfg, src.name, text, title, context=ctx, manual_module=pick[0],
                     manual_part=pick[1], error=error, when=when)
        dup = None if src.is_dir() else self.dups.find(src)
        if dup:
            if self._already_in_place(dup, c, src):
                if kind == "fetched":
                    src.unlink(missing_ok=True)   # our own background fetch of something we already have
                    return None
                binned = self._to_bin(src)        # discard the new copy (kept in Bin, never deleted)
                e = self.log.add(kind=kind, status="duplicate", original_path=str(src), current_path=str(binned),
                                 duplicate_of=dup, original_name=src.name, classification=c.to_dict(),
                                 context=ctx, message=f"Already in {self.short_dest(dup)}")
                self.notify("Already have it", f"{src.name}\nin {self.short_dest(dup)}")
                return e
            # We have it, but in the wrong place: this copy goes to the right folder, the stray one to the Bin.
            self._retire_stray(dup)
        if c.not_course and not pick[0] and not ctx:
            return self.log.add(kind=kind, status="skipped", original_path=str(src), current_path=str(src),
                                original_name=src.name, classification=c.to_dict(), text=text[:3000],
                                title=title, context=ctx, message="Not course material - left in Downloads")
        return self._place(src, c, kind=kind, text=text, title=title, ctx=ctx)

    def _already_in_place(self, dup, c, src):
        """Is the existing identical copy where this file belongs (or right next to it)?"""
        if not self.in_layout(dup):
            return False
        owner = self._owner(dup)
        if owner and "Fixed by you" in (owner.get("message") or ""):
            return True                          # you put it there yourself
        owner_src = ((owner or {}).get("classification") or {}).get("sources", {}).get("module")
        if owner_src == "blackboard" and c.sources.get("module") != "blackboard":
            return True                          # placed with Blackboard's exact course info: trust it
        if not placer.is_confident(self.cfg, c):
            return True                          # we don't know better than where it already is
        home = placer.category_dir(self.cfg, c)  # e.g. DLCV/Lectures/Deep Learning (any lecture folder in it)
        try:
            Path(dup).relative_to(home)
            return True
        except ValueError:
            return False

    def _owner(self, path):
        return next((e for e in reversed(self.log.entries)
                     if norm(e.get("current_path", "")) == norm(path) and e["status"] in ("sorted", "flagged")), None)

    def _to_bin(self, path):
        bin_dir = self.cfg.root_folder.parent / "Bin" / "organiser-duplicates"
        bin_dir.mkdir(parents=True, exist_ok=True)
        self.dups.remove(path)
        return placer.move(path, bin_dir / Path(path).name)

    def _retire_stray(self, dup):
        owner = self._owner(dup)
        old_parent = Path(dup).parent
        binned = self._to_bin(dup)
        placer.remove_if_empty_practical(old_parent)
        if owner:
            self.log.update(owner["id"], status="duplicate", current_path=str(binned),
                            message="Wrong place: newer copy sorted, this one moved to Bin")
        log.info("stray duplicate %s moved to Bin", dup)

    def _repair_notebook(self, src, ctx):
        """A '.ipynb' that is really a Colab web page: fetch the real notebook instead."""
        if src.suffix.lower() != ".ipynb" or not src.is_file() or notebooks.is_notebook(src):
            return src
        raw = notebooks.raw_url((ctx or {}).get("url", ""))
        if not raw:
            return src
        try:
            good = notebooks.fetch(raw, src.parent, name=src.stem + ".nb-download.tmp")
            junk_dir = self.cfg.root_folder.parent / "Bin" / "organiser-replaced"
            junk_dir.mkdir(parents=True, exist_ok=True)
            final = src
            self.suppress(src)
            placer.move(src, junk_dir / src.name)
            os.replace(good, final)
            log.info("replaced Colab page %s with the real notebook", src.name)
            return final
        except Exception as ex:
            log.warning("could not fetch real notebook for %s: %s", src.name, ex)
            return src

    def _retarget_code(self, c, ctx, src):
        """Notebooks linked from a lecture line go to the practical on the same topic, if there is one."""
        mod = self.cfg.module(c.module)
        if not mod or c.part is None or not mod.parts:
            return
        pdir = self.cfg.root_folder / mod.key / "Practicals" / mod.parts[c.part]
        want = _tokens(rules.clean_topic((ctx or {}).get("item_title") or "")) | _tokens(src.stem)
        best, best_score = None, 0
        for d in (pdir.iterdir() if pdir.is_dir() else []):
            m = re.match(r"Practical (\d+)(?: - (.*))?$", d.name)
            if d.is_dir() and m:
                score = len(want & _tokens(m.group(2) or ""))
                if score > best_score:
                    best, best_score = int(m.group(1)), score
        if best is not None and best_score >= 2:
            c.category, c.number = "Practicals", best
            c.sources["category"] = "matched practical"

    def _fetch_linked_notebooks(self, entry_id):
        """Slides/practical PDFs often link Colab notebooks: download those too."""
        e = self.log.get(entry_id)
        if not e or e["status"] != "sorted" or not e["current_path"].lower().endswith(".pdf"):
            return
        c = Classification.from_dict(e.get("classification"))
        mod = self.cfg.module(c.module) if c.module else None
        if not mod:
            return
        urls = notebooks.links_in_pdf(e["current_path"])
        have = {p.name.lower() for p in (self.cfg.root_folder / mod.key).rglob("*.ipynb")}
        ctx = dict(e.get("context") or {})
        ctx.setdefault("course_code", mod.code)
        ctx.setdefault("course_name", mod.name)
        if c.part is not None and mod.parts and not ctx.get("chain"):
            ctx["chain"] = [mod.parts[c.part]]
        if c.number and c.category in ("Lectures", "Practicals"):
            ctx["item_title"] = f"{c.category[:-1]} {c.number}: {c.topic}"
        for url in urls:
            name = url.rstrip("/").split("/")[-1]
            if not name.lower().endswith(".ipynb") or name.lower() in have:
                continue
            try:
                path = notebooks.fetch(url, self.cfg.downloads_folder)
            except Exception as ex:
                log.warning("linked notebook %s failed: %s", url, ex)
                continue
            self.suppress(path)
            self.process_file(path, (None, None), {**ctx, "link_text": "", "url": url, "source": "pdf link"},
                              kind="fetched")
            have.add(name.lower())

    def _bundle_hint(self, c):
        hint = self._last_practical.get((c.module, c.part))
        if hint and time.time() - hint[1] < BUNDLE_WINDOW:
            return hint[0]
        return None

    def _place(self, src, c, kind, text="", title="", ctx=None, entry=None, extract_zips=True):
        src = Path(src)
        if ctx and c.category == "Lectures" and src.suffix.lower() in (".ipynb", ".py") \
                and c.sources.get("category") != "user":
            self._retarget_code(c, ctx, src)
        pl = placer.plan(self.cfg, c, src.name, is_dir=src.is_dir(), bundle_hint=self._bundle_hint(c))
        if pl.rename_folder and placer.apply_folder_rename(pl.rename_folder):
            self.log.repath(pl.rename_folder[0], pl.rename_folder[1])
            self.dups.add(pl.rename_folder[1])
        old_parent = src.parent
        dest = placer.move(src, pl.dest)
        self.dups.remove(src)
        self.dups.add(dest)
        extras, flags = [], list(c.flags)
        if extract_zips and dest.suffix.lower() == ".zip" and not pl.unsorted:
            try:
                extras.append(str(placer.extract_zip(dest)))
            except Exception as ex:
                flags.append(f"zip not extracted: {ex}")
        if dest.suffix.lower() == ".ipynb" and not pl.unsorted and notebooks.is_notebook(dest):
            pdf = notebooks.to_pdf(dest)              # printable copy next to the notebook
            if pdf:
                extras.append(str(pdf))
                self.dups.add(pdf)
        if c.category == "Practicals" and not pl.unsorted:
            folder = dest if dest.is_dir() else dest.parent
            if folder.name.startswith("Practical "):
                self._last_practical[(c.module, c.part)] = (folder, time.time())
        placer.remove_if_empty_practical(old_parent)
        c.flags = flags
        status = "flagged" if pl.unsorted else "sorted"
        fields = dict(status=status, current_path=str(dest), classification=c.to_dict(), extras=extras,
                      message=self._reason(c, pl.unsorted))
        if entry is None:
            e = self.log.add(kind=kind, original_path=str(src), original_name=src.name, text=text[:3000],
                             title=title, context=ctx, **fields)
        else:
            e = self.log.update(entry["id"], **fields)
        if pl.unsorted:
            self.notify("Needs a check", f"{src.name} -> _Unsorted ({e['message']})")
        elif kind == "download":
            self.notify(f"Sorted: {dest.name}"[:60], self.short_dest(dest))
        if not pl.unsorted and dest.suffix.lower() == ".pdf" and c.category in ("Lectures", "Practicals"):
            self.submit(self._fetch_linked_notebooks, e["id"])
        return e

    # ---------------------------------------------------------------- failed downloads
    def fetch_url(self, url, name=None, ctx=None):
        """Download a URL ourselves (fallback when the browser failed). Logs a clear failure otherwise."""
        try:
            path = notebooks.fetch(notebooks.raw_url(url) or url, self.cfg.downloads_folder, name=name)
        except Exception as ex:
            err = _friendly_error(ex)
            self.log.add(kind="download", status="failed", original_path="", current_path="",
                         original_name=name or url.rstrip("/").split("/")[-1], classification={},
                         context=ctx, url=url, message=f"Download failed: {err}")
            self.notify("Download failed", f"{name or url}\n{err}")
            return None, err
        self.suppress(path)
        e = self.process_file(path, (None, None), {**(ctx or {}), "path": str(path), "url": url}, kind="download")
        return e, None

    def retry_failed(self, entry_id):
        e = self.log.get(entry_id)
        if not e or e["status"] != "failed":
            return None
        self.log.update(entry_id, status="retried", message="Retried")
        r, err = self.fetch_url(e.get("url") or "", e.get("original_name"), e.get("context"))
        return r

    def short_dest(self, path):
        try:
            return " › ".join(Path(path).parent.relative_to(self.cfg.root_folder).parts)
        except ValueError:
            return str(Path(path).parent)

    def _reason(self, c, unsorted):
        if not unsorted:
            return ""
        if any(f.startswith("unreadable") for f in c.flags):
            return "Unreadable file"
        if not c.module:
            return "Module unknown"
        if part_needed(self.cfg, c) and c.part is None:
            return "Part unknown"
        return f"Low confidence ({int(c.confidence * 100)}%)"

    # ---------------------------------------------------------------- fixes
    def reassign(self, entry_id, **changes):
        """changes: module, part, category, number, topic. Returns entry or 'need_part'."""
        e = self.log.get(entry_id)
        if not e:
            return None
        c = Classification.from_dict(e.get("classification") or {})
        if not c.topic:
            c.topic = rules.clean_topic(e.get("title")) or rules.clean_topic(rules.clean_stem(e["original_name"]))
        if not c.category:
            c.category = "Other"
        if "module" in changes and changes["module"] != c.module:
            c.module = changes["module"]
            c.part = None
            if "part" not in changes:
                c.part = self._guess_part(e, c)
        for k in ("part", "category", "number", "topic"):
            if k in changes:
                setattr(c, k, changes[k])
        mod = self.cfg.module(c.module) if c.module else None
        if not mod:
            return "need_module"
        if c.category in self.cfg.module_categories and "part" not in changes and \
                c.sources.get("part") not in ("blackboard", "manual", "ai", "user"):
            c.part = None
        if part_needed(self.cfg, c) and c.part is None:
            return "need_part"
        c.confidence = 1.0
        c.not_course = False
        c.flags = [f for f in c.flags if not f.startswith(("unreadable", "AI"))]
        for k in changes:
            c.sources[k] = "user"
        src = Path(e["current_path"])
        if not src.exists():
            self.log.update(entry_id, status="error", message="File no longer exists")
            return None
        old_parent = src.parent
        # Docs are renamed from the topic; code files and folders keep their original name.
        pl = placer.plan(self.cfg, c, e.get("original_name") or src.name, is_dir=src.is_dir())
        if pl.rename_folder and placer.apply_folder_rename(pl.rename_folder):
            self.log.repath(*pl.rename_folder)
            src = Path(self.log.get(entry_id)["current_path"])
            old_parent = src.parent
        if norm(pl.dest.parent) == norm(src.parent) and _strip_n(pl.dest.name) == _strip_n(src.name):
            dest = src  # already in the right place with the right name
        else:
            dest = placer.move(src, pl.dest)
        extras = []
        for x in e.get("extras", []):
            if Path(x).exists():
                extras.append(str(placer.move(x, dest.parent / Path(x).name)))
        self.dups.remove(src)
        self.dups.add(dest)
        placer.remove_if_empty_practical(old_parent)
        if c.category == "Practicals":
            self._last_practical[(c.module, c.part)] = (dest.parent, time.time())
        return self.log.update(entry_id, status="sorted", current_path=str(dest), extras=extras,
                               classification=c.to_dict(), message="Fixed by you")

    def _guess_part(self, e, c):
        mod = self.cfg.module(c.module)
        if not mod or not mod.parts:
            return None
        ctx = e.get("context") or {}
        trimmed = {"chain": ctx.get("chain"), "prev_chain": ctx.get("prev_chain"),
                   "item_title": ctx.get("item_title")} if ctx else None
        g = classify(self.cfg, e["original_name"], e.get("text", ""), e.get("title", ""), context=trimmed,
                     manual_module=c.module, use_ai=True)
        return g.part

    def accept(self, entry_id):
        e = self.log.get(entry_id)
        c = Classification.from_dict((e or {}).get("classification"))
        if not c.module:
            return "need_module"
        return self.reassign(entry_id, module=c.module, part=c.part, category=c.category or "Other")

    def undo(self, entry_id):
        e = self.log.get(entry_id)
        if not e or e["status"] == "undone":
            return None
        src = Path(e["current_path"])
        orig = Path(e["original_path"])
        if norm(src) == norm(orig) or not src.exists():
            return self.log.update(entry_id, status="undone", message="Nothing to undo")
        target = placer.unique_path(orig)
        self.suppress(target)
        orig.parent.mkdir(parents=True, exist_ok=True)
        placer.move(src, target)
        for x in e.get("extras", []):
            if Path(x).exists():
                t = placer.unique_path(orig.parent / Path(x).name)
                self.suppress(t)
                placer.move(x, t)
        self.dups.remove(src)
        placer.remove_if_empty_practical(src.parent)
        return self.log.update(entry_id, status="undone", current_path=str(target), extras=[],
                               message="Moved back")

    # ---------------------------------------------------------------- existing files in Downloads
    def list_downloads(self):
        out = []
        for p in self.cfg.downloads_folder.iterdir():
            if p.is_file() and self.is_candidate(p):
                st = p.stat()
                out.append({"path": str(p), "name": p.name, "mtime": st.st_mtime, "size": st.st_size})
        out.sort(key=lambda d: -d["mtime"])
        return out

    def preview_files(self, paths, pick=(None, None), progress=None):
        """Classify without moving. Returns items for a preview table."""
        items = []
        for i, p in enumerate(paths):
            p = Path(p)
            if progress:
                progress(i, len(paths), p.name)
            dup = self.dups.find(p)
            if dup:
                items.append({"src": str(p), "action": "duplicate", "dest": dup, "c": None, "text": "", "title": ""})
                continue
            text, title, error = "", "", None
            try:
                text, title = extract(p)
            except ExtractError as ex:
                error = str(ex)[:200]
            c = classify(self.cfg, p.name, text, title, manual_module=pick[0], manual_part=pick[1],
                         error=error, when=datetime.fromtimestamp(p.stat().st_mtime))
            if c.not_course and not pick[0]:
                items.append({"src": str(p), "action": "skip", "dest": "", "c": c.to_dict(), "text": text, "title": title})
                continue
            pl = placer.plan(self.cfg, c, p.name)
            items.append({"src": str(p), "action": "move", "dest": str(pl.dest), "unsorted": pl.unsorted,
                          "c": c.to_dict(), "text": text, "title": title})
        if progress:
            progress(len(paths), len(paths), "")
        return items

    def apply_items(self, items, kind="existing"):
        done = []
        for it in items:
            src = Path(it["src"])
            if it.get("action") != "move" or not src.exists():
                continue
            c = Classification.from_dict(it["c"])
            done.append(self._place(src, c, kind=kind, text=it.get("text", ""), title=it.get("title", ""),
                                    extract_zips=kind != "migration"))
        for d in {Path(it["cleanup"]) for it in items if it.get("cleanup")}:
            _remove_empty_tree(d)
        return done


def _strip_n(name):
    return re.sub(r" \(\d+\)(?=\.[^.]*$|$)", "", name).lower()


def _remove_empty_tree(root):
    """Remove empty directories under (and including) root. Files are never touched."""
    root = Path(root)
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        try:
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
        except OSError:
            pass


_STOP = {"and", "the", "for", "with", "from", "into", "model", "models", "lecture", "practical", "notebook",
         "colab", "ipynb", "minimal", "simple", "intro", "introduction", "part", "using", "based"}


def _friendly_error(ex):
    import requests
    if isinstance(ex, requests.HTTPError) and ex.response is not None:
        r = ex.response
        hint = " (needs your Blackboard login: retry from the extension)" if r.status_code in (401, 403) else ""
        return f"HTTP {r.status_code} {r.reason}{hint}"
    if isinstance(ex, requests.Timeout):
        return "the server took too long to answer"
    if isinstance(ex, requests.ConnectionError):
        return "could not connect to the server"
    return str(ex)[:160]


def _tokens(s):
    return {w for w in re.findall(r"[a-z]+", (s or "").lower()) if len(w) >= 3 and w not in _STOP}
