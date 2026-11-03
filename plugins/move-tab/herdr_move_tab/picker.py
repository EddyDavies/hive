"""The popup: pick a workspace, or type a name for a new one.

Keys: up/down or j/k to select, 1-9 to pick directly, enter to move, n to
name a new workspace, q or esc to cancel. A popup closes when this exits.
"""

import os
import select
import sys
from typing import Any, Dict, List, Optional

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - linux/macos only
    termios = None
    tty = None


def render(rows, selected, tab_label):
    # type: (List[Dict[str, Any]], int, str) -> List[str]
    lines = ["Move '%s' to:  (up/down or 1-9, enter moves, n new workspace, q cancels)" % tab_label, ""]
    for i, w in enumerate(rows):
        marker = ">" if i == selected else " "
        key = str(i + 1) if i < 9 else " "
        lines.append("%s %s. %-28s %d tab%s" % (marker, key, (w.get("label") or w["workspace_id"])[:28],
                                                w.get("tab_count", 0), "" if w.get("tab_count") == 1 else "s"))
    lines.append("%s n. new workspace..." % (">" if selected == len(rows) else " "))
    return lines


def read_key(fd):
    # type: (int) -> str
    chunk = os.read(fd, 1)
    if not chunk:
        return "eof"
    ch = chunk.decode("utf-8", "ignore")
    if ch != "\x1b":
        return ch
    if not select.select([fd], [], [], 0.01)[0]:
        return "esc"
    rest = os.read(fd, 2).decode("utf-8", "ignore")
    return {"[A": "up", "[B": "down"}.get(rest, "esc")


def read_name(fd, tab_label):
    # type: (int, str) -> Optional[str]
    name = ""
    while True:
        sys.stdout.write("\x1b[2J\x1b[HNew workspace for '%s' (enter creates, esc cancels):\r\n\r\n> %s" % (tab_label, name))
        sys.stdout.flush()
        key = read_key(fd)
        if key in ("esc", "\x03", "eof"):
            return None
        if key in ("\r", "\n"):
            return name.strip() or None
        if key in ("\x7f", "\x08"):
            name = name[:-1]
        elif len(key) == 1 and key.isprintable():
            name += key


def run(rows, tab_label):
    # type: (List[Dict[str, Any]], str) -> Optional[Dict[str, Any]]
    """Returns {"workspace_id": id} or {"new": name}, or None on cancel."""
    if not sys.stdin.isatty() or termios is None:
        print("\n".join(render(rows, 0, tab_label)))
        return None
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    count = len(rows) + 1
    selected = 0
    try:
        tty.setraw(fd)
        while True:
            sys.stdout.write("\x1b[2J\x1b[H" + "\r\n".join(render(rows, selected, tab_label)) + "\r\n")
            sys.stdout.flush()
            key = read_key(fd)
            if key in ("q", "esc", "\x03", "eof"):
                return None
            if key in ("k", "up"):
                selected = (selected - 1) % count
            elif key in ("j", "down"):
                selected = (selected + 1) % count
            elif key == "n" or (key in ("\r", "\n") and selected == len(rows)):
                name = read_name(fd, tab_label)
                if name:
                    return {"new": name}
            elif key in ("\r", "\n"):
                return {"workspace_id": rows[selected]["workspace_id"]}
            elif len(key) == 1 and key.isdigit() and key != "0" and int(key) <= min(len(rows), 9):
                return {"workspace_id": rows[int(key) - 1]["workspace_id"]}
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
