"""Remote bees: hc terminals on a saved machine, mirrored into the Mac registry."""

import pytest

from hive import cli
from hive.registry import Registry



@pytest.fixture
def orch(fake, monkeypatch, tmp_path):
    """A queen chat live in pane w1:p1 of workspace w1, with a brief file; same as tests/test_cli.py."""
    monkeypatch.setenv("HERDR_WORKSPACE_ID", "w1")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p1")
    fake.seed(workspaces={"w1": {"label": "old"}},
              tabs={"w1:t1": {"label": "1", "workspace_id": "w1", "pane_id": "w1:p1"}},
              agents=[{"agent": "claude", "pane_id": "w1:p1", "tab_id": "w1:t1", "agent_status": "working",
                       "agent_session": {"kind": "id", "value": "orch-sid"}}])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "orch-sid")
    assert cli.main(["init", "fc: postiz"]) == 0
    brief = tmp_path / "brief.md"
    brief.write_text("Write the drip copy.")
    return brief


def reg():
    return Registry.load("fc-postiz")


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(cli, "SETTLE_POLL", 0.0)


def spawn_remote(orch, label="Drip", cwd="/home/ubuntu/code/app", machine="box"):
    return cli.main(["spawn", label, "--model", "opus", "--why", "x", "--brief", str(orch),
                     "--on", machine, "--cwd", cwd])


def remote_handoff_path(w):
    return w["remote_handoff"]


def test_spawn_on_a_machine_records_the_terminal_and_sends_the_brief(fake, orch):
    assert spawn_remote(orch) == 0
    w = reg().worker("drip")
    assert w["status"] == "live"
    assert w["machine"] == "box" and w["address"] == "box/t1"
    assert w["cwd"] == "/home/ubuntu/code/app"
    assert w["remote_brief"] == "/home/ubuntu/.local/state/hive/fc-postiz/briefs/drip.md"
    assert w["remote_handoff"] == "/home/ubuntu/.local/state/hive/fc-postiz/handoffs/drip.txt"
    assert fake.hc_world()["files"][w["remote_brief"]] == "Write the drip copy."
    run = next(c for c in fake.hc_calls() if c[0] == "run")
    assert run[1:9] == ["--bg", "--outlive-parent", "--on", "box", "--cwd", "/home/ubuntu/code/app", "--name", "drip"]
    program = run[run.index("--") + 1:]
    assert program[:2] == ["bash", "-lc"]
    line = program[2]
    assert line.startswith("exec claude ")
    assert f"--session-id {w['session_id']}" in line and "--model claude-opus-5-5" in line
    assert "--dangerously-skip-permissions" in line
    assert w["remote_handoff"] in line and w["remote_brief"] in line and "HIVE HANDOFF Drip" in line
    assert "SendMessage" in line  # the kickoff tells the bee there is no queen to message


def test_a_remote_bee_gets_a_mac_tab_that_attaches_to_it(fake, orch):
    assert spawn_remote(orch) == 0
    w = reg().worker("drip")
    tabs = fake.world()["tabs"]
    assert tabs[w["tab_id"]]["label"] == "o> Drip @box"
    assert fake.world()["ran"][w["pane_id"]] == "hc attach box/t1"
    assert not any(c[:2] == ["agent", "start"] for c in fake.calls())


def test_spawn_on_needs_an_absolute_cwd(fake, orch, capsys):
    assert cli.main(["spawn", "Drip", "--model", "opus", "--why", "x", "--brief", str(orch), "--on", "box"]) == 1
    assert "--cwd" in capsys.readouterr().err
    assert spawn_remote(orch, cwd="code/app") == 1
    assert "absolute" in capsys.readouterr().err
    assert reg().worker("drip") is None
    assert not any(c[0] == "run" for c in fake.hc_calls())


def test_spawn_on_an_unknown_machine_is_refused(fake, orch, capsys):
    assert spawn_remote(orch, machine="nowhere") == 1
    err = capsys.readouterr().err
    assert "nowhere" in err and "box" in err
    assert reg().worker("drip") is None


def test_spawn_clears_the_trust_dialog(fake, orch):
    fake.hc_seed(trust=True)
    assert spawn_remote(orch) == 0
    assert ["keys", "box/t1", "down", "enter"] in fake.hc_calls()
    assert reg().worker("drip")["status"] == "live"


def test_spawn_fails_when_claude_never_reports(fake, orch, capsys, monkeypatch):
    monkeypatch.setattr(cli, "SETTLE_FIRST", 2)
    monkeypatch.setattr(cli, "SETTLE_AFTER", 2)
    fake.hc_seed(never_ready=True, screens={"box/t1": "command not found: claude\n$ "})
    assert spawn_remote(orch) == 1
    err = capsys.readouterr().err
    assert "command not found: claude" in err
    w = reg().worker("drip")
    assert w["status"] == "failed" and "command not found" in w["error"]
    assert "box/t1" not in fake.hc_world()["terminals"]
    assert w["tab_id"] is None and len(fake.world()["tabs"]) == 1


def test_sync_records_the_remote_handoff(fake, orch):
    spawn_remote(orch)
    w = reg().worker("drip")
    fake.hc_seed(files={**fake.hc_world()["files"], w["remote_handoff"]: "HIVE HANDOFF Drip\ncomplete: yes\nsummary: done\n"})
    assert cli.main(["sync"]) == 0
    w = reg().worker("drip")
    assert w["status"] == "handed-off"
    assert w["handoff"]["text"].startswith("HIVE HANDOFF Drip")


def test_sync_detaches_a_finished_or_vanished_remote_bee(fake, orch):
    spawn_remote(orch, "Alpha")
    spawn_remote(orch, "Beta")
    world = fake.hc_world()
    world["terminals"]["box/t1"]["state"] = "finished"
    del world["terminals"]["box/t2"]
    fake.hc_seed(terminals=world["terminals"])
    assert cli.main(["sync"]) == 0
    assert reg().worker("alpha")["status"] == "detached"
    assert reg().worker("beta")["status"] == "detached"


def test_sync_leaves_a_live_remote_bee_alone_even_though_herdr_never_saw_it(fake, orch):
    spawn_remote(orch)
    assert cli.main(["sync"]) == 0
    assert reg().worker("drip")["status"] == "live"


def test_status_mirrors_remote_handoffs_too(fake, orch, capsys):
    spawn_remote(orch)
    w = reg().worker("drip")
    fake.hc_seed(files={**fake.hc_world()["files"], w["remote_handoff"]: "HIVE HANDOFF Drip\ncomplete: yes (all)\n"})
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "handed-off" in out and "complete: yes (all)" in out


def test_wait_returns_the_handoff(fake, orch, capsys):
    spawn_remote(orch)
    w = reg().worker("drip")
    fake.hc_seed(wait={"reason": "status", "status": "done", "ended": True, "then_status": "done"},
                 files={**fake.hc_world()["files"], w["remote_handoff"]: "HIVE HANDOFF Drip\ncomplete: yes\n"})
    capsys.readouterr()
    assert cli.main(["wait", "Drip"]) == 0
    out = capsys.readouterr().out
    assert "HIVE HANDOFF Drip" in out
    assert ["wait", "box/t1", "--timeout", "180"] in fake.hc_calls()
    assert reg().worker("drip")["status"] == "handed-off"


def test_wait_on_a_blocked_bee_shows_its_screen(fake, orch, capsys):
    spawn_remote(orch)
    fake.hc_seed(wait={"reason": "status", "status": "blocked", "ended": True, "then_status": "blocked"},
                 screens={"box/t1": "May I delete the folder? (y/n)\n"})
    capsys.readouterr()
    assert cli.main(["wait", "Drip", "--timeout", "30"]) == 0
    out = capsys.readouterr().out
    assert "blocked" in out and "May I delete the folder?" in out
    assert ["wait", "box/t1", "--timeout", "30"] in fake.hc_calls()


def test_wait_timeout_says_still_working(fake, orch, capsys):
    spawn_remote(orch)
    fake.hc_seed(wait={"reason": "timeout", "status": None, "ended": False})
    capsys.readouterr()
    assert cli.main(["wait", "Drip"]) == 0
    assert "still working" in capsys.readouterr().out


def test_wait_is_for_remote_bees_only(fake, orch, capsys):
    cli.main(["spawn", "Local", "--model", "opus", "--why", "x", "--brief", str(orch)])
    assert cli.main(["wait", "Local"]) == 1
    assert "SendMessage" in capsys.readouterr().err


def test_close_refuses_while_the_remote_bee_works(fake, orch, tmp_path, capsys):
    spawn_remote(orch)
    (tmp_path / "h.txt").write_text("HIVE HANDOFF Drip\ncomplete: yes")
    cli.main(["handoff", "Drip", "--file", str(tmp_path / "h.txt")])
    assert cli.main(["close", "Drip"]) == 1
    assert "working" in capsys.readouterr().err
    assert fake.hc_world()["terminals"]["box/t1"]["state"] == "live"


def test_close_kills_removes_and_closes_the_tab(fake, orch):
    spawn_remote(orch)
    w = reg().worker("drip")
    world = fake.hc_world()
    world["terminals"]["box/t1"]["status"] = {"state": "done"}
    fake.hc_seed(terminals=world["terminals"],
                 files={**world["files"], w["remote_handoff"]: "HIVE HANDOFF Drip\ncomplete: yes\n"})
    assert cli.main(["sync"]) == 0
    assert cli.main(["close", "Drip"]) == 0
    assert reg().worker("drip")["status"] == "closed"
    assert ["kill", "box/t1"] in fake.hc_calls() and ["rm", "box/t1"] in fake.hc_calls()
    assert "box/t1" not in fake.hc_world()["terminals"]
    assert w["tab_id"] not in fake.world()["tabs"]


def test_restore_resumes_a_detached_remote_bee_on_its_machine(fake, orch):
    spawn_remote(orch)
    w = reg().worker("drip")
    world = fake.hc_world()
    del world["terminals"]["box/t1"]
    fake.hc_seed(terminals=world["terminals"])
    tabs = fake.world()["tabs"]
    del tabs[w["tab_id"]]
    fake.seed(tabs=tabs)
    assert cli.main(["sync"]) == 0
    assert reg().worker("drip")["status"] == "detached"
    assert cli.main(["restore"]) == 0
    w = reg().worker("drip")
    assert w["status"] == "live" and w["address"] == "box/t2"
    run = [c for c in fake.hc_calls() if c[0] == "run"][-1]
    assert run[3:9] == ["--on", "box", "--cwd", "/home/ubuntu/code/app", "--name", "drip"]
    assert f"--resume {w['session_id']}" in run[-1]
    assert fake.world()["ran"][w["pane_id"]] == "hc attach box/t2"


def test_restore_skips_a_remote_bee_that_is_still_live(fake, orch, capsys):
    spawn_remote(orch)
    before = len([c for c in fake.hc_calls() if c[0] == "run"])
    capsys.readouterr()
    assert cli.main(["restore"]) == 0
    assert "already open" in capsys.readouterr().out
    assert len([c for c in fake.hc_calls() if c[0] == "run"]) == before


def test_local_bees_still_spawn_as_herdr_agents(fake, orch):
    assert cli.main(["spawn", "Local", "--model", "opus", "--why", "x", "--brief", str(orch)]) == 0
    w = reg().worker("local")
    assert w["machine"] is None and w["address"] is None
    assert any(c[:2] == ["agent", "start"] for c in fake.calls())
    assert not fake.hc_log.exists()
