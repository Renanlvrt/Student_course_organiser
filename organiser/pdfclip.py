"""Alt+L in desktop PDF viewers (Acrobat, Foxit, SumatraPDF): turn a box drawn on a screenshot of the viewer into
the same clipboard content the Chrome extension produces - formatted, editable HTML in the subset OneNote keeps,
plain text, and the exact picture.

    find_open_pdf(window_title) -> path of the PDF shown in that window, or None
    locate(pdf_path, screenshot, box) -> Match(page, rect, zoom, score) or None
    rich(page, rects) -> (html, text)
    set_clipboard(html, text, png_image)

The box is located on the page by estimating the viewer's zoom from the white page edges and confirming it by
matching the screenshot pixels against the page rendered at that zoom (OpenCV). Below MIN_SCORE nothing is
guessed: the caller pastes the exact picture instead.
"""
import io
import logging
import re
import time
import winreg
from dataclasses import dataclass
from pathlib import Path

import cv2
import fitz
import numpy as np

log = logging.getLogger("organiser.pdfclip")

MIN_SCORE = 0.75
RENDER_SCALE = 1.0          # px per pt for the coarse search (one render per page)


# ---------------------------------------------------------------- which PDF is open
def pdf_name_from_title(title):
    m = re.match(r"\s*(.+?\.pdf)\b", title or "", re.I)
    return m.group(1).strip() if m else None


def _acrobat_recent():
    """(file name, full path) of the files in Acrobat's recent list, most recent first."""
    out = []
    for product in ("Adobe Acrobat", "Acrobat Reader"):
        for version in ("DC", "2020", "2017", "2015", "11.0"):
            key = rf"Software\Adobe\{product}\{version}\AVGeneral\cRecentFiles"
            try:
                root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key)
            except OSError:
                continue
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, sub) as k:
                        di = winreg.QueryValueEx(k, "tDIText")[0]
                        name = winreg.QueryValueEx(k, "tFileName")[0]
                    out.append((int(sub[1:]) if sub[1:].isdigit() else 999, name, di))
                except OSError:
                    pass
    out.sort()
    # "/C/Users/x/file.pdf" -> "C:/Users/x/file.pdf"
    return [(n, re.sub(r"^/([A-Za-z])/", r"\1:/", p)) for _, n, p in out]


def find_open_pdf(title, search_dirs=()):
    name = pdf_name_from_title(title)
    if not name:
        return None
    for n, p in _acrobat_recent():
        if n.lower() == name.lower() and Path(p).exists():
            return Path(p)
    for d in search_dirs:                          # other viewers: look where course files live
        d = Path(d)
        if d.exists():
            for hit in d.rglob(name):
                return hit
    return None


# ---------------------------------------------------------------- where the box is on the page
@dataclass
class Match:
    page: int          # 0-based
    rect: fitz.Rect    # in PDF points (page coordinates)
    zoom: float        # screen px per pt
    score: float


def _page_gray(page, scale, clip=None):
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, colorspace=fitz.csGRAY, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)


def _edge_zoom(gray, box, doc):
    """Zoom from the width of the white page around the box: page margins are white, the viewer behind is not."""
    l, t, r, b = box
    band = gray[max(0, t):b]
    if band.size == 0:
        return None
    white = (band >= 240).mean(axis=0)
    def edge(x, step):
        run = 0
        while 0 < x < len(white) - 1:
            run = run + 1 if white[x] < 0.25 else 0
            if run >= 4:
                return x - step * 3
            x += step
        return x
    left, right = edge(l, -1), edge(r - 1, 1)
    width = right - left
    widths = sorted({round(p.rect.width, 1) for p in doc})
    for w in widths:
        z = width / w
        if 0.3 < z < 8:
            return z
    return None


def locate(pdf_path, shot, box):
    """shot: PIL image of the screen region holding the viewer; box: (left, top, right, bottom) in shot pixels."""
    t0 = time.time()
    doc = fitz.open(str(pdf_path))
    gray = np.asarray(shot.convert("L"))
    l, t, r, b = [int(v) for v in box]
    crop = gray[t:b, l:r]
    if crop.shape[0] < 8 or crop.shape[1] < 8 or crop.std() < 3:
        return None
    z0 = _edge_zoom(gray, (l, t, r, b), doc)
    if z0:
        zooms = [z0 * (1 + d / 100) for d in range(-4, 5)]
    else:
        zooms, z = [], 0.4
        while z < 6:
            zooms.append(z)
            z *= 1.04
    best = (0.0, None, None, None)                 # score, page, zoom, (x, y) at RENDER_SCALE
    for pno in range(len(doc)):
        img = _page_gray(doc[pno], RENDER_SCALE)
        for z in zooms:
            f = RENDER_SCALE / z
            tw, th = int(crop.shape[1] * f), int(crop.shape[0] * f)
            if tw < 12 or th < 6 or tw >= img.shape[1] or th >= img.shape[0]:
                continue
            tmpl = cv2.resize(crop, (tw, th), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(img, tmpl, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(res)
            if score > best[0]:
                best = (score, pno, z, loc)
        if best[0] > 0.97:
            break
    score, pno, z, loc = best
    if pno is None or score < MIN_SCORE * 0.9:
        log.info("locate: no match (best %.2f) in %.2fs", score, time.time() - t0)
        return None
    # refine at the screen's own scale, around the coarse hit
    page = doc[pno]
    x0, y0 = loc[0] / RENDER_SCALE, loc[1] / RENDER_SCALE
    w_pt, h_pt = crop.shape[1] / z, crop.shape[0] / z
    pad = 20
    clip = fitz.Rect(x0 - pad, y0 - pad, x0 + w_pt + pad, y0 + h_pt + pad) & page.rect
    fine = None
    for zz in (z, z * 0.995, z * 1.005):
        img = _page_gray(page, zz, clip)
        if img.shape[0] <= crop.shape[0] or img.shape[1] <= crop.shape[1]:
            continue
        res = cv2.matchTemplate(img, crop, cv2.TM_CCOEFF_NORMED)
        _, sc, _, lc = cv2.minMaxLoc(res)
        if fine is None or sc > fine[0]:
            fine = (sc, zz, lc)
    if fine is None:
        return None
    score, z, loc = fine
    x = clip.x0 + loc[0] / z
    y = clip.y0 + loc[1] / z
    rect = fitz.Rect(x, y, x + crop.shape[1] / z, y + crop.shape[0] / z)
    log.info("locate: page %d zoom %.3f score %.3f in %.2fs", pno + 1, z, score, time.time() - t0)
    return Match(pno, rect, z, score) if score >= MIN_SCORE else None


# ---------------------------------------------------------------- formatted text (same rules as clip.js)
FAMILY_NAMES = {"Helvetica": "Arial", "TimesNewRoman": "Times New Roman", "Times": "Times New Roman",
                "CourierNew": "Courier New", "Courier": "Courier New", "ArialNarrow": "Arial Narrow",
                "SegoeUI": "Segoe UI", "CalibriLight": "Calibri Light", "CambriaMath": "Cambria Math"}


def _family(font):
    ps = re.sub(r"^[A-Z]{6}\+", "", font or "")
    fam = re.split(r"[-,]", ps)[0]
    fam = re.sub(r"(PSMT|PS|MT)$", "", fam)
    if re.match(r"^(CM|LM|SF)[A-Z]*\d*$", fam, re.I):
        fam = "Cambria Math" if re.match(r"^(CMMI|CMSY|CMEX)", fam, re.I) else "Times New Roman"
    return FAMILY_NAMES.get(fam) or re.sub(r"([a-z])([A-Z])", r"\1 \2", fam) or "Arial"


def _css_family(f):
    generic = "serif" if re.search(r"Times|Georgia|Cambria|Garamond|Roman|Serif|Book", f, re.I) else \
              "monospace" if re.search(r"Courier|Mono|Consol", f, re.I) else "sans-serif"
    return f"'{f}', {generic}"


def _style(span):
    suffix = re.sub(r"^[A-Z]{6}\+", "", span["font"])
    return {"family": _family(span["font"]), "size": round(span["size"] * 2) / 2, "color": "#%06x" % span["color"],
            "bold": bool(span["flags"] & 16) or bool(re.search(r"bold|black|heavy|semibold|demi", suffix, re.I)),
            "italic": bool(span["flags"] & 2) or bool(re.search(r"italic|oblique", suffix, re.I))}


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _span_html(run, base, full=False):
    st = []
    if full or run["family"] != base["family"]:
        st.append(f"font-family:{_css_family(run['family'])}")
    if full or run["size"] != base["size"]:
        st.append(f"font-size:{run['size']:g}pt")
    if full or run["color"] != base["color"]:
        st.append(f"color:{run['color']}")
    if run["bold"]:
        st.append("font-weight:bold")
    if run["italic"]:
        st.append("font-style:italic")
    return f'<span style="{";".join(st)}">{_esc(run["s"])}</span>' if st else _esc(run["s"])


def _merge(runs, run):
    keys = ("family", "size", "color", "bold", "italic")
    if runs and (all(runs[-1][k] == run[k] for k in keys) or not run["s"].strip()):
        runs[-1]["s"] += run["s"]
    else:
        runs.append(dict(run))


def _spacer(gap_pt):
    return f'<p style="margin:0;font-size:{max(1, round(gap_pt / 1.15))}pt">&nbsp;</p>' if gap_pt >= 2.5 else ""


def rich(page, rect):
    """Formatted HTML (OneNote's subset) + plain text for the part of `page` inside `rect`."""
    rect = fitz.Rect(rect)
    tables = []
    try:
        tables = [t for t in page.find_tables(clip=rect).tables if fitz.Rect(t.bbox).intersects(rect)]
    except Exception:
        log.debug("find_tables failed", exc_info=True)
    in_table = lambda bb: any(fitz.Rect(t.bbox).contains(fitz.Rect(bb).tl + (1, 1)) for t in tables)

    lines = []
    for blk in page.get_text("dict", clip=rect)["blocks"]:
        if blk["type"] != 0:
            continue
        for ln in blk["lines"]:
            if abs(ln["dir"][1]) > 0.1 or in_table(ln["bbox"]):
                continue
            spans = [s for s in ln["spans"] if s["text"]]
            if not "".join(s["text"] for s in spans).strip():
                continue
            runs = []
            for s in spans:
                _merge(runs, {"s": s["text"], **_style(s)})
            size = max(((r["size"], len(r["s"])) for r in runs if r["s"].strip()), key=lambda p: p[1])[0]
            lines.append({"bbox": fitz.Rect(ln["bbox"]), "runs": runs, "size": size,
                          "text": "".join(r["s"] for r in runs)})
    lines.sort(key=lambda l: (round(l["bbox"].y1), l["bbox"].x0))

    if not lines and not tables:
        return "", ""
    xs = [l["bbox"].x0 for l in lines] + [t.bbox[0] for t in tables]
    left = min(xs)
    right = max([l["bbox"].x1 for l in lines] + [t.bbox[2] for t in tables])
    width = max(1.0, right - left)

    def centred(l):
        lm, rm = l["bbox"].x0 - rect.x0, rect.x1 - l["bbox"].x1
        return l["bbox"].width < width * 0.85 and lm > l["size"] and abs(lm - rm) < max(l["size"] * 1.5, rect.width * 0.06)

    blocks = []
    for l in lines:
        p = blocks[-1] if blocks and blocks[-1]["kind"] == "para" else None
        prev = p["lines"][-1] if p else None
        joins = prev is not None and \
            l["bbox"].y1 - prev["bbox"].y1 < max(prev["size"], l["size"]) * 1.45 and \
            abs(prev["size"] - l["size"]) < 1 and \
            prev["bbox"].x1 > right - max(prev["size"] * 3, width * 0.12) and \
            abs(l["bbox"].x0 - p["lines"][0]["bbox"].x0) < prev["size"] * 2.5 and \
            centred(prev) == centred(l)
        if joins:
            last = p["runs"][-1]
            if re.search(r"[A-Za-z]-$", last["s"]) and re.match(r"[a-z]", l["text"]):
                last["s"] = last["s"][:-1]
            elif not last["s"].endswith(" "):
                p["runs"].append({**last, "s": " "})
            for r in l["runs"]:
                _merge(p["runs"], r)
            p["lines"].append(l)
        else:
            blocks.append({"kind": "para", "lines": [l], "runs": [dict(r) for r in l["runs"]],
                           "centred": centred(l), "top": l["bbox"].y0, "bottom": l["bbox"].y1})
        blocks[-1]["bottom"] = l["bbox"].y1
    for t in tables:
        blocks.append({"kind": "table", "table": t, "top": t.bbox[1], "bottom": t.bbox[3]})
    blocks.sort(key=lambda b: b["top"])

    all_runs = [r for b in blocks if b["kind"] == "para" for r in b["runs"] if r["s"].strip()]
    def common(key, default):
        tally = {}
        for r in all_runs:
            tally[r[key]] = tally.get(r[key], 0) + len(r["s"])
        return max(tally, key=tally.get) if tally else default
    base = {"family": common("family", "Arial"), "size": common("size", 11), "color": common("color", "#000000")}

    html, text = [], []
    for i, b in enumerate(blocks):
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        gap = (nxt["top"] - b["bottom"]) if nxt else 0
        if b["kind"] == "table":
            t = b["table"]
            rows_html, rows_text = [], []
            for row in t.rows:
                cells_html, cells_text = [], []
                for cell in row.cells:
                    if cell is None:
                        continue
                    cr = fitz.Rect(cell)
                    runs = []
                    for blk in page.get_text("dict", clip=cr)["blocks"]:
                        for ln in blk.get("lines", []):
                            if runs:
                                _merge(runs, {**runs[-1], "s": " "})
                            for s in ln["spans"]:
                                if s["text"]:
                                    _merge(runs, {"s": s["text"], **_style(s)})
                    w = round(cr.width * 4 / 3)
                    body = "".join(_span_html(r, base, full=True) for r in runs) or "&nbsp;"
                    cells_html.append(f'<td width="{w}" style="width:{w}px;vertical-align:top;padding:1pt 4pt">{body}</td>')
                    cells_text.append("".join(r["s"] for r in runs).strip())
                rows_html.append("<tr>" + "".join(cells_html) + "</tr>")
                rows_text.append("\t".join(cells_text))
            html.append(f'<table border="1" cellspacing="0" style="border-collapse:collapse;margin:0">{"".join(rows_html)}</table>')
            text.append("\n".join(rows_text))
        else:
            line_w = max(l["bbox"].width for l in b["lines"])
            if b["centred"]:
                pad = max(0.0, (rect.width - line_w) / 2 - (left - rect.x0))
                margin, align = f"margin:0 {pad:.0f}pt 0 {pad:.0f}pt", ";text-align:center"
            else:
                margin, align = f"margin:0 0pt 0 {b['lines'][0]['bbox'].x0 - left:.0f}pt", ""
            html.append(f'<p style="{margin}{align}">' + "".join(_span_html(r, base) for r in b["runs"]) + "</p>")
            text.append("".join(r["s"] for r in b["runs"]))
        if nxt:                                    # white space beyond normal line spacing -> an empty paragraph
            leading = b["lines"][-1]["size"] * 0.25 if b["kind"] == "para" else 0
            html.append(_spacer(min(gap - leading, 36)))
    wrapper = (f'<div style="width:{width + 2:.0f}pt;max-width:100%;font-family:{_css_family(base["family"])};'
               f'font-size:{base["size"]:g}pt;color:{base["color"]};line-height:1.15">')
    return wrapper + "".join(html) + "</div>", "\n".join(text)


# ---------------------------------------------------------------- clipboard
def _cf_html(fragment):
    pre, post = "<html><body><!--StartFragment-->", "<!--EndFragment--></body></html>"
    header = "Version:0.9\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\nStartFragment:{:010d}\r\nEndFragment:{:010d}\r\n"
    h0 = len(header.format(0, 0, 0, 0).encode())
    sf = h0 + len(pre.encode())
    ef = sf + len(fragment.encode("utf-8"))
    eh = ef + len(post.encode())
    return (header.format(h0, eh, sf, ef) + pre + fragment + post).encode("utf-8")


def set_clipboard(html=None, text=None, image=None):
    """Write all formats in one clipboard session (retrying while another app holds the clipboard)."""
    import win32clipboard as cb
    dib = png = None
    if image is not None:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, "BMP")
        dib = buf.getvalue()[14:]                   # CF_DIB = BMP without the file header
        buf = io.BytesIO()
        image.save(buf, "PNG")
        png = buf.getvalue()
    for attempt in range(20):
        try:
            cb.OpenClipboard()
            break
        except Exception:
            time.sleep(0.05)
    else:
        raise RuntimeError("the clipboard is busy")
    try:
        cb.EmptyClipboard()
        if html:
            cb.SetClipboardData(cb.RegisterClipboardFormat("HTML Format"), _cf_html(html))
        if text:
            cb.SetClipboardData(cb.CF_UNICODETEXT, text)
        if dib:
            cb.SetClipboardData(cb.CF_DIB, dib)
            cb.SetClipboardData(cb.RegisterClipboardFormat("PNG"), png)
    finally:
        cb.CloseClipboard()
