"""Subcommands: python3 -m herdr_move_tab.cli <subcommand>.

    open-picker   the `pick` action: open the popup for the tab it fired on
    pick          the popup pane's own command
    move          plain CLI: move <tab_id> (--to <workspace_id> | --new <name>)
"""

import json
import os
import socket
import sys
from typing import Any, Dict, List, Optional

from . import mover, picker


def rpc(method, params):
    # type: (str, Dict[str, Any]) -> Dict[str, Any]
    """One request on the Herdr socket, for calls the CLI has no command for."""
    path = os.environ.get("HERDR_SOCKET_PATH")
    if not path:
        raise mover.MoveError("HERDR_SOCKET_PATH is not set")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(10)
        s.connect(path)
        s.sendall((json.dumps({"id": "move-tab", "method": method, "params": params}) + "\n").encode())
        body = json.loads(s.makefile().readline())
    if "error" in body:
        raise mover.MoveError("%s: %s" % (method, body["error"].get("message")))
    return body.get("result", {})


def notify(title, body=""):
    # type: (str, str) -> None
    try:
        rpc("notification.show", {"title": title, "body": body})
    except (mover.MoveError, OSError, ValueError):
        pass


def run_move(tab_id, workspace_id=None, new_name=None):
    # type: (str, Optional[str], Optional[str]) -> str
    """Move the tab, then fix up hive and the overseer. Returns one summary
    line; raises MoveError if the move itself failed."""
    result = mover.move_tab(tab_id, workspace_id=workspace_id, new_workspace_label=new_name)
    notes = []  # type: List[str]
    if not result["layout_exact"]:
        notes.append("%d panes stacked top to bottom" % len(result["panes"]))
    notes.extend(mover.resync_hives([m["session"] for m in result["panes"]]))
    try:
        told = mover.tell_overseer(result)
    except mover.MoveError as exc:
        told = "could not tell the overseer: %s" % exc
    if told:
        notes.append(told)
    target = next((w.get("label") or w["workspace_id"] for w in mover.workspaces()
                   if w["workspace_id"] == result["workspace_id"]), result["workspace_id"])
    line = "Moved '%s' to %s" % (result["label"], target)
    return line + ("; " + "; ".join(notes) if notes else "")


def cmd_open_picker(argv):
    # type: (List[str]) -> int
    try:
        ctx = json.loads(os.environ.get("HERDR_PLUGIN_CONTEXT_JSON") or "{}")
    except ValueError:
        ctx = {}
    tab_id = ctx.get("tab_id") or os.environ.get("HERDR_TAB_ID")
    if not tab_id:
        notify("Move tab", "no tab in focus")
        return 1
    try:
        rpc("plugin.pane.open", {"plugin_id": os.environ.get("HERDR_PLUGIN_ID", "move-tab"), "entrypoint": "picker",
                                 "focus": True, "env": {"MOVE_TAB_ID": tab_id,
                                                        "MOVE_TAB_LABEL": ctx.get("tab_label") or ""}})
    except (mover.MoveError, OSError, ValueError) as exc:
        sys.stderr.write("herdr-move-tab: open-picker failed: %s\n" % exc)
        return 1
    return 0


def cmd_pick(argv):
    # type: (List[str]) -> int
    tab_id = os.environ.get("MOVE_TAB_ID")
    if not tab_id:
        print("No tab given")
        return 1
    source = tab_id.split(":")[0]
    rows = [w for w in mover.workspaces() if w["workspace_id"] != source]
    choice = picker.run(rows, os.environ.get("MOVE_TAB_LABEL") or tab_id)
    if choice is None:
        return 0
    try:
        line = run_move(tab_id, workspace_id=choice.get("workspace_id"), new_name=choice.get("new"))
    except mover.MoveError as exc:
        notify("Move tab failed", str(exc))
        print("Move failed: %s" % exc)
        return 1
    notify("Tab moved", line)
    return 0


def cmd_move(argv):
    # type: (List[str]) -> int
    if len(argv) != 3 or argv[1] not in ("--to", "--new"):
        sys.stderr.write("usage: move <tab_id> --to <workspace_id> | --new <name>\n")
        return 2
    tab_id, flag, value = argv
    try:
        print(run_move(tab_id, workspace_id=value if flag == "--to" else None,
                       new_name=value if flag == "--new" else None))
    except mover.MoveError as exc:
        sys.stderr.write("herdr-move-tab: %s\n" % exc)
        return 1
    return 0


COMMANDS = {"open-picker": cmd_open_picker, "pick": cmd_pick, "move": cmd_move}


def main(argv=None):
    # type: (Optional[List[str]]) -> int
    argv = list(sys.argv[1:] if argv is None else argv)
    handler = COMMANDS.get(argv[0]) if argv else None
    if handler is None:
        sys.stderr.write("usage: python3 -m herdr_move_tab.cli <%s>\n" % "|".join(sorted(COMMANDS)))
        return 2
    return handler(argv[1:])


if __name__ == "__main__":
    sys.exit(main())
