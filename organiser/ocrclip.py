"""Alt+L in any desktop app: editable, formatted text from a screenshot box, via the Windows OCR engine.

    screen_rich(image, dpi_scale) -> (html, text)

Words and their boxes come from Windows.Media.Ocr; they are grouped into lines and paragraphs with the same rules
as the PDF path (wrapped lines joined, gaps -> spacer paragraphs, indents and centring as margins), sizes come from
the line heights, colours from the glyph pixels (light text from dark themes becomes dark text), and ruled tables
from the ruling lines (OpenCV morphology) with every word placed in its cell. Output uses the HTML subset OneNote
keeps (see pdfclip / clip.js).
"""
import asyncio
import io
import logging
import re

import cv2
import numpy as np
from PIL import Image

log = logging.getLogger("organiser.ocrclip")


# ---------------------------------------------------------------- OCR
async def _recognize(png_bytes):
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png_bytes)
    await writer.store_async()
    await writer.flush_async()
    writer.detach_stream()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError("Windows OCR isn't available (install a language with text recognition)")
    result = await engine.recognize_async(bitmap)
    lines = []
    for ln in result.lines:
        words = [{"text": w.text, "x": w.bounding_rect.x, "y": w.bounding_rect.y,
                  "w": w.bounding_rect.width, "h": w.bounding_rect.height} for w in ln.words]
        if words:
            lines.append(words)
    return lines


def ocr_words(image):
    """[[word, ...] per OCR line] in the image's pixel coordinates. Small text is upscaled first for accuracy."""
    scale = 2 if image.height < 1600 else 1
    img = image.convert("RGB")
    if scale != 1:
        img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    lines = asyncio.run(_recognize(buf.getvalue()))
    for ln in lines:
        for w in ln:
            for k in ("x", "y", "w", "h"):
                w[k] /= scale
    return lines


# ---------------------------------------------------------------- tables from ruling lines
def grids(gray, with_mask=False):
    """Ruled tables: [(row y boundaries, column x boundaries)] in pixels (and the ruling-line mask)."""
    h, w = gray.shape
    binv = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 8)
    horiz = cv2.morphologyEx(binv, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, w // 12), 1)))
    vert = cv2.morphologyEx(binv, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 25))))
    joints = cv2.bitwise_or(horiz, vert)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(joints, np.ones((3, 3), np.uint8)))
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if bw < 60 or bh < 30:
            continue
        sub_h, sub_v = horiz[y:y + bh, x:x + bw], vert[y:y + bh, x:x + bw]
        rows = _positions(sub_h.sum(axis=1) > bw * 255 * 0.5) + y
        cols = _positions(sub_v.sum(axis=0) > bh * 255 * 0.5) + x
        if len(rows) >= 2 and len(cols) >= 2:
            out.append((rows, cols))
    return (out, joints) if with_mask else out


def _positions(mask):
    """Centres of runs of True (one ruling line may be several pixels thick)."""
    idx = np.flatnonzero(mask)
    if not len(idx):
        return np.array([], dtype=float)
    runs = np.split(idx, np.flatnonzero(np.diff(idx) > 2) + 1)
    return np.array([r.mean() for r in runs])


# ---------------------------------------------------------------- colours
def _glyph_colour(rgb, x0, y0, x1, y1):
    """Text colour inside a box: the background is the most common colour, the text the pixels furthest from it."""
    patch = rgb[max(0, int(y0)):int(y1) + 1, max(0, int(x0)):int(x1) + 1].reshape(-1, 3).astype(int)
    if not len(patch):
        return (0, 0, 0), (255, 255, 255)
    q = (patch >> 4)
    keys = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
    bg_key = np.bincount(keys).argmax()
    bg = np.array([(bg_key >> 8) * 16 + 8, ((bg_key >> 4) & 15) * 16 + 8, (bg_key & 15) * 16 + 8])
    dist = np.abs(patch - bg).sum(axis=1)
    if dist.max() < 60:
        return (0, 0, 0), tuple(bg)
    fg = patch[dist >= dist.max() * 0.75].mean(axis=0)
    return tuple(int(v) for v in fg), tuple(int(v) for v in bg)


def _lum(c):
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255


def readable(fg, bg):
    """Hex colour for pasting on a white page: light text from a dark theme becomes its dark equivalent."""
    if _lum(fg) > 0.6 and _lum(bg) < 0.5:
        r, g, b = fg
        spread = max(fg) - min(fg)
        if spread < 40:                            # grey/white text -> black
            return "#000000"
        k = 0.45 / max(_lum(fg), 0.01)            # coloured (links...) -> same hue, darker
        fg = tuple(int(min(255, v * k * 0.6)) for v in fg)
    if max(fg) < 70 and max(fg) - min(fg) < 30:
        return "#000000"
    return "#%02x%02x%02x" % fg


# ---------------------------------------------------------------- formatted text
def join_words(words):
    """Words of one line, with a space only where there is a real gap (OCR sometimes splits "128" into "1 28")."""
    out, prev = "", None
    for w in words:
        if prev is not None:
            gap = w["x"] - (prev["x"] + prev["w"])
            same_line = abs(w["y"] - prev["y"]) < max(w["h"], prev["h"]) * 0.5
            tight = min(w["h"], prev["h"]) * (0.4 if prev["text"][-1:].isdigit() and w["text"][:1].isdigit() else 0.18)
            out += "" if same_line and gap < tight else " "     # digits split by OCR ("1 28") are rejoined
        out += w["text"]
        prev = w
    return out


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def screen_rich(image, dpi_scale=1.0):
    """Formatted HTML (OneNote's subset) + plain text for a screenshot box."""
    rgb = np.asarray(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    found, mask = grids(gray, with_mask=True)
    clean = rgb.copy()                             # ruling lines erased: letters touching them (g, p, y) read better
    if found:
        bg = np.median(rgb.reshape(-1, 3), axis=0).astype(np.uint8)
        lines_mask = cv2.dilate(mask, np.ones((3, 3), np.uint8)) > 0
        inside = np.zeros_like(lines_mask)
        for rows, cols in found:                  # only inside tables: bold letters elsewhere have line-like strokes
            inside[int(rows[0]) - 3:int(rows[-1]) + 4, int(cols[0]) - 3:int(cols[-1]) + 4] = True
        clean[lines_mask & inside] = bg
    ocr = ocr_words(Image.fromarray(clean))
    if not ocr:
        return "", ""
    px_to_pt = 0.75 / dpi_scale                    # physical px -> pt
    lines = []
    for li, words in enumerate(ocr):
        for wi, w in enumerate(words):
            w["order"] = (li, wi)
        x0 = min(w["x"] for w in words); y0 = min(w["y"] for w in words)
        x1 = max(w["x"] + w["w"] for w in words); y1 = max(w["y"] + w["h"] for w in words)
        fg, bg = _glyph_colour(rgb, x0, y0, x1, y1)
        hts = sorted(w["h"] for w in words)
        lines.append({"words": words, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "h": hts[len(hts) // 2],
                      "colour": readable(fg, bg), "text": " ".join(w["text"] for w in words)})
    lines.sort(key=lambda l: (l["y0"], l["x0"]))

    # tables: words inside a ruled grid go to their cells
    tables = []
    for rows, cols in found:
        cells = [[[] for _ in range(len(cols) - 1)] for _ in range(len(rows) - 1)]
        used = False
        for ln in lines:
            for w in ln["words"]:
                cx, cy = w["x"] + w["w"] / 2, w["y"] + w["h"] / 2
                r = next((k for k in range(len(rows) - 1) if rows[k] <= cy <= rows[k + 1]), None)
                c = next((k for k in range(len(cols) - 1) if cols[k] <= cx <= cols[k + 1]), None)
                if r is None or c is None:
                    continue
                cells[r][c].append((w, ln["colour"], ln["h"]))
                w["in_table"] = used = True
        if used:
            tables.append({"kind": "table", "top": rows[0], "bottom": rows[-1], "rows": rows, "cols": cols, "cells": cells})
    for ln in lines:
        ln["words"] = [w for w in ln["words"] if not w.get("in_table")]
        ln["text"] = " ".join(w["text"] for w in ln["words"])
    lines = [ln for ln in lines if ln["words"]]
    for ln in lines:
        ln["x0"] = min(w["x"] for w in ln["words"]); ln["x1"] = max(w["x"] + w["w"] for w in ln["words"])

    left = min([ln["x0"] for ln in lines] + [t["cols"][0] for t in tables])
    right = max([ln["x1"] for ln in lines] + [t["cols"][-1] for t in tables])
    width = max(1.0, right - left)
    box_w = image.width

    def centred(l):
        lm, rm = l["x0"], box_w - l["x1"]
        return (l["x1"] - l["x0"]) < width * 0.85 and lm > l["h"] and abs(lm - rm) < max(l["h"] * 1.5, box_w * 0.06)

    blocks = []
    for ln in lines:
        b = blocks[-1] if blocks and blocks[-1]["kind"] == "para" else None
        prev = b["lines"][-1] if b else None
        joins = prev is not None and \
            ln["y0"] - prev["y1"] < max(prev["h"], ln["h"]) * 0.8 and \
            abs(prev["h"] - ln["h"]) < max(2, prev["h"] * 0.2) and \
            prev["x1"] > right - max(prev["h"] * 3, width * 0.12) and \
            abs(ln["x0"] - b["lines"][0]["x0"]) < prev["h"] * 2 and \
            centred(prev) == centred(ln) and prev["colour"] == ln["colour"]
        if joins:
            b["lines"].append(ln)
            b["bottom"] = ln["y1"]
        else:
            blocks.append({"kind": "para", "lines": [ln], "top": ln["y0"], "bottom": ln["y1"], "centred": centred(ln)})
    blocks += tables
    blocks.sort(key=lambda b: b["top"])

    sizes = [round(l["h"] * px_to_pt / 0.72 * 2) / 2 for b in blocks if b["kind"] == "para" for l in b["lines"]]
    base_size = max(set(sizes), key=sizes.count) if sizes else 11
    html, text = [], []
    for i, b in enumerate(blocks):
        if b["kind"] == "table":
            rows_html, rows_text = [], []
            for r, row in enumerate(b["cells"]):
                tds, tts = [], []
                for c, cell in enumerate(row):
                    cell.sort(key=lambda t: t[0]["order"])     # OCR reading order
                    words = join_words([t[0] for t in cell])
                    size = round((cell[0][2] if cell else 12) * px_to_pt / 0.72 * 2) / 2
                    colour = cell[0][1] if cell else "#000000"
                    wpx = round((b["cols"][c + 1] - b["cols"][c]) / dpi_scale)
                    tds.append(f'<td width="{wpx}" style="width:{wpx}px;vertical-align:top;font-family:Calibri;'
                               f'font-size:{size:g}pt;color:{colour}">{_esc(words) or "&nbsp;"}</td>')
                    tts.append(words)
                if any(tts):
                    rows_html.append("<tr>" + "".join(tds) + "</tr>")
                    rows_text.append("\t".join(tts))
            html.append(f'<table border="1" cellspacing="0" style="border-collapse:collapse">{"".join(rows_html)}</table>')
            text.append("\n".join(rows_text))
        else:
            lines_text = " ".join(join_words(ln["words"]) for ln in b["lines"])
            joined = re.sub(r"(\w)- (\w)", r"\1\2", lines_text)   # re-join hyphenated line breaks
            size = round(b["lines"][0]["h"] * px_to_pt / 0.72 * 2) / 2
            style = [f"font-size:{size:g}pt", f"color:{b['lines'][0]['colour']}"]
            if b["centred"]:
                line_w = max(l["x1"] - l["x0"] for l in b["lines"])
                pad = max(0.0, (box_w - line_w) / 2) * px_to_pt
                margin = f"margin:0 {pad:.0f}pt 0 {pad:.0f}pt;text-align:center"
            else:
                margin = f"margin:0 0pt 0 {(b['lines'][0]['x0'] - left) * px_to_pt:.0f}pt"
            html.append(f'<p style="{margin}"><span style="{";".join(style)}">{_esc(joined)}</span></p>')
            text.append(joined)
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if nxt:
            gap_pt = (nxt["top"] - b["bottom"]) * px_to_pt - 3
            if gap_pt >= 2.5:
                html.append(f'<p style="margin:0;font-size:{max(1, round(min(gap_pt, 36) / 1.15))}pt">&nbsp;</p>')
    wrapper = f'<div style="font-family:Calibri,Arial,sans-serif;font-size:{base_size:g}pt">'
    return wrapper + "".join(html) + "</div>", "\n".join(text)
