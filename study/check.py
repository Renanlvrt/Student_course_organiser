"""Coverage checker (no model): a lecture counts as done only when every concept has everything it should."""
import json
import re

from .lecture import lecture_folders, lecture_id, out_dir, _read_json

MIN = {"drill": 3, "exam": 2, "transfer": 1}
MIN_INTERLEAVED = 10


def check_lecture(cfg, module, part, folder):
    od, stem = out_dir(cfg, module, part, folder), folder.name
    problems = []
    audit = _read_json(od / f"{stem} - audit.json", {})
    if audit.get("verdict") != "PASS":
        problems.append(f"audit verdict is {audit.get('verdict', 'missing')!r}")
    concepts = _read_json(od / f"{stem} - concepts.json", [])
    plan_raw = _read_json(od / f"{stem} - plan.json", [])
    plan = {p["id"]: p for p in (plan_raw.get("concepts", []) if isinstance(plan_raw, dict) else plan_raw)}
    teaching = {t["id"]: t for t in _read_json(od / f"{stem} - teaching.json", [])}
    exercises = _read_json(od / f"{stem} - exercises.json", [])
    vis_path = od / f"{stem} - visuals.js"
    visuals = set(re.findall(r'Study\.visuals\[\s*["\']([^"\']+)', vis_path.read_text(encoding="utf-8"))) if vis_path.exists() else set()
    rows = []
    for c in concepts:
        cid = c["id"]
        mode = (plan.get(cid) or {}).get("teach", "all")
        t = teaching.get(cid, {})
        counts = {k: sum(1 for e in exercises if cid in (e.get("concepts") or []) and e.get("layer") == k) for k in MIN}
        need = {}
        if cid not in plan:
            need["plan"] = "missing"
        if mode != "recap":
            for f in ("explanation", "analogies", "examples", "animation", "sandbox"):
                if not t.get(f):
                    need[f] = "missing"
            if len(t.get("recall_cards") or []) < 3:
                need["cards"] = f"{len(t.get('recall_cards') or [])}/3"
            if cid not in visuals:
                need["visuals"] = "missing"
        for k, n in MIN.items():
            if counts[k] < n:
                need[k] = f"{counts[k]}/{n}"
        rows.append((cid, mode, counts, need))
        if need:
            problems.append(f"{cid}: " + ", ".join(f"{k} {v}" for k, v in need.items()))
    inter = sum(1 for e in exercises if e.get("layer") == "interleaved")
    if inter < MIN_INTERLEAVED:
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
        log(f"{lecture_id(folder)}: {len(rows)} concepts, " + ("COMPLETE" if not problems else f"{len(problems)} problem(s)"))
        for p in problems:
            log("   - " + p)
        total += len(problems)
    return total
