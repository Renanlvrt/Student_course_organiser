"""Step 7d: NotebookLM video overviews for the hard concepts (unofficial notebooklm-py CLI, the user's own Google
account; no Claude tokens). One notebook per lecture, sourced from the audited Master notes; one explainer
video per hard concept, focused on that concept only. Needs a one-time `notebooklm login`.
"""
import json
import re
import subprocess

MAX_PER_LECTURE = 2           # hard topics only; NotebookLM limits video overviews per day
STYLE = ("Clean, light, minimal diagrams on an off-white background; soft Apple-style colours (teal, orange, "
         "blue, red, green), never purple; large clear labels; maths written properly; calm pacing.")


def _nlm(*args, timeout=600):
    proc = subprocess.run(["notebooklm", *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def _json(text):
    m = re.search(r"\{.*\}|\[.*\]", text, re.S)
    return json.loads(m.group(0)) if m else {}


def _find_id(data):
    if isinstance(data, dict):
        for k in ("artifact_id", "id", "notebook_id"):
            if isinstance(data.get(k), str):
                return data[k]
        for v in data.values():
            got = _find_id(v)
            if got:
                return got
    if isinstance(data, list):
        for v in data:
            got = _find_id(v)
            if got:
                return got
    return None


def logged_in():
    """A real call: `auth check` can report valid cookies that Google has already signed out."""
    code, out, err = _nlm("list", "--json", timeout=120)
    return code == 0 and '"error": true' not in out


def nlm_videos(cfg, module, part, folder, runner_name=None, log=print):
    from .lecture import lecture_id, out_dir, _read_json, _write_json
    from .site import site_dir
    lid, od, stem = lecture_id(folder), out_dir(cfg, module, part, folder), folder.name
    state_path = od / f"{stem} - notebooklm.json"
    state = _read_json(state_path, {"notebook": None, "videos": []})
    topics_list = _read_json(od / f"{stem} - topics.json", [])
    hard = [t for t in topics_list if t.get("hard")][:MAX_PER_LECTURE]
    todo = [t for t in hard if t["id"] not in {v["concept"] for v in state["videos"]}]
    if not todo:
        return log(f"{lid} NotebookLM videos: {len(state['videos'])} (nothing to do)")
    if not logged_in():
        return log(f"{lid} NotebookLM videos skipped: run `notebooklm login` once, then re-run the step.")
    if not state["notebook"]:
        code, out, err = _nlm("create", f"{module.code} {stem}", "--json")
        state["notebook"] = _find_id(_json(out))
        if code or not state["notebook"]:
            return log(f"{lid} NotebookLM: could not create a notebook: {(err or out)[-300:]}")
        code, out, err = _nlm("source", "add", str(od / f"{stem} - Master.md"), "-n", state["notebook"],
                              "--type", "file", "--title", f"{stem} (audited notes)")
        if code:
            return log(f"{lid} NotebookLM: could not add the notes: {(err or out)[-300:]}")
        _nlm("source", "wait", "-n", state["notebook"], timeout=900)
        _write_json(state_path, state)
    names = {t["id"]: t["title"] for t in topics_list}
    concept_names = {c["id"]: c["name"] for c in _read_json(od / f"{stem} - concepts.json", [])}
    out_dir_site = site_dir(cfg, module, part) / "videos"
    out_dir_site.mkdir(parents=True, exist_ok=True)
    for t in todo:
        name = names.get(t["id"], t["id"])
        covers = ", ".join(concept_names.get(c, c) for c in t.get("concepts", []))
        brief = (f"Explain ONLY the topic '{name}' (covering: {covers}) from these lecture notes, for a university "
                 f"student revising for the {module.name} exam who has never understood it. Start from the intuition "
                 f"({t.get('why', '')}), "
                 "then build the formal idea step by step with a worked example, using exactly the course's "
                 "notation and definitions. End with the common mistakes and how it is examined. Stay faithful to "
                 "the notes; do not add material they do not contain.")
        code, out, err = _nlm("generate", "video", brief, "-n", state["notebook"], "--format", "explainer",
                              "--style", "custom", "--style-prompt", STYLE, "--wait", "--json", timeout=2400)
        art = _find_id(_json(out))
        if code or not art:
            log(f"{lid} NotebookLM video for {t['id']} failed: {(err or out)[-300:]}")
            if "limit" in (err + out).lower() or "quota" in (err + out).lower():
                break
            continue
        fname = "nlm_" + re.sub(r"[^A-Za-z0-9]+", "_", t["id"]) + ".mp4"
        code, out, err = _nlm("download", "video", str(out_dir_site / fname), "-n", state["notebook"], "-a", art,
                              "--force", timeout=900)
        if code:
            log(f"{lid} NotebookLM download for {t['id']} failed: {(err or out)[-300:]}")
            continue
        state["videos"].append({"concept": t["id"], "title": f"NotebookLM explainer: {name}", "file": "videos/" + fname,
                                "kind": "notebooklm"})
        _write_json(state_path, state)
        log(f"{lid} NotebookLM video: {t['id']}")
    log(f"{lid} NotebookLM videos: {len(state['videos'])}")
