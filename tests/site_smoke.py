"""Render the revision-site shell from sample data in headless Chrome, from file://, and fail on console errors.

python -m tests.site_smoke
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from organiser.notebooks import browser
from study.site import TEMPLATE

CONCEPT = {"id": "L01.xor", "name": "XOR of bit strings", "kind": "definition",
           "summary": "Bitwise addition mod 2, $a \\oplus b$.", "src": ["Lecture 01 p.3"]}
TEACH = {"id": "L01.xor", "learning_order": 1, "hook": "How can one operation both lock and unlock?",
         "explanation": "For bits, $0 \\oplus 0 = 0$, $1 \\oplus 1 = 0$ and otherwise $1$.\n\n$$m \\oplus k \\oplus k = m$$",
         "analogies": [{"analogy": "A light switch flipped twice is back where it started.", "breaks": "Switches have no notion of strings."}],
         "examples": ["$1010 \\oplus 0110 = 1100$"], "misconceptions": ["XOR is not OR."], "exam_tips": ["Show the bitwise working."],
         "animation": {"title": "XOR bit by bit"}, "sandbox": {"title": "XOR playground", "challenge": "Make the output all zeros."},
         "recall_cards": [{"front": "What is $1 \\oplus 1$?", "back": "$0$", "layer": "recall"}]}
EXERCISES = [
    {"id": "L01.ex.001", "concepts": ["L01.xor"], "layer": "drill", "difficulty": 1, "format": "numeric",
     "question": "Compute $1 \\oplus 1$.", "check": {"type": "numeric", "answer": "0"}, "solution": "Equal bits give $0$."},
    {"id": "L01.ex.002", "concepts": ["L01.xor"], "layer": "drill", "difficulty": 2, "format": "mcq", "options": ["$0$", "$1$"],
     "question": "Which is $1 \\oplus 0$?", "check": {"type": "mcq", "answer": "1"}, "solution": "Different bits give $1$."},
    {"id": "L01.ex.003", "concepts": ["L01.xor"], "layer": "exam", "difficulty": 3, "format": "proof", "marks": 4,
     "question": "Prove $m \\oplus k \\oplus k = m$.", "check": {"type": "none"}, "solution": "Associativity and $k \\oplus k = 0$.",
     "mark_scheme": ["associativity (1)", "self-inverse (2)", "identity (1)"]}]
VISUAL = r"""
Study.visuals["L01.xor"] = {
  animation: { frames: [
    { caption: "Two bit strings, $m$ and $k$.", render(stage, C) { stage.append(Study.svg("svg", {viewBox: "0 0 200 40", width: 200},
        Study.svg("text", {x: 10, y: 25, fill: C.plain}, "1010"), Study.svg("text", {x: 110, y: 25, fill: C.key}, "0110"))); } },
    { caption: "XOR them: $1100$.", svg: "<svg viewBox='0 0 200 40' width='200'><text x='10' y='25'>1100</text></svg>" } ] },
  sandbox: { build(stage, api) {
    const a = api.h("input", {type: "text", value: "1010"}), b = api.h("input", {type: "text", value: "1010"}), out = api.h("output", {}, "");
    const xor = (x, y) => x.split("").map((c, i) => c === y[i] ? "0" : "1").join("");
    const upd = () => { out.textContent = xor(a.value, b.value); if (/^0+$/.test(out.textContent)) api.solved(); };
    a.oninput = b.oninput = upd; stage.append(a, " xor ", b, " = ", out); upd();
  } } };
Study.selftest("xor", () => ["1010","0110"].length === 2 || "broken");
"""


def run(url, profile):
    exe = browser()
    proc = subprocess.run([exe, "--headless=new", "--disable-gpu", "--allow-file-access-from-files", f"--user-data-dir={profile}",
                           "--enable-logging=stderr", "--v=0", "--virtual-time-budget=4000", "--dump-dom", url],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    errors = [l for l in proc.stderr.splitlines() if "CONSOLE" in l and ("error" in l.lower() or "SELFTEST" in l)]
    return proc.stdout, errors


def main():
    tmp = Path(tempfile.mkdtemp(prefix="site-smoke-"))
    site = tmp / "site"
    shutil.copytree(TEMPLATE, site)
    (site / "data").mkdir()
    (site / "visuals").mkdir()
    course = {"key": "Test", "module": "Cryptography", "code": "COMP0000", "part": "Symmetric",
              "lectures": [{"id": "L01", "title": "Lecture 01 - Basics", "concepts": ["L01.xor"]}]}
    (site / "data/course.js").write_text("window.COURSE = " + json.dumps(course) + ";", encoding="utf-8")
    lec = {"id": "L01", "title": "Lecture 01 - Basics", "concepts": [CONCEPT], "teaching": [TEACH], "exercises": EXERCISES,
           "plan": [{"id": "L01.xor", "teach": "all"}], "videos": [{"concept": "L01.xor", "title": "XOR undoes itself", "file": "videos/L01_xor.mp4"}],
           "master": "### p.3: XOR\n\nDefinition of $\\oplus$. [src: Lecture 01 p.3]"}
    (site / "data/L01.js").write_text("window.LECTURES = window.LECTURES || {}; window.LECTURES.L01 = " + json.dumps(lec) + ";", encoding="utf-8")
    (site / "visuals/L01.js").write_text(VISUAL, encoding="utf-8")
    checks = [
        ("lecture.html?id=L01", ["XOR of bit strings", "Next step", "XOR playground", "Solved.", "katex", "light switch", "Quick check", "Short film: XOR undoes itself"]),
        ("lecture.html?id=L01&tab=practice", ["Ask Claude to mark it", "3 exercises"]),
        ("index.html", ["0 of 1 concepts mastered", "3 exercises in the gym"]),
        ("practice.html?tab=recall", ["Show answer"]),
    ]
    failed = 0
    for page, needles in checks:
        dom, errors = run((site / page.split("?")[0]).as_uri() + ("?" + page.split("?")[1] if "?" in page else ""), tmp / "profile")
        missing = [n for n in needles if n not in dom]
        ok = not missing and not errors
        failed += not ok
        print(("PASS " if ok else "FAIL ") + page + ("" if ok else f"  missing={missing} errors={errors[:3]}"))
    print(f"{len(checks) - failed}/{len(checks)} passed. Site: {site}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
