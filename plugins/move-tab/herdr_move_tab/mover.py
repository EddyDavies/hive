"""Moving a tab between workspaces.

Herdr has no "move tab to workspace" call: `tab.move` only reorders a tab
inside its own workspace. What it does have is `pane move`, which carries a
pane and the process running in it (a Claude chat keeps running) into a new
tab of any workspace. So a tab move is: move its first pane into a new tab
of the target, under the tab's label, then move every other pane into that
same tab as a split. A one-pane tab moves exactly; a split tab keeps all its
panes but stacks them top to bottom, which `MoveResult.layout_exact` says.

Herdr closes the source workspace by itself once its last pane leaves.

Moved panes get new ids. Two things hold on to old ids and are fixed here:
- hive records each bee's tab id. A bee whose tab moved would otherwise be
  "closed" by `hive close` without its tab closing, so the queen of any moved
  bee gets a `hive sync`, which re-reads tab ids.
- an overseer chat in the target workspace (a chat whose name contains
  "overseer") is told about the new chat, but only when it is idle, so a
  prompt never lands on top of work in progress.
"""

import glob
import json
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional


class MoveError(Exception):
    pass


def _herdr_bin():
    # type: () -> str
    return os.environ.get("HERDR_BIN_PATH") or shutil.which("herdr") or "herdr"


def herdr(*args):
    # type: (str) -> Dict[str, Any]
    """Run one herdr CLI command and return its `result`, or raise MoveError
    carrying herdr's own message."""
    p = subprocess.run([_herdr_bin()] + list(args), capture_output=True, text=True, timeout=60)
    body = None
    for stream in (p.stdout, p.stderr):
        try:
            body = json.loads(stream) if stream.strip() else None
        except ValueError:
            body = None
        if body is not None:
            break
    if p.returncode != 0 or body is None or "error" in body:
        err = (body or {}).get("error") or {}
        raise MoveError("herdr %s: %s" % (" ".join(args[:2]), err.get("message") or p.stderr.strip() or p.returncode))
    return body.get("result", {})


def workspaces():
    # type: () -> List[Dict[str, Any]]
    return herdr("workspace", "list")["workspaces"]


def _moved(result):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    return result.get("move_result", result)


def move_tab(tab_id, workspace_id=None, new_workspace_label=None, run=herdr):
    # type: (str, Optional[str], Optional[str], Any) -> Dict[str, Any]
    """Move every pane of `tab_id` into one new tab, either in `workspace_id`
    or in a new workspace named `new_workspace_label`. Returns what happened:
    target workspace, new tab and pane ids, and whether the layout is exact."""
    if bool(workspace_id) == bool(new_workspace_label):
        raise MoveError("give exactly one of a workspace or a new workspace name")
    if workspace_id and workspace_id == tab_id.split(":")[0]:
        raise MoveError("the tab is already in that workspace")

    ws = tab_id.split(":")[0]
    panes = [p for p in run("pane", "list", "--workspace", ws)["panes"] if p["tab_id"] == tab_id]
    if not panes:
        raise MoveError("tab %s has no panes" % tab_id)
    label = next((t.get("label") or "" for t in run("tab", "list", "--workspace", ws)["tabs"]
                  if t["tab_id"] == tab_id), "")

    tree = None
    if len(panes) > 1:
        layout = run("pane", "layout", "--pane", panes[0]["pane_id"])["layout"]
        tree = split_tree(layout)
    by_id = {p["pane_id"]: p for p in panes}
    order = leaves(tree) if tree else [p["pane_id"] for p in panes]
    if set(order) != set(by_id):
        tree, order = None, [p["pane_id"] for p in panes]

    first = by_id[order[0]]
    if new_workspace_label:
        r = _moved(run("pane", "move", first["pane_id"], "--new-workspace", "--label", new_workspace_label,
                       "--tab-label", label or new_workspace_label, "--no-focus"))
        target = r["created_workspace"]["workspace_id"]
    else:
        r = _moved(run("pane", "move", first["pane_id"], "--new-tab", "--workspace", workspace_id,
                       "--label", label, "--no-focus"))
        target = workspace_id
    new_tab = r["pane"]["tab_id"]
    new_ids = {first["pane_id"]: r["pane"]["pane_id"]}

    def place(pane_id, direction, ratio, anchor_old):
        args = ["pane", "move", pane_id, "--tab", new_tab, "--split", direction,
                "--target-pane", new_ids[anchor_old], "--no-focus"]
        if ratio is not None:
            args[-1:-1] = ["--ratio", "%.4f" % ratio]
        new_ids[pane_id] = _moved(run(*args))["pane"]["pane_id"]

    def rebuild(node, anchor_old):
        # The anchor pane fills this node's area: split off the second child,
        # then fill each half from its own anchor.
        if node["kind"] == "leaf":
            return
        second_anchor = leaves(node["second"])[0]
        place(second_anchor, node["direction"], node["ratio"], anchor_old)
        rebuild(node["first"], anchor_old)
        rebuild(node["second"], second_anchor)

    if tree:
        rebuild(tree, order[0])
    else:
        for pid in order[1:]:
            place(pid, "down", None, order[0])

    moved = [{"old": pid, "new": new_ids[pid], "agent": by_id[pid].get("agent"),
              "session": (by_id[pid].get("agent_session") or {}).get("value")} for pid in order]
    return {"label": label, "workspace_id": target, "tab_id": new_tab, "panes": moved,
            "layout_exact": len(panes) == 1 or tree is not None}


def _rect(o):
    # type: (Dict[str, Any]) -> tuple
    r = o["rect"] if "rect" in o else o
    return (r["x"], r["y"], r["width"], r["height"])


def split_tree(layout):
    # type: (Dict[str, Any]) -> Optional[Dict[str, Any]]
    """Rebuild the split tree from `pane layout`: each split names the area it
    divides, its direction and ratio; panes give their rects. Returns None if
    the rects do not form a clean tree, so the caller falls back to stacking."""
    splits = {_rect(s): s for s in layout.get("splits", [])}
    panes = [(p["pane_id"], _rect(p)) for p in layout.get("panes", [])]

    def build(area, members):
        if len(members) == 1:
            return {"kind": "leaf", "pane_id": members[0][0]}
        s = splits.get(area)
        if not s or s.get("direction") not in ("right", "down"):
            return None
        x, y, w, h = area
        axis = 0 if s["direction"] == "right" else 1
        start, size = (x, w) if axis == 0 else (y, h)
        # The boundary is where the second child starts: the smallest pane start
        # past the area's start that no pane straddles.
        starts = sorted(set(r[axis] for _, r in members if r[axis] > start))
        cut = next((c for c in starts if all(r[axis] + r[axis + 2] <= c or r[axis] >= c for _, r in members)), None)
        if cut is None:
            return None
        first = [m for m in members if m[1][axis] < cut]
        second = [m for m in members if m[1][axis] >= cut]
        if axis == 0:
            a1, a2 = (x, y, cut - x, h), (cut, y, x + w - cut, h)
        else:
            a1, a2 = (x, y, w, cut - y), (x, cut, w, y + h - cut)
        n1, n2 = build(a1, first), build(a2, second)
        if n1 is None or n2 is None:
            return None
        return {"kind": "split", "direction": s["direction"], "ratio": s.get("ratio"), "first": n1, "second": n2}

    if not panes:
        return None
    return build(_rect(layout["area"]), panes)


def leaves(node):
    # type: (Dict[str, Any]) -> List[str]
    if node["kind"] == "leaf":
        return [node["pane_id"]]
    return leaves(node["first"]) + leaves(node["second"])


def _hive_state_dirs():
    # type: () -> List[str]
    home = os.path.expanduser("~")
    env = os.environ.get("HIVE_STATE_DIR")
    return [d for d in ([env] if env else []) + [os.path.join(home, ".local/state/herd"),
                                                  os.path.join(home, ".local/state/hive")] if os.path.isdir(d)]


def queens_of(sessions):
    # type: (List[str]) -> List[str]
    """Hive slugs that have one of these chat sessions as a bee."""
    wanted = set(s for s in sessions if s)
    slugs = []
    for d in _hive_state_dirs():
        for path in glob.glob(os.path.join(d, "*.json")):
            try:
                data = json.load(open(path))
            except (OSError, ValueError):
                continue
            workers = data.get("workers") if isinstance(data, dict) else None
            if isinstance(workers, list) and any(w.get("session_id") in wanted for w in workers if isinstance(w, dict)):
                slugs.append(os.path.splitext(os.path.basename(path))[0])
    return sorted(set(slugs))


def resync_hives(sessions):
    # type: (List[str]) -> List[str]
    """Run `hive sync` for each queen of a moved bee. Returns problems, if any."""
    hive = shutil.which("hive")
    problems = []
    if not hive:
        return problems
    for slug in queens_of(sessions):
        p = subprocess.run([hive, "sync", "--orch", slug], capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            problems.append("hive sync %s failed: %s" % (slug, (p.stderr or p.stdout).strip()[:200]))
    return problems


def overseer_in(workspace_id, run=herdr):
    # type: (str, Any) -> Optional[Dict[str, Any]]
    for p in run("pane", "list", "--workspace", workspace_id)["panes"]:
        if p.get("agent") and "overseer" in (p.get("terminal_title_stripped") or "").lower():
            return p
    return None


def tell_overseer(result, run=herdr):
    # type: (Dict[str, Any], Any) -> str
    """Tell the target workspace's overseer about the new chat. Returns a
    short line for the user saying what happened."""
    o = overseer_in(result["workspace_id"], run)
    chats = [m for m in result["panes"] if m.get("agent")]
    if not o or not chats:
        return ""
    name = (o.get("terminal_title_stripped") or "overseer")
    if o.get("agent_status") not in ("idle", "done"):
        return "%s is busy, so it was not told" % name
    panes = ", ".join(m["new"] for m in chats)
    text = ("A chat moved into this workspace: tab '%s' (pane %s). Add it to your picture the next time you "
            "report." % (result["label"], panes))
    run("agent", "prompt", o["pane_id"], text)
    return "told %s" % name
