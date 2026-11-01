"""hive reap: stop Herdr sessions nobody is looking at.

A Herdr server outlives its window, so every Claude in it (and each one's MCP
servers) keeps running after Eddy closes the terminal. Run once a minute by
launchd, this stops a session once it has had no client attached and no agent
working for GRACE seconds. Herdr keeps each pane's Claude session id in
session.json, so `herdr --session <name>` later resumes every chat.

It fails safe: a session whose log or agent list it cannot read counts as in use."""

import json
import os
import plistlib
import re
import shutil
import subprocess
import time
from pathlib import Path

from hive.registry import state_dir

GRACE = int(os.environ.get("HIVE_REAP_GRACE", 600))  # seconds detached and idle before a stop
SKIP = set(os.environ.get("HIVE_REAP_SKIP", "default").split(","))  # session names never stopped
QUIET_STATES = {"idle", "done", "blocked"}  # anything else (working, unknown) keeps a session alive
LABEL = "com.eddydavies.hive-reaper"
PLIST = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"

CLIENT_EVENT = re.compile(r"client (connected|detached) client_id=(\d+)")


def herdr(*args, socket=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HERDR_")}
    if socket:
        env["HERDR_SOCKET_PATH"] = socket
    p = subprocess.run(["herdr", *args], capture_output=True, text=True, timeout=30, env=env)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or f"exit {p.returncode}")
    return json.loads(p.stdout)


def attached_clients(log: Path):
    """Clients attached right now, from the server log since its last start; None if unreadable."""
    try:
        text = log.read_text(errors="replace")
    except OSError:
        return None
    start = text.rfind("herdr server started")
    if start < 0:
        return None
    live = set()
    for kind, cid in CLIENT_EVENT.findall(text[start:]):
        (live.add if kind == "connected" else live.discard)(cid)
    return len(live)


def busy_agents(socket: str):
    """Agents not settled (working or unclassified); None if the list cannot be read."""
    try:
        agents = herdr("agent", "list", socket=socket)["result"]["agents"]
    except (RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired):
        return None
    return sum(1 for a in agents if a.get("agent_status") not in QUIET_STATES)


def why_in_use(s: dict):
    """A reason the session is in use, or None when it is detached and idle."""
    clients = attached_clients(Path(s["session_dir"]) / "herdr-server.log")
    if clients is None:
        return "server log unreadable"
    if clients:
        return f"{clients} client(s) attached"
    busy = busy_agents(s["socket_path"])
    if busy is None:
        return "agent list unreadable"
    if busy:
        return f"{busy} agent(s) working"
    return None


def log(line: str) -> None:
    with open(state_dir() / "reaper.log", "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")


def reap(dry_run=False, now=None) -> list:
    """One pass. Returns the names of sessions stopped (or that would be, with dry_run)."""
    now = now or time.time()
    state_dir().mkdir(parents=True, exist_ok=True)
    quiet_file = state_dir() / "reaper.json"
    try:
        quiet_since = json.loads(quiet_file.read_text())
    except (OSError, ValueError):
        quiet_since = {}
    sessions = [s for s in herdr("session", "list", "--json")["sessions"] if s["running"] and s["name"] not in SKIP]
    seen, stopped = {}, []
    for s in sessions:
        name, reason = s["name"], why_in_use(s)
        if reason:
            if dry_run:
                print(f"{name}: keep ({reason})")
            continue
        seen[name] = since = quiet_since.get(name, now)
        left = GRACE - (now - since)
        if left > 0:
            if dry_run:
                print(f"{name}: detached and idle, stops in {int(left)}s")
            continue
        if dry_run:
            print(f"{name}: would stop now")
        else:
            herdr("session", "stop", name, "--json")
            log(f"stopped {name} (detached and idle for {int(now - since)}s)")
            del seen[name]
        stopped.append(name)
    if not dry_run:
        quiet_file.write_text(json.dumps(seen))
    return stopped


def install() -> str:
    hive = shutil.which("hive")
    if not hive:
        raise RuntimeError("hive is not on PATH; run ./install.sh first")
    herdr_bin = shutil.which("herdr")
    path = ":".join(dict.fromkeys([str(Path(herdr_bin).parent) if herdr_bin else "/opt/homebrew/bin",
                                   str(Path(hive).parent), "/usr/bin", "/bin"]))
    state_dir().mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [hive, "reap"],
        "StartInterval": 60,
        "RunAtLoad": True,
        "EnvironmentVariables": {"PATH": path},
        "StandardErrorPath": str(state_dir() / "reaper.err"),
    }))
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(PLIST)], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST)], check=True)
    return str(PLIST)


def uninstall() -> None:
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(PLIST)], capture_output=True)
    PLIST.unlink(missing_ok=True)
