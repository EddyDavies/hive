"""hive: a queen Claude chat spawns, tracks, closes and restores
labelled bee chats in Herdr tabs. See docs/specs/2026-09-25-hive-design.md."""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from hive import drone
from hive.drone import DroneError
from hive.hc import Hc, HcError
from hive.herdr import Herdr, HerdrError
from hive.registry import Registry, RegistryError, new_worker, now, slugify, state_dir

MODEL_IDS = {"opus": "claude-opus-5-5", "fable": "claude-fable-5-1"}
REVIEW = "👀 "
RENAME_MAX_TABS = 3  # hive relabels a workspace only while it holds this few tabs; busier ones keep Eddy's name
OPEN_STATES = ("live", "handed-off", "review", "detached")
SETTLE_POLL = 1.0  # seconds between status checks on a remote bee that is starting
SETTLE_FIRST = 20  # polls before hive looks for the folder trust dialog
SETTLE_AFTER = 30  # polls for a status once the dialog is answered
WAIT_TIMEOUT = 180  # hc's own default


class HiveError(Exception):
    pass


def tab_label(w: dict) -> str:
    label = f"{w['model'][0]}> {w['label']}"
    if w.get("machine"):
        label += f" @{w['machine']}"
    return REVIEW + label if w["status"] == "review" else label


def claude_args(session_id: str, name: str, model: str, resume: bool) -> list:
    args = ["--resume" if resume else "--session-id", session_id]
    if name:
        args += ["--name", name]
    return args + ["--model", MODEL_IDS[model], "--dangerously-skip-permissions"]


def queen_name(label: str) -> str:
    """The queen chat's fixed SendMessage name. A name set with /rename survives restarts,
    unlike the derived one (cwd plus a random suffix)."""
    return f"queen: {label}"


def kickoff(w: dict, orch_name: str) -> str:
    return (f'You are a hive bee named "{w["label"]}". Load the hive-bee skill now. '
            f'Your queen\'s SendMessage name is "{orch_name}". If a message to it cannot be '
            f'delivered, run `hive queen` for its current name. '
            f'Your brief is at {w["brief"]}. Read it and start.')


def remote_kickoff(w: dict) -> str:
    """A remote bee has no hive-bee skill and no queen it can message, so its kickoff carries the handoff
    format and the file the queen reads it from."""
    return (f'You are a hive bee named "{w["label"]}", running on machine {w["machine"]}, away from your queen. '
            f'There is no hive-bee skill and no SendMessage here: never try to message the queen, and never ask '
            f'who to report to. Your brief is at {w["remote_brief"]}. Read it in full; it is your whole scope. '
            f'Do the work. Stop and report instead of improvising when the code or data does not match the brief, '
            f'a command fails after one sensible retry, or the task needs files outside scope. '
            f'When you are finished, or stopped, write this handoff to {w["remote_handoff"]} '
            f'(create the folder if needed):\n\n'
            f'HIVE HANDOFF {w["label"]}\n'
            f'complete: yes|no (what remains, if no)\n'
            f'review_worthy: yes|no (the decision or thing only Eddy can judge)\n'
            f'summary: <3 to 6 lines: what you did and what you found>\n'
            f'artifacts: <paths, urls, commits; or none>\n'
            f'open: <loose ends, risks, things you could not verify; or none>\n\n'
            f'Evidence over adjectives: file paths with line numbers, the commands you ran and their result, exact '
            f'failures. Then stop and stay open; the queen reads the file and decides when you close.')


def remote_command(args: list) -> list:
    """The program hc starts on the machine: a login shell, so the box profile sets PATH and the Claude token."""
    return ["bash", "-lc", "exec claude " + shlex.join(args)]


def projects_dir() -> Path:
    return Path(os.environ.get("HIVE_CLAUDE_PROJECTS_DIR") or Path.home() / ".claude/projects")


def sessions_dir() -> Path:
    return Path(os.environ.get("HIVE_CLAUDE_SESSIONS_DIR") or Path.home() / ".claude/sessions")


def pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def live_name(session_id: str):
    """SendMessage name of the running Claude process for this session, or None.
    A queen that was never renamed gets a fresh derived name on every start, so a recorded name goes stale."""
    best = None
    for f in sessions_dir().glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if d.get("sessionId") != session_id or not d.get("name") or not pid_alive(d.get("pid")):
            continue
        if best is None or d.get("startedAt", 0) > best.get("startedAt", 0):
            best = d
    return best["name"] if best else None


def refresh_orchestrator(r: Registry):
    """Record the queen's current name. Returns it, or None when that chat is not running."""
    o = r.data["orchestrator"]
    name = live_name(o.get("session_id", ""))
    if name and name != o.get("name"):
        o["name"] = name
        r.save()
    return name


def input_draft(screen: str):
    """Text in a Claude chat's input box, "" when it is empty, None when no input box is on screen.
    The box is the lines from the one starting with ❯ down to the next ─── rule."""
    lines = screen.splitlines()
    starts = [i for i, l in enumerate(lines) if l.lstrip().startswith("❯")]
    if not starts:
        return None
    draft = [lines[starts[-1]].lstrip()[1:].strip()]
    for l in lines[starts[-1] + 1:]:
        if l.strip().startswith("─"):
            return "\n".join(draft).strip()
        draft.append(l.strip())
    return None


def ensure_queen_name(r: Registry, h: Herdr) -> str:
    """Rename the queen chat to its fixed name if it is running under any other.
    /rename is typed into the chat, so it waits while Eddy has a draft there; the next hive command retries."""
    o = r.data["orchestrator"]
    want = queen_name(r.data["label"])
    agent = h.live_sessions().get(o.get("session_id"))
    live = live_name(o.get("session_id", ""))
    if agent and (o.get("name") != want or (live and live != want)):
        try:
            draft = input_draft(h.pane_screen(agent["pane_id"]))
            if draft != "":
                why = "it has an unsent draft" if draft else "its input box is not on screen"
                print(f"hive: not renaming the queen chat to {want!r} yet: {why}; "
                      f"the next hive command retries", file=sys.stderr)
                return refresh_orchestrator(r) or o.get("name", "")
            h.agent_prompt(agent["pane_id"], f"/rename {want}")
        except HerdrError as e:
            print(f"hive: could not rename the queen chat to {want!r}: {e}", file=sys.stderr)
            return refresh_orchestrator(r) or o.get("name", "")
        o["name"] = want
        r.save()
    elif not agent:
        refresh_orchestrator(r)
    return o.get("name", "")


def my_session_id():
    return os.environ.get("CLAUDE_CODE_SESSION_ID")


def registry_of_session(sid):
    """The hive this chat belongs to, as queen or bee. Workspaces change hands and panes move,
    so a chat's own session id is the reliable key."""
    if not sid:
        return None
    mine = [r for r in Registry.all()
            if r.data["orchestrator"].get("session_id") == sid or any(w["session_id"] == sid for w in r.data["workers"])]
    # one chat can queen several hives in turn: the current one is not retired, and the newest
    mine.sort(key=lambda r: (not r.data.get("retired_at"), r.data.get("created_at", "")))
    return mine[-1] if mine else None


def current_registry(slug=None) -> Registry:
    if slug:
        r = Registry.load(slug)
        if my_session_id() and r.data["orchestrator"].get("session_id") == my_session_id():
            moved = rehome(r)
            if moved:
                print(moved)
        return r
    r = registry_of_session(my_session_id())
    if r:
        if r.data["orchestrator"].get("session_id") == my_session_id():
            moved = rehome(r)
            if moved:
                print(moved)
        return r
    ws = os.environ.get("HERDR_WORKSPACE_ID")
    r = Registry.find_by_workspace(ws, os.environ.get("HERDR_SOCKET_PATH")) if ws else None
    if r is None:
        raise HiveError("this workspace has no queen; pass --orch <slug> (see: hive ls) or run hive init")
    return r


def herdr_for(r: Registry) -> Herdr:
    """The Herdr server this queen lives in, which may not be the one hive was run from."""
    return Herdr(r.data.get("herdr_socket"))


def need_worker(r: Registry, name: str) -> dict:
    w = r.worker(name)
    if w is None:
        raise HiveError(f"no bee {name!r} in {r.slug}")
    return w


def set_status(w: dict, status: str) -> None:
    w["status"] = status
    w["updated_at"] = now()


# commands

def own_pane(h: Herdr):
    """(workspace id, pane id, this chat's agent record, its Claude session id), or a loud error.
    Found by session id first: HERDR_PANE_ID and HERDR_WORKSPACE_ID go stale once the pane is moved."""
    agents = h.agents()
    sid = my_session_id()
    mine = next((x for x in agents if ((x.get("agent_session") or {}).get("value")) == sid), None) if sid else None
    if mine is None:
        pane = os.environ.get("HERDR_PANE_ID")
        if not pane:
            raise HiveError("cannot find this chat in herdr; run this from the queen's own pane")
        mine = next((x for x in agents if x.get("pane_id") == pane), None)
        sid = ((mine or {}).get("agent_session") or {}).get("value")
    if not mine or not sid:
        raise HiveError("herdr reports no Claude session for this chat; cannot record the queen")
    ws = mine.get("workspace_id") or os.environ.get("HERDR_WORKSPACE_ID")
    return ws, mine["pane_id"], mine, sid


def open_workers(r: Registry) -> list:
    return [w["label"] for w in r.data["workers"] if w["status"] in OPEN_STATES]


def stale(r: Registry, h: Herdr):
    """Why this hive may give up its workspace, or None while it is still in use. A hive whose bees are all
    closed is done; only a different queen chat mid-turn (it may be about to spawn) keeps it."""
    if any(w["status"] not in ("closed", "failed") for w in r.data["workers"]):
        return None
    o = r.data["orchestrator"]
    if o.get("session_id") != my_session_id() and any(
            a.get("agent_status") == "working" for a in h.agents() if a.get("pane_id") == o.get("pane_id")):
        return None
    return "every bee closed"


def retire(r: Registry) -> None:
    """The queen gives up its workspace. Its record and bees stay restorable (into a new workspace)."""
    r.data["workspace_id"] = None
    r.data["retired_at"] = now()
    r.save()


def label_workspace(h: Herdr, ws: str, label: str) -> None:
    """Name the workspace after the hive only while it is small (RENAME_MAX_TABS tabs or fewer). A workspace
    with many chats already has a name Eddy chose for that area; the queen's own tab carries the hive label."""
    tabs = next((w.get("tab_count") for w in h.workspaces() if w["workspace_id"] == ws), None)
    if tabs is not None and tabs <= RENAME_MAX_TABS:
        h.workspace_rename(ws, label)


def make_room(r: Registry, h: Herdr, ws: str, pane: str, mine: dict, socket):
    """r's queen chat sits in ws. If another hive holds ws, take it when that hive is stale (every bee
    closed, queen idle); otherwise move this chat into a new workspace. Returns (workspace id, agent record)."""
    other = Registry.find_by_workspace(ws, socket)
    if not other or other.slug == r.slug:
        r.data["workspace_id"] = ws
        return ws, mine
    why = stale(other, h)
    if why:
        retire(other)
        print(f"took workspace {ws} from {other.slug} ({why}); it stays restorable")
        r.data["workspace_id"] = ws
        return ws, mine
    moved = h.pane_move_to_new_workspace(pane, f"◆ {r.data['label']}", below=ws)
    new_ws, pane, tab = moved["workspace_id"], moved["pane_id"], moved["tab_id"]
    r.data["workspace_id"] = new_ws
    r.data["orchestrator"].update(pane_id=pane, tab_id=tab)
    print(f"workspace {ws} belongs to {other.slug}, which is still in use; moved this chat to new workspace {new_ws}")
    return new_ws, {**mine, "pane_id": pane, "tab_id": tab}


def go_out(r: Registry, h: Herdr) -> str:
    """Move the queen chat into a workspace of its own, `◆ <label>`, where its bees' tabs open, just under
    the workspace it came from. Every hive works in its own workspace, so Eddy's workspaces are never relabelled or
    crowded, and the pair stay side by side."""
    o = r.data["orchestrator"]
    home = (r.data.get("home") or {}).get("workspace_id")
    moved = h.pane_move_to_new_workspace(o["pane_id"], f"◆ {r.data['label']}", below=home)
    r.data["workspace_id"] = moved["workspace_id"]
    o.update(pane_id=moved["pane_id"], tab_id=moved["tab_id"])
    r.save()
    return moved["workspace_id"]


def label_here(r: Registry, h: Herdr) -> None:
    """A solo queen's own workspace and tab carry the hive label while it has bees."""
    o = r.data["orchestrator"]
    h.workspace_rename(r.data["workspace_id"], f"◆ {r.data['label']}")
    if o.get("tab_id"):
        h.tab_rename(o["tab_id"], f"◆ {r.data['label']}")
    r.data["home"]["returned"] = False
    r.save()


def without_mark(label: str) -> str:
    """The name a tab or workspace goes back to: ◆ marks a live hive, and it may be left over from an earlier one."""
    return label.removeprefix("◆").strip()


def go_home(r: Registry, h: Herdr):
    """Every bee is closed: move the queen chat back to the workspace it started in, under its old tab
    name. Herdr closes the hive workspace once it is empty. Returns a line for Eddy, or None if it stays put."""
    home = r.data.get("home") or {}
    o = r.data["orchestrator"]
    if open_workers(r) or not home.get("workspace_id") or not r.data.get("workspace_id"):
        return None
    if r.data["workspace_id"] == home["workspace_id"]:
        if not home.get("solo") or home.get("returned"):
            return None
        if home.get("workspace_label"):
            h.workspace_rename(home["workspace_id"], without_mark(home["workspace_label"]))
        if o.get("tab_id"):
            h.tab_rename(o["tab_id"], without_mark(home.get("tab_label") or r.data["label"]))
        home["returned"] = True
        r.save()
        return "every bee closed: the workspace and the queen's tab have their old names back"
    if home["workspace_id"] not in {w["workspace_id"] for w in h.workspaces()}:
        return f"its home workspace {home['workspace_id']} is gone, so the queen stays in {r.data['workspace_id']}"
    if o.get("session_id") not in h.live_sessions():
        return None
    hive_ws = r.data["workspace_id"]
    moved = h.pane_move_to_workspace(o["pane_id"], home["workspace_id"], without_mark(home.get("tab_label") or r.data["label"]))
    o.update(pane_id=moved["pane_id"], tab_id=moved["tab_id"])
    r.data["workspace_id"] = None  # at home; the next spawn moves it out again
    r.save()
    left = "" if moved.get("closed_workspace_id") == hive_ws else f"; workspace {hive_ws} still has other tabs, so it stays"
    return f"every bee closed: the queen moved back to workspace {home['workspace_id']}{left}"


def at_home(r: Registry, ws: str) -> bool:
    return r.data.get("workspace_id") is None and (r.data.get("home") or {}).get("workspace_id") == ws


def old_server_sessions(r: Registry, socket) -> dict:
    """Live sessions in the Herdr server r was recorded on, when that is not `socket`; {} otherwise."""
    old_socket = r.data.get("herdr_socket")
    if not (old_socket and socket and old_socket != socket):
        return {}
    try:
        return herdr_for(r).live_sessions()
    except HerdrError:
        return {}  # that Herdr server is gone, so none of its chats are running


def refuse_stranded(r: Registry, live: dict) -> None:
    stranded = [w["label"] for w in r.data["workers"] if w["status"] in OPEN_STATES and w["session_id"] in live]
    if stranded:
        raise HiveError(f"{r.slug}'s bees ({', '.join(stranded)}) run in another Herdr session "
                        f"(socket {r.data.get('herdr_socket')}); run hive adopt from a pane in that session, or close them first")


def move_cwd(r: Registry, new: str) -> None:
    """The hive's folder was moved: point it, and bees that worked inside it, at the folder the chat is in now."""
    old = r.data.get("cwd")
    if not old or old == new or Path(old).exists() or not Path(new).is_dir():
        return
    r.data["cwd"] = new
    for w in r.data["workers"]:
        if w.get("cwd") == old or (w.get("cwd") or "").startswith(old + "/"):
            w["cwd"] = new + w["cwd"][len(old):]


def rehome(r: Registry):
    """r's queen is this chat, but it now runs somewhere else: its folder moved, or Herdr brought it back
    in another session or workspace. Point r at where the chat is now. Returns what moved, or None."""
    h = Herdr()
    try:
        ws, pane, mine, sid = own_pane(h)
    except HiveError:
        return None
    if sid != r.data["orchestrator"].get("session_id"):
        return None
    socket = os.environ.get("HERDR_SOCKET_PATH")
    o = r.data["orchestrator"]
    was = r.data.get("workspace_id")
    cwd = mine.get("cwd") or os.getcwd()
    if (ws, pane, socket) == (was, o.get("pane_id"), r.data.get("herdr_socket")) and (
            Path(r.data.get("cwd") or cwd).exists()):
        return None
    if at_home(r, ws) and socket == r.data.get("herdr_socket") and Path(r.data.get("cwd") or cwd).exists():
        if pane != o.get("pane_id"):
            o.update(pane_id=pane, tab_id=mine.get("tab_id"))
            r.save()
        return None
    refuse_stranded(r, old_server_sessions(r, socket))
    o.update(pane_id=pane, tab_id=mine.get("tab_id"))
    r.data["herdr_socket"] = socket
    r.data.pop("retired_at", None)
    move_cwd(r, cwd)
    ws, mine = make_room(r, h, ws, pane, mine, socket)
    r.save()
    label_workspace(h, ws, f"◆ {r.data['label']}")
    if mine.get("tab_id"):
        h.tab_rename(mine["tab_id"], f"◆ {r.data['label']}")
    return f"moved {r.slug} to where this chat runs now: workspace {was} to {ws}, folder {r.data['cwd']}"


def cmd_init(a) -> None:
    h = Herdr()
    ws, pane, mine, sid = own_pane(h)
    mine_already = registry_of_session(sid)
    if mine_already and mine_already.data["orchestrator"].get("session_id") == sid and not mine_already.data.get("retired_at"):
        left = open_workers(mine_already)
        if left:
            raise HiveError(f"this chat already is the queen of {mine_already.slug}, which still has open bees "
                            f"({', '.join(left)}); close them first, or run hive adopt {mine_already.slug} if it moved")
        retire(mine_already)  # its bees are all closed: that hive is done, this chat starts the next one here
        print(f"retired {mine_already.slug} (every bee closed); it stays restorable")
    socket = os.environ.get("HERDR_SOCKET_PATH")
    r = Registry.create(a.label, workspace_id=None, cwd=(mine.get("cwd") or os.getcwd()), orchestrator={
        "name": live_name(sid) or a.name or "", "session_id": sid, "model": a.model, "pane_id": pane, "tab_id": mine.get("tab_id")})
    r.data["herdr_socket"] = socket
    tabs = h.tabs()
    tab_label = next((t.get("label") for t in tabs if t["tab_id"] == mine.get("tab_id")), None)
    solo = [t["tab_id"] for t in tabs if t.get("workspace_id") == ws] == [mine.get("tab_id")]
    ws_label = next((w.get("label") for w in h.workspaces() if w["workspace_id"] == ws), None)
    r.data["home"] = {"workspace_id": ws, "tab_label": tab_label, "workspace_label": ws_label, "solo": solo}
    r.save()
    if solo:
        # the chat's tab is its workspace's only one: moving it out would close the workspace it returns to,
        # so the hive works here and the names go back when every bee is closed
        ws, mine = make_room(r, h, ws, pane, mine, socket)
        r.save()
        if r.data["workspace_id"] == ws and r.data["home"]["workspace_id"] == ws:
            label_here(r, h)
        else:
            r.data["home"]["solo"] = False  # make_room moved it out after all
            r.save()
    else:
        ws = go_out(r, h)
    name = ensure_queen_name(r, h)
    print(f"queen {r.slug} in {ws} (session {sid}, SendMessage name {name!r})")


def cmd_adopt(a) -> None:
    """This chat becomes the queen of an existing hive, in the workspace it is in."""
    h = Herdr()
    ws, pane, mine, sid = own_pane(h)
    r = Registry.load(a.slug)
    old = r.data["orchestrator"]
    if old.get("session_id") == sid:
        print(rehome(r) or f"this chat already is the queen of {r.slug}")
        return
    if old.get("session_id") in h.live_sessions():
        raise HiveError(f"{r.slug}'s queen chat is still running (pane {old.get('pane_id')}); close it first")
    socket = os.environ.get("HERDR_SOCKET_PATH")
    live = old_server_sessions(r, socket)
    if old.get("session_id") in live:
        raise HiveError(f"{r.slug}'s queen chat is still running in another Herdr session "
                        f"(socket {r.data.get('herdr_socket')}); close it first")
    refuse_stranded(r, live)
    move_cwd(r, mine.get("cwd") or os.getcwd())
    r.data["orchestrator"] = {"name": live_name(sid) or "", "session_id": sid, "model": a.model,
                              "pane_id": pane, "tab_id": mine.get("tab_id")}
    r.data["previous_orchestrators"] = r.data.get("previous_orchestrators", []) + [old]
    r.data["herdr_socket"] = socket
    r.data.pop("retired_at", None)
    ws, mine = make_room(r, h, ws, pane, mine, socket)
    r.save()
    label_workspace(h, ws, f"◆ {r.data['label']}")
    if mine.get("tab_id"):
        h.tab_rename(mine["tab_id"], f"◆ {r.data['label']}")
    name = ensure_queen_name(r, h)
    left = open_workers(r)
    print(f"adopted {r.slug} (SendMessage name {name!r})" + (f"; open bees: {', '.join(left)}" if left else ""))


def check_machine(hc: Hc, machine: str, cwd) -> None:
    if not cwd:
        raise HiveError("a bee on another machine needs --cwd: an absolute path on that machine")
    if not str(cwd).startswith("/"):
        raise HiveError(f"--cwd {cwd!r} must be absolute on {machine}; hive cannot expand paths there")
    names = [m["name"] for m in hc.machines()]
    if machine not in names:
        raise HiveError(f"no hc machine {machine!r}; hc machine ls knows: {', '.join(names) or 'none'} "
                        f"(add one with: hc machine add <ssh host> --name {machine} --install)")


def screen_tail(hc: Hc, address: str, lines: int = 12) -> str:
    try:
        text = hc.screen(address)
    except HcError as e:
        return f"(screen unreadable: {e})"
    kept = [l.rstrip() for l in text.splitlines() if l.strip()]
    return "\n".join(kept[-lines:])


def settle_remote(hc: Hc, address: str) -> None:
    """Wait for the remote Claude to report a status. A fresh folder shows a trust dialog first, which reports
    nothing; hive answers it. Raises with the screen when nothing arrives."""
    for _ in range(SETTLE_FIRST):
        if hc.status(hc.get(address)) not in ("", "finished"):
            return
        time.sleep(SETTLE_POLL)
    screen = screen_tail(hc, address)
    if "trust" in screen.lower():
        hc.keys(address, "down", "enter")
        for _ in range(SETTLE_AFTER):
            if hc.status(hc.get(address)) not in ("", "finished"):
                return
            time.sleep(SETTLE_POLL)
        screen = screen_tail(hc, address)
    raise HiveError(f"{address} never reported a status; its screen:\n{screen}")


def start_remote(hc: Hc, h: Herdr, r: Registry, w: dict, args: list) -> None:
    """Start the bee's Claude on its machine, settle it, then open a Mac tab attached to it."""
    w["address"] = hc.start(w["machine"], w["cwd"], w["slug"], remote_command(args))
    r.save()
    settle_remote(hc, w["address"])
    w["tab_id"], w["pane_id"] = h.tab_create(r.data["workspace_id"], tab_label(w), str(Path.home()))
    r.save()
    h.pane_run(w["pane_id"], f"hc attach {w['address']}")


def spawn_remote(r: Registry, h: Herdr, w: dict, brief_text: str) -> None:
    hc = Hc()
    home = hc.home(w["machine"]).rstrip("/")
    w["remote_brief"] = f"{home}/.local/state/hive/{r.slug}/briefs/{w['slug']}.md"
    w["remote_handoff"] = f"{home}/.local/state/hive/{r.slug}/handoffs/{w['slug']}.txt"
    r.save()
    hc.write_file(w["machine"], w["remote_brief"], brief_text)
    args = claude_args(w["session_id"], w["label"], w["model"], resume=False) + [remote_kickoff(w)]
    try:
        start_remote(hc, h, r, w, args)
    except (HcError, HiveError, HerdrError):
        if w.get("address"):  # never leave a half started bee on the box
            try:
                hc.kill(w["address"])
                hc.rm(w["address"])
            except HcError:
                pass
            w["address"] = None
        raise


def cmd_spawn(a) -> None:
    r = current_registry(a.orch)
    h = herdr_for(r)
    orch_name = ensure_queen_name(r, h)
    brief_src = Path(a.brief).expanduser()
    if not brief_src.is_file():
        raise HiveError(f"brief not found: {brief_src}")
    if a.on:
        check_machine(Hc(), a.on, a.cwd)
    same = [x for x in r.data["workers"] if x["label"].lower() == a.label.strip().lower()]
    if any(x["status"] != "failed" for x in same):
        raise HiveError(f"a bee labelled {a.label!r} already exists in {r.slug}; pick another label "
                        f"(or hive restore it if it is closed)")
    open_tabs = {t["tab_id"] for t in h.tabs()} if any(x.get("tab_id") for x in same) else set()
    for x in same:  # a retry replaces the failed spawn, and its tab if one was left behind
        if x.get("tab_id") in open_tabs:
            h.tab_close(x["tab_id"])
    r.data["workers"] = [x for x in r.data["workers"] if x not in same]
    if not r.data.get("workspace_id"):
        print(f"queen moved to its hive workspace {go_out(r, h)}")
    elif (r.data.get("home") or {}).get("returned"):
        label_here(r, h)
    cwd = a.cwd if a.on else str(Path(a.cwd or r.data["cwd"]).expanduser())
    w = new_worker(r, a.label, model=a.model, why=a.why, cwd=cwd, brief="")
    w["machine"] = a.on
    briefs = state_dir() / r.slug / "briefs"
    briefs.mkdir(parents=True, exist_ok=True)
    w["brief"] = str(briefs / f"{w['slug']}.md")
    shutil.copyfile(brief_src, w["brief"])
    r.data["workers"].append(w)
    r.save()
    try:
        if a.on:
            spawn_remote(r, h, w, brief_src.read_text())
        else:
            w["tab_id"], w["pane_id"] = h.tab_create(r.data["workspace_id"], tab_label(w), w["cwd"])
            r.save()
            h.agent_start(w["slug"], w["pane_id"], claude_args(w["session_id"], w["label"], w["model"], resume=False))
            h.agent_prompt(w["slug"], kickoff(w, orch_name))
    except (HerdrError, HcError, HiveError) as e:
        set_status(w, "failed")
        w["error"] = str(e)
        if w.get("tab_id"):  # never leave an empty tab behind
            try:
                h.tab_close(w["tab_id"])
                w["tab_id"] = w["pane_id"] = None
            except HerdrError:
                pass
        r.save()
        raise
    set_status(w, "live")
    r.save()
    where_ = f"{w['address']} (tab {w['tab_id']})" if a.on else w["tab_id"]
    print(f"spawned {w['label']} as {w['slug']} on {w['model']} in {where_} (session {w['session_id']})")


def cmd_handoff(a) -> None:
    r = current_registry(a.orch)
    w = need_worker(r, a.label)
    text = sys.stdin.read() if a.file == "-" else Path(a.file).read_text()
    if not text.strip():
        raise HiveError("handoff text is empty")
    w["handoff"] = {"text": text.strip(), "at": now()}
    set_status(w, "handed-off")
    r.save()
    print(f"handoff recorded for {w['label']}")


def cmd_orchestrator(a) -> None:
    r = current_registry(a.orch)
    name = refresh_orchestrator(r)
    if not name:
        o = r.data["orchestrator"]
        raise HiveError(f"queen chat for {r.slug} is not running (session {o.get('session_id')}, "
                        f"last known as {o.get('name')}); do not guess another session")
    print(name)


def cmd_mark_review(a) -> None:
    r = current_registry(a.orch)
    w = need_worker(r, a.label)
    set_status(w, "review")
    w["review_reason"] = a.reason
    r.save()
    if w.get("tab_id"):
        herdr_for(r).tab_rename(w["tab_id"], tab_label(w))
    print(f"{w['label']} awaits review")


def cmd_close(a) -> None:
    r = current_registry(a.orch)
    w = need_worker(r, a.label)
    if w["status"] == "closed":
        print(f"{w['label']} is already closed")
        return
    if not w.get("handoff") and not a.force:
        raise HiveError(f"{w['label']} has no handoff on record; record one first or pass --force")
    h = herdr_for(r)
    if w.get("machine"):
        hc = Hc()
        if w.get("address") and hc.status(hc.get(w["address"])) == "working":
            raise HiveError(f"{w['label']} is still working on {w['machine']}; not closing")
        if w.get("address"):
            hc.kill(w["address"])
            hc.rm(w["address"])
    else:
        agent = h.live_sessions().get(w["session_id"])
        if agent and agent.get("agent_status") == "working":
            raise HiveError(f"{w['label']} is still working; not closing")
    if w.get("tab_id") and any(t["tab_id"] == w["tab_id"] for t in h.tabs()):
        h.tab_close(w["tab_id"])
    set_status(w, "closed")
    w["closed_at"] = now()
    r.save()
    print(f"closed {w['label']} (restore with: hive restore {r.slug} {w['slug']})")
    back = go_home(r, h)
    if back:
        print(back)


def sync_remote(r: Registry, hc: Hc = None) -> list:
    """Mirror each remote bee's hc terminal into the registry: a finished or vanished terminal is detached, a
    live one is back, and a handoff file the bee wrote becomes its recorded handoff. Returns the detached labels."""
    changed = []
    remote = [w for w in r.data["workers"] if w.get("machine") and w["status"] in OPEN_STATES and w.get("address")]
    if not remote:
        return changed
    hc = hc or Hc()
    for w in remote:
        alive = hc.status(hc.get(w["address"])) != "finished"
        if not alive and w["status"] != "detached":
            set_status(w, "detached")
            changed.append(w["label"])
        elif alive and w["status"] == "detached":
            set_status(w, "handed-off" if w.get("handoff") else "live")
        if alive and not w.get("handoff") and w.get("remote_handoff"):
            text = hc.read_file(w["machine"], w["remote_handoff"])
            if text and text.strip():
                w["handoff"] = {"text": text.strip(), "at": now()}
                if w["status"] == "live":
                    set_status(w, "handed-off")
    r.save()
    return changed


def sync(r: Registry, h: Herdr) -> list:
    live = h.live_sessions()
    changed = sync_remote(r)
    for w in r.data["workers"]:
        if w.get("machine"):
            continue
        if w["status"] in ("live", "handed-off", "review") and w["session_id"] not in live:
            set_status(w, "detached")
            changed.append(w["label"])
        elif w["session_id"] in live:
            if w["status"] == "detached":
                set_status(w, "handed-off" if w.get("handoff") else "live")
            w["tab_id"] = live[w["session_id"]].get("tab_id") or w.get("tab_id")
            w["pane_id"] = live[w["session_id"]].get("pane_id") or w.get("pane_id")
    r.save()
    return changed


def cmd_sync(a) -> None:
    r = current_registry(a.orch)
    h = herdr_for(r)
    ensure_queen_name(r, h)
    changed = sync(r, h)
    print(f"detached: {', '.join(changed)}" if changed else "in sync")


def where(r: Registry) -> str:
    if r.data.get("workspace_id"):
        return r.data["workspace_id"]
    if r.data.get("retired_at"):
        return "retired"
    home = (r.data.get("home") or {}).get("workspace_id")
    return f"home {home}" if home else "none"


def cmd_wait(a) -> None:
    """Block until a remote bee stops working (done, blocked, error, exit) or hc's timeout, then show what it has."""
    r = current_registry(a.orch)
    w = need_worker(r, a.label)
    if not w.get("machine"):
        raise HiveError(f"{w['label']} is a local bee; it reports by SendMessage, so there is nothing to wait on")
    if not w.get("address") or w["status"] not in OPEN_STATES:
        raise HiveError(f"{w['label']} is {w['status']} with no terminal to wait on; hive restore it first")
    hc = Hc()
    res = hc.wait(w["address"], a.timeout)
    sync_remote(r, hc)
    status = hc.status(hc.get(w["address"])) if res.get("reason") != "timeout" else "working"
    if w.get("handoff"):
        print(f"{w['label']} handed off ({status}):\n{w['handoff']['text']}")
    elif res.get("reason") == "timeout":
        print(f"{w['label']} is still working after {a.timeout}s; wait again or hc attach {w['address']}")
    elif status == "finished":
        print(f"{w['label']}'s terminal ended with no handoff; last screen:\n{screen_tail(hc, w['address'])}")
    else:
        print(f"{w['label']} is {status} with no handoff yet; its screen:\n{screen_tail(hc, w['address'])}")


def cmd_status(a) -> None:
    r = current_registry(a.orch)
    try:
        sync_remote(r)
    except HcError as e:
        print(f"hive: remote bees not refreshed: {e}", file=sys.stderr)
    o = r.data["orchestrator"]
    running = "" if refresh_orchestrator(r) else ", not running"
    print(f"◆ {r.data['label']}  [{r.slug}]  workspace {where(r)}  queen {o.get('name')} ({o.get('model')}{running})")
    for w in r.data["workers"]:
        last = (w.get("handoff") or {}).get("text", "").splitlines()
        tail = last[1] if len(last) > 1 else (last[0] if last else "")
        print(f"  {w['status']:<10} {w['model']:<5} {w['label']:<28} {w.get('tab_id') or '':<8} {tail[:60]}")

def cmd_ls(a) -> None:
    for r in Registry.all():
        counts = {}
        for w in r.data["workers"]:
            counts[w["status"]] = counts.get(w["status"], 0) + 1
        summary = ", ".join(f"{n} {s}" for s, n in sorted(counts.items())) or "no bees"
        print(f"{r.slug:<28} {r.data['label']:<32} {where(r):<8} {summary}")


def restore_one(r: Registry, include_closed: bool, labels: list) -> None:
    h = herdr_for(r)
    live = h.live_sessions()
    names = {a.get("name") for a in h.agents() if a.get("name")}
    ws_ids = {x["workspace_id"] for x in h.workspaces()}
    o = r.data["orchestrator"]
    if r.data["workspace_id"] not in ws_ids and o.get("session_id") in live:
        o["pane_id"] = live[o["session_id"]]["pane_id"]
        print(f"moved the queen to workspace {go_out(r, h)} for {r.slug}")
    elif r.data["workspace_id"] not in ws_ids:
        ws, tab, pane = h.workspace_create(f"◆ {r.data['label']}", r.data["cwd"],
                                            below=(r.data.get("home") or {}).get("workspace_id"))
        r.data["workspace_id"] = ws
        r.save()
        if o.get("session_id") not in live:
            h.agent_start(slugify("orch-" + r.slug, names), pane, claude_args(o["session_id"], queen_name(r.data["label"]), o.get("model", "fable"), resume=True))
            o.update(tab_id=tab, pane_id=pane)
            r.save()
        print(f"rebuilt workspace {ws} for {r.slug}")
    elif o.get("session_id") and o["session_id"] not in live:
        tab, pane = h.tab_create(r.data["workspace_id"], f"◆ {r.data['label']}", r.data["cwd"])
        h.agent_start(slugify("orch-" + r.slug, names), pane, claude_args(o["session_id"], queen_name(r.data["label"]), o.get("model", "fable"), resume=True))
        o.update(tab_id=tab, pane_id=pane)
        r.save()
    wanted = [need_worker(r, l) for l in labels] if labels else [
        w for w in r.data["workers"] if w["status"] in OPEN_STATES or (include_closed and w["status"] == "closed")]
    for w in wanted:
        if w.get("machine"):
            restore_remote(r, h, w)
            continue
        if w["session_id"] in live:
            print(f"  {w['label']}: already open")
            continue
        if w["status"] in ("detached", "closed", "failed"):
            set_status(w, "handed-off" if w.get("handoff") else "live")
        name = slugify(w["slug"], names)
        names.add(name)
        w["tab_id"], w["pane_id"] = h.tab_create(r.data["workspace_id"], tab_label(w), w["cwd"])
        r.save()
        h.agent_start(name, w["pane_id"], claude_args(w["session_id"], w["label"], w["model"], resume=True))
        w["slug"] = name
        r.save()
        print(f"  {w['label']}: resumed in {w['tab_id']}")


def restore_remote(r: Registry, h: Herdr, w: dict) -> None:
    """Resume a remote bee's Claude on its machine and reopen the Mac tab attached to it."""
    hc = Hc()
    if w.get("address") and hc.status(hc.get(w["address"])) != "finished":
        print(f"  {w['label']}: already open on {w['machine']} ({w['address']})")
        return
    if w.get("address"):
        hc.rm(w["address"])
    if w["status"] in ("detached", "closed", "failed"):
        set_status(w, "handed-off" if w.get("handoff") else "live")
    if w.get("tab_id") and any(t["tab_id"] == w["tab_id"] for t in h.tabs()):
        h.tab_close(w["tab_id"])
    w["tab_id"] = w["pane_id"] = None
    start_remote(hc, h, r, w, claude_args(w["session_id"], w["label"], w["model"], resume=True))
    r.save()
    print(f"  {w['label']}: resumed on {w['machine']} as {w['address']} (tab {w['tab_id']})")


def cmd_restore(a) -> None:
    if a.every:
        regs = Registry.all()
    else:
        regs = [current_registry(a.orch)]
    for r in regs:
        restore_one(r, include_closed=a.all, labels=a.labels if not a.every else [])


def cmd_reap(a) -> None:
    from hive import reaper
    try:
        if a.install:
            print(f"reaper installed: {reaper.install()} (every 60s, grace {reaper.GRACE}s)")
        elif a.uninstall:
            reaper.uninstall()
            print("reaper removed")
        else:
            reaper.reap(dry_run=a.dry_run)
    except (RuntimeError, subprocess.SubprocessError) as e:
        raise HiveError(f"reap: {e}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hive", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        s = sub.add_parser(name, help=help_)
        s.set_defaults(fn=fn)
        return s

    s = add("init", cmd_init, "adopt this Herdr workspace for the queen chat in this pane")
    s.add_argument("label")
    s.add_argument("--name", help="deprecated: init renames this chat to 'queen: <label>' itself")
    s.add_argument("--model", choices=MODEL_IDS, default="fable")

    s = add("adopt", cmd_adopt, "become the queen of an existing hive whose chat is gone")
    s.add_argument("slug", help="queen slug (see: hive ls)")
    s.add_argument("--model", choices=MODEL_IDS, default="fable")

    s = add("spawn", cmd_spawn, "open a labelled tab and start a bee chat")
    s.add_argument("label")
    s.add_argument("--model", choices=MODEL_IDS, required=True)
    s.add_argument("--why", required=True, help="one line: why this model")
    s.add_argument("--brief", required=True, help="markdown brief file")
    s.add_argument("--cwd", help="folder for the bee; with --on, an absolute path on that machine (required)")
    s.add_argument("--on", metavar="MACHINE", help="run the bee on this hc machine (hc machine ls) instead of a tab here")

    s = add("handoff", cmd_handoff, "record a bee's HIVE HANDOFF message")
    s.add_argument("label")
    s.add_argument("--file", required=True, help="file with the handoff text, or - for stdin")

    s = add("wait", cmd_wait, "block until a remote bee stops working, then print its handoff or screen")
    s.add_argument("label")
    s.add_argument("--timeout", type=int, default=WAIT_TIMEOUT, help=f"seconds before giving up (default {WAIT_TIMEOUT})")

    add("queen", cmd_orchestrator, "print the queen's current SendMessage name")

    add("shepherd", cmd_orchestrator, "old name for hive queen")
    add("orchestrator", cmd_orchestrator, "old name for hive queen")

    s = add("mark-review", cmd_mark_review, "flag a bee as awaiting Eddy's review")
    s.add_argument("label")
    s.add_argument("--reason", default="")

    s = add("close", cmd_close, "close a bee's tab after its handoff")
    s.add_argument("label")
    s.add_argument("--force", action="store_true", help="close without a recorded handoff")

    add("status", cmd_status, "bees of this queen")
    add("ls", cmd_ls, "every queen on record")
    add("sync", cmd_sync, "mark bees whose tabs vanished as detached")

    s = add("restore", cmd_restore, "reopen a queen and its bees")
    s.add_argument("labels", nargs="*", help="only these bees")
    s.add_argument("--all", action="store_true", help="include closed bees")
    s.add_argument("--every", action="store_true", help="every queen on record")

    s = add("reap", cmd_reap, "stop Herdr sessions left detached and idle (run by launchd)")
    s.add_argument("--dry-run", action="store_true", help="print what each session would get, change nothing")
    s.add_argument("--install", action="store_true", help="install the launchd job that runs this every minute")
    s.add_argument("--uninstall", action="store_true", help="remove the launchd job")

    drone.add_parser(sub)

    for sp in sub.choices.values():
        sp.add_argument("--orch", help="queen slug (default: the one owning this workspace)")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "restore" and args.labels and not args.orch:
        # `hive restore <orch> [labels]`: first positional names the orchestrator when it is one
        if (state_dir() / f"{args.labels[0]}.json").exists():
            args.orch, args.labels = args.labels[0], args.labels[1:]
    try:
        args.fn(args)
    except (HiveError, HerdrError, HcError, RegistryError, DroneError) as e:
        print(f"hive: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
