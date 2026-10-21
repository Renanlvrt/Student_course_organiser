"""Publish a module's revision sites to its own GitHub repo with GitHub Pages, so they open on a phone.

The repo can be private, but a Pages site is reachable by anyone who has the link (unlisted, not indexed:
noindex meta + robots.txt). Repos per module are listed in study/repos.json.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .site import site_dir

REPOS = Path(__file__).resolve().parent / "repos.json"


class PublishError(RuntimeError):
    pass


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _git(repo_dir, *args, check=True):
    proc = subprocess.run(["git", *args], cwd=repo_dir, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and proc.returncode:
        raise PublishError(f"git {' '.join(args)} failed: {proc.stderr.strip()[-500:]}")
    return proc.stdout.strip()


def _gh(*args, check=True):
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and proc.returncode:
        raise PublishError(f"gh {' '.join(args[:3])} failed: {proc.stderr.strip()[-500:]}")
    return proc


def _index(module, parts):
    links = "\n".join(f'    <li><a href="{slug(p)}/index.html">{p}</a></li>' for p in parts)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{module.name} revision</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap">
<link rel="stylesheet" href="{slug(parts[0])}/css/site.css">
</head>
<body>
<main class="read" style="margin: 0 auto">
  <h1>{module.name}</h1>
  <p class="lede">{module.code}. Pick a part.</p>
  <ol class="map ui">
{links}
  </ol>
</main>
</body>
</html>
"""


def _readme(module, url, parts):
    rows = "\n".join(f"- [{p}]({url}{slug(p)}/index.html)" for p in parts)
    return f"""# {module.name} ({module.code}) revision site

**Open on any device: {url}**

{rows}

Built by the Download Organiser study pipeline (`python -m study publish {module.key}`). Progress and spaced
repetition are stored in each browser, so phone and laptop keep separate progress (use Progress → export/import
on the practice page to move it).

The link is unlisted (noindex, robots.txt) but not password-protected: anyone who has it can open the site.
"""


def publish(cfg, module, log=print):
    repos = json.loads(REPOS.read_text(encoding="utf-8"))
    repo = repos.get(module.key)
    if not repo:
        raise PublishError(f"No repo for {module.key} in {REPOS}")
    owner, name = repo.split("/")
    url = f"https://{owner.lower()}.github.io/{name}/"
    parts = [p for p in module.parts if (site_dir(cfg, module, p) / "index.html").exists()]
    if not parts:
        raise PublishError("No built site yet: run `python -m study site <module> <part>` first.")

    work = cfg.data_dir / "study" / "publish" / module.key
    if not (work / ".git").exists():
        work.parent.mkdir(parents=True, exist_ok=True)
        _gh("repo", "clone", repo, str(work))
    _git(work, "checkout", "-B", "main")
    for item in work.iterdir():                           # the repo holds only generated output: rebuild it
        if item.name != ".git":
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    for p in parts:
        shutil.copytree(site_dir(cfg, module, p), work / slug(p))
    (work / "index.html").write_text(_index(module, parts), encoding="utf-8")
    (work / "README.md").write_text(_readme(module, url, parts), encoding="utf-8")
    (work / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (work / ".nojekyll").write_text("", encoding="utf-8")

    _git(work, "add", "-A")
    key = os.environ.get("GEMINI_API_KEY")
    if key and _git(work, "grep", "--cached", "-l", "-F", key, check=False):
        raise PublishError("A secret (GEMINI_API_KEY) is in the staged files; nothing was pushed.")
    if not _git(work, "status", "--porcelain"):
        log("No changes to publish.")
    else:
        _git(work, "commit", "-m", f"Publish {module.name} revision site ({', '.join(parts)})")
        _git(work, "push", "-u", "origin", "main")
        log(f"Pushed to {repo}.")
    if _gh("api", f"repos/{repo}/pages", check=False).returncode:
        r = _gh("api", "-X", "POST", f"repos/{repo}/pages", "-f", "source[branch]=main", "-f", "source[path]=/", check=False)
        if r.returncode:
            raise PublishError(f"Pushed, but GitHub refused to turn on Pages: {r.stderr.strip()[-300:]} "
                               "(Pages on a private repo needs GitHub Pro / the Student Developer Pack.)")
        log("GitHub Pages turned on (first build takes a minute or two).")
    log(f"Site: {url}")
    return url
