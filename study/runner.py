"""Run one prompt through a CLI agent on the user's subscription (no API keys) and record usage.

claude: `claude -p` (stream-json gives rate_limit_event with 5-hour / weekly utilisation).
agy:    `agy -p <prompt file>` (Antigravity, Google quota). Opt-in only (--runner agy / auto): the user wants
        Claude Code to run every step (2026-10-21). Headless agy hangs if an MCP server never connects (StitchMCP did: removed
        from ~/.gemini/config/mcp_config.json on 2026-10-21, backup next to it).
"""
import json
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

CLAUDE_MODELS = {"sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5", "haiku": "claude-haiku-5-5"}
AGY_MODELS = {"gemini": "gemini-4-argon-high", "flash": "gemini-3.8-flash-high"}
AGY_DEFAULT = "gemini-4-argon-high"
STOP_AT = 0.85         # don't start Claude jobs above this 5-hour or weekly utilisation


class RunnerError(RuntimeError):
    pass


def _usage_file(cfg):
    return cfg.data_dir / "study" / "usage.json"


def last_usage(cfg):
    f = _usage_file(cfg)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


_LOCK = __import__("threading").Lock()     # steps may run in parallel threads


def _save_usage(cfg, runner, info):
    with _LOCK:
        _save_usage_unlocked(cfg, runner, info)


def _save_usage_unlocked(cfg, runner, info):
    f = _usage_file(cfg)
    f.parent.mkdir(parents=True, exist_ok=True)
    data = last_usage(cfg)
    data[runner] = {**info, "seen": datetime.now().isoformat(timespec="seconds")}
    f.write_text(json.dumps(data, indent=2), encoding="utf-8")


def claude_headroom(cfg):
    """(ok, message) from the last rate_limit_event seen."""
    u = last_usage(cfg).get("claude", {})
    five, week = u.get("five_hour"), u.get("seven_day")
    age = (datetime.now() - datetime.fromisoformat(u["seen"])).total_seconds() / 3600 if u.get("seen") else 0
    if age >= 5:                       # that 5-hour window has reset since the reading
        five = None
    if age >= 24 * 7:
        week = None
    if five is None:
        return True, "Claude usage unknown (no run yet)"
    msg = f"Claude: 5-hour {five:.0%}, week {week:.0%}"
    return (five < STOP_AT and (week or 0) < STOP_AT), msg


def run_claude(cfg, prompt, model="sonnet", tools=("Read",), add_dirs=(), cwd=None, timeout=1800):
    ok, msg = claude_headroom(cfg)
    if not ok:
        raise RunnerError(f"Stopped before starting: {msg} (limit {STOP_AT:.0%}).")
    cmd = [shutil.which("claude") or "claude", "-p", "--model", CLAUDE_MODELS.get(model, model), "--output-format", "stream-json",
           "--verbose", "--allowedTools", ",".join(tools)]
    for d in add_dirs:
        cmd += ["--add-dir", str(d)]
    t0 = time.time()
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                          timeout=timeout, cwd=cwd, shell=False)
    result, usage = None, {}
    for line in proc.stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "rate_limit_event":
            w = ev["rate_limit_info"].get("unifiedWindows", {})
            usage = {"five_hour": w.get("five_hour", {}).get("utilization"),
                     "seven_day": w.get("seven_day", {}).get("utilization")}
        elif ev.get("type") == "result":
            result = ev
    if usage:
        _save_usage(cfg, "claude", usage)
    if not result or result.get("is_error") or result.get("subtype") != "success":
        raise RunnerError(f"claude failed (exit {proc.returncode}): "
                          f"{(result or {}).get('result') or proc.stderr[-800:]}")
    return result["result"], {"seconds": round(time.time() - t0), "cost_usd": result.get("total_cost_usd"), **usage}


def run_agy(cfg, prompt, model=None, add_dirs=(), cwd=None, timeout=1800, **_):
    """Same call as semi-automated-placement: the prompt goes in a file and `agy -p <file>` reads it
    (no Windows command-line length limit). Plain-text stdout is the answer."""
    work = cfg.data_dir / "study" / "agy"
    work.mkdir(parents=True, exist_ok=True)
    pf = work / f"prompt-{datetime.now():%Y%m%d-%H%M%S-%f}.md"
    pf.write_text(prompt, encoding="utf-8")
    cmd = [shutil.which("agy") or "agy", "-p", str(pf), "--model", AGY_MODELS.get(model) or (model if model and model not in CLAUDE_MODELS else AGY_DEFAULT),
           "--print-timeout", f"{max(1, timeout // 60)}m"]
    for d in add_dirs:
        cmd += ["--add-dir", str(d)]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL, timeout=timeout + 120, cwd=cwd or work, shell=False)
    finally:
        pf.unlink(missing_ok=True)
    out, err = proc.stdout.strip(), proc.stderr.strip()
    if "print timeout" in err or "print timeout" in out[-200:]:
        raise RunnerError(f"agy timed out after {timeout // 60} min with the turn still running.")
    if proc.returncode or not out:
        raise RunnerError(f"agy failed (exit {proc.returncode}): {(err or out)[-600:]}")
    usage = {"seconds": round(time.time() - t0), "model": cmd[4]}
    _save_usage(cfg, "agy", usage)
    return out, usage


VISUAL_STEPS = {"visuals", "videos"}     # Claude builds visuals / sandboxes / videos; agy (Google quota) does the rest


def pick(runner, step=None):
    """'auto' -> claude for visual steps, agy for reading and teaching content."""
    if runner != "auto":
        return runner
    return "claude" if step in VISUAL_STEPS else "agy"


def run(cfg, prompt, runner="claude", **kw):
    return (run_agy if runner == "agy" else run_claude)(cfg, prompt, **kw)


def describe(usage):
    """'139s, gemini-4-argon-high' or '80s, Claude 5h 41%'."""
    if usage.get("five_hour") is not None:
        return f"{usage.get('seconds')}s, Claude 5h {usage['five_hour']:.0%}"
    return f"{usage.get('seconds')}s, {usage.get('model', '?')}"


def extract_json(text):
    """The last ```json fenced block (or the whole text) parsed as JSON."""
    import re
    blocks = re.findall(r"```(?:json)?\s*\n(.*?)\n```", text, re.S)
    for candidate in reversed(blocks or [text]):
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    raise RunnerError(f"No JSON found in model output: {text[:300]}")


PROMPTS = Path(__file__).resolve().parent / "prompts"


def build_prompt(name, **values):
    text = (PROMPTS / "00_rules.md").read_text(encoding="utf-8") + "\n\n---\n\n" + \
        (PROMPTS / name).read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text
