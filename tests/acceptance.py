"""End-to-end acceptance tests against temporary folders (never the real Downloads/courses).

    python -m tests.acceptance [workdir]

Uses the real Gemini key if available (Auto-mode test needs it).
"""
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from organiser import ai  # noqa: E402
from organiser.config import load_config  # noqa: E402
from organiser.core import Organiser  # noqa: E402
from organiser.server import make_server  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def make_pdf(path, title, body):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((60, 90), title, fontsize=26)
    y = 150
    for line in body.split("\n"):
        page.insert_text((60, y), line, fontsize=11)
        y += 18
    doc.save(str(path))
    doc.close()


def download(downloads, name, writer):
    """Simulate Chrome: write <name>.crdownload, then rename to the final name."""
    tmp = downloads / (name + ".crdownload")
    writer(tmp)
    time.sleep(0.3)
    os.replace(tmp, downloads / name)
    return downloads / name


def wait_for(pred, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        r = pred()
        if r:
            return r
        time.sleep(0.3)
    return None


def latest(core, name):
    for e in reversed(core.log.entries):
        if e.get("original_name") == name:
            return e
    return None


def rel(cfg, p):
    try:
        return Path(p).relative_to(cfg.root_folder).as_posix()
    except ValueError:
        return str(p)


def main(work=None):
    work = Path(work or tempfile.mkdtemp(prefix="organiser-accept-"))
    if work.exists():
        shutil.rmtree(work)
    downloads, root, data = work / "Downloads", work / "courses", work / "data"
    for d in (downloads, root, data):
        d.mkdir(parents=True)
    cfg_raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cfg_raw.update(downloads_folder=str(downloads), root_folder=str(root), port=47899)
    cfg_path = work / "config.json"
    cfg_path.write_text(json.dumps(cfg_raw), encoding="utf-8")
    os.environ["ORGANISER_DATA"] = str(data)
    cfg = load_config(cfg_path)
    core = Organiser(cfg)
    core.start()
    make_server(core, cfg.port)
    print(f"workdir: {work}   AI available: {ai.available()}")

    # 1 ------------------------------------------------------------------
    core.activate("Crypto", None)
    name1 = "week2.pdf"
    download(downloads, name1, lambda p: make_pdf(p, "Block Ciphers and AES",
             "Lecture 2\nSymmetric cryptography: block ciphers, the AES round structure,\nFeistel networks and DES."))
    e = wait_for(lambda: latest(core, name1))
    dest = rel(cfg, e["current_path"]) if e else ""
    check("1 manual module -> Crypto/Symmetric/Lectures/Lecture NN - Topic.pdf",
          e and e["status"] == "sorted" and dest.startswith("Crypto/Lectures/Symmetric Cryptography/Lecture 02 - "),
          dest)

    # 2 ------------------------------------------------------------------
    core.deactivate()
    name2 = "after_off.pdf"
    download(downloads, name2, lambda p: make_pdf(p, "Lecture 3", "Stream ciphers"))
    time.sleep(6)
    check("2 after Alt+O off nothing is moved", (downloads / name2).exists() and not latest(core, name2))

    # 3 ------------------------------------------------------------------
    core.activate(None, None)
    name3 = "slides-4.pdf"
    download(downloads, name3, lambda p: make_pdf(p, "Markov Decision Processes",
             "Lecture 4\nStates, actions, transition probabilities, rewards.\nBellman equations, value iteration, policy iteration."))
    e3 = wait_for(lambda: latest(core, name3), 90)
    dest3 = rel(cfg, e3["current_path"]) if e3 else ""
    check("3 Auto -> RL_AGT/Reinforcement Learning/Lectures", e3 and e3["status"] == "sorted" and
          dest3.startswith("RL_AGT/Lectures/Reinforcement Learning/Lecture 04 - "), dest3)

    # 4 (drag & drop = reassign) ------------------------------------------
    if e3:
        core.reassign(e3["id"], module="AADS", part=1, category="Practicals")
        e4 = core.log.get(e3["id"])
        dest4 = rel(cfg, e4["current_path"])
        check("4 drag to AADS / Part 2 / Practicals moves + renames", Path(e4["current_path"]).exists() and
              dest4.startswith("AADS/Practicals/Advanced Algorithms/Practical 04 - ") and
              not (cfg.root_folder / dest3).exists(), dest4)

    # 5 ------------------------------------------------------------------
    if e:
        core.undo(e["id"])
        e5 = core.log.get(e["id"])
        check("5 undo returns file to Downloads", (downloads / name1).exists() and e5["status"] == "undone",
              rel(cfg, e5["current_path"]))
        time.sleep(5)
        check("5b undone file is not re-sorted by the watcher", (downloads / name1).exists())

    # 6 ------------------------------------------------------------------
    name6 = "lecture5.pdf"
    download(downloads, name6, lambda p: p.write_bytes(b"%PDF-1.4 this is not really a pdf \x00\x01"))
    e6 = wait_for(lambda: latest(core, name6))
    check("6 corrupted file -> _Unsorted + flagged, no crash", e6 and e6["status"] == "flagged" and
          rel(cfg, e6["current_path"]) == "_Unsorted/lecture5.pdf", e6 and e6.get("message"))

    # extension context: Blackboard wins over the dashboard pick ---------
    core.set_pick("ProjectPrep", None)
    name7 = "slides.pdf"
    req = urllib.request.Request(f"http://127.0.0.1:{cfg.port}/context", method="POST",
                                 headers={"Content-Type": "application/json"},
                                 data=json.dumps({"path": str(downloads / name7), "course_code": "COMP3801_2026",
                                                  "course_name": "Deep Learning & Computer Vision (26/27)",
                                                  "chain": ["Week 3", "Computer Vision"],
                                                  "item_title": "Lecture 3 - Edge detection"}).encode())
    urllib.request.urlopen(req).read()
    download(downloads, name7, lambda p: make_pdf(p, "Edges", "Canny, Sobel, gradients"))
    e7 = wait_for(lambda: latest(core, name7), 90)
    dest7 = rel(cfg, e7["current_path"]) if e7 else ""
    check("7 Blackboard context wins -> DLCV/Computer Vision/Lectures/Lecture 03", e7 and
          dest7.startswith("DLCV/Lectures/Computer Vision/Lecture 03 - "), dest7)

    # late context: file lands first, Blackboard context arrives seconds later ------
    core.set_pick(None, None)
    name_l = "lecture-notes.pdf"
    download(downloads, name_l, lambda p: make_pdf(p, "Some Notes", "General notes about the course structure"))
    time.sleep(4)
    req = urllib.request.Request(f"http://127.0.0.1:{cfg.port}/context", method="POST",
                                 headers={"Content-Type": "application/json"},
                                 data=json.dumps({"path": str(downloads / name_l), "course_code": "COMP3811_2026",
                                                  "course_name": "Advanced Algorithms & Data Structures (26/27)",
                                                  "chain": ["Part II: Advanced Algorithms"],
                                                  "item_title": "Lecture 7 - Network Flow"}).encode())
    urllib.request.urlopen(req).read()
    el = wait_for(lambda: (lambda e: e if e and rel(cfg, e["current_path"]).startswith("AADS/") else None)(
        latest(core, name_l)), 120)
    destl = rel(cfg, el["current_path"]) if el else rel(cfg, (latest(core, name_l) or {}).get("current_path", ""))
    check("7b late Blackboard context still wins -> AADS/Advanced Algorithms/Lectures/Lecture 07",
          destl.startswith("AADS/Lectures/Advanced Algorithms/Lecture 07 - "), destl)

    # duplicate ----------------------------------------------------------
    core.set_pick("Crypto", 0)
    shutil.copy(e7["current_path"], downloads / "slides (1).pdf.tmpcopy")
    os.replace(downloads / "slides (1).pdf.tmpcopy", downloads / "slides (1).pdf")
    e8 = wait_for(lambda: latest(core, "slides (1).pdf"))
    check("8 re-download of a file already in its right place -> extra copy removed, original kept",
          e8 and e8["status"] == "duplicate" and not (downloads / "slides (1).pdf").exists()
          and Path(e7["current_path"]).exists() and not (work / "Bin").exists())

    # practical bundle: code first, then sheet ---------------------------
    core.set_pick("DLCV", 0)
    download(downloads, "dl-practical5.py", lambda p: p.write_text("import torch\nprint('hi')\n"))
    ez = wait_for(lambda: latest(core, "dl-practical5.py"))
    download(downloads, "dl-practical5.pdf", lambda p: make_pdf(p, "Practical 5: Training a CNN",
             "Deep learning practical\nTrain a convolutional neural network with PyTorch."))
    es = wait_for(lambda: latest(core, "dl-practical5.pdf"), 90)
    ez = core.log.get(ez["id"]) if ez else None
    ok = es and ez and Path(es["current_path"]).parent == Path(ez["current_path"]).parent and \
        Path(es["current_path"]).parent.name.startswith("Practical 05 - ") and Path(ez["current_path"]).exists()
    check("9 practical bundle: code + sheet share 'Practical 05 - Topic' folder", ok,
          rel(cfg, es["current_path"]) if es else "")

    # zip ----------------------------------------------------------------
    def write_zip(p):
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("starter/main.py", "print(1)\n")
            z.writestr("../evil.txt", "nope")
    download(downloads, "practical6-starter.zip", write_zip)
    ezip = wait_for(lambda: latest(core, "practical6-starter.zip"))
    ok = ezip and ezip["extras"] and (Path(ezip["extras"][0]) / "starter" / "main.py").exists() and \
        not (Path(ezip["current_path"]).parent.parent / "evil.txt").exists()
    check("10 zip moved + extracted safely", ok, rel(cfg, ezip["current_path"]) if ezip else "")

    # unsupported type stays ---------------------------------------------
    download(downloads, "photo.jpg", lambda p: p.write_bytes(b"\xff\xd8\xff"))
    time.sleep(5)
    check("11 unsupported file type stays in Downloads", (downloads / "photo.jpg").exists())

    # fix flagged with Accept/editor --------------------------------------
    if e6:
        core.reassign(e6["id"], module="Crypto", part=0, category="Lectures", number=5, topic="Stream Ciphers")
        e6b = core.log.get(e6["id"])
        check("12 flagged item fixed via editor", rel(cfg, e6b["current_path"]) ==
              "Crypto/Lectures/Symmetric Cryptography/Lecture 05 - Stream Ciphers/Lecture 05 - Stream Ciphers.pdf", rel(cfg, e6b["current_path"]))

    # extension download while Alt+O is OFF is still sorted, and /recent reports it --
    core.deactivate()
    name_x = "Topic2Pt1.pdf"
    download(downloads, name_x, lambda p: make_pdf(p, "Asymmetric encryption", "RSA and public key encryption"))
    req = urllib.request.Request(f"http://127.0.0.1:{cfg.port}/context", method="POST",
                                 headers={"Content-Type": "application/json"},
                                 data=json.dumps({"path": str(downloads / name_x), "course_code": "COMP3731_2026",
                                                  "course_name": "Cryptography (26/27)",
                                                  "chain": ["Lectures", "Part 2: Asymmetric Cryptography"],
                                                  "item_title": "Topic 2 Part 1"}).encode())
    urllib.request.urlopen(req).read()
    ex = wait_for(lambda: latest(core, name_x), 90)
    destx = rel(cfg, ex["current_path"]) if ex else ""
    recent = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{cfg.port}/recent").read())["entries"]
    check("13 extension download sorted even when Alt+O is OFF + reported by /recent",
          destx.startswith("Crypto/Lectures/Asymmetric Cryptography/") and
          any(r["original_name"] == name_x and r["where"].startswith("Crypto") for r in recent), destx)

    # recap page API: taxonomy, recent (with tree path), move ------------------
    base = f"http://127.0.0.1:{cfg.port}"
    tax = json.loads(urllib.request.urlopen(base + "/taxonomy").read())
    ent = next(r for r in json.loads(urllib.request.urlopen(base + "/recent").read())["entries"]
               if r["original_name"] == name_x)
    req = urllib.request.Request(base + "/move", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"id": ent["id"], "module": "Crypto", "part": 1,
                                                  "category": "Practicals", "number": 4}).encode())
    mv = json.loads(urllib.request.urlopen(req).read())
    check("14 recap API: taxonomy + recent tree path + move into Practical 04",
          len(tax["modules"]) == 6 and ent["rel"][:3] == ["Crypto", "Lectures", "Asymmetric Cryptography"] and
          mv.get("ok") and mv["entry"]["rel"][:4] == ["Crypto", "Practicals", "Asymmetric Cryptography", mv["entry"]["rel"][3]]
          and mv["entry"]["rel"][3].startswith("Practical 04"), mv.get("entry", {}).get("rel"))

    # duplicate whose only copy is in an OLD-layout folder still gets sorted properly ----
    old = root / "DL" / "Lec"
    old.mkdir(parents=True)
    make_pdf(old / "dl-lecture1.pdf", "Deep Learning Lecture 1", "Introduction to deep learning")
    core.dups.add(old / "dl-lecture1.pdf")
    core.activate("DLCV", 0)
    shutil.copy(old / "dl-lecture1.pdf", downloads / "dl-lecture1.pdf.tmpcopy")
    os.replace(downloads / "dl-lecture1.pdf.tmpcopy", downloads / "dl-lecture1.pdf")
    eo = wait_for(lambda: latest(core, "dl-lecture1.pdf"), 90)
    check("15 'already have it' in an old folder -> sorted into the new layout, stray copy removed",
          eo and eo["status"] == "sorted" and rel(cfg, eo["current_path"]).startswith("DLCV/Lectures/Deep Learning/Lecture 01")
          and not (old / "dl-lecture1.pdf").exists(), eo and rel(cfg, eo["current_path"]))

    # same file already sorted but into the WRONG module -> moved to the right place, one copy --
    core.set_pick(None, None)
    wrong = root / "AADS" / "Other" / "stray.pdf"
    wrong.parent.mkdir(parents=True, exist_ok=True)
    make_pdf(wrong, "Stream ciphers", "Lecture 5 stream ciphers")
    core.dups.add(wrong)
    req = urllib.request.Request(base + "/context", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"path": str(downloads / "crypto5.pdf"), "course_code": "COMP3731_2026",
                                                  "chain": ["Part 1: Symmetric Cryptography"],
                                                  "item_title": "Lecture 5: Stream ciphers"}).encode())
    urllib.request.urlopen(req).read()
    shutil.copy(wrong, downloads / "crypto5.tmpcopy")
    os.replace(downloads / "crypto5.tmpcopy", downloads / "crypto5.pdf")
    ew = wait_for(lambda: latest(core, "crypto5.pdf"), 90)
    check("15b copy in the wrong place -> file sorted correctly, wrong copy removed (no Bin)",
          ew and ew["status"] == "sorted" and rel(cfg, ew["current_path"]).startswith("Crypto/Lectures/Symmetric Cryptography/Lecture 05")
          and not wrong.exists() and not (work / "Bin").exists(), ew and rel(cfg, ew["current_path"]))

    # notebook linked from a lecture line goes to the practical on the same topic --------
    pdir = root / "DLCV" / "Practicals" / "Deep Learning" / "Practical 04 - Designing Architectures"
    pdir.mkdir(parents=True, exist_ok=True)
    core.deactivate()
    nb_path = downloads / "unet.ipynb"
    req = urllib.request.Request(base + "/context", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"path": str(nb_path), "course_code": "COMP3801_2026",
                                                  "course_name": "Deep Learning & Computer Vision",
                                                  "chain": ["Slides and Code", "Deep Learning"],
                                                  "item_title": "Lecture 3: Designing architectures",
                                                  "link_text": "unet"}).encode())
    urllib.request.urlopen(req).read()
    download(downloads, "unet.ipynb", lambda p: p.write_text(json.dumps(
        {"cells": [{"cell_type": "markdown", "source": ["# U-Net"]}], "nbformat": 4}), encoding="utf-8"))
    en = wait_for(lambda: latest(core, "unet.ipynb"), 90)
    ok = en and Path(en["current_path"]).parent == pdir and any(x.endswith(".pdf") for x in en.get("extras", []))
    check("16 lecture notebook -> matching practical folder + printable PDF copy", ok,
          en and rel(cfg, en["current_path"]))

    # failed download is logged clearly -------------------------------------------------
    req = urllib.request.Request(base + "/fetch", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"url": "http://127.0.0.1:9/nope.pdf", "name": "nope.pdf",
                                                  "ctx": {"course_code": "COMP3801_2026"}}).encode())
    fr = json.loads(urllib.request.urlopen(req).read())
    ef = latest(core, "nope.pdf")
    check("17 failed download -> clear 'failed' entry with reason", not fr["ok"] and ef and ef["status"] == "failed",
          ef and ef.get("message"))

    core.shutdown()
    print()
    failed = [r for r in RESULTS if not r[1]]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} passed. Work dir: {work}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
