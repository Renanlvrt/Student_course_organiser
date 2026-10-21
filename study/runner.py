"""Run one prompt through a CLI agent on the user's subscription (no API keys) and record usage.

claude: `claude -p` (stream-json gives rate_limit_event with 5-hour / weekly utilisation).
agy:    `agy -p` (Antigravity). Headless print mode currently never starts a turn on this account, so it
        is opt-in only (--runner agy) until that works.
"""
import json
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

CLAUDE_MODELS = {"sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5", "haiku": "claude-haiku-5-5"}
STOP_AT = 0.85          # don't start Claude jobs above this 5-hour or weekly utilisation


class RunnerError(RuntimeError):
    pass


def _usage_file(cfg):
    return cfg.data_dir / "study" / "usage.json"


def last_usage(cfg):
    f = _usage_file(cfg)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _save_usage(cfg, runner, info):
    f = _usage_file(cfg)
    f.parent.mkdir(parents=True, exist_ok=True)
    data = last_usage(cfg)
    data[runner] = {**info, "seen": datetime.now().isoformat(timespec="seconds")}
    f.write_text(json.dumps(data, indent=2), encoding="utf-8")


def claude_headroom(cfg):
    """(ok, message) from the last rate_limit_event seen."""
    u = last_usage(cfg).get("claude", {})
    five, week = u.get("five_hour"), u.get("seven_day")
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


def run_agy(cfg, prompt, model=None, timeout=1800, **_):
    cmd = ["agy", "--output-format", "json", "--print-timeout", f"{timeout}s", f"-p={prompt}"]
    if model:
        cmd[1:1] = ["--model", model]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout + 60)
    try:
        out = json.loads(proc.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        raise RunnerError(f"agy gave no JSON: {proc.stdout[-400:]} {proc.stderr[-400:]}")
    if not out.get("response"):
        raise RunnerError("agy returned an empty response (headless print mode did not start a turn).")
    _save_usage(cfg, "agy", out.get("usage", {}))
    return out["response"], out.get("usage", {})


def run(cfg, prompt, runner="claude", **kw):
    return (run_agy if runner == "agy" else run_claude)(cfg, prompt, **kw)


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
