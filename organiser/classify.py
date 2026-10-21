"""Combine Blackboard context, the dashboard pick, rules and Gemini into one decision.

Precedence for the module: Blackboard page > dashboard pick > rules/AI.
"""
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

from . import ai, rules


GENERIC_LINKS = {"slides", "slide", "lecture", "lecture slides", "pdf", "here", "link", "download", "notes",
                 "file", "open", "view"}


@dataclass
class Classification:
    module: str = None
    part: int = None          # index into Module.parts, None = module level
    category: str = None
    number: int = None
    topic: str = ""
    confidence: float = 0.0
    sources: dict = field(default_factory=dict)   # field -> where it came from
    flags: list = field(default_factory=list)
    not_course: bool = False
    used_ai: bool = False
    relates_to: str = None    # Solutions: "Lectures" or "Practicals"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__})


def part_needed(cfg, c):
    mod = cfg.module(c.module)
    if not mod or not mod.parts:
        return False
    if c.category in ("Lectures", "Practicals"):
        return True
    return c.category == "Solutions" and c.number is not None  # attached to a lecture/practical


def score(cfg, c, confs):
    vals = [confs.get("module", 0), confs.get("category", 0)]
    if part_needed(cfg, c):
        vals.append(confs.get("part", 0) if c.part is not None else 0)
    return round(min(vals), 2)


def classify(cfg, filename, text="", title="", context=None, manual_module=None, manual_part=None,
             error=None, when=None, use_ai=True):
    ctx = context or {}
    when = when or datetime.now()
    ext = Path(filename).suffix.lower()
    stem = rules.clean_stem(filename)
    item_title = ctx.get("item_title") or ""
    if rules.is_junk_title(item_title):
        item_title = ""
    chain = [s for s in (ctx.get("chain") or []) if s] + [s for s in (ctx.get("prev_chain") or []) if s]
    head = (text or "")[:1500]
    thr = cfg.confidence_threshold
    c = Classification()
    conf = {}

    # ---- module -------------------------------------------------------
    if ctx:
        course = f"{ctx.get('course_code', '')} {ctx.get('course_name', '')}"
        key = rules.module_from_code(cfg, course) or rules.module_from_names(cfg, ctx.get("course_name", ""))
        if key:
            c.module, conf["module"], c.sources["module"] = key, 1.0, "blackboard"
    if not c.module and manual_module:
        c.module, conf["module"], c.sources["module"] = manual_module, 1.0, "manual"
    prefix_mod, prefix_part = rules.module_from_prefix(cfg, filename)
    if not c.module:
        key = rules.module_from_code(cfg, f"{filename} {head}")
        if key:
            c.module, conf["module"], c.sources["module"] = key, 0.95, "course code"
        elif prefix_mod:
            c.module, conf["module"], c.sources["module"] = prefix_mod, 0.9, "filename"
        else:
            key = rules.module_from_names(cfg, f"{stem} {title}")
            if key:
                c.module, conf["module"], c.sources["module"] = key, 0.85, "module name"
            else:
                key, kc = rules.module_from_keywords(cfg, f"{stem} {title} {text}")
                if key:
                    c.module, conf["module"], c.sources["module"] = key, kc, "keywords"

    # ---- part -----------------------------------------------------------
    def detect_part():
        mod = cfg.module(c.module)
        c.part, conf["part"] = None, 0.0
        if not mod:
            return
        for s in chain:
            idx = rules.part_from_label(mod, s)
            if idx is not None:
                c.part, conf["part"], c.sources["part"] = idx, 0.95, "blackboard"
                return
        if manual_part is not None and manual_module == c.module:
            c.part, conf["part"], c.sources["part"] = manual_part, 1.0, "manual"
            return
        if prefix_mod == c.module and prefix_part is not None:
            c.part, conf["part"], c.sources["part"] = prefix_part, 0.9, "filename"
            return
        if mod.parts_by_term:
            c.part, conf["part"], c.sources["part"] = rules.part_by_term(when), 0.9, "term date"
            return
        idx = rules.part_from_label(mod, f"{stem} {item_title} {title}")
        if idx is not None:
            c.part, conf["part"], c.sources["part"] = idx, 0.85, "title"
            return
        idx, pc = rules.part_from_keywords(mod, f"{stem} {item_title} {title} {text}")
        if idx is not None:
            c.part, conf["part"], c.sources["part"] = idx, pc, "keywords"

    detect_part()

    # ---- category -------------------------------------------------------
    cat_candidates = [(item_title, 0.0, "blackboard"), (stem, 0.0, "filename")]
    cat_candidates += [(s, 0.1, "blackboard") for s in chain]
    cat_candidates += [(title, 0.1, "title"), ((text or "")[:300], 0.2, "text")]
    for s, penalty, src in cat_candidates:
        cat, cc = rules.category_from_text(s)
        if cat:
            c.category, conf["category"], c.sources["category"] = cat, cc - penalty, src
            break
    if not c.category and ext in rules.CODE_EXTS:
        c.category, conf["category"], c.sources["category"] = "Practicals", 0.75, "file type"

    # ---- number ---------------------------------------------------------
    for s in (item_title, stem, title, (text or "")[:300]):
        n = rules.number_from_text(s)
        if n:
            c.number = n
            break

    # ---- AI -------------------------------------------------------------
    is_doc = ext not in rules.CODE_EXTS
    topic_from_bb = bool(rules.clean_topic(item_title))
    weak = conf.get("module", 0) < thr or conf.get("category", 0) < thr or \
        (part_needed(cfg, c) and conf.get("part", 0) < thr)
    if use_ai and not error and ai.available() and (weak or (is_doc and not topic_from_bb)):
        known = {}
        if conf.get("module", 0) >= thr:
            m = cfg.module(c.module)
            known["module"] = f"{m.key} ({m.code} {m.name})"
            if c.part is not None and conf.get("part", 0) >= thr:
                known["part"] = f"part {c.part + 1} = {m.parts[c.part]}"
        if conf.get("category", 0) >= thr:
            known["category"] = c.category
        if ctx:
            known["Blackboard course"] = f"{ctx.get('course_code', '')} {ctx.get('course_name', '')}".strip()
            known["Blackboard folder path (innermost first)"] = " < ".join(chain[:6])
            known["Blackboard item title"] = item_title
        known["downloaded"] = when.strftime("%d %B %Y")
        res = ai.classify(cfg, filename, text, known)
        if res:
            c.used_ai = True
            _merge_ai(cfg, c, conf, res, thr, detect_part)
        else:
            c.flags.append("AI unavailable")

    # ---- topic ----------------------------------------------------------
    if not c.topic:
        for cand in (item_title, title, stem):
            t = rules.clean_topic(cand)
            if t and not t.isdigit():
                c.topic = t
                c.sources.setdefault("topic", "fallback")
                break
    c.topic = rules.clean_topic(c.topic) or rules.clean_topic(stem) or stem or "Untitled"
    # A page link like "Lecture 10: Generalisation theory (slides, K(x), proof)": the slides take the
    # lecture's topic, the other links are named after their own text ("Proof").
    link = rules.clean_topic(ctx.get("link_text") or "")
    if link and link.lower() not in GENERIC_LINKS and c.sources.get("topic") != "user":
        c.topic = link

    # Assessment / Exam Prep / Other live at module level unless a part was stated explicitly.
    if c.category in cfg.module_categories and c.sources.get("part") not in ("blackboard", "manual", "ai"):
        c.part = None

    if c.category == "Solutions":
        text = rules.normalise(f"{stem} {item_title} {title}")
        c.relates_to = "Lectures" if re.search(r"(?<![a-z])lectures?(?![a-z])", text) else "Practicals"
    c.confidence = score(cfg, c, conf)
    if not c.module:
        c.confidence = 0.0
    if error:
        c.flags.append(f"unreadable: {error}")
        c.confidence = min(c.confidence, 0.3)
    return c


def _merge_ai(cfg, c, conf, res, thr, detect_part):
    rc = res["confidence"]
    locked = c.sources.get("module") in ("blackboard", "manual")
    if res["module"] == "NONE":
        if not locked and conf.get("module", 0) < thr and rc >= 0.6:
            c.not_course = True
    elif res["module"]:
        if res["module"] == c.module:
            conf["module"] = max(conf.get("module", 0), min(1.0, rc + 0.1))
        elif not locked and rc > conf.get("module", 0):
            c.module, conf["module"], c.sources["module"] = res["module"], rc, "ai"
            detect_part()

    mod = cfg.module(c.module) if c.module else None
    if mod and mod.parts and not mod.parts_by_term and c.sources.get("part") not in ("blackboard", "manual"):
        if res["part"] is not None and res["module"] == c.module:
            if res["part"] == c.part:
                conf["part"] = max(conf.get("part", 0), min(1.0, rc + 0.1))
            elif rc > conf.get("part", 0):
                c.part, conf["part"], c.sources["part"] = res["part"], rc, "ai"
        elif res.get("module_wide") and c.sources.get("part") == "ai":
            c.sources["part"] = "ai module-wide"

    if res["category"]:
        if res["category"] == c.category:
            conf["category"] = max(conf.get("category", 0), min(1.0, rc + 0.1))
        elif c.sources.get("category") != "blackboard" and rc > conf.get("category", 0):
            c.category, conf["category"], c.sources["category"] = res["category"], rc, "ai"

    if c.number is None and res["number"]:
        c.number = res["number"]
    if res["topic"]:
        c.topic = res["topic"]
        c.sources["topic"] = "ai"
