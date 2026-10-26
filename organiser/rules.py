"""Deterministic classification rules: course codes, filename patterns, keywords."""
import re
from datetime import datetime

CODE_RE = re.compile(r"\bCOMP\s?(\d{4})", re.I)
DUP_SUFFIX_RE = re.compile(r"(\s*\(\d+\))+$")

# Order matters: "Answers to Practice Questions of Lecture 1" is a solution, not a lecture.
CATEGORY_PATTERNS = [
    ("Solutions", 0.9, r"\b(answers?|solutions?|sols?|model answers?|worked solutions?|mark ?scheme|marking scheme)\b"),
    ("Exam Prep", 0.85, r"\b(exams?|past papers?|revision|mock exam|past exam)\b"),
    # "Formative exercises" are practice sheets, so formative is not Assessment.
    ("Assessment", 0.85, r"\b(coursework|assignments?|assessments?|summative|submission|rubric|cw\d?)\b"),
    ("Practicals", 0.85, r"\b(practicals?|pract|prac|labs?|tutorials?|tut|worksheets?|exercises?|excercises?|formative|problem sheets?|problem set|questions|workshop|seminar|sheet)\b"),
    ("Lectures", 0.85, r"\b(lectures?|lec|slides?|lecture notes|week|wk)\b"),
    ("Other", 0.8, r"\b(handbook|syllabus|start here|module guide|timetable|overview|welcome|introduction to the module)\b"),
    ("Readings", 0.8, r"\b(readings?|reading list|papers?|curated papers|chapters?|textbooks?|books?|articles?|survey|references?)\b"),
]
CODE_EXTS = {".py", ".ipynb", ".c", ".h", ".csv", ".zip"}

NUM_RE = re.compile(
    r"\b(?:lecture|lec|l|practical|pract|prac|p|lab|tutorial|tut|weeks?|wk|w|sheet|worksheet|"
    r"exercises?|problems?|questions? of lecture|session|unit|topic|chapter|ch|class)\s*0*(\d{1,2})\b"
)
SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "vs", "via", "with"}


def normalise(s):
    s = (s or "").lower()
    s = re.sub(r"[_\-.+]", " ", s)
    s = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_stem(name):
    """Filename stem without browser duplicate markers like ' (1)'."""
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return DUP_SUFFIX_RE.sub("", stem).strip()


def _kw_re(kw):
    kw = kw.lower()
    tail = r"\b" if len(kw) <= 4 else ""
    return re.compile(r"(?<![a-z0-9])" + re.escape(kw) + tail)


def module_from_code(cfg, text):
    for m in CODE_RE.finditer(text or ""):
        code = "COMP" + m.group(1)
        for mod in cfg.modules:
            if mod.code == code:
                return mod.key
    return None


def module_from_names(cfg, text):
    """Full module name or alias appearing in text (e.g. a course title)."""
    t = normalise(text)
    for mod in cfg.modules:
        names = [mod.name, mod.key] + mod.aliases
        for n in names:
            n2 = normalise(n.replace("&", "and"))
            if n2 and re.search(r"(?<![a-z0-9])" + re.escape(n2) + r"(?![a-z0-9])", t.replace("&", "and")):
                return mod.key
    return None


def module_from_prefix(cfg, filename):
    """Filename prefixes like 'dl-lecture1.pdf' -> (DLCV, part 0)."""
    first = normalise(clean_stem(filename)).split(" ")[0] if filename else ""
    for mod in cfg.modules:
        if first in mod.filename_prefixes:
            return mod.key, mod.filename_prefixes[first]
    return None, None


def module_from_keywords(cfg, text):
    t = (text or "").lower()
    scores = []
    for mod in cfg.modules:
        hits = sum(1 for kw in mod.keywords if _kw_re(kw).search(t))
        scores.append((hits, mod.key))
    scores.sort(reverse=True)
    best, second = scores[0], scores[1] if len(scores) > 1 else (0, None)
    if best[0] == 0 or best[0] == second[0]:
        return None, 0.0
    return best[1], min(0.85, 0.45 + 0.1 * (best[0] - second[0]))


def part_from_keywords(mod, text):
    if not mod.part_keywords:
        return None, 0.0
    t = (text or "").lower()
    hits = [sum(1 for kw in kws if _kw_re(kw).search(t)) for kws in mod.part_keywords]
    order = sorted(range(len(hits)), key=lambda i: -hits[i])
    best = order[0]
    margin = hits[best] - (hits[order[1]] if len(order) > 1 else 0)
    if hits[best] == 0 or margin <= 0:
        return None, 0.0
    return best, min(0.85, 0.5 + 0.1 * margin)


PART_NUM_RE = [   # "Term 2", "Term2 [Security]", "Part II", Durham's "Epiphany" / "Michaelmas" terms
    (1, re.compile(r"\b(?:(?:part|term|submodule)\s*(?:2|ii|two)\b|epiphany)")),
    (0, re.compile(r"\b(?:(?:part|term|submodule)\s*(?:1|i|one)\b|michaelmas)")),
]


def part_from_label(mod, text):
    """Match a Blackboard section title such as 'Part 1: Symmetric Cryptography'."""
    t = normalise(text)
    # Longest name first + word boundaries: "symmetric" must not match inside "asymmetric".
    for i, name in sorted(enumerate(mod.parts), key=lambda x: -len(x[1])):
        if re.search(r"(?<![a-z0-9])" + re.escape(normalise(name)) + r"(?![a-z0-9])", t):
            return i
    for i, rx in PART_NUM_RE:
        if rx.search(t):
            return i
    return None


def part_by_term(when=None):
    """Durham: Michaelmas (Sep-Dec) = Term 1, everything after New Year = Term 2."""
    when = when or datetime.now()
    return 0 if when.month >= 9 else 1


def category_from_text(text, ext=""):
    t = normalise(text)
    for cat, conf, rx in CATEGORY_PATTERNS:
        if re.search(rx, t):
            return cat, conf
    if ext in CODE_EXTS:
        return "Practicals", 0.75
    return None, 0.0


def number_from_text(text):
    raw = DUP_SUFFIX_RE.sub("", text or "")
    m = NUM_RE.search(normalise(raw)) or LEAD_NUM_RE.match(raw)
    if m:
        n = int(m.group(1))
        if 0 < n < 100:
            return n
    return None


# "AGT 1 - Introduction", "2 Nash's Theorem", "L3: Hashing"
LEAD_NUM_RE = re.compile(r"^\s*(?:[A-Za-z]{1,6}\s*)?0*(\d{1,2})(?:\s*[-–:.]\s+|\s+(?=[A-Za-z]))")
FILE_EXT_RE = re.compile(r"\.(pdf|pptx?|docx?|ipynb|py|zip|txt|md|csv|c|h)$", re.I)
JUNK_TITLE_RE = re.compile(r"^(ultra\s*document\s*body|untitled|document|file|attachment|download)\b", re.I)


def citation_title(s):
    """Paper title from a reference: 'X, "Title," in ...' or 'X (2016). Title. In ...'."""
    s = s or ""
    m = re.search(r'[“"]([^”"]{8,}?)[,.]?[”"]', s)
    if m:
        return m.group(1).strip(" ,.")
    m = re.search(r"\(\d{4}[a-z]?(?:,[^)]*)?\)\.\s*(.{8,}?)(?:\.\s|\.$|\?\s|$)", s)
    if m:
        return m.group(1).strip(" ,.")
    return ""


def is_junk_title(s):
    """Blackboard internal names such as 'ultraDocumentBody Copy' are not real titles."""
    s = (s or "").strip()
    return not s or bool(JUNK_TITLE_RE.match(s))


def clean_topic(raw, max_len=60):
    if not raw:
        return ""
    s = str(raw).replace("\n", " ").strip()
    s = DUP_SUFFIX_RE.sub("", FILE_EXT_RE.sub("", DUP_SUFFIX_RE.sub("", s)))  # "x (1).pdf" -> "x"
    if " " not in s:
        s = re.sub(r"[-_]+", " ", s)                                  # filename-ish: week1-questions
    s = re.sub(r"\(\s*\d{2}\s*/\s*\d{2}\s*\)", " ", s)              # (26/27)
    s = re.sub(r"\bCOMP\s?\d{4}(_\d{4})?\b", " ", s, flags=re.I)
    # Only strip "Week 2 " / "Solutions: " style prefixes (keyword + whole number or separator), so that
    # cleaning twice is harmless: "Answers 1a and 1b" stays as it is.
    s = re.sub(r"^\s*(lectures?|lec|practicals?|pract|lab|tutorial|weeks?|topic|solutions?|answers?|sheet)(?![a-z])"
               r"[\s\-_]*(?:\d{1,2}(?:\s*-\s*\d{1,2})?(?![a-z0-9])\s*[:\-–.]*|[:\-–.]+)\s*", "", s, flags=re.I)
    s = re.sub(r"^\s*[A-Za-z]{1,6}\s*\d{1,2}\s*[-–:.]\s+", "", s)  # "AGT 1 - ", "L3: "
    s = re.sub(r"^\s*\d{1,2}\s+(?=[A-Za-z])", "", s)                # "2 Nash's Theorem"
    s = re.sub(r"\s*[-–]\s*(slides?|notes|handout)\s*$", "", s, flags=re.I)
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", s)
    s = re.sub(r"[_]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .-–")
    words = []
    for i, w in enumerate(s.split(" ")):
        if w.isupper() and len(w) > 1 or any(c.isdigit() for c in w) or any(c.isupper() for c in w[1:]):
            words.append(w)                                          # AES, RSA, k-NN, pH
        elif i > 0 and w.lower() in SMALL_WORDS:
            words.append(w.lower())
        else:
            words.append(w[:1].upper() + w[1:].lower() if w else w)
    s = " ".join(words)
    if len(s) > max_len:
        s = s[:max_len].rsplit(" ", 1)[0]
    return s.strip(" .-–")
