"""Steps 1b, 2, 3, 3b for one lecture: map notes -> capture -> independent audit (<= 3 rounds) -> registry.

Everything the model returns comes back between <<<NAME ... NAME>>> markers; this module writes the files
into Lectures/<Part>/lectures_markdown/<Lecture NN - Topic>/ so the model needs no write access.
"""
import json
import re
from pathlib import Path

from . import runner
from .convert import MD_DIR
from .fix_pages import split_pages

MAX_AUDIT_ROUNDS = 3
EX_BATCH = 5            # concepts per exercises call


def block(text, name):
    m = re.search(rf"<<<{name}\s*\n(.*?)\n\s*{name}>>>", text, re.S)
    if not m:
        raise runner.RunnerError(f"Model reply has no <<<{name} block: {text[:300]}")
    return m.group(1).strip()


def json_block(text, name="JSON"):
    raw = block(text, name)
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    return json.loads(raw)


# ------------------------------------------------------------------ layout
def part_dir(cfg, module, part):
    return cfg.root_folder / module.key / "Lectures" / part


def lecture_folders(cfg, module, part):
    return sorted(d for d in part_dir(cfg, module, part).iterdir()
                  if d.is_dir() and re.match(r"Lecture \d+", d.name))


def lecture_id(folder):
    return "L%02d" % int(re.match(r"Lecture (\d+)", folder.name).group(1))


def _manifest(md_dir):
    p = md_dir / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def lecture_sources(cfg, module, part, folder):
    """[(name, markdown)] for every converted PDF inside the lecture folder."""
    md_dir = part_dir(cfg, module, part) / MD_DIR
    rel = str(folder.relative_to(cfg.root_folder / module.key))
    out = []
    for stem, e in _manifest(md_dir).items():
        if e["pdf"].startswith(rel + "\\") or e["pdf"].startswith(rel + "/"):
            unfixed = [p for p in e["flagged"] if int(p) not in e["fixed_pages"]]
            if unfixed:
                raise runner.RunnerError(f"{stem}: pages {unfixed} still need step 1 (python -m study fix).")
            out.append((stem, (md_dir / f"{stem}.md").read_text(encoding="utf-8")))
    return out


def notes_docs(cfg, module):
    md_dir = cfg.root_folder / module.key / "Lectures" / MD_DIR
    return md_dir, _manifest(md_dir)


def out_dir(cfg, module, part, folder):
    d = part_dir(cfg, module, part) / MD_DIR / folder.name
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------ step 1b
def map_notes(cfg, module, runner_name="claude", log=print):
    md_dir, man = notes_docs(cfg, module)
    outlines = []
    for part in module.parts:
        if not part_dir(cfg, module, part).is_dir():
            continue
        for f in lecture_folders(cfg, module, part):
            titles = []
            for name, md in lecture_sources(cfg, module, part, f):
                _, pages = split_pages(md)
                titles += [next((l.strip("# ") for l in t.splitlines() if l.strip()), "") for t in pages.values()]
            outlines.append(f"- {part}:{lecture_id(f)} ({f.name}): " + " | ".join(t for t in titles if t)[:3000])
    for stem, e in man.items():
        if (md_dir / f"{stem} - notes-map.json").exists():
            log(f"notes map exists: {stem}")
            continue
        _, pages = split_pages((md_dir / f"{stem}.md").read_text(encoding="utf-8"))
        notes = "\n".join(f"<!-- page {n} -->\n{t[:700]}" for n, t in sorted(pages.items()))
        prompt = runner.build_prompt("01b_map_notes.md", MODULE_NAME=module.name, MODULE_CODE=module.code,
                                     PART="all parts", NOTES_MD=f"{stem} (first 700 characters of each page below)",
                                     NOTES_PAGES=e["pages"], LECTURE_OUTLINES="\n" + "\n".join(outlines),
                                     OUT_DIR=md_dir) + "\n\n## Notes pages\n" + notes
        text, usage = runner.run(cfg, prompt, runner=runner_name, model="sonnet")
        m = json_block(text)
        keys = sorted(int(k) for k in m["pages"])
        if keys != list(range(1, e["pages"] + 1)):
            missing = sorted(set(range(1, e["pages"] + 1)) - set(keys))
            raise runner.RunnerError(f"notes map for {stem} does not cover every page; missing {missing}")
        (md_dir / f"{stem} - notes-map.json").write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"mapped {stem}: {e['pages']} pages ({usage.get('seconds')}s)")


def notes_for(cfg, module, part, lid):
    """[(name, markdown of the notes pages mapped to this lecture)] (front pages go with the first lecture)."""
    md_dir, man = notes_docs(cfg, module)
    out = []
    first = lecture_id(lecture_folders(cfg, module, part)[0]) == lid
    for stem in man:
        mp = md_dir / f"{stem} - notes-map.json"
        if not mp.exists():
            raise runner.RunnerError(f"Run step 1b first (python -m study mapnotes {module.key}).")
        m = json.loads(mp.read_text(encoding="utf-8"))["pages"]
        want = f"{part}:{lid}"
        _, pages = split_pages((md_dir / f"{stem}.md").read_text(encoding="utf-8"))
        sel = [n for n, v in m.items() if want in (v if isinstance(v, list) else [v]) or (first and v == "front")]
        if sel:
            sel = sorted(int(n) for n in sel)
            out.append((f"{stem} (pages {sel[0]}-{sel[-1]})",
                        "".join(f"\n<!-- page {n} -->\n{pages[n].strip()}\n" for n in sel)))
    return out


def _sources_text(sources):
    return "\n\n".join(f"### SOURCE: {name}\n<<<SOURCE\n{md}\nSOURCE>>>" for name, md in sources)


# ------------------------------------------------------------------ steps 2, 3, 3b
def capture(cfg, module, part, folder, runner_name="claude", log=print):
    lid, od = lecture_id(folder), out_dir(cfg, module, part, folder)
    stem = folder.name
    if (od / f"{stem} - Master.md").exists():
        log(f"{lid} capture exists")
        return
    lect = lecture_sources(cfg, module, part, folder)
    notes = notes_for(cfg, module, part, lid) if notes_docs(cfg, module)[1] else []
    prev = [c for f in lecture_folders(cfg, module, part) if lecture_id(f) < lid
            for c in _read_json(out_dir(cfg, module, part, f) / f"{f.name} - concepts.json", [])]
    prompt = runner.build_prompt(
        "02_capture_lecture.md", MODULE_NAME=module.name, MODULE_CODE=module.code, PART=part, LECTURE_ID=lid,
        LECTURE_MD_FILES=", ".join(n for n, _ in lect), NOTES_MD_SECTIONS=", ".join(n for n, _ in notes) or "none",
        READING_MD_FILES="none", PREVIOUS_CONCEPTS_JSON=json.dumps([{"id": c["id"], "name": c["name"]} for c in prev]),
        SOURCES=_sources_text(lect + notes))
    text, usage = runner.run(cfg, prompt, runner=runner_name, model="sonnet", timeout=3600)
    master, concepts = block(text, "MASTER_MD"), json_block(text)
    (od / f"{stem} - Master.md").write_text(master + "\n", encoding="utf-8")
    _write_json(od / f"{stem} - concepts.json", concepts)
    (od / f"{stem} - capture-selfaudit.md").write_text(text.split("JSON>>>")[-1].strip() + "\n", encoding="utf-8")
    log(f"{lid} captured: {len(concepts)} concepts ({runner.describe(usage)})")


def audit(cfg, module, part, folder, runner_name="claude", log=print):
    lid, od, stem = lecture_id(folder), out_dir(cfg, module, part, folder), folder.name
    status = _read_json(od / f"{stem} - audit.json", {"rounds": []})
    if status.get("verdict") in ("PASS", "needs human"):
        log(f"{lid} audit: {status['verdict']}")
        return status["verdict"]
    sources = lecture_sources(cfg, module, part, folder) + (
        notes_for(cfg, module, part, lid) if notes_docs(cfg, module)[1] else [])
    while len(status["rounds"]) < MAX_AUDIT_ROUNDS:
        master = (od / f"{stem} - Master.md").read_text(encoding="utf-8")
        concepts = (od / f"{stem} - concepts.json").read_text(encoding="utf-8")
        prompt = runner.build_prompt(
            "03_audit_coverage.md", MODULE_NAME=module.name, MODULE_CODE=module.code, PART=part,
            LECTURE_MD_FILES="the sources below", NOTES_MD_SECTIONS="(included below)", MASTER_MD="below",
            CONCEPTS_JSON="below", OUT_DIR=od, LECTURE_STEM=stem,
            SOURCES=_sources_text(sources), MASTER=master, CONCEPTS=concepts)
        # a different, stronger model than the capture (Sonnet): Opus on Claude Code; Sonnet-in-agy on agy
        model = "claude-sonnet-5-5-high" if runner_name == "agy" else "opus"
        try:
            text, usage = runner.run(cfg, prompt, runner=runner_name, model=model, timeout=3600)
        except runner.RunnerError as e:
            if runner_name != "agy" or "quota" not in str(e).lower():
                raise
            # Claude-in-agy quota is small; fall back to Gemini in a fresh session (independent of the capture run)
            log(f"{lid} audit: {model} quota reached, auditing with {runner.AGY_DEFAULT} instead")
            model = runner.AGY_DEFAULT
            text, usage = runner.run(cfg, prompt, runner=runner_name, model=model, timeout=3600)
        result = json_block(text, "AUDIT")
        counts = {k: len(result.get(k, [])) for k in ("missing", "distorted", "unsupported", "concepts_missing")}
        status["rounds"].append({"model": model, "counts": counts, "result": result})
        new_master = block(text, "MASTER_MD")
        if len(new_master) < 0.9 * len(master):          # an audit adds and corrects; it must never shrink the notes
            raise runner.RunnerError(f"{lid} audit returned a Master {len(new_master)} chars long (was {len(master)}); "
                                     "kept the old one. Re-run the audit.")
        (od / f"{stem} - Master.md").write_text(new_master + "\n", encoding="utf-8")
        _write_json(od / f"{stem} - concepts.json", json_block(text))
        _write_json(od / f"{stem} - audit.json", status)
        log(f"{lid} audit round {len(status['rounds'])}: {counts} ({runner.describe(usage)})")
        if not any(counts.values()):
            status["verdict"] = "PASS"
            break
    else:
        # Each round returns the notes with its own fixes applied. After the last round, accept them if nothing
        # was missing (only wording / marking fixes remained); missing content never passes.
        last = status["rounds"][-1]["counts"]
        ok = last["missing"] == 0 and last["concepts_missing"] == 0 and last["distorted"] <= 2
        status["verdict"] = "PASS" if ok else "needs human"
        if ok:
            status["note"] = "last round's fixes applied but not re-verified"
    _write_json(od / f"{stem} - audit.json", status)
    return status["verdict"]


def merge_registry(cfg, module, part, folder, runner_name="claude", log=print):
    lid, od, stem = lecture_id(folder), out_dir(cfg, module, part, folder), folder.name
    reg_path = part_dir(cfg, module, part) / MD_DIR / "registry.json"
    registry = _read_json(reg_path, {"concepts": [], "merged": []})
    if lid in registry["merged"]:
        log(f"{lid} already in registry")
        return
    prompt = runner.build_prompt(
        "03b_merge_registry.md", MODULE_NAME=module.name, MODULE_CODE=module.code, PART=part, LECTURE_ID=lid,
        REGISTRY_JSON="below", CONCEPTS_JSON="below", MASTER_MD="below", OUT_DIR=od, LECTURE_STEM=stem,
        REGISTRY=json.dumps(registry["concepts"], ensure_ascii=False),
        CONCEPTS=(od / f"{stem} - concepts.json").read_text(encoding="utf-8"),
        MASTER=(od / f"{stem} - Master.md").read_text(encoding="utf-8"))
    text, usage = runner.run(cfg, prompt, runner=runner_name, model="sonnet", timeout=3600)
    new_reg = json_block(text, "REGISTRY")
    registry = {"concepts": new_reg if isinstance(new_reg, list) else new_reg.get("concepts", new_reg),
                "merged": registry["merged"] + [lid]}
    _write_json(od / f"{stem} - plan.json", json_block(text, "PLAN"))
    _write_json(od / f"{stem} - backlinks.json", json_block(text, "BACKLINKS"))
    _write_json(reg_path, registry)
    log(f"{lid} merged into registry ({len(registry['concepts'])} concepts, {usage.get('seconds')}s)")


def _practicals(cfg, module, part, lid):
    """Practical sheets numbered like the lecture (Practical NN), as converted markdown."""
    md_dir = part_dir(cfg, module, part) / MD_DIR
    want = f"Practicals\\{part}\\Practical {lid[1:]}"
    return [(stem, (md_dir / f"{stem}.md").read_text(encoding="utf-8"))
            for stem, e in _manifest(md_dir).items() if e["pdf"].replace("/", "\\").startswith(want)]


def _inputs(cfg, module, part, folder):
    od, stem = out_dir(cfg, module, part, folder), folder.name
    need = ["Master.md", "concepts.json", "plan.json"]
    missing = [n for n in need if not (od / f"{stem} - {n}").exists()]
    if missing:
        raise runner.RunnerError(f"{stem}: missing {missing}; run capture, audit and registry first.")
    return {n.split(".")[0].upper(): (od / f"{stem} - {n}").read_text(encoding="utf-8") for n in need}


def teaching(cfg, module, part, folder, runner_name="claude", log=print):
    lid, od, stem = lecture_id(folder), out_dir(cfg, module, part, folder), folder.name
    if (od / f"{stem} - teaching.json").exists():
        return log(f"{lid} teaching exists")
    i = _inputs(cfg, module, part, folder)
    prompt = runner.build_prompt("04_teaching_plan.md", MODULE_NAME=module.name, MODULE_CODE=module.code,
                                 PART=part, MASTER_MD="below", CONCEPTS_JSON="below", PLAN_JSON="below",
                                 OUT_DIR=od, LECTURE_STEM=stem, MASTER=i["MASTER"], CONCEPTS=i["CONCEPTS"],
                                 PLAN=i["PLAN"])
    ids = [c["id"] for c in json.loads(i["CONCEPTS"])]

    def one(batch):
        focus = (f"\n\n## This call\nDesign ONLY these concept ids (all of them, in full): {', '.join(batch)}. "
                 "Reply with a JSON list of exactly those concepts.")
        text, usage = runner.run(cfg, prompt + focus, runner=runner_name, model="sonnet", timeout=3600)
        got = json_block(text)
        log(f"{lid} teaching: {[t['id'] for t in got]} ({runner.describe(usage)})")
        return got
    partial = od / f"{stem} - teaching.partial.json"
    t = _batched(partial, ids, TEACH_BATCH, one)
    missing = sorted(set(ids) - {x["id"] for x in t})
    if missing:
        raise runner.RunnerError(f"{lid} teaching is missing concepts {missing}; delete {partial.name} and re-run.")
    _write_json(od / f"{stem} - teaching.json", t)
    partial.unlink()
    log(f"{lid} teaching: {len(t)} concepts designed")


def exercises(cfg, module, part, folder, runner_name="claude", log=print):
    lid, od, stem = lecture_id(folder), out_dir(cfg, module, part, folder), folder.name
    if (od / f"{stem} - exercises.json").exists():
        return log(f"{lid} exercises exist")
    i = _inputs(cfg, module, part, folder)
    pracs = _practicals(cfg, module, part, lid)
    profile = part_dir(cfg, module, part) / MD_DIR / "exam-profile.md"
    prompt = runner.build_prompt(
        "05_exercises.md", MODULE_NAME=module.name, MODULE_CODE=module.code, PART=part, MASTER_MD="below",
        CONCEPTS_JSON="below", TEACHING_JSON="below", PLAN_JSON="below", OUT_DIR=od, LECTURE_STEM=stem,
        PRACTICAL_MD_FILES=", ".join(n for n, _ in pracs) or "none yet",
        EXAM_PROFILE_MD="below" if profile.exists() else "not built yet",
        NOT_EXAMINED="none stated", MASTER=i["MASTER"], CONCEPTS=i["CONCEPTS"], PLAN=i["PLAN"],
        TEACHING=(od / f"{stem} - teaching.json").read_text(encoding="utf-8"),
        PRACTICALS=_sources_text(pracs) or "none yet",
        EXAM_PROFILE=profile.read_text(encoding="utf-8") if profile.exists()
        else "Not built yet (no past papers sorted). Use the style of formal university exam questions in this "
             "module's notation: definitions, short proofs, computations, attacks, 'explain why'.")
    # Many exercises per concept: one call per batch of concepts keeps each reply well under output limits.
    part_path = od / f"{stem} - exercises.partial.json"
    done = _read_json(part_path, {"batches": [], "exercises": []})
    ids = [c["id"] for c in json.loads(i["CONCEPTS"])]
    batches = [ids[k:k + EX_BATCH] for k in range(0, len(ids), EX_BATCH)]
    for b, batch in enumerate(batches):
        if b in done["batches"]:
            continue
        last = b == len(batches) - 1
        focus = (f"\n\n## This call\nWrite exercises ONLY for these concept ids: {', '.join(batch)}. "
                 + ("Also write this lecture's ≥ 10 interleaved questions and include every practical question."
                    if last else "Do not write interleaved or practical questions in this call.")
                 + f" Number ids from L{lid[1:]}.ex.{b * 100 + 1:03d}.")
        text, usage = runner.run(cfg, prompt + focus, runner=runner_name, model="sonnet", timeout=3600)
        done["exercises"] += json_block(text)
        done["batches"].append(b)
        _write_json(part_path, done)
        log(f"{lid} exercises batch {b + 1}/{len(batches)}: {len(done['exercises'])} so far "
            f"({runner.describe(usage)})")
    _write_json(od / f"{stem} - exercises.json", done["exercises"])
    part_path.unlink()
    log(f"{lid} exercises: {len(done['exercises'])}")


def visuals(cfg, module, part, folder, runner_name="claude", log=print):
    from .site import site_dir
    lid, od, stem = lecture_id(folder), out_dir(cfg, module, part, folder), folder.name
    target = od / f"{stem} - visuals.js"
    if target.exists():
        return log(f"{lid} visuals exist")
    i = _inputs(cfg, module, part, folder)
    teaching = _read_json(od / f"{stem} - teaching.json", [])
    concepts = json.loads(i["CONCEPTS"])

    def prompt_for(batch):                       # only this batch's teaching data: small input, focused output
        return runner.build_prompt(
            "07_lecture_page.md", MODULE_NAME=module.name, MODULE_CODE=module.code, PART=part, LECTURE_ID=lid,
            PLAN=i["PLAN"], CONCEPTS=json.dumps([c for c in concepts if c["id"] in batch], ensure_ascii=False),
            TEACHING=json.dumps([t for t in teaching if t.get("id") in batch], ensure_ascii=False))
    plan = json.loads(i["PLAN"]) if i["PLAN"].strip().startswith(("[", "{")) else []
    plan = plan.get("concepts", plan) if isinstance(plan, dict) else plan
    recap = {p["id"] for p in plan if isinstance(p, dict) and p.get("teach") == "recap"}
    ids = [c["id"] for c in json.loads(i["CONCEPTS"]) if c["id"] not in recap]

    def one(batch):
        focus = (f"\n\n## This call\nBuild visuals ONLY for these concept ids: {', '.join(batch)}. "
                 "Your file is one of several chunks loaded on the same page: keep every helper inside it.")
        text, usage = runner.run(cfg, prompt_for(batch) + focus, runner=runner_name, model="sonnet", timeout=3600)
        js = block(text, "VISUALS_JS")
        log(f"{lid} visuals: {batch} ({runner.describe(usage)})")
        return [f"// ---- {', '.join(batch)}\n(function () {{\n{js}\n}})();\n"]
    partial = od / f"{stem} - visuals.partial.json"
    js = "\n".join(_batched(partial, ids, VIS_BATCH, one))
    partial.unlink()
    target.write_text(js + "\n", encoding="utf-8")
    vis_dir = site_dir(cfg, module, part) / "visuals"
    vis_dir.mkdir(parents=True, exist_ok=True)
    (vis_dir / f"{lid}.js").write_text(js + "\n", encoding="utf-8")
    log(f"{lid} visuals: {js.count('Study.visuals[')} concepts, {js.count('Study.selftest(')} self-tests")


def _render_scenes(py_file, classes, media):
    """Render each Scene class with Manim; returns ({class: mp4 path}, {class: error tail})."""
    import subprocess
    done, failed = {}, {}
    for cls in classes:
        proc = subprocess.run(["manim", "-qm", "--disable_caching", "--media_dir", str(media), str(py_file), cls],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        mp4 = next(iter(media.glob(f"videos/{py_file.stem}/*/{cls}.mp4")), None)
        if proc.returncode or not mp4:
            failed[cls] = (proc.stderr or proc.stdout)[-1500:]
        else:
            done[cls] = mp4
    return done, failed


def videos(cfg, module, part, folder, runner_name="claude", log=print):
    """Step 7c: Claude writes one Manim scene per `video` storyboard; Manim renders them locally (free)."""
    import shutil
    import tempfile
    from .site import site_dir
    lid, od, stem = lecture_id(folder), out_dir(cfg, module, part, folder), folder.name
    index = od / f"{stem} - videos.json"
    if index.exists():
        return log(f"{lid} videos exist")
    teaching = _read_json(od / f"{stem} - teaching.json", [])
    if not any(t.get("video") for t in teaching):
        _write_json(index, [])
        return log(f"{lid} videos: none planned")
    prompt = runner.build_prompt("07c_videos.md", MODULE_NAME=module.name, MODULE_CODE=module.code, PART=part,
                                 TEACHING=json.dumps(teaching, ensure_ascii=False),
                                 MASTER=(od / f"{stem} - Master.md").read_text(encoding="utf-8"))
    text, usage = runner.run(cfg, prompt, runner=runner_name, model="sonnet", timeout=3600)
    code, listing = block(text, "MANIM_PY"), json_block(text, "VIDEOS")
    py = od / f"{stem} - videos.py"
    out = site_dir(cfg, module, part) / "videos"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "scenes.py"
        src.write_text(code, encoding="utf-8")
        done, failed = _render_scenes(src, [v["class"] for v in listing], tmp / "media")
        if failed:                                       # one repair round, with the render errors
            errors = "\n\n".join(f"### {c}\n```\n{e}\n```" for c, e in failed.items())
            fix = (prompt + f"\n\n## Your previous file\n```python\n{code}\n```\n\n## Render errors\n{errors}\n\n"
                   "Fix the failing scenes and reply with the complete corrected file and the list, same markers.")
            text, _ = runner.run(cfg, fix, runner=runner_name, model="sonnet", timeout=3600)
            code, listing = block(text, "MANIM_PY"), json_block(text, "VIDEOS")
            src.write_text(code, encoding="utf-8")
            retry, failed = _render_scenes(src, list(failed), tmp / "media")
            done.update(retry)
        py.write_text(code, encoding="utf-8")
        result = []
        for v in listing:
            if v["class"] in done:
                name = re.sub(r"[^A-Za-z0-9]+", "_", v["concept"]) + ".mp4"
                shutil.copy2(done[v["class"]], out / name)
                result.append({"concept": v["concept"], "title": v.get("title", ""), "file": "videos/" + name})
    _write_json(index, result)
    log(f"{lid} videos: {len(result)} rendered" + (f", FAILED: {sorted(failed)}" if failed else "") +
        f" ({runner.describe(usage)})")


TEACH_BATCH, VIS_BATCH = 5, 2


def _batched(partial, ids, size, call):
    """Run call(batch) over ids in batches, saving after each so an interrupted step resumes where it stopped."""
    done = _read_json(partial, {"batches": [], "items": []})
    for b in range(0, len(ids), size):
        if b in done["batches"]:
            continue
        done["items"] += call(ids[b:b + size])
        done["batches"].append(b)
        _write_json(partial, done)
    return done["items"]


def _read_json(p, default):
    return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else default


def _write_json(p, data):
    Path(p).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _nlm(*a, **k):
    from .nlm import nlm_videos
    return nlm_videos(*a, **k)


STEPS = {"capture": capture, "audit": audit, "registry": merge_registry, "teaching": teaching,
         "exercises": exercises, "visuals": visuals, "videos": videos, "nlm": _nlm}



def run_lecture(cfg, module, part, number, steps, runner_name="claude", log=print):
    folder = next((f for f in lecture_folders(cfg, module, part) if lecture_id(f) == "L%02d" % number), None)
    if not folder:
        raise runner.RunnerError(f"No 'Lecture {number:02d} - …' folder in {part_dir(cfg, module, part)}")
    serial = [s for s in steps if s not in PARALLEL]
    for s in serial:
        result = STEPS[s](cfg, module, part, folder, runner_name=runner.pick(runner_name, s), log=log)
        if s == "audit" and result != "PASS":
            log(f"Stopping: audit verdict is {result!r}; see '{folder.name} - audit.json'.")
            return
    # exercises, visuals and videos only need the teaching design: run them side by side
    from concurrent.futures import ThreadPoolExecutor
    group = [s for s in steps if s in PARALLEL]
    with ThreadPoolExecutor(max_workers=len(group) or 1) as pool:
        futures = {s: pool.submit(STEPS[s], cfg, module, part, folder, runner_name=runner.pick(runner_name, s), log=log)
                   for s in group}
    errors = {s: f.exception() for s, f in futures.items() if f.exception()}
    if errors:
        raise runner.RunnerError("; ".join(f"{s}: {e}" for s, e in errors.items()))


PARALLEL = {"exercises", "visuals", "videos", "nlm"}
