"""Jupyter notebooks: resolve Colab/GitHub links to the real .ipynb, find notebook links inside
slide PDFs, download them, and print a PDF copy of each notebook (like File > Print > PDF)."""
import base64
import html
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests

log = logging.getLogger("organiser.notebooks")

BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]


def raw_url(url):
    """Colab / GitHub notebook link -> downloadable raw .ipynb URL, or None (e.g. Colab Drive links)."""
    url = (url or "").strip()
    m = re.match(r"https?://colab\.research\.google\.com/gist/([^/]+)/([0-9a-f]+)/([^?#]+\.ipynb)", url)
    if m:
        return f"https://gist.githubusercontent.com/{m.group(1)}/{m.group(2)}/raw/{m.group(3)}"
    m = re.match(r"https?://colab\.research\.google\.com/github/([^/]+)/([^/]+)/blob/([^?#]+\.ipynb)", url)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/(?:blob|raw)/([^?#]+\.ipynb)", url)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"
    m = re.match(r"https?://gist\.github\.com/([^/]+)/([0-9a-f]+)", url)
    if m:
        return f"https://gist.githubusercontent.com/{m.group(1)}/{m.group(2)}/raw"
    if re.match(r"https?://(raw\.githubusercontent\.com|gist\.githubusercontent\.com)/.+\.ipynb", url):
        return url
    return None


def links_in_pdf(path):
    """Notebook links (deduplicated, raw URLs) found in a PDF's link annotations."""
    import fitz
    out = []
    try:
        with fitz.open(path) as doc:
            for page in doc:
                for l in page.get_links():
                    r = raw_url(l.get("uri"))
                    if r and r not in out:
                        out.append(r)
    except Exception as e:
        log.warning("could not read links from %s: %s", path, e)
    return out


def is_notebook(path):
    try:
        with open(path, "rb") as f:
            head = f.read(2048).lstrip()
        return head.startswith(b"{") and b'"cells"' in Path(path).read_bytes()[:20_000_000]
    except OSError:
        return False


def fetch(url, dest_dir, name=None, timeout=40):
    """Download url into dest_dir (never overwrites). Returns the path or raises."""
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 organiser"})
    r.raise_for_status()
    if not name:
        cd = r.headers.get("content-disposition", "")
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', cd)
        name = m.group(1) if m else (url.rstrip("/").split("/")[-1].split("?")[0] or "download")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)[:180]
    dest = Path(dest_dir) / name
    i = 2
    while dest.exists():
        dest = Path(dest_dir) / f"{Path(name).stem} ({i}){Path(name).suffix}"
        i += 1
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(r.content)
    os.replace(tmp, dest)
    return dest


# ---------------------------------------------------------------- notebook -> PDF
def _md(text):
    """Small Markdown subset: headings, bold/italic, inline code, links, lists, paragraphs."""
    out, in_list = [], False
    text = re.sub(r"<[^>]+>", "", text)          # raw HTML such as the "Open in Colab" badge
    for line in text.splitlines():
        s = html.escape(line)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        if m:
            out.append(f"<h{len(m.group(1))}>{m.group(2)}</h{len(m.group(1))}>")
            continue
        if re.match(r"^\s*[-*+]\s+", s):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>" + re.sub(r"^\s*[-*+]\s+", "", s) + "</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p>{s}</p>" if s.strip() else "")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _code(src):
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import PythonLexer
        return highlight(src, PythonLexer(), HtmlFormatter(nowrap=True))
    except Exception:
        return html.escape(src)


def notebook_html(nb, title):
    parts = []
    for cell in nb.get("cells", []):
        src = cell.get("source", "")
        src = "".join(src) if isinstance(src, list) else str(src)
        if cell.get("cell_type") == "markdown":
            parts.append(f'<div class="md">{_md(src)}</div>')
        elif cell.get("cell_type") == "code":
            parts.append(f'<pre class="code">{_code(src)}</pre>')
            for o in cell.get("outputs", []):
                data = o.get("data", {})
                if "image/png" in data:
                    img = data["image/png"]
                    img = "".join(img) if isinstance(img, list) else img
                    parts.append(f'<img src="data:image/png;base64,{img.strip()}">')
                elif "text/plain" in data or o.get("text"):
                    t = data.get("text/plain") or o.get("text")
                    t = "".join(t) if isinstance(t, list) else str(t)
                    parts.append(f'<pre class="out">{html.escape(t[:20000])}</pre>')
    try:
        from pygments.formatters import HtmlFormatter
        css = HtmlFormatter().get_style_defs("pre.code")
    except Exception:
        css = ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title><style>
body {{ font: 11pt "Segoe UI", sans-serif; margin: 28px; color: #222; }}
h1,h2,h3 {{ margin: 14px 0 6px; }}
pre.code {{ background: #f5f6f8; border-left: 3px solid #5b8cff; padding: 8px 10px; white-space: pre-wrap; font: 9pt Consolas, monospace; }}
pre.out {{ padding: 4px 10px; white-space: pre-wrap; font: 9pt Consolas, monospace; color: #444; }}
img {{ max-width: 100%; }} code {{ background: #f0f0f0; padding: 0 3px; }}
{css}
</style></head><body><h1>{html.escape(title)}</h1>{''.join(parts)}</body></html>"""


def browser():
    return next((b for b in BROWSERS if os.path.exists(b)), None)


def to_pdf(ipynb_path):
    """Print a PDF next to the notebook ('<name>.pdf'). Returns the PDF path or None."""
    ipynb_path = Path(ipynb_path)
    exe = browser()
    if not exe:
        log.warning("no Chrome/Edge found for notebook PDF")
        return None
    try:
        nb = json.loads(ipynb_path.read_text(encoding="utf-8", errors="ignore"))
    except ValueError:
        return None
    pdf = ipynb_path.with_suffix(".pdf")
    i = 2
    while pdf.exists():
        pdf = ipynb_path.with_name(f"{ipynb_path.stem} ({i}).pdf")
        i += 1
    tmpdir = Path(tempfile.mkdtemp(prefix="nbpdf-"))
    try:
        page = tmpdir / "nb.html"
        page.write_text(notebook_html(nb, ipynb_path.stem), encoding="utf-8")
        out = tmpdir / "nb.pdf"
        subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--user-data-dir={tmpdir / 'profile'}", f"--print-to-pdf={out}", page.as_uri()],
                       timeout=90, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.exists() and out.stat().st_size > 0:
            shutil.move(str(out), str(pdf))
            return pdf
    except Exception as e:
        log.warning("notebook PDF failed for %s: %s", ipynb_path, e)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return None
