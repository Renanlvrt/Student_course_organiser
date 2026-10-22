"""Coverage checker (no model): a lecture counts as done only when every topic has everything it should.

The notes, glossary and cards cover every concept; the rich teaching (visuals, sandbox, exercises) is per topic.
"""
import re

from .lecture import lecture_folders, lecture_id, load_teaching, out_dir, _read_json

MIN = {"drill": 2, "exam": 1, "transfer": 1}
MIN_INTERLEAVED = 4


def check_lecture(cfg, module, part, folder):
    od, stem = out_dir(cfg, module, part, folder), folder.name
    problems = []
    if _read_json(od / f"{stem} - audit.json", {}).get("verdict") != "PASS":
        problems.append("audit has not passed")
    concepts = _read_json(od / f"{stem} - concepts.json", [])
    topics = _read_json(od / f"{stem} - topics.json", [])
    if not topics:
        return [], problems + ["no topics yet"]
    placed = {c for t in topics for c in t["concepts"]}
    lost = [c["id"] for c in concepts if c["id"] not in placed]
    if lost:
        problems.append(f"concepts in no topic: {lost[:5]}")
    entries, glossary, cards = load_teaching(od, stem)
    pilot = isinstance(_read_json(od / f"{stem} - teaching.json", {}), list)   # first lecture: per-concept design
    teach = {t["id"]: t for t in entries}
    exercises = _read_json(od / f"{stem} - exercises.json", [])
    vis_path = od / f"{stem} - visuals.js"
    visuals = set(re.findall(r"""Study\.visuals\[\s*["']([^"']+)""", vis_path.read_text(encoding="utf-8"))) \
        if vis_path.exists() else set()
    if not pilot:
        if not glossary:
            problems.append("no glossary")
        if len(cards) < len(concepts):
            problems.append(f"flashcards {len(cards)} for {len(concepts)} concepts")
    rows = []
    for tp in topics:
        tid, need = tp["id"], {}
        recap = str(tp.get("prior", "")).startswith("recap")
        members = {tid, *tp["concepts"]}
        if not recap:
            t = teach.get(tid)
            if tp.get("hard") and not (visuals & members) and tid in {x["id"] for x in topics if x.get("hard")}:
                need["visuals"] = "missing (hard topic)"
            if not pilot:
                for f in ("explanation",) + (("animation", "sandbox", "figures") if tp.get("hard") else ()):
                    if not (t or {}).get(f):
                        need[f] = "missing"
                if tp.get("hard"):
                    for f in ("intuition", "tables"):
                        if not (t or {}).get(f):
                            need[f"hard: {f}"] = "missing"
            counts = {k: sum(1 for e in exercises if members & set(e.get("concepts") or []) and e.get("layer") == k)
                      for k in MIN}
            for k, n in MIN.items():
                if counts[k] < n:
                    need[k] = f"{counts[k]}/{n}"
        rows.append((tid, need))
        if need:
            problems.append(f"{tid} ({tp['title']}): " + ", ".join(f"{k} {v}" for k, v in need.items()))
    inter = sum(1 for e in exercises if e.get("layer") == "interleaved")
    if not pilot and inter < MIN_INTERLEAVED:
        problems.append(f"interleaved questions {inter}/{MIN_INTERLEAVED}")
    bad_mcq = [e["id"] for e in exercises if (e.get("check") or {}).get("type") == "mcq" and not e.get("options")]
    if bad_mcq:
        problems.append(f"mcq without options: {bad_mcq[:5]}")
    return rows, problems


def check_part(cfg, module, part, log=print):
    total = 0
    for folder in lecture_folders(cfg, module, part):
        if not (out_dir(cfg, module, part, folder) / f"{folder.name} - concepts.json").exists():
            log(f"{lecture_id(folder)}: not captured yet")
            continue
        rows, problems = check_lecture(cfg, module, part, folder)
        log(f"{lecture_id(folder)}: {len(rows)} topics, " + ("COMPLETE" if not problems else f"{len(problems)} problem(s)"))
        for p in problems:
            log("   - " + p)
        total += len(problems)
    return total
