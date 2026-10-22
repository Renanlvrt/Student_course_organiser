"""python -m study all <Module> [--part P]: build everything, unattended.

Page fixes, notes map, then every lecture of every part through every step; the site is rebuilt and published
after each finished lecture. When Claude's usage window is full it sleeps until the reset and carries on. Any
other failure is retried once; a second failure stops the run with the error (nothing half-built is published).
"""
import time
import traceback
from datetime import datetime

from . import runner
from .check import check_lecture
from .fix_pages import fix_module
from .lecture import lecture_folders, lecture_id, map_notes, out_dir, run_lecture
from .publish import publish
from .site import build_site

ALL_STEPS = ["capture", "audit", "topics", "teaching", "exercises", "visuals", "videos", "nlm"]


def _log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def _with_retries(label, fn):
    attempt = 0
    while True:
        try:
            return fn()
        except runner.LimitReached as e:
            wait = max(60, (e.resume_at or time.time() + 1800) - time.time() + 120)
            _log(f"{label}: {e} Sleeping {wait / 60:.0f} min until the window resets.")
            time.sleep(wait)
        except Exception as e:                          # noqa: BLE001 - report everything, retry once
            attempt += 1
            _log(f"{label} failed (attempt {attempt}): {e}")
            if attempt >= 2:
                traceback.print_exc()
                raise
            time.sleep(30)


def run_all(cfg, module, parts=None):
    _with_retries("fix pages", lambda: fix_module(cfg, module, log=_log))
    _with_retries("notes map", lambda: map_notes(cfg, module, log=_log))
    for part in parts or module.parts:
        folders = lecture_folders(cfg, module, part)
        if not folders:
            _log(f"{part}: no lectures yet")
            continue
        for folder in folders:
            lid = lecture_id(folder)
            n = int(lid[1:])
            _with_retries(f"{lid}", lambda: run_lecture(cfg, module, part, n, ALL_STEPS, "claude", log=_log))
            audit = out_dir(cfg, module, part, folder) / f"{folder.name} - audit.json"
            if '"needs human"' in (audit.read_text(encoding="utf-8") if audit.exists() else ""):
                raise runner.RunnerError(f"{lid}: audit needs a human look ({audit}). Stopping before later lectures.")
            _, problems = check_lecture(cfg, module, part, folder)
            _log(f"{lid}: built" + (f", check: {len(problems)} problem(s): {problems[:5]}" if problems else ", check COMPLETE"))
            build_site(cfg, module, part, log=_log)
            _with_retries("publish", lambda: publish(cfg, module, log=_log))
    _log("All done.")
