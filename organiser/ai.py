"""Gemini classification. Returns a dict or None; never raises."""
import json
import logging
import time

from .config import gemini_key

log = logging.getLogger("organiser.ai")

_client = None
_cooldown = {}   # model -> time until which it is skipped (daily quota used up)


def _get_client():
    global _client
    key = gemini_key()
    if not key:
        return None
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=key, http_options={"timeout": 25_000})
    return _client


def available():
    return gemini_key() is not None


def _schema(cfg):
    cats = sorted(set(cfg.part_categories) | set(cfg.module_categories))
    return {
        "type": "OBJECT",
        "properties": {
            "module": {"type": "STRING", "enum": [m.key for m in cfg.modules] + ["NONE"]},
            "part": {"type": "STRING", "enum": ["1", "2", "module-wide"]},
            "category": {"type": "STRING", "enum": cats},
            "number": {"type": "INTEGER", "nullable": True},
            "topic": {"type": "STRING"},
            "confidence": {"type": "NUMBER"},
        },
        "required": ["module", "part", "category", "number", "topic", "confidence"],
    }


def _prompt(cfg, filename, text, known):
    mods = []
    for m in cfg.modules:
        parts = "parts are split by term (Term 1 / Term 2)" if m.parts_by_term else \
            "; ".join(f"part {i + 1} = {p}" for i, p in enumerate(m.parts))
        mods.append(f"- {m.key}: {m.code} {m.name} ({parts})")
    facts = "\n".join(f"- {k}: {v}" for k, v in known.items() if v not in (None, "")) or "- none"
    return f"""You sort a Durham University 3rd-year Computer Science student's downloaded course files.

Modules (pick exactly one key, or NONE if the file is clearly not material for any of these modules):
{chr(10).join(mods)}

Categories:
- Lectures: lecture slides / lecture notes
- Practicals: practical, lab, tutorial or problem sheets and their code/notebooks
- Solutions: answers or solutions to practicals, problem sheets or lecture questions
- Readings: papers, book chapters, extra reading
- Assessment: coursework / assignment briefs, specs, marking criteria
- Exam Prep: past papers, revision material, mock exams
- Other: module handbook, admin, anything else

Facts already known (trust these; fill in the rest):
{facts}

Return:
- module, part ("1", "2", or "module-wide" for things that belong to the whole module such as assessment briefs or the handbook)
- category
- number: the lecture / practical / week number if it is printed in the filename or text, else null
- topic: a short human title for the file content, 2-7 words, Title Case, no module name, no "Lecture N", no file extension
- confidence: 0-1, how sure you are about module+part+category overall

Filename: {filename}

First page text:
\"\"\"
{(text or '')[:4000]}
\"\"\"
"""


def classify(cfg, filename, text, known=None):
    client = _get_client()
    if client is None:
        return None
    from google.genai import types
    prompt = _prompt(cfg, filename, text, known or {})
    conf = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=_schema(cfg),
        temperature=0.1,
    )
    models = [m for m in (cfg.gemini_model, cfg.gemini_fallback_model) if m]
    for model in models:
        if _cooldown.get(model, 0) > time.time():
            continue
        for attempt in range(3):
            try:
                resp = client.models.generate_content(model=model, contents=prompt, config=conf)
                data = json.loads(resp.text)
                return _normalise(cfg, data)
            except Exception as e:
                msg = str(e)
                log.warning("Gemini %s attempt %d failed: %s", model, attempt + 1, msg[:300])
                if "quota" in msg.lower():
                    _cooldown[model] = time.time() + 15 * 60   # quota gone: skip this model for a while
                    break
                if ("429" in msg or "RESOURCE_EXHAUSTED" in msg) and attempt < 2:
                    time.sleep([5, 15][attempt])
                    continue
                break  # overloaded / timeout / gone: go straight to the fallback model
    return None


def _normalise(cfg, d):
    module = d.get("module")
    if module not in [m.key for m in cfg.modules]:
        module = None if module != "NONE" else "NONE"
    part = d.get("part")
    part_idx = {"1": 0, "2": 1}.get(str(part))
    num = d.get("number")
    try:
        num = int(num) if num is not None else None
        if num is not None and not (0 < num < 100):
            num = None
    except (TypeError, ValueError):
        num = None
    try:
        confidence = max(0.0, min(1.0, float(d.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "module": module,
        "part": part_idx,
        "module_wide": str(part) == "module-wide",
        "category": d.get("category"),
        "number": num,
        "topic": d.get("topic") or "",
        "confidence": confidence,
    }
