"""Build Website/<Part>/ : copy the shell (study/site_template) and turn the pipeline's JSON into data/*.js globals.

Visuals (visuals/LNN.js) are written per lecture by step 7 and are never overwritten here.
"""
import json
import shutil
from pathlib import Path

from .convert import MD_DIR
from .lecture import lecture_folders, lecture_id, out_dir, part_dir, _read_json

TEMPLATE = Path(__file__).resolve().parent / "site_template"


def site_dir(cfg, module, part):
    return cfg.root_folder / module.key / "Website" / part


def _js(var_path, data):
    return f"{var_path} = {json.dumps(data, ensure_ascii=False)};\n"


def build_site(cfg, module, part, log=print):
    site = site_dir(cfg, module, part)
    for item in TEMPLATE.iterdir():                       # shell files are ours: always refresh them
        dst = site / item.name
        if item.is_dir():
            shutil.copytree(item, dst, dirs_exist_ok=True)
        else:
            site.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst)
    (site / "data").mkdir(exist_ok=True)
    (site / "visuals").mkdir(exist_ok=True)
    lectures = []
    for folder in lecture_folders(cfg, module, part):
        lid, od, stem = lecture_id(folder), out_dir(cfg, module, part, folder), folder.name
        concepts = _read_json(od / f"{stem} - concepts.json", None)
        lectures.append({"id": lid, "title": stem, "concepts": [c["id"] for c in concepts or []]})
        if concepts is None:
            continue
        plan = _read_json(od / f"{stem} - plan.json", [])
        data = {"id": lid, "title": stem, "concepts": concepts,
                "teaching": _read_json(od / f"{stem} - teaching.json", []),
                "exercises": _read_json(od / f"{stem} - exercises.json", []),
                "videos": _read_json(od / f"{stem} - videos.json", []) +
                          _read_json(od / f"{stem} - notebooklm.json", {}).get("videos", []),
                "plan": plan.get("concepts", plan) if isinstance(plan, dict) else plan,
                "master": (od / f"{stem} - Master.md").read_text(encoding="utf-8") if (od / f"{stem} - Master.md").exists() else ""}
        (site / "data" / f"{lid}.js").write_text(
            "window.LECTURES = window.LECTURES || {};\n" + _js(f'window.LECTURES["{lid}"]', data), encoding="utf-8")
        log(f"{lid}: {len(concepts)} concepts, {len(data['teaching'])} taught, {len(data['exercises'])} exercises")
    course = {"key": module.key, "module": module.name, "code": module.code, "part": part, "lectures": lectures}
    (site / "data" / "course.js").write_text(_js("window.COURSE", course), encoding="utf-8")
    reg = _read_json(part_dir(cfg, module, part) / MD_DIR / "registry.json", {"concepts": []})
    (site / "data" / "registry.js").write_text(
        _js("window.REGISTRY", {c["id"]: c for c in reg.get("concepts", []) if isinstance(c, dict) and "id" in c}), encoding="utf-8")
    mocks = _read_json(part_dir(cfg, module, part) / MD_DIR / "mocks.json", [])
    (site / "data" / "mocks.js").write_text(_js("window.MOCKS", mocks), encoding="utf-8")
    log(f"site: {site / 'index.html'}")
    return site
