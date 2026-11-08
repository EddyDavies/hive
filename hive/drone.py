"""hive drone: fork this chat into a new Herdr tab that takes one slice of the work and carries on alone.

A drone is a bee that went on a journey. It needs no queen: any Claude chat inside Herdr can launch one. By default
the drone is a fork of the launching chat (claude --resume <parent> --fork-session), so it starts with the whole
conversation and needs no context copied over; the task file only says which slice is now its job. The parent keeps
going on the main thread. The drone records a DRONE REPORT here and pings the parent over SendMessage when done.

Records: <state dir>/drones/<slug>.json, one per drone, written before its tab opens.
"""

import json
import os
import sys
import uuid
from pathlib import Path

from hive.herdr import Herdr, HerdrError
from hive.registry import now, slugify, state_dir

MARK = "✈ "
OPEN = ("live", "reported", "detached")


class DroneError(Exception):
    pass


def drones_dir() -> Path:
    d = state_dir() / "drones"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save(d: dict) -> None:
    d["updated_at"] = now()
    path = drones_dir() / f"{d['slug']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def all_drones() -> list:
    out = []
    for p in sorted(drones_dir().glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except (OSError, ValueError):
            print(f"hive: unreadable drone record {p}", file=sys.stderr)
    return sorted(out, key=lambda d: d.get("created_at", ""))


def find(name: str) -> dict:
    """By slug, then by label (newest wins), then by session id."""
    key = name.strip().lower()
    drones = all_drones()
    for d in drones:
        if d["slug"] == key:
            return d
    matches = [d for d in drones if d["label"].lower() == key or d["session_id"] == name.strip()]
    if not matches:
        raise DroneError(f"no drone {name!r} (see: hive drone ls)")
    return matches[-1]


def mine():
    """This chat's own drone record, when this chat is a drone."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    return next((d for d in all_drones() if sid and d["session_id"] == sid), None)


def transcript(session_id: str):
    from hive.cli import projects_dir
    return next(iter(sorted(projects_dir().glob(f"*/{session_id}.jsonl"))), None)


def transcript_cwd(path: Path):
    """The folder a chat started in. Claude resumes a session only from there, so a fork must start there too."""
    try:
        with open(path) as f:
            for line in f:
                try:
                    cwd = json.loads(line).get("cwd")
                except ValueError:
                    continue
                if cwd:
                    return cwd
    except OSError:
        return None
    return None


def claude_args(d: dict, resume: bool) -> list:
    from hive.cli import MODEL_IDS
    if resume:
        head = ["--resume", d["session_id"]]
    elif d["mode"] == "fork":
        head = ["--resume", d["parent"]["session_id"], "--fork-session", "--session-id", d["session_id"]]
    else:
        head = ["--session-id", d["session_id"]]
    return head + ["--name", f"drone: {d['label']}", "--model", MODEL_IDS[d["model"]], "--dangerously-skip-permissions"]


def kickoff(d: dict) -> str:
    parent = d["parent"].get("name") or "the chat that launched you"
    if d["mode"] == "fork":
        opening = (f'You are now a hive drone named "{d["label"]}": a fork of the conversation above, launched into '
                   f'your own Herdr tab. Everything above is background you already have. From here on your only job '
                   f'is the slice in your task file, not the rest of that conversation. ')
    else:
        opening = (f'You are a hive drone named "{d["label"]}", launched into your own Herdr tab by another chat. '
                   f'Your task file is your whole context. ')
    return (opening +
            f'Load the hive-drone skill now. Your task is at {d["task"]}; read it in full and start. '
            f'The parent chat ({parent!r}) carries on with its own thread and is not waiting on you: do not do its '
            f'other work and do not ask it for permission to start. When you are done, record a DRONE REPORT with '
            f'`hive drone report` and ping the parent as the skill says.')


def tab_label(d: dict) -> str:
    return MARK + d["label"]


def live(h: Herdr) -> dict:
    return h.live_sessions()


def cmd_launch(a) -> None:
    from hive.cli import live_name, own_pane
    h = Herdr()
    ws, pane, me, sid = own_pane(h)
    text = sys.stdin.read() if a.task == "-" else Path(a.task).expanduser().read_text()
    if not text.strip():
        raise DroneError("the task is empty; write the slice the drone owns")
    if any(d["label"].lower() == a.label.strip().lower() and d["status"] in OPEN for d in all_drones()):
        raise DroneError(f"a drone labelled {a.label!r} is still open; land it first or pick another label")
    mode = "fresh" if a.fresh else "fork"
    cwd = a.cwd and str(Path(a.cwd).expanduser())
    if mode == "fork":
        src = transcript(sid)
        if not src:
            raise DroneError(f"cannot find this chat's transcript (session {sid}) to fork; pass --fresh to start the "
                             f"drone from the task file alone")
        started = transcript_cwd(src) or me.get("cwd") or os.getcwd()
        if cwd and cwd != started:
            raise DroneError(f"a fork must start where this chat started ({started}), since Claude resumes a chat only "
                             f"from its own folder; drop --cwd and say the folder in the task, or pass --fresh")
        cwd = started
    cwd = cwd or me.get("cwd") or os.getcwd()
    taken = {p.stem for p in drones_dir().glob("*.json")}
    slug = slugify(a.label, taken)
    tasks = drones_dir() / "tasks"
    tasks.mkdir(exist_ok=True)
    task_path = tasks / f"{slug}.md"
    task_path.write_text(text.strip() + "\n")
    d = {
        "label": a.label.strip(), "slug": slug, "model": a.model, "mode": mode, "session_id": str(uuid.uuid4()),
        "cwd": cwd, "task": str(task_path), "status": "starting", "tab_id": None, "pane_id": None,
        "workspace_id": ws, "herdr_socket": os.environ.get("HERDR_SOCKET_PATH"), "agent_name": None,
        "parent": {"session_id": sid, "name": live_name(sid) or "", "pane_id": pane, "tab_id": me.get("tab_id")},
        "report": None, "error": None, "created_at": now(),
    }
    save(d)
    try:
        names = {x.get("name") for x in h.agents() if x.get("name")}
        d["agent_name"] = slugify("d-" + slug, names)
        d["tab_id"], d["pane_id"] = h.tab_create(ws, tab_label(d), cwd)
        save(d)
        h.agent_start(d["agent_name"], d["pane_id"], claude_args(d, resume=False))
        h.agent_prompt(d["agent_name"], kickoff(d))
    except HerdrError as e:
        d["status"], d["error"] = "failed", str(e)
        if d.get("tab_id"):  # never leave an empty tab behind
            try:
                h.tab_close(d["tab_id"])
                d["tab_id"] = d["pane_id"] = None
            except HerdrError:
                pass
        save(d)
        raise
    d["status"] = "live"
    save(d)
    print(f"launched drone {d['label']} ({mode}, {a.model}) in tab {d['tab_id']}, session {d['session_id']}; "
          f"it reports with hive drone report and pings this chat")


def cmd_report(a) -> None:
    d = find(a.label) if a.label else mine()
    if d is None:
        raise DroneError("this chat is not a drone on record; pass the drone's label")
    text = sys.stdin.read() if a.file == "-" else Path(a.file).expanduser().read_text()
    if not text.strip():
        raise DroneError("report text is empty")
    d["report"] = {"text": text.strip(), "at": now()}
    d["status"] = "reported"
    save(d)
    print(f"report recorded for drone {d['label']}")
    name = parent_name(d)
    print(f"parent SendMessage name: {name}" if name else
          "parent chat is not running; the report is on record for hive drone ls")


def parent_name(d: dict):
    from hive.cli import live_name
    name = live_name(d["parent"]["session_id"])
    if name and name != d["parent"].get("name"):
        d["parent"]["name"] = name
        save(d)
    return name


def cmd_parent(a) -> None:
    d = find(a.label) if a.label else mine()
    if d is None:
        raise DroneError("this chat is not a drone on record; pass the drone's label")
    name = parent_name(d)
    if not name:
        raise DroneError(f"the parent chat (session {d['parent']['session_id']}, last known as "
                         f"{d['parent'].get('name')!r}) is not running; leave the report on record, do not guess")
    print(name)


def sync(h: Herdr) -> None:
    sessions = live(h)
    for d in all_drones():
        if d["status"] in ("live", "reported") and d["session_id"] not in sessions:
            d["status"] = "detached"
            save(d)
        elif d["status"] == "detached" and d["session_id"] in sessions:
            d["status"] = "reported" if d.get("report") else "live"
            save(d)
        if d["session_id"] in sessions:
            a = sessions[d["session_id"]]
            if a.get("tab_id") and a.get("tab_id") != d.get("tab_id"):
                d["tab_id"], d["pane_id"] = a.get("tab_id"), a.get("pane_id")
                save(d)


def cmd_ls(a) -> None:
    try:
        sync(Herdr())
    except HerdrError as e:
        print(f"hive: drone states not refreshed: {e}", file=sys.stderr)
    drones = all_drones() if a.all else [d for d in all_drones() if d["status"] in OPEN]
    if not drones:
        print("no open drones" + ("" if a.all else " (--all shows landed ones)"))
        return
    for d in drones:
        lines = (d.get("report") or {}).get("text", "").splitlines()
        summary = next((l.split(":", 1)[1].strip() for l in lines if l.lower().startswith("summary:")), "")
        print(f"  {d['status']:<9} {d['model']:<5} {d['label']:<30} {d.get('tab_id') or '':<10} {summary[:60]}")


def cmd_show(a) -> None:
    d = find(a.label)
    print(f"{MARK}{d['label']}  [{d['slug']}]  {d['status']}, {d['model']}, {d['mode']}, tab {d.get('tab_id')}")
    print(f"  task: {d['task']}")
    print(f"  parent: {d['parent'].get('name') or d['parent']['session_id']}")
    print(d["report"]["text"] if d.get("report") else "  no report yet")


def cmd_land(a) -> None:
    d = find(a.label)
    if d["status"] in ("landed", "failed"):
        print(f"drone {d['label']} is already {d['status']}")
        return
    if not d.get("report") and not a.force:
        raise DroneError(f"drone {d['label']} has no report on record; wait for it or pass --force")
    h = Herdr(d.get("herdr_socket"))
    agent = live(h).get(d["session_id"])
    if agent and agent.get("agent_status") == "working" and not a.force:
        raise DroneError(f"drone {d['label']} is still working; not landing it")
    tab = (agent or {}).get("tab_id") or d.get("tab_id")
    if tab and any(t["tab_id"] == tab for t in h.tabs()):
        h.tab_close(tab)
    d["status"], d["landed_at"] = "landed", now()
    save(d)
    print(f"landed drone {d['label']} (reopen with: hive drone restore {d['slug']})")


def cmd_restore(a) -> None:
    from hive.cli import own_pane
    d = find(a.label)
    h = Herdr()
    if d["session_id"] in live(h):
        print(f"drone {d['label']} is already open")
        return
    try:
        ws = own_pane(h)[0]
    except Exception:
        ws = d.get("workspace_id")
    names = {x.get("name") for x in h.agents() if x.get("name")}
    d["agent_name"] = slugify("d-" + d["slug"], names)
    d["tab_id"], d["pane_id"] = h.tab_create(ws, tab_label(d), d["cwd"])
    d["workspace_id"] = ws
    save(d)
    h.agent_start(d["agent_name"], d["pane_id"], claude_args(d, resume=True))
    d["status"] = "reported" if d.get("report") else "live"
    save(d)
    print(f"drone {d['label']} resumed in tab {d['tab_id']}")


def add_parser(sub) -> None:
    from hive.cli import MODEL_IDS
    p = sub.add_parser("drone", help="fork this chat into a new tab that takes one slice and carries on alone")
    ds = p.add_subparsers(dest="drone_cmd", required=True)

    def add(name, fn, help_):
        s = ds.add_parser(name, help=help_)
        s.set_defaults(fn=fn)
        return s

    s = add("launch", cmd_launch, "fork this chat into a drone tab and hand it its slice")
    s.add_argument("label", help="2 to 4 plain words; the tab shows ✈ <label>")
    s.add_argument("--task", required=True, help="markdown file naming the slice the drone owns, or - for stdin")
    s.add_argument("--model", choices=MODEL_IDS, default="opus")
    s.add_argument("--fresh", action="store_true", help="start from the task file alone, not a fork of this chat")
    s.add_argument("--cwd", help="folder for a --fresh drone (a fork always starts where this chat started)")

    s = add("report", cmd_report, "a drone records its DRONE REPORT")
    s.add_argument("label", nargs="?", help="default: this chat's own drone record")
    s.add_argument("--file", required=True, help="file with the report, or - for stdin")

    s = add("parent", cmd_parent, "print the launching chat's current SendMessage name")
    s.add_argument("label", nargs="?", help="default: this chat's own drone record")

    s = add("ls", cmd_ls, "open drones and their report summaries")
    s.add_argument("--all", action="store_true", help="include landed and failed drones")

    s = add("show", cmd_show, "one drone's record and full report")
    s.add_argument("label")

    s = add("land", cmd_land, "close a drone's tab once it has reported")
    s.add_argument("label")
    s.add_argument("--force", action="store_true", help="land without a report, or while it works")

    s = add("restore", cmd_restore, "reopen a landed or detached drone, conversation intact")
    s.add_argument("label")
