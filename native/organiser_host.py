"""Chrome native-messaging host: lets the extension start the organiser if it is not running.

Chrome sends one length-prefixed JSON message ({"cmd": "start"}); we answer {"ok": ..., "started": ...}.
The organiser is launched through Explorer so it lives on after Chrome / this host exits.
"""
import json
import os
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
STARTUP_LNK = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup\Alt+O Organiser.lnk"
STATUS = "http://127.0.0.1:{port}/status"


def port():
    try:
        return json.loads((PROJECT / "config.json").read_text(encoding="utf-8")).get("port", 47821)
    except (OSError, ValueError):
        return 47821


def running():
    try:
        with urllib.request.urlopen(STATUS.format(port=port()), timeout=2) as r:
            return json.loads(r.read()).get("app") == "alt-o-organiser"
    except Exception:
        return False


def launch():
    if STARTUP_LNK.exists():
        subprocess.Popen(["explorer.exe", str(STARTUP_LNK)])
        return
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    flags = 0x00000008 | 0x00000200 | 0x01000000   # DETACHED_PROCESS | NEW_PROCESS_GROUP | BREAKAWAY_FROM_JOB
    subprocess.Popen([str(pythonw), str(PROJECT / "run.pyw")], cwd=str(PROJECT), creationflags=flags,
                     close_fds=True)


def read_message():
    raw = sys.stdin.buffer.read(4)
    if len(raw) < 4:
        return None
    n = struct.unpack("<I", raw)[0]
    return json.loads(sys.stdin.buffer.read(n) or b"{}")


def send(obj):
    data = json.dumps(obj).encode()
    sys.stdout.buffer.write(struct.pack("<I", len(data)) + data)
    sys.stdout.buffer.flush()


def main():
    msg = read_message() or {}
    if msg.get("cmd") != "start":
        return send({"ok": False, "error": "unknown command"})
    if running():
        return send({"ok": True, "started": False})
    launch()
    for _ in range(40):                       # up to ~20 s for the app to come up
        time.sleep(0.5)
        if running():
            return send({"ok": True, "started": True})
    send({"ok": False, "error": "organiser did not start"})


if __name__ == "__main__":
    main()
