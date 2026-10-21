"""Step 1: rewrite flagged pages from their page image (vision model). Resumable: progress is saved after
every batch in manifest.json (fixed_pages). Pages whose text is identical to an already-fixed page (the
per-lecture notes extracts are cut from the full notes) reuse that fix instead of a new model call."""
import hashlib
import json
import re
from pathlib import Path

import fitz

from . import runner
from .convert import MD_DIR

BATCH = 4
PAGE_RE = re.compile(r"\n<!-- page (\d+) -->\n")


def split_pages(md):
    """{page: text} plus the header before page 1."""
    parts = PAGE_RE.split(md)
    head, pages = parts[0], {}
    for i in range(1, len(parts), 2):
        pages[int(parts[i])] = parts[i + 1]
    return head, pages


def join_pages(head, pages):
    return head + "".join(f"\n<!-- page {n} -->\n{pages[n].strip()}\n" for n in sorted(pages))


def _text_key(page):
    return hashlib.sha256(" ".join(page.get_text().split()).encode()).hexdigest()


def md_dirs(cfg, module):
    base = cfg.root_folder / module.key / "Lectures"
    dirs = [base / MD_DIR] + [base / p / MD_DIR for p in module.parts]
    return [d for d in dirs if (d / "manifest.json").exists()]


def fix_module(cfg, module, runner_name="claude", model="sonnet", limit=None, log=print):
    cache_path = cfg.data_dir / "study" / module.key / "fixed_pages_cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    calls = 0
    for md_dir in md_dirs(cfg, module):                     # module-level notes first: extracts reuse them
        man_path = md_dir / "manifest.json"
        manifest = json.loads(man_path.read_text(encoding="utf-8"))
        part = md_dir.parent.name if md_dir.parent.name != "Lectures" else "whole module"
        for stem, entry in manifest.items():
            todo = [int(p) for p in entry["flagged"] if int(p) not in entry["fixed_pages"]]
            if not todo:
                continue
            pdf = fitz.open(cfg.root_folder / module.key / entry["pdf"])
            md_path = md_dir / f"{stem}.md"
            head, pages = split_pages(md_path.read_text(encoding="utf-8"))
            keys = {n: _text_key(pdf[n - 1]) for n in todo}
            for n in [n for n in todo if keys[n] in cache]:  # identical page already fixed elsewhere
                pages[n] = cache[keys[n]]
                entry["fixed_pages"].append(n)
            todo = [n for n in todo if n not in entry["fixed_pages"]]
            for i in range(0, len(todo), BATCH):
                if limit is not None and calls >= limit:
                    break
                batch = todo[i:i + BATCH]
                img = Path(entry["page_images"])
                listing = "\n\n".join(
                    f"### Page {n}\nImage: `{img / f'page-{n:03d}.png'}`\nCurrent markdown:\n````markdown\n"
                    f"{pages.get(n, '').strip()}\n````" for n in batch)
                prompt = runner.build_prompt(
                    "01_fix_pages.md", MODULE_NAME=module.name, MODULE_CODE=module.code, PART=part,
                    PDF_NAME=Path(entry["pdf"]).name,
                    FLAGGED_PAGES="; ".join(f"{n}: {', '.join(entry['flagged'][str(n)])}" for n in batch),
                    PAGES=listing)
                text, usage = runner.run(cfg, prompt, runner=runner_name, model=model, add_dirs=[img])
                calls += 1
                fixed = runner.extract_json(text)
                for n in batch:
                    new = fixed.get(str(n))
                    if not new or new.startswith("NEEDS HUMAN"):
                        log(f"  page {n}: {new or 'missing from reply'}")
                        continue
                    pages[n] = new
                    cache[keys[n]] = new
                    entry["fixed_pages"].append(n)
                    entry.setdefault("fixed_by", {})[str(n)] = f"{runner_name}:{usage.get('model', model)}"
                md_path.write_text(join_pages(head, pages), encoding="utf-8")
                man_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
                cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                log(f"fixed {stem} pages {batch} ({runner.describe(usage)})")
            md_path.write_text(join_pages(head, pages), encoding="utf-8")
            man_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return calls
