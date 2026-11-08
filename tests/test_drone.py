import json

import pytest

from hive import cli, drone


@pytest.fixture
def parent(fake, monkeypatch, tmp_path):
    """A plain chat (no hive) live in pane w1:p1, whose transcript started in /work/app."""
    monkeypatch.setenv("HERDR_WORKSPACE_ID", "w1")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p1")
    fake.seed(workspaces={"w1": {"label": "pally"}},
              tabs={"w1:t1": {"label": "main", "workspace_id": "w1", "pane_id": "w1:p1"}},
              agents=[{"agent": "claude", "pane_id": "w1:p1", "tab_id": "w1:t1", "agent_status": "working",
                       "workspace_id": "w1", "cwd": "/work/app/sub",
                       "agent_session": {"kind": "id", "value": "parent-sid"}}])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent-sid")
    proj = tmp_path / "projects" / "-work-app"
    proj.mkdir(parents=True)
    (proj / "parent-sid.jsonl").write_text(json.dumps({"type": "summary"}) + "\n" +
                                          json.dumps({"type": "user", "cwd": "/work/app"}) + "\n")
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "1.json").write_text(json.dumps({"sessionId": "parent-sid", "name": "pally main", "pid": 1}))
    monkeypatch.setattr(cli, "pid_alive", lambda pid: True)
    task = tmp_path / "task.md"
    task.write_text("Investigate how failed tools land with users.")
    return task


def launch(task, *extra):
    return cli.main(["drone", "launch", "failure experience", "--task", str(task), *extra])


def only():
    [d] = drone.all_drones()
    return d


def start_call(fake):
    return next(c for c in fake.calls() if c[:2] == ["agent", "start"])


def test_launch_forks_this_chat_into_a_tab_beside_it(fake, parent):
    assert launch(parent) == 0
    d = only()
    assert d["status"] == "live" and d["mode"] == "fork" and d["model"] == "opus"
    assert d["parent"] == {"session_id": "parent-sid", "name": "pally main", "pane_id": "w1:p1", "tab_id": "w1:t1"}
    tab = fake.world()["tabs"][d["tab_id"]]
    assert tab["label"] == "✈ failure experience" and tab["workspace_id"] == "w1"
    args = start_call(fake)
    extra = args[args.index("--") + 1:]
    assert extra[:5] == ["--resume", "parent-sid", "--fork-session", "--session-id", d["session_id"]]
    assert "drone: failure experience" in extra and "claude-opus-5-5" in extra
    prompt = next(c for c in fake.calls() if c[:2] == ["agent", "prompt"])
    assert d["task"] in prompt[3] and "hive-drone skill" in prompt[3]


def test_fork_starts_in_the_folder_the_parent_chat_started_in(fake, parent):
    assert launch(parent) == 0
    assert only()["cwd"] == "/work/app"
    create = next(c for c in fake.calls() if c[:2] == ["tab", "create"])
    assert create[create.index("--cwd") + 1] == "/work/app"


def test_fork_refuses_another_folder(fake, parent, capsys):
    assert launch(parent, "--cwd", "/elsewhere") == 1
    assert "must start where this chat started" in capsys.readouterr().err
    assert drone.all_drones() == []


def test_fork_without_a_transcript_says_to_use_fresh(fake, parent, tmp_path, capsys):
    (tmp_path / "projects" / "-work-app" / "parent-sid.jsonl").unlink()
    assert launch(parent) == 1
    assert "--fresh" in capsys.readouterr().err


def test_fresh_drone_starts_a_new_session(fake, parent, tmp_path):
    assert launch(parent, "--fresh", "--cwd", str(tmp_path), "--model", "fable") == 0
    args = start_call(fake)
    extra = args[args.index("--") + 1:]
    assert extra[:2] == ["--session-id", only()["session_id"]] and "--fork-session" not in extra
    assert "claude-fable-5-1" in extra


def test_empty_task_is_refused(fake, parent, capsys):
    parent.write_text("  \n")
    assert launch(parent) == 1
    assert "task is empty" in capsys.readouterr().err


def test_a_label_still_open_is_refused(fake, parent, capsys):
    assert launch(parent) == 0
    assert launch(parent) == 1
    assert "still open" in capsys.readouterr().err


def test_failed_start_closes_its_tab_and_marks_failed(fake, parent, monkeypatch):
    monkeypatch.setenv("FAKE_HERDR_FAIL", "agent start")
    assert launch(parent) == 1
    d = only()
    assert d["status"] == "failed" and d["tab_id"] is None
    assert not any(t["label"].startswith("✈") for t in fake.world()["tabs"].values())


def as_drone(monkeypatch, d):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", d["session_id"])


def test_drone_reports_and_learns_the_parents_name(fake, parent, monkeypatch, tmp_path, capsys):
    launch(parent)
    as_drone(monkeypatch, only())
    rep = tmp_path / "r.txt"
    rep.write_text("DRONE REPORT failure experience\ncomplete: yes\nsummary: users retried twice")
    capsys.readouterr()
    assert cli.main(["drone", "report", "--file", str(rep)]) == 0
    out = capsys.readouterr().out
    assert "parent SendMessage name: pally main" in out
    assert only()["status"] == "reported" and "users retried" in only()["report"]["text"]
    assert cli.main(["drone", "parent"]) == 0
    assert capsys.readouterr().out.strip() == "pally main"


def test_parent_not_running_is_said_plainly(fake, parent, monkeypatch, capsys):
    launch(parent)
    as_drone(monkeypatch, only())
    monkeypatch.setattr(cli, "pid_alive", lambda pid: False)
    assert cli.main(["drone", "parent"]) == 1
    assert "not running" in capsys.readouterr().err


def test_ls_shows_summary_and_marks_vanished_tabs_detached(fake, parent, monkeypatch, tmp_path, capsys):
    launch(parent)
    d = only()
    rep = tmp_path / "r.txt"
    rep.write_text("DRONE REPORT x\nsummary: users retried twice")
    cli.main(["drone", "report", d["slug"], "--file", str(rep)])
    capsys.readouterr()
    assert cli.main(["drone", "ls"]) == 0
    assert "users retried twice" in capsys.readouterr().out
    w = fake.world()
    w["agents"] = [a for a in w["agents"] if a.get("tab_id") != d["tab_id"]]
    fake.seed(agents=w["agents"])
    cli.main(["drone", "ls"])
    assert only()["status"] == "detached"


def test_land_needs_a_report_then_closes_the_tab(fake, parent, tmp_path, capsys):
    launch(parent)
    d = only()
    assert cli.main(["drone", "land", d["slug"]]) == 1
    assert "no report" in capsys.readouterr().err
    rep = tmp_path / "r.txt"
    rep.write_text("DRONE REPORT x\nsummary: done")
    cli.main(["drone", "report", d["slug"], "--file", str(rep)])
    assert cli.main(["drone", "land", "failure experience"]) == 0
    assert d["tab_id"] not in fake.world()["tabs"] and only()["status"] == "landed"


def test_land_refuses_while_working(fake, parent, tmp_path, capsys):
    launch(parent)
    d = only()
    w = fake.world()
    for a in w["agents"]:
        if a.get("tab_id") == d["tab_id"]:
            a["agent_status"] = "working"
    fake.seed(agents=w["agents"])
    rep = tmp_path / "r.txt"
    rep.write_text("x")
    cli.main(["drone", "report", d["slug"], "--file", str(rep)])
    assert cli.main(["drone", "land", d["slug"]]) == 1
    assert "still working" in capsys.readouterr().err


def test_restore_resumes_the_drones_own_session(fake, parent, tmp_path):
    launch(parent)
    d = only()
    cli.main(["drone", "land", d["slug"], "--force"])
    assert cli.main(["drone", "restore", d["slug"]]) == 0
    starts = [c for c in fake.calls() if c[:2] == ["agent", "start"]]
    extra = starts[-1][starts[-1].index("--") + 1:]
    assert extra[:2] == ["--resume", d["session_id"]] and "--fork-session" not in extra
    assert only()["status"] == "live"


def test_drones_never_show_up_as_hives(fake, parent, capsys):
    launch(parent)
    capsys.readouterr()
    assert cli.main(["ls"]) == 0
    assert "failure" not in capsys.readouterr().out
