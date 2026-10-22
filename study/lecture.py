"""One lecture: map notes -> capture -> audit (one pass, edits applied) -> topics -> teaching -> exercises /
visuals / videos / NotebookLM. Rich teaching is built per topic (2-5 per lecture) to keep token use low.

Everything the model returns comes back between <<<NAME ... NAME>>> markers; this module writes the files
into Lectures/<Part>/lectures_markdown/<Lecture NN - Topic>/ so the model needs no write access.
"""
import json
import re
from pathlib import Path

from . import runner
from .convert import MD_DIR
from .fix_pages import split_pages



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
    """Lecture folders of a part, plus lectures known only from the module notes (notes_lectures.json); a real
    folder wins when its slides arrive."""
    pd = part_dir(cfg, module, part)
    real = [d for d in pd.iterdir() if d.is_dir() and re.match(r"Lecture \d+", d.name)] if pd.is_dir() else []
    nums = {int(re.match(r"Lecture (\d+)", d.name).group(1)) for d in real}
    virtual = [pd / f"Lecture {v['n']:02d} - {v['title']}"
               for v in _read_json(pd / MD_DIR / "notes_lectures.json", []) if v["n"] not in nums]
    return sorted(real + virtual, key=lambda d: int(re.match(r"Lecture (\d+)", d.name).group(1)))


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


CHUNK_CHARS = 28000      # source text per capture call: keeps the reply (full notes) under the output limit


def _chunks(sources):
    """Split [(name, markdown)] into groups of whole pages of at most CHUNK_CHARS characters."""
    chunks, cur, size = [], [], 0
    for name, md in sources:
        head, pages = split_pages(md if md.startswith("\n") else "\n" + md)
        if not pages:
            pages = {1: md}
        for n in sorted(pages):
            text = f"\n<!-- page {n} -->\n{pages[n].strip()}\n"
            if cur and size + len(text) > CHUNK_CHARS:
                chunks.append(cur)
                cur, size = [], 0
            if cur and cur[-1][0] == name:
                cur[-1] = (name, cur[-1][1] + text)
            else:
                cur.append((name, text))
            size += len(text)
    if cur:
        chunks.append(cur)
    return chunks or [sources]


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
    chunks = _chunks(lect + notes)
    partial_path = od / f"{stem} - capture.partial.json"
    part_state = _read_json(partial_path, {"done": [], "master": [], "concepts": [], "selfaudit": []})
    usage = {}
    for k, chunk in enumerate(chunks):
        if k in part_state["done"]:
            continue
        prompt = runner.build_prompt(
            "02_capture_lecture.md", MODULE_NAME=module.name, MODULE_CODE=module.code, PART=part, LECTURE_ID=lid,
            LECTURE_MD_FILES=", ".join(n for n, _ in lect), NOTES_MD_SECTIONS=", ".join(n for n, _ in notes) or "none",
            READING_MD_FILES="none", PREVIOUS_CONCEPTS_JSON=json.dumps([{"id": c["id"], "name": c["name"]} for c in prev]),
            SOURCES=_sources_text(chunk))
        if len(chunks) > 1:                       # a long lecture is captured a few pages at a time
            used = [c["id"] for c in part_state["concepts"]]
            prompt += (f"\n\n## This call\nPart {k + 1} of {len(chunks)} of this lecture: capture ONLY the pages "
                       f"given above, completely. Concept ids already used (do not reuse): {used or 'none'}.")
        text, usage = runner.run(cfg, prompt, runner=runner_name, model="sonnet", timeout=3600)
        part_state["master"].append(block(text, "MASTER_MD"))
        part_state["concepts"] += json_block(text)
        part_state["selfaudit"].append(text.split("JSON>>>")[-1].strip())
        part_state["done"].append(k)
        _write_json(partial_path, part_state)
        if len(chunks) > 1:
            log(f"{lid} capture part {k + 1}/{len(chunks)} ({runner.describe(usage)})")
    seen, concepts = set(), []
    for c in part_state["concepts"]:
        if c["id"] not in seen:
            seen.add(c["id"])
            concepts.append(c)
    (od / f"{stem} - Master.md").write_text("\n\n".join(part_state["master"]) + "\n", encoding="utf-8")
    _write_json(od / f"{stem} - concepts.json", concepts)
    (od / f"{stem} - capture-selfaudit.md").write_text("\n\n".join(part_state["selfaudit"]) + "\n", encoding="utf-8")
    partial_path.unlink()
    log(f"{lid} captured: {len(concepts)} concepts ({runner.describe(usage)})")


def audit(cfg, module, part, folder, runner_name="claude", log=print):
    """One independent Sonnet pass that returns edits (not a rewrite); the edits are applied here."""
    lid, od, stem = lecture_id(folder), out_dir(cfg, module, part, folder), folder.name
    status = _read_json(od / f"{stem} - audit.json", {"rounds": []})
    if status.get("verdict") in ("PASS", "needs human"):
        log(f"{lid} audit: {status['verdict']}")
        return status["verdict"]
    sources = lecture_sources(cfg, module, part, folder) + (
        notes_for(cfg, module, part, lid) if notes_docs(cfg, module)[1] else [])
    master_path, concepts_path = od / f"{stem} - Master.md", od / f"{stem} - concepts.json"
    master = master_path.read_text(encoding="utf-8")
    prompt = runner.build_prompt(
        "03_audit_coverage.md", MODULE_NAME=module.name, MODULE_CODE=module.code, PART=part, LECTURE_ID=lid,
        LECTURE_MD_FILES="the sources below", NOTES_MD_SECTIONS="(included below)", MASTER_MD="below",
        CONCEPTS_JSON="below", OUT_DIR=od, LECTURE_STEM=stem, SOURCES=_sources_text(sources), MASTER=master,
        CONCEPTS=concepts_path.read_text(encoding="utf-8"))
    text, usage = runner.run(cfg, prompt, runner=runner_name, model="haiku", timeout=3600)
    result = json_block(text, "AUDIT")
    applied, skipped = 0, []
    for e in result.get("edits", []):
        if e.get("find") and master.count(e["find"]) == 1:
            master = master.replace(e["find"], e.get("replace", ""))
            applied += 1
        else:
            skipped.append(e)
    adds = result.get("missing", []) + [{"src": "audit", "text": f"> ⚠ Check (audit could not place this edit): "
                                         f"{e.get('why', '')}: \"{e.get('find', '')}\" → \"{e.get('replace', '')}\""}
                                        for e in skipped]
    if adds:
        master = master.rstrip() + "\n\n## Additions from the audit\n\n" + "\n\n".join(
            a.get("text") or f"{a.get('item', '')} [src: {a.get('src', '')}]" for a in adds) + "\n"
    master_path.write_text(master, encoding="utf-8")
    if result.get("concepts_missing"):
        _write_json(concepts_path, _read_json(concepts_path, []) + result["concepts_missing"])
    counts = {"missing": len(result.get("missing", [])), "edits": len(result.get("edits", [])),
              "edits_unplaced": len(skipped), "concepts_missing": len(result.get("concepts_missing", []))}
    status["rounds"].append({"model": "haiku", "counts": counts, "result": result})
    status["verdict"] = "PASS"                      # every finding has been applied to the notes
    _write_json(od / f"{stem} - audit.json", status)
    log(f"{lid} audit: {counts} applied ({runner.describe(usage)})")
    return status["verdict"]


def topics(cfg, module, part, folder, runner_name="claude", log=print):
    """Step 3c: 2-5 teaching topics per lecture (replaces the per-concept registry). Part-level topics.json."""
    lid, od, stem = lecture_id(folder), out_dir(cfg, module, part, folder), folder.name
    target = od / f"{stem} - topics.json"
    if target.exists():
        return log(f"{lid} topics exist")
    reg_path = part_dir(cfg, module, part) / MD_DIR / "topics.json"
    registry = [t for t in _read_json(reg_path, []) if not t["id"].startswith(lid + ".")]
    concepts = _read_json(od / f"{stem} - concepts.json", [])
    slim = [{k: c.get(k) for k in ("id", "name", "kind", "summary")} for c in concepts]
    prompt = runner.build_prompt(
        "03c_topics.md", MODULE_NAME=module.name, MODULE_CODE=module.code, PART=part, LECTURE_ID=lid,
        EARLIER_TOPICS=json.dumps([{k: t.get(k) for k in ("id", "title", "why")} for t in registry],
                                  ensure_ascii=False) or "none",
        CONCEPTS=json.dumps(slim, ensure_ascii=False))
    text, usage = runner.run(cfg, prompt, runner=runner_name, model="haiku", timeout=1800)
    got = json_block(text, "TOPICS")
    ids = {c["id"] for c in concepts}
    placed = [c for t in got for c in t.get("concepts", [])]
    unplaced = sorted(ids - set(placed))
    if unplaced:                                   # every concept must sit in a topic: add leftovers to the last
        got[-1].setdefault("concepts", []).extend(unplaced)
    for t in got:
        t["concepts"] = [c for c in t["concepts"] if c in ids]
    _write_json(target, got)
    with REGISTRY_LOCK:
        _write_json(reg_path, [t for t in _read_json(reg_path, []) if not t["id"].startswith(lid + ".")] + got)
    log(f"{lid} topics: {[t['title'] for t in got]} ({runner.describe(usage)})")


def _practicals(cfg, module, part, lid):
    """Practical sheets numbered like the lecture (Practical NN), as converted markdown."""
    md_dir = part_dir(cfg, module, part) / MD_DIR
    want = f"Practicals\\{part}\\Practical {lid[1:]}"
    return [(stem, (md_dir / f"{stem}.md").read_text(encoding="utf-8"))
            for stem, e in _manifest(md_dir).items() if e["pdf"].replace("/", "\\").startswith(want)]


def _inputs(cfg, module, part, folder):
    od, stem = out_dir(cfg, module, part, folder), folder.name
    need = ["Master.md", "concepts.json", "topics.json"]
    missing = [n for n in need if not (od / f"{stem} - {n}").exists()]
    if missing:
        raise runner.RunnerError(f"{stem}: missing {missing}; run capture, audit and topics first.")
    return {n.split(".")[0].upper(): (od / f"{stem} - {n}").read_text(encoding="utf-8") for n in need}


def load_teaching(od, stem):
    """(entries, glossary, cards). Topic-mode teaching is a dict; the first pilot lecture stored a per-concept list."""
    t = _read_json(od / f"{stem} - teaching.json", [])
    if isinstance(t, dict):
        return t.get("topics", []), t.get("glossary", []), t.get("cards", [])
    return t, [], []


def teaching(cfg, module, part, folder, runner_name="claude", log=print):
    lid, od, stem = lecture_id(folder), out_dir(cfg, module, part, folder), folder.name
    if (od / f"{stem} - teaching.json").exists():
        return log(f"{lid} teaching exists")
    i = _inputs(cfg, module, part, folder)
    prompt = runner.build_prompt("04_teaching_plan.md", MODULE_NAME=module.name, MODULE_CODE=module.code, PART=part,
                                 TOPICS=i["TOPICS"], CONCEPTS=i["CONCEPTS"], MASTER=i["MASTER"])
    text, usage = runner.run(cfg, prompt, runner=runner_name, model="sonnet", timeout=3600)
    t = json_block(text)
    want = {x["id"] for x in json.loads(i["TOPICS"])}
    missing = sorted(want - {x.get("id") for x in t.get("topics", [])})
    if missing:
        raise runner.RunnerError(f"{lid} teaching is missing topics {missing}")
    _write_json(od / f"{stem} - teaching.json", t)
    log(f"{lid} teaching: {len(t['topics'])} topics, {len(t.get('glossary', []))} terms, "
        f"{len(t.get('cards', []))} cards ({runner.describe(usage)})")


def exercises(cfg, module, part, folder, runner_name="claude", log=print):
    lid, od, stem = lecture_id(folder), out_dir(cfg, module, part, folder), folder.name
    target, partial = od / f"{stem} - exercises.json", od / f"{stem} - exercises.partial.json"
    if target.exists():
        return log(f"{lid} exercises exist")
    if partial.exists():                           # pilot lecture: keep what the earlier (per-concept) run wrote
        ex = _read_json(partial, {}).get("exercises", [])
        _write_json(target, ex)
        partial.unlink()
        return log(f"{lid} exercises: kept {len(ex)} from the earlier run")
    i = _inputs(cfg, module, part, folder)
    entries, _, _ = load_teaching(od, stem)
    pracs = _practicals(cfg, module, part, lid)
    profile = part_dir(cfg, module, part) / MD_DIR / "exam-profile.md"
    prompt = runner.build_prompt(
        "05_exercises.md", MODULE_NAME=module.name, MODULE_CODE=module.code, PART=part, MASTER_MD="below",
        CONCEPTS_JSON="below", TEACHING_JSON="below", PLAN_JSON="the topics below", OUT_DIR=od, LECTURE_STEM=stem,
        PRACTICAL_MD_FILES=", ".join(n for n, _ in pracs) or "none yet",
        EXAM_PROFILE_MD="below" if profile.exists() else "not built yet",
        NOT_EXAMINED="none stated", MASTER=i["MASTER"], CONCEPTS=i["CONCEPTS"], PLAN=i["TOPICS"],
        TEACHING=json.dumps(entries, ensure_ascii=False),
        PRACTICALS=_sources_text(pracs) or "none yet",
        EXAM_PROFILE=profile.read_text(encoding="utf-8") if profile.exists()
        else "Not built yet (no past papers sorted). Use the style of formal university exam questions in this "
             "module's notation: definitions, short proofs, computations, attacks, 'explain why'.")
    text, usage = runner.run(cfg, prompt + f"\n\nNumber ids {lid}.ex.001, {lid}.ex.002, ...", runner=runner_name,
                             model="sonnet", timeout=3600)
    ex = json_block(text)
    _write_json(target, ex)
    log(f"{lid} exercises: {len(ex)} ({runner.describe(usage)})")


VISUAL_RE = re.compile(r"""Study\.visuals\[\s*["']([^"']+)""")


def _visual_targets(od, stem, topics_list, entries):
    """[(topic, teaching entry)] that still need visuals. A topic uses its own teaching entry, or (pilot
    lecture) the teaching of its most important concept; topics already covered by a concept visual are skipped."""
    by_id = {t["id"]: t for t in entries}
    done_js = "".join(_read_json(od / f"{stem} - visuals.partial.json", {"items": []})["items"])
    have = set(VISUAL_RE.findall(done_js + "".join(
        _read_json(od / f"{stem} - visuals.topics.partial.json", {"items": []})["items"])))
    out = []
    budget = vis_budget(topics_list) - sum(1 for tp in topics_list if tp["id"] in have)
    for tp in sorted(topics_list, key=lambda t: not t.get("hard")):
        if budget <= 0:
            break
        if str(tp.get("prior", "")).startswith("recap") or tp["id"] in have or have & set(tp["concepts"]):
            continue
        if not tp.get("hard") and any(t.get("hard") for t in topics_list):
            continue
        entry = by_id.get(tp["id"])
        if not entry:
            cands = [by_id[c] for c in tp["concepts"] if c in by_id and by_id[c].get("animation")]
            cands.sort(key=lambda e: (not e.get("hard"), -(e.get("difficulty") or 0)))
            if not cands:
                continue
            entry = dict(cands[0], id=tp["id"], title=tp["title"])
        out.append((tp, entry))
        budget -= 1
    return out, done_js


def visuals(cfg, module, part, folder, runner_name="claude", log=print):
    from .site import site_dir
    lid, od, stem = lecture_id(folder), out_dir(cfg, module, part, folder), folder.name
    target = od / f"{stem} - visuals.js"
    if target.exists():
        return log(f"{lid} visuals exist")
    i = _inputs(cfg, module, part, folder)
    topics_list = json.loads(i["TOPICS"])
    concepts = json.loads(i["CONCEPTS"])
    entries, _, _ = load_teaching(od, stem)
    todo, legacy_js = _visual_targets(od, stem, topics_list, entries)
    entry_of = {tp["id"]: e for tp, e in todo}

    def one(batch):
        tps = [tp for tp in topics_list if tp["id"] in batch]
        prompt = runner.build_prompt(
            "07_lecture_page.md", MODULE_NAME=module.name, MODULE_CODE=module.code, PART=part, LECTURE_ID=lid,
            PLAN=json.dumps(tps, ensure_ascii=False),
            CONCEPTS=json.dumps([c for c in concepts if any(c["id"] in tp["concepts"] for tp in tps)], ensure_ascii=False),
            TEACHING=json.dumps([entry_of[b] for b in batch], ensure_ascii=False))
        focus = (f"\n\n## This call\nBuild visuals ONLY for these topic ids: {', '.join(batch)}. "
                 "Your file is one of several chunks loaded on the same page: keep every helper inside it.")
        text, usage = runner.run(cfg, prompt + focus, runner=runner_name, model="sonnet", timeout=3600)
        js = block(text, "VISUALS_JS")
        log(f"{lid} visuals: {batch} ({runner.describe(usage)})")
        return [f"// ---- {', '.join(batch)}\n(function () {{\n{js}\n}})();\n"]
    partial = od / f"{stem} - visuals.topics.partial.json"
    js = legacy_js + "\n".join(_batched(partial, [tp["id"] for tp, _ in todo], VIS_BATCH, one))
    partial.unlink(missing_ok=True)
    (od / f"{stem} - visuals.partial.json").unlink(missing_ok=True)
    target.write_text(js + "\n", encoding="utf-8")
    vis_dir = site_dir(cfg, module, part) / "visuals"
    vis_dir.mkdir(parents=True, exist_ok=True)
    (vis_dir / f"{lid}.js").write_text(js + "\n", encoding="utf-8")
    log(f"{lid} visuals: {len(VISUAL_RE.findall(js))} registered, {js.count('Study.selftest(')} self-tests")


def part_videos(cfg, module, part, every=3, log=print):
    """One Manim film per `every` lectures, for the hardest topic in each group; lectures that already have a
    film count as covered. Claude designs the storyboard and writes the scene in one call; Manim renders locally."""
    folders = [f for f in lecture_folders(cfg, module, part)
               if (out_dir(cfg, module, part, f) / f"{f.name} - teaching.json").exists()]
    for g in range(0, len(folders), every):
        group = folders[g:g + every]
        if any(_read_json(out_dir(cfg, module, part, f) / f"{f.name} - videos.json", []) for f in group):
            continue
        best = None
        for f in group:
            od = out_dir(cfg, module, part, f)
            entries = {t["id"]: t for t in load_teaching(od, f.name)[0]}
            for tp in _read_json(od / f"{f.name} - topics.json", []):
                score = (bool(tp.get("hard")), len(tp.get("concepts", [])))
                if tp["id"] in entries and (best is None or score > best[0]):
                    best = (score, f, dict(entries[tp["id"]], id=tp["id"], title=tp["title"]))
        if not best:
            continue
        _, f, entry = best
        entry["video"] = {"title": entry["title"], "shots": []}   # empty: the video step designs the shots
        log(f"film for {lecture_id(f)} {entry['id']} ({entry['title']})")
        videos(cfg, module, part, f, log=log, extra=[entry])


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


def videos(cfg, module, part, folder, runner_name="claude", log=print, extra=None):
    """Step 7c: Claude writes one Manim scene per `video` storyboard; Manim renders them locally (free).
    `extra`: teaching entries chosen by part_videos (their storyboard is designed in the same call)."""
    import shutil
    import tempfile
    from .site import site_dir
    lid, od, stem = lecture_id(folder), out_dir(cfg, module, part, folder), folder.name
    index = od / f"{stem} - videos.json"
    previous = _read_json(index, []) if extra else []
    if index.exists() and not extra:
        return log(f"{lid} videos exist")
    teaching = extra or load_teaching(od, stem)[0]
    if not any(t.get("video") for t in teaching):
        _write_json(index, [])
        return log(f"{lid} videos: none planned")
    prompt = runner.build_prompt("07c_videos.md", MODULE_NAME=module.name, MODULE_CODE=module.code, PART=part,
                                 TEACHING=json.dumps(teaching, ensure_ascii=False),
                                 MASTER=(od / f"{stem} - Master.md").read_text(encoding="utf-8"))
    text, usage = runner.run(cfg, prompt, runner=runner_name, model="sonnet", timeout=3600)
    code, listing = block(text, "MANIM_PY"), json_block(text, "VIDEOS")
    py = od / (f"{stem} - videos-{len(previous) + 1}.py" if extra else f"{stem} - videos.py")
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
    _write_json(index, previous + result)
    log(f"{lid} videos: {len(result)} rendered" + (f", FAILED: {sorted(failed)}" if failed else "") +
        f" ({runner.describe(usage)})")


VIS_BATCH = 3            # topics per visuals call
REGISTRY_LOCK = __import__("threading").Lock()


def vis_budget(topics_list):
    """Visuals only where they pay off: the hard topics, at most 1 per lecture (2 for a dense lecture)."""
    return 2 if len(topics_list) >= 4 else 1


def _batched(partial, ids, size, call):
    """Run call(batch) over ids in batches, saving after each so an interrupted step resumes where it stopped."""
    done = _read_json(partial, {"batches": [], "items": []})
    for b in range(0, len(ids), size):
        key = ",".join(ids[b:b + size])
        if key in done["batches"]:
            continue
        done["items"] += call(ids[b:b + size])
        done["batches"].append(key)
        _write_json(partial, done)
    return done["items"]


def _read_json(p, default):
    return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else default


def _write_json(p, data):
    Path(p).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _nlm(*a, **k):
    from .nlm import nlm_videos
    return nlm_videos(*a, **k)


STEPS = {"capture": capture, "audit": audit, "topics": topics, "teaching": teaching,
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
    limits = [e for e in errors.values() if isinstance(e, runner.LimitReached)]
    if limits:                                     # let the driver sleep until the window resets
        raise limits[0]
    if errors:
        raise runner.RunnerError("; ".join(f"{s}: {e}" for s, e in errors.items()))


PARALLEL = {"exercises", "visuals", "videos", "nlm"}
