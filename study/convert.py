"""Step 0: PDF -> markdown with <!-- page N --> markers, plus flags for pages a vision model must re-read.

Local and free. Output: courses/<Module>/Lectures/<Part>/lectures_markdown/<stem>.md and manifest.json.
Flagged pages are rendered to data/study/<Module>/<stem>/page-NNN.png (never inside courses/).
"""
import hashlib
import json
import statistics
import unicodedata
from datetime import datetime
from pathlib import Path

import fitz

MD_DIR = "lectures_markdown"
MATH_FONTS = ("CMMI", "CMSY", "CMEX", "MSAM", "MSBM", "EUFM", "RSFS")
MONO_FONTS = ("CMTT", "Consolas", "Courier", "Mono")
BIG_OPS = set("∑∏∫∮⋃⋂⨁⨂√")
DENSE_MATH_SPANS = 12      # more maths spans than this: layout probably lost (fractions, matrices, indices)
DIAGRAM_PATHS = 6          # line/curve drawings (not plain boxes) above this: a vector diagram


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _plain(text):
    """Map maths italic/bold letters (U+1D400-1D7FF) to plain ones; leave every other symbol alone."""
    return "".join(unicodedata.normalize("NFKC", c) if 0x1D400 <= ord(c) <= 0x1D7FF else c for c in text)


def _is_math(font):
    base = font.split("+")[-1]
    return "Math" in base or base.startswith(MATH_FONTS)


def _line_md(line):
    spans = [s for s in line["spans"] if s["text"].strip() or s["text"] == " "]
    if not spans:
        return "", 0
    main = max(spans, key=lambda s: (s["size"], len(s["text"])))
    base_y, size = main["origin"][1], main["size"]
    out = []
    for s in spans:
        t = _plain(s["text"])
        if s["size"] < 0.8 * size and t.strip():
            dy = s["origin"][1] - base_y
            if dy > 0.12 * size:
                t = "_{" + t.strip() + "}"
            elif dy < -0.12 * size:
                t = "^{" + t.strip() + "}"
        elif s["font"].split("+")[-1].startswith(MONO_FONTS) and t.strip():
            t = "`" + t.strip() + "`"
        elif ("Bold" in s["font"] or s["font"].split("+")[-1].startswith("CMBX")) and t.strip():
            t = "**" + t.strip() + "**"
        out.append(t)
    return "".join(out).replace("****", "").replace("}_{", "").strip(), size


def _diagram_paths(page):
    W, H = page.rect.width, page.rect.height
    n = 0
    for d in page.get_drawings():
        r = d["rect"]
        if r.width > 0.9 * W and r.height > 0.9 * H:          # page background
            continue
        if all(it[0] == "re" for it in d["items"]):              # plain boxes / header bars
            continue
        if r.height < 1.5 and r.width < 0.6 * W:                 # fraction bars count as maths, see below
            continue
        n += 1
    return n


def _fraction_bars(page):
    return sum(1 for d in page.get_drawings()
               if d["rect"].height < 1.5 and 3 < d["rect"].width < 0.5 * page.rect.width
               and all(it[0] in ("l", "re") for it in d["items"]))


def _visible_images(page):
    area = page.rect.width * page.rect.height
    return [r for img in page.get_images(full=True) for r in page.get_image_rects(img[0])
            if r.width * r.height > 0.03 * area]


def page_flags(page, text_chars, math_spans, orphans):
    reasons = []
    if orphans:
        reasons.append(f"detached sub/superscripts ({orphans} lines)")
    if math_spans > DENSE_MATH_SPANS:
        reasons.append(f"dense maths ({math_spans} maths spans)")
    if any(c in BIG_OPS for c in page.get_text()) or any(
            f[3].split("+")[-1].startswith("CMEX") for f in page.get_fonts()):
        reasons.append("big operators / roots")
    fb = _fraction_bars(page)
    if fb and math_spans:
        reasons.append(f"fractions ({fb})")
    dp = _diagram_paths(page)
    if dp > DIAGRAM_PATHS:
        reasons.append(f"vector diagram ({dp} paths)")
    area = page.rect.width * page.rect.height
    images = _visible_images(page)
    if images:
        reasons.append(f"figure image ({round(100 * max(r.width * r.height for r in images) / area)}% of page)")
    if page.find_tables().tables:
        reasons.append("table")
    if text_chars < 60 and (dp or images):
        reasons.append("little text")
    return reasons


def convert_pdf(pdf, md_path, img_dir):
    doc = fitz.open(pdf)
    sizes = [s["size"] for p in doc for b in p.get_text("dict")["blocks"] for l in b.get("lines", [])
             for s in l["spans"] if s["text"].strip()]
    body = statistics.median(sizes) if sizes else 10
    parts, flagged = [f"# {pdf.stem}\n\n_Source: `{pdf.name}` · {len(doc)} pages_\n"], {}
    for i, page in enumerate(doc, 1):
        lines, math_spans, orphans = [], 0, 0
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                math_spans += sum(1 for s in l["spans"] if s["text"].strip() and _is_math(s["font"]))
                text, size = _line_md(l)
                if not text:
                    continue
                if size < 0.8 * body and len(text) <= 8 and not text.isdigit():
                    orphans += 1          # a sub/superscript that landed on its own line
                if size >= 1.6 * body:
                    text = "## " + text
                elif size >= 1.25 * body:
                    text = "### " + text
                lines.append(text)
            lines.append("")
        page_text = "\n".join(lines).strip()
        reasons = page_flags(page, len(page_text), math_spans, orphans)
        parts.append(f"\n<!-- page {i} -->\n{page_text}\n")
        if reasons:
            flagged[i] = reasons
            img_dir.mkdir(parents=True, exist_ok=True)
            page.get_pixmap(dpi=150).save(str(img_dir / f"page-{i:03d}.png"))
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("".join(parts), encoding="utf-8")
    return len(doc), flagged


def targets(cfg, module):
    """(pdf, lectures_markdown dir) pairs. Module-level files (Other/: full notes, exams) go once to
    Lectures/lectures_markdown/; each part's lectures, readings and practicals to Lectures/<Part>/lectures_markdown/."""
    mod_dir = cfg.root_folder / module.key
    out = []
    for part in module.parts:
        md_dir = mod_dir / "Lectures" / part / MD_DIR
        for kind in ("Lectures", "Practicals"):
            base = mod_dir / kind / part
            out += [(p, md_dir) for p in sorted(base.rglob("*.pdf")) if MD_DIR not in p.parts]
    out += [(p, mod_dir / "Lectures" / MD_DIR) for p in sorted((mod_dir / "Other").rglob("*.pdf"))]
    return out


def convert_module(cfg, module, force=False, log=print):
    results = {}
    for pdf, md_dir in targets(cfg, module):
        man_path = md_dir / "manifest.json"
        manifest = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {}
        digest = sha256(pdf)
        rel = str(pdf.relative_to(cfg.root_folder / module.key))
        if not force and manifest.get(pdf.stem, {}).get("sha256") == digest:
            log(f"unchanged  {rel}")
            continue
        img_dir = cfg.data_dir / "study" / module.key / pdf.stem
        pages, flagged = convert_pdf(pdf, md_dir / f"{pdf.stem}.md", img_dir)
        manifest[pdf.stem] = {"pdf": rel, "sha256": digest, "pages": pages,
                              "flagged": {str(k): v for k, v in flagged.items()},
                              "page_images": str(img_dir), "converted": datetime.now().isoformat(timespec="seconds"),
                              "fixed_pages": []}
        man_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        results[rel] = (pages, flagged)
        log(f"converted  {rel}: {pages} pages, {len(flagged)} flagged")
    return results
