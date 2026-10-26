"""First-page / first-slide text extraction. Raises ExtractError for unreadable files."""
import json
import zipfile
from pathlib import Path

MAX_CHARS = 4000


class ExtractError(Exception):
    pass


def extract(path):
    """Return (text, title_guess). title_guess may be ''."""
    path = Path(path)
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            return _pdf(path)
        if ext == ".pptx":
            return _pptx(path)
        if ext == ".docx":
            return _docx(path)
        if ext == ".ipynb":
            return _ipynb(path)
        if ext == ".zip":
            return _zip(path)
        if ext in (".html", ".htm"):
            return _html(path)
        return path.read_text(encoding="utf-8", errors="ignore")[:MAX_CHARS], ""
    except ExtractError:
        raise
    except Exception as e:  # corrupted / encrypted / wrong format
        raise ExtractError(f"{type(e).__name__}: {e}") from e


def _pdf(path):
    import fitz
    with fitz.open(path) as doc:
        if doc.page_count == 0:
            raise ExtractError("PDF has no pages")
        text = doc[0].get_text()
        if len(text.strip()) < 200 and doc.page_count > 1:
            text += "\n" + doc[1].get_text()
        return text[:MAX_CHARS], _pdf_title(doc[0])


def _pdf_title(page):
    """Largest-font line on the page, a decent topic fallback for slides."""
    best_size, lines = 0.0, {}
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            size = round(max(s["size"] for s in spans), 1)
            txt = " ".join(s["text"].strip() for s in spans)
            lines.setdefault(size, []).append(txt)
            best_size = max(best_size, size)
    if not best_size:
        return ""
    return " ".join(lines[best_size])[:120].strip()


def _pptx(path):
    from pptx import Presentation
    prs = Presentation(str(path))
    texts, title = [], ""
    for i, slide in enumerate(prs.slides):
        if i > 1 or (i == 1 and len("\n".join(texts)) > 200):
            break
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                t = shape.text_frame.text.strip()
                texts.append(t)
                if not title and getattr(shape, "is_placeholder", False):
                    try:
                        if shape.placeholder_format.type in (1, 3):  # TITLE, CENTER_TITLE
                            title = t.splitlines()[0]
                    except Exception:
                        pass
    if not title and texts:
        title = texts[0].splitlines()[0]
    return "\n".join(texts)[:MAX_CHARS], title[:120]


def _docx(path):
    import docx
    d = docx.Document(str(path))
    texts, title, total = [], "", 0
    for p in d.paragraphs:
        t = p.text.strip()
        if not t:
            continue
        if not title and (p.style.name.lower().startswith(("title", "heading")) or not texts):
            title = t
        texts.append(t)
        total += len(t)
        if total > MAX_CHARS:
            break
    return "\n".join(texts)[:MAX_CHARS], title[:120]


def _ipynb(path):
    nb = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    parts = []
    for cell in nb.get("cells", [])[:20]:
        src = cell.get("source", "")
        parts.append("".join(src) if isinstance(src, list) else str(src))
    text = "\n".join(parts)
    title = next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("#")), "")
    return text[:MAX_CHARS], title[:120]


def _zip(path):
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            raise ExtractError(f"corrupt member {bad}")
        names = z.namelist()
    return "ZIP archive containing:\n" + "\n".join(names[:80]), ""


def _html(path):
    """Blackboard pages saved by the extension: their words and <title> (tags and styles stripped)."""
    import html as htmlmod
    import re
    raw = path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"<title>(.*?)</title>", raw, re.S | re.I)
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    text = htmlmod.unescape(re.sub(r"<[^>]+>", " ", body))
    return re.sub(r"\s+", " ", text).strip()[:MAX_CHARS], htmlmod.unescape(m.group(1).strip()) if m else ""
