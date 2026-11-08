import json
import os
import shutil
import socket
import tempfile
import threading
import time
from types import SimpleNamespace

import pytest

from hive import cli
from hive.registry import Registry


@pytest.fixture
def orch(fake, monkeypatch, tmp_path):
    """An orchestrator chat live in pane w1:p1 of workspace w1."""
    monkeypatch.setenv("HERDR_WORKSPACE_ID", "w1")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p1")
    fake.seed(workspaces={"w1": {"label": "old"}},
              tabs={"w1:t1": {"label": "1", "workspace_id": "w1", "pane_id": "w1:p1"}},
              agents=[{"agent": "claude", "pane_id": "w1:p1", "tab_id": "w1:t1", "agent_status": "working",
                       "agent_session": {"kind": "id", "value": "orch-sid"}}])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "orch-sid")  # claude sets it; the moved pane's HERDR_* go stale
    assert cli.main(["init", "fc: postiz", "--name", "Herta and agent messaging"]) == 0
    brief = tmp_path / "brief.md"
    brief.write_text("Write the drip copy.")
    return brief


def reg():
    return Registry.load("fc-postiz")


def reg_of(slug):
    return Registry.load(slug)


def test_init_records_orchestrator_and_labels_workspace(fake, orch):
    r = reg()
    assert r.data["orchestrator"]["session_id"] == "orch-sid"
    assert r.data["orchestrator"]["name"] == "queen: fc: postiz"
    assert ["agent", "prompt", "w1:p1", "/rename queen: fc: postiz"] in fake.calls()
    assert fake.world()["workspaces"]["w1"]["label"] == "◆ fc: postiz"
    assert fake.world()["tabs"]["w1:t1"]["label"] == "◆ fc: postiz"


def test_init_refuses_while_this_chats_hive_has_open_bees(fake, orch, monkeypatch, capsys):
    spawn(orch)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "orch-sid")
    assert cli.main(["init", "other"]) == 1
    assert "already is the queen of fc-postiz" in capsys.readouterr().err


def test_init_in_a_chat_whose_hive_is_done_stays_in_its_workspace(fake, orch, tmp_path, monkeypatch, capsys):
    spawn(orch)
    (tmp_path / "h.txt").write_text("done")
    cli.main(["handoff", "Drip", "--file", str(tmp_path / "h.txt")])
    cli.main(["close", "Drip"])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "orch-sid")
    capsys.readouterr()
    assert cli.main(["init", "next round"]) == 0
    assert "retired fc-postiz" in capsys.readouterr().out
    assert not any(c[:2] == ["pane", "move"] for c in fake.calls())
    assert reg().data["retired_at"] and reg().data["workspace_id"] is None
    nxt = Registry.load("next-round")
    assert nxt.data["workspace_id"] == "w1" and nxt.data["orchestrator"]["pane_id"] == "w1:p1"
    assert cli.main(["status"]) == 0 and "next round" in capsys.readouterr().out


def test_init_keeps_the_name_of_a_busy_workspace(fake, monkeypatch):
    monkeypatch.setenv("HERDR_WORKSPACE_ID", "w1")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p1")
    tabs = {f"w1:t{i}": {"label": f"chat {i}", "workspace_id": "w1", "pane_id": f"w1:p{i}"} for i in range(1, 6)}
    fake.seed(workspaces={"w1": {"label": "pink ladies"}}, tabs=tabs,
              agents=[{"agent": "claude", "pane_id": "w1:p1", "tab_id": "w1:t1", "agent_status": "working",
                       "agent_session": {"kind": "id", "value": "orch-sid"}}])
    assert cli.main(["init", "fc: postiz"]) == 0
    assert fake.world()["workspaces"]["w1"]["label"] == "pink ladies"
    r = reg()
    assert r.data["workspace_id"] != "w1" and r.data["home"]["workspace_id"] == "w1"
    assert fake.world()["workspaces"][r.data["workspace_id"]]["label"] == "◆ fc: postiz"
    assert fake.world()["tabs"][r.data["orchestrator"]["tab_id"]]["label"] == "◆ fc: postiz"


def second_chat_in_w1(fake, keep_first=False):
    """A new chat in pane w1:p2 of fc-postiz's workspace; the fc-postiz chat is gone unless keep_first."""
    world = fake.world()
    if not keep_first:
        world["agents"] = [a for a in world["agents"] if a.get("pane_id") != "w1:p1"]
    world["agents"].append({"agent": "claude", "pane_id": "w1:p2", "tab_id": "w1:t1", "agent_status": "idle",
                            "agent_session": {"kind": "id", "value": "new-sid"}})
    fake.seed(agents=world["agents"])


def init_from_second_chat(monkeypatch, label="other"):
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p2")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "new-sid")
    return cli.main(["init", label])


def test_init_moves_to_a_new_workspace_while_the_old_hive_has_open_workers(fake, orch, monkeypatch, capsys):
    spawn(orch)
    second_chat_in_w1(fake)
    assert init_from_second_chat(monkeypatch) == 0
    new = Registry.load("other")
    assert new.data["workspace_id"] not in (None, "w1")
    assert new.data["orchestrator"]["pane_id"] != "w1:p2"
    assert fake.world()["workspaces"][new.data["workspace_id"]]["label"] == "◆ other"
    assert reg().data["workspace_id"] == "w1"


def test_init_takes_a_done_herds_workspace_even_if_its_queen_was_active_recently(fake, orch, tmp_path, monkeypatch, capsys):
    spawn(orch)
    (tmp_path / "h.txt").write_text("done")
    cli.main(["handoff", "Drip", "--file", str(tmp_path / "h.txt")])
    cli.main(["close", "Drip"])
    d = tmp_path / "projects" / "-p"
    d.mkdir(parents=True)
    (d / "orch-sid.jsonl").write_text("{}\n")  # written just now
    second_chat_in_w1(fake)
    assert init_from_second_chat(monkeypatch) == 0
    assert "took workspace w1" in capsys.readouterr().out
    assert Registry.load("other").data["workspace_id"] == "w1"


def test_init_moves_while_a_done_herds_other_queen_is_mid_turn(fake, orch, tmp_path, monkeypatch, capsys):
    spawn(orch)
    (tmp_path / "h.txt").write_text("done")
    cli.main(["handoff", "Drip", "--file", str(tmp_path / "h.txt")])
    cli.main(["close", "Drip"])
    second_chat_in_w1(fake, keep_first=True)  # the fc-postiz chat is still working
    assert init_from_second_chat(monkeypatch) == 0
    assert "moved this chat to new workspace" in capsys.readouterr().out


def test_init_takes_the_workspace_of_a_stale_hive(fake, orch, tmp_path, monkeypatch, capsys):
    spawn(orch)
    (tmp_path / "h.txt").write_text("done")
    cli.main(["handoff", "Drip", "--file", str(tmp_path / "h.txt")])
    cli.main(["close", "Drip"])
    d = tmp_path / "projects" / "-p"
    d.mkdir(parents=True)
    f = d / "orch-sid.jsonl"
    f.write_text("{}\n")
    old = time.time() - 4 * 3600
    os.utime(f, (old, old))
    second_chat_in_w1(fake, keep_first=True)
    world = fake.world()
    for a in world["agents"]:
        if a["pane_id"] == "w1:p1":
            a["agent_status"] = "idle"
    fake.seed(agents=world["agents"])
    capsys.readouterr()
    assert init_from_second_chat(monkeypatch) == 0
    assert "took workspace w1 from fc-postiz" in capsys.readouterr().out
    assert reg().data["workspace_id"] is None and reg().data["retired_at"]
    assert Registry.load("other").data["workspace_id"] == "w1"


def test_old_workers_still_find_their_own_hive_after_a_takeover(fake, orch, tmp_path, monkeypatch, capsys):
    w = spawn(orch)
    second_chat_in_w1(fake)
    assert init_from_second_chat(monkeypatch) == 0
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", w["session_id"])
    monkeypatch.setenv("HERDR_WORKSPACE_ID", Registry.load("other").data["workspace_id"])
    (tmp_path / "h.txt").write_text("HIVE HANDOFF Drip")
    assert cli.main(["handoff", "Drip", "--file", str(tmp_path / "h.txt")]) == 0
    assert reg().worker("drip")["status"] == "handed-off"


def test_restore_of_a_retired_orchestrator_builds_a_new_workspace(fake, orch, monkeypatch):
    spawn(orch)
    r = reg()
    for w in r.data["workers"]:
        w["status"] = "closed"
    r.save()
    cli.retire(reg())
    before = len(fake.calls())
    assert cli.main(["restore", "fc-postiz", "--all"]) == 0
    assert any(c[:2] == ["pane", "move"] for c in fake.calls()[before:])  # the live queen moves, no empty shell
    assert reg().data["workspace_id"] not in (None, "w1")


def test_adopt_makes_this_chat_the_orchestrator(fake, orch, monkeypatch, capsys):
    spawn(orch)
    second_chat_in_w1(fake)
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p2")
    assert cli.main(["adopt", "fc-postiz"]) == 0
    assert "Drip" in capsys.readouterr().out
    r = reg()
    assert r.data["orchestrator"]["session_id"] == "new-sid" and r.data["orchestrator"]["pane_id"] == "w1:p2"
    assert r.data["previous_orchestrators"][0]["session_id"] == "orch-sid"
    assert ["agent", "prompt", "w1:p2", "/rename queen: fc: postiz"] in fake.calls()
    assert cli.main(["adopt", "fc-postiz"]) == 0 and "already" in capsys.readouterr().out


def test_adopt_refuses_while_old_chat_runs(fake, orch, monkeypatch, capsys):
    world = fake.world()
    world["agents"].append({"agent": "claude", "pane_id": "w1:p2", "tab_id": "w1:t1", "agent_status": "idle",
                            "agent_session": {"kind": "id", "value": "new-sid"}})
    fake.seed(agents=world["agents"])
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p2")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "new-sid")
    assert cli.main(["adopt", "fc-postiz"]) == 1
    assert "still running" in capsys.readouterr().err
    assert reg().data["orchestrator"]["session_id"] == "orch-sid"


def test_adopt_from_another_herds_busy_workspace_moves_to_a_new_one(fake, orch, monkeypatch, capsys):
    spawn(orch)
    second_chat_in_w1(fake)
    assert init_from_second_chat(monkeypatch, "busy") == 0  # busy hive now lives in its own workspace
    busy = Registry.load("busy").data["workspace_id"]
    world = fake.world()
    world["agents"].append({"agent": "claude", "pane_id": f"{busy}:p9", "tab_id": f"{busy}:t9", "agent_status": "idle",
                            "workspace_id": busy, "agent_session": {"kind": "id", "value": "third-sid"}})
    fake.seed(agents=world["agents"])
    spawn_from = Registry.load("busy")
    spawn_from.data["workers"].append({**reg().worker("drip"), "session_id": "busy-worker"})
    spawn_from.save()
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "third-sid")
    capsys.readouterr()
    assert cli.main(["adopt", "fc-postiz"]) == 0
    assert "moved this chat to new workspace" in capsys.readouterr().out
    r = reg()
    assert r.data["orchestrator"]["session_id"] == "third-sid"
    assert r.data["workspace_id"] not in (busy, "w1")
    assert Registry.load("busy").data["workspace_id"] == busy


def test_adopt_refuses_when_open_workers_live_in_another_herdr_session(fake, orch, monkeypatch, capsys):
    spawn(orch)
    r = reg()
    r.data["herdr_socket"] = "/tmp/old.sock"
    r.save()
    second_chat_in_w1(fake)
    monkeypatch.setenv("HERDR_SOCKET_PATH", "/tmp/new.sock")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p2")
    assert cli.main(["adopt", "fc-postiz"]) == 1
    assert "another Herdr session" in capsys.readouterr().err
    assert reg().data["orchestrator"]["session_id"] == "orch-sid"


def test_rename_waits_while_the_orchestrator_has_a_draft(fake, orch, tmp_path, monkeypatch, capsys):
    session_file(tmp_path, monkeypatch, "app-32")
    fake.seed(screens={"w1:p1": "────\n❯ half a thought about\n  the drip copy\n────\n  status"})
    before = len(fake.calls())
    assert cli.main(["sync"]) == 0
    assert not [c for c in fake.calls()[before:] if c[:2] == ["agent", "prompt"]]
    assert "unsent draft" in capsys.readouterr().err
    assert reg().data["orchestrator"]["name"] == "app-32"
    fake.seed(screens={"w1:p1": "────\n❯ \n────\n  status"})
    assert cli.main(["sync"]) == 0
    assert ["agent", "prompt", "w1:p1", "/rename queen: fc: postiz"] in fake.calls()[before:]


def test_input_draft_reads_the_claude_input_box():
    assert cli.input_draft("x\n───\n❯\n───\n  ⏺ main") == ""
    assert cli.input_draft("❯ old message\n───\n❯ hi\n there\n───") == "hi\nthere"
    assert cli.input_draft("no box here") is None


def test_init_fails_loud_when_own_session_unknown(fake, monkeypatch, capsys):
    monkeypatch.setenv("HERDR_WORKSPACE_ID", "w9")
    monkeypatch.setenv("HERDR_PANE_ID", "w9:p9")
    assert cli.main(["init", "o", "--name", "x"]) == 1
    assert "session" in capsys.readouterr().err


def test_spawn_registers_before_tab_and_starts_claude(fake, orch):
    assert cli.main(["spawn", "Drip copy", "--model", "opus", "--why", "bounded copy", "--brief", str(orch)]) == 0
    w = reg().worker("drip copy")
    assert w["status"] == "live" and w["tab_id"] and w["model"] == "opus"
    calls = fake.calls()
    create = next(c for c in calls if c[:2] == ["tab", "create"])
    assert create[create.index("--label") + 1] == "o> Drip copy"
    start = next(c for c in calls if c[:2] == ["agent", "start"])
    claude = start[start.index("--") + 1:]
    assert claude[:6] == ["--session-id", w["session_id"], "--name", "Drip copy", "--model", "claude-opus-5-5"]
    prompt = next(c for c in calls if c[:2] == ["agent", "prompt"] and "hive-bee" in c[3])
    assert '"queen: fc: postiz"' in prompt[3] and w["brief"] in prompt[3]
    assert len([c for c in calls if c[:2] == ["agent", "prompt"] and c[3].startswith("/rename")]) == 1
    assert open(w["brief"]).read() == "Write the drip copy."


def test_spawn_fable_uses_fable_model(fake, orch):
    cli.main(["spawn", "Pricing review", "--model", "fable", "--why", "tradeoffs", "--brief", str(orch)])
    start = next(c for c in fake.calls() if c[:2] == ["agent", "start"])
    assert "claude-fable-5-1" in start


def test_spawn_failure_marks_failed_and_exits_1(fake, orch, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_HERDR_FAIL", "agent start")
    assert cli.main(["spawn", "Drip", "--model", "opus", "--why", "x", "--brief", str(orch)]) == 1
    w = reg().worker("drip")
    assert w["status"] == "failed" and "injected failure" in w["error"]
    assert "injected failure" in capsys.readouterr().err


def test_spawn_failure_closes_the_tab_it_opened(fake, orch, monkeypatch):
    monkeypatch.setenv("FAKE_HERDR_FAIL", "agent start")
    assert cli.main(["spawn", "Drip", "--model", "opus", "--why", "x", "--brief", str(orch)]) == 1
    w = reg().worker("drip")
    assert w["tab_id"] is None
    assert any(c[:2] == ["tab", "close"] for c in fake.calls())


def test_spawn_waits_for_the_new_shell(fake, orch, monkeypatch):
    monkeypatch.setattr(cli.Herdr, "SHELL_WAIT", 0.01)
    monkeypatch.setenv("FAKE_HERDR_BUSY", "2")
    w = spawn(orch)
    assert w["status"] == "live"
    assert len([c for c in fake.calls() if c[:2] == ["agent", "start"]]) == 3


def test_respawning_a_failed_label_reuses_its_record(fake, orch, monkeypatch):
    monkeypatch.setenv("FAKE_HERDR_FAIL", "agent start")
    cli.main(["spawn", "Drip", "--model", "opus", "--why", "x", "--brief", str(orch)])
    monkeypatch.delenv("FAKE_HERDR_FAIL")
    w = spawn(orch)
    assert [x["label"] for x in reg().data["workers"]] == ["Drip"]
    assert len([c for c in fake.calls() if c[:2] == ["tab", "create"]]) == 2
    assert w["status"] == "live" and w["slug"] == "drip"


def test_spawn_refuses_a_label_already_in_use(fake, orch, capsys):
    spawn(orch)
    assert cli.main(["spawn", "drip", "--model", "opus", "--why", "x", "--brief", str(orch)]) == 1
    assert "already" in capsys.readouterr().err
    assert len(reg().data["workers"]) == 1


def test_respawn_closes_a_tab_an_old_failed_spawn_left_open(fake, orch):
    r = reg()
    fake.seed(tabs={**fake.world()["tabs"], "w1:t9": {"label": "o> Drip", "workspace_id": "w1", "pane_id": "w1:p9"}})
    r.data["workers"].append({"label": "Drip", "slug": "drip", "status": "failed", "tab_id": "w1:t9"})
    r.save()
    spawn(orch)
    assert ["tab", "close", "w1:t9"] in fake.calls()


def test_lookup_prefers_the_live_record_over_a_failed_one(fake, orch):
    r = reg()
    r.data["workers"] = [{"label": "Drip", "slug": "drip", "status": "failed"},
                         {"label": "Drip", "slug": "drip-2", "status": "live"}]
    assert r.worker("Drip")["slug"] == "drip-2"


def test_same_slug_labels_get_distinct_names(fake, orch):
    cli.main(["spawn", "Drip copy", "--model", "opus", "--why", "x", "--brief", str(orch)])
    cli.main(["spawn", "drip-copy", "--model", "opus", "--why", "x", "--brief", str(orch)])
    names = [c[2] for c in fake.calls() if c[:2] == ["agent", "start"]]
    assert names == ["drip-copy", "drip-copy-2"]


def spawn(orch, label="Drip"):
    assert cli.main(["spawn", label, "--model", "opus", "--why", "x", "--brief", str(orch)]) == 0
    return reg().worker(label)


def test_close_refuses_without_handoff(fake, orch, capsys):
    spawn(orch)
    assert cli.main(["close", "Drip"]) == 1
    assert "handoff" in capsys.readouterr().err
    assert reg().worker("drip")["status"] == "live"


def test_close_refuses_while_working(fake, orch, tmp_path, capsys):
    w = spawn(orch)
    world = fake.world()
    for a in world["agents"]:
        if a.get("tab_id") == w["tab_id"]:
            a["agent_status"] = "working"
    fake.seed(agents=world["agents"])
    (tmp_path / "h.txt").write_text("HIVE HANDOFF Drip\ncomplete: yes")
    cli.main(["handoff", "Drip", "--file", str(tmp_path / "h.txt")])
    assert cli.main(["close", "Drip"]) == 1
    assert "working" in capsys.readouterr().err
    assert w["tab_id"] in fake.world()["tabs"]


def test_handoff_then_close(fake, orch, tmp_path):
    w = spawn(orch)
    (tmp_path / "h.txt").write_text("HIVE HANDOFF Drip\ncomplete: yes")
    assert cli.main(["handoff", "Drip", "--file", str(tmp_path / "h.txt")]) == 0
    assert reg().worker("drip")["status"] == "handed-off"
    assert cli.main(["close", "Drip"]) == 0
    assert reg().worker("drip")["status"] == "closed"
    assert w["tab_id"] not in fake.world()["tabs"]


def test_mark_review_adds_eyes_to_tab(fake, orch):
    w = spawn(orch)
    assert cli.main(["mark-review", "Drip", "--reason", "new layout"]) == 0
    assert fake.world()["tabs"][w["tab_id"]]["label"] == "👀 o> Drip"
    assert reg().worker("drip")["status"] == "review"


def test_sync_marks_vanished_tabs_detached(fake, orch):
    w = spawn(orch)
    world = fake.world()
    del world["tabs"][w["tab_id"]]
    world["agents"] = [a for a in world["agents"] if a.get("tab_id") != w["tab_id"]]
    fake.seed(tabs=world["tabs"], agents=world["agents"])
    assert cli.main(["sync"]) == 0
    assert reg().worker("drip")["status"] == "detached"


def test_restore_skips_live_and_resumes_the_rest(fake, orch):
    a = spawn(orch, "Alpha")
    b = spawn(orch, "Beta")
    world = fake.world()
    del world["tabs"][b["tab_id"]]
    world["agents"] = [x for x in world["agents"] if x.get("tab_id") != b["tab_id"]]
    fake.seed(tabs=world["tabs"], agents=world["agents"])
    before = len(fake.calls())
    assert cli.main(["restore"]) == 0
    starts = [c for c in fake.calls()[before:] if c[:2] == ["agent", "start"]]
    assert len(starts) == 1
    claude = starts[0][starts[0].index("--") + 1:]
    assert claude[:2] == ["--resume", b["session_id"]]
    assert reg().worker("beta")["status"] == "live"


def test_restore_skips_closed_unless_all(fake, orch, tmp_path):
    spawn(orch)
    (tmp_path / "h.txt").write_text("done")
    cli.main(["handoff", "Drip", "--file", str(tmp_path / "h.txt")])
    cli.main(["close", "Drip"])
    before = len(fake.calls())
    cli.main(["restore"])
    assert not [c for c in fake.calls()[before:] if c[:2] == ["agent", "start"]]
    cli.main(["restore", "--all"])
    assert [c for c in fake.calls()[before:] if c[:2] == ["agent", "start"]]


def test_restore_rebuilds_missing_workspace_with_orchestrator(fake, orch, monkeypatch):
    spawn(orch)
    fake.seed(workspaces={}, tabs={}, agents=[])
    monkeypatch.setenv("HERDR_WORKSPACE_ID", "w-elsewhere")
    assert cli.main(["restore", "fc-postiz"]) == 0
    calls = fake.calls()
    assert any(c[:2] == ["workspace", "create"] and "◆ fc: postiz" in c for c in calls)
    resumed = [c[c.index("--") + 2] for c in calls if c[:2] == ["agent", "start"] and "--resume" in c]
    assert "orch-sid" in resumed and reg().worker("drip")["session_id"] in resumed
    assert reg().data["workspace_id"] != "w1"


def test_restore_every(fake, orch):
    spawn(orch)
    fake.seed(workspaces={}, tabs={}, agents=[])
    assert cli.main(["restore", "--every"]) == 0
    assert any(c[:2] == ["workspace", "create"] for c in fake.calls())


def test_status_prints_workers(fake, orch, capsys):
    spawn(orch)
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Drip" in out and "opus" in out and "live" in out


def session_file(tmp_path, monkeypatch, name, sid="orch-sid", pid=None, started=1):
    d = tmp_path / "sessions"
    d.mkdir(exist_ok=True)
    monkeypatch.setenv("HIVE_CLAUDE_SESSIONS_DIR", str(d))
    pid = os.getpid() if pid is None else pid
    (d / f"{name}.json").write_text(json.dumps({"pid": pid, "sessionId": sid, "name": name, "startedAt": started}))


def test_orchestrator_prints_live_name_after_restart(fake, orch, tmp_path, monkeypatch, capsys):
    session_file(tmp_path, monkeypatch, "app-56", pid=2 ** 22 + 12345, started=1)  # the dead old process
    session_file(tmp_path, monkeypatch, "app-32", started=2)
    session_file(tmp_path, monkeypatch, "app-7b", sid="someone-else", started=3)
    capsys.readouterr()
    assert cli.main(["orchestrator"]) == 0
    assert capsys.readouterr().out.strip() == "app-32"
    assert reg().data["orchestrator"]["name"] == "app-32"


def test_orchestrator_fails_loud_when_not_running(fake, orch, tmp_path, monkeypatch, capsys):
    session_file(tmp_path, monkeypatch, "app-7b", sid="someone-else")
    assert cli.main(["orchestrator"]) == 1
    err = capsys.readouterr().err
    assert "not running" in err and "queen: fc: postiz" in err
    assert reg().data["orchestrator"]["name"] == "queen: fc: postiz"


def test_spawn_renames_an_orchestrator_running_under_a_derived_name(fake, orch, tmp_path, monkeypatch):
    session_file(tmp_path, monkeypatch, "app-32")
    before = len(fake.calls())
    spawn(orch)
    prompts = [c for c in fake.calls()[before:] if c[:2] == ["agent", "prompt"]]
    assert prompts[0][2:] == ["w1:p1", "/rename queen: fc: postiz"]
    assert '"queen: fc: postiz"' in prompts[1][3] and "hive queen" in prompts[1][3]


def test_init_detects_name_without_flag(fake, tmp_path, monkeypatch):
    monkeypatch.setenv("HERDR_WORKSPACE_ID", "w1")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p1")
    fake.seed(workspaces={"w1": {"label": "old"}},
              tabs={"w1:t1": {"label": "1", "workspace_id": "w1", "pane_id": "w1:p1"}},
              agents=[{"agent": "claude", "pane_id": "w1:p1", "tab_id": "w1:t1", "agent_status": "working",
                       "agent_session": {"kind": "id", "value": "orch-sid"}}])
    session_file(tmp_path, monkeypatch, "app-32")
    assert cli.main(["init", "fc: postiz"]) == 0
    assert reg().data["orchestrator"]["name"] == "queen: fc: postiz"


def test_failed_rename_keeps_live_name_and_warns(fake, orch, tmp_path, monkeypatch, capsys):
    session_file(tmp_path, monkeypatch, "app-32")
    monkeypatch.setenv("FAKE_HERDR_FAIL", "agent prompt w1:p1")
    assert cli.main(["sync"]) == 0
    assert "could not rename" in capsys.readouterr().err
    assert reg().data["orchestrator"]["name"] == "app-32"


def test_restore_resumes_orchestrator_under_its_fixed_name(fake, orch, monkeypatch):
    fake.seed(workspaces={}, tabs={}, agents=[])
    monkeypatch.setenv("HERDR_WORKSPACE_ID", "w-elsewhere")
    assert cli.main(["restore", "fc-postiz"]) == 0
    start = next(c for c in fake.calls() if c[:2] == ["agent", "start"] and "orch-sid" in c)
    assert start[start.index("--name") + 1] == "queen: fc: postiz"


def test_commands_use_the_orchestrators_own_herdr_server(fake, orch, monkeypatch):
    """Run from another Herdr session, hive must still talk to the server the orchestrator lives in."""
    r = reg()
    r.data["herdr_socket"] = "/tmp/ple.sock"
    r.save()
    monkeypatch.setenv("HERDR_SOCKET_PATH", "/tmp/default.sock")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")  # run from some other chat, not the queen
    monkeypatch.setenv("FAKE_HERDR_LOG_SOCKET", "1")
    before = len(fake.calls())
    assert cli.main(["sync", "--orch", "fc-postiz"]) == 0
    assert {c[0] for c in fake.calls()[before:]} == {"@/tmp/ple.sock"}


def test_same_workspace_id_in_another_herdr_server_is_not_this_orchestrator(fake, orch, monkeypatch, capsys):
    r = reg()
    r.data["herdr_socket"] = "/tmp/ple.sock"
    r.save()
    monkeypatch.setenv("HERDR_SOCKET_PATH", "/tmp/default.sock")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    assert cli.main(["status"]) == 1
    assert "no queen" in capsys.readouterr().err


def test_sync_reattaches_a_detached_worker_that_is_live(fake, orch, tmp_path):
    spawn(orch)
    (tmp_path / "h.txt").write_text("HIVE HANDOFF Drip\ncomplete: yes")
    cli.main(["handoff", "Drip", "--file", str(tmp_path / "h.txt")])
    r = reg()
    r.worker("drip")["status"] = "detached"
    r.save()
    assert cli.main(["sync"]) == 0
    assert reg().worker("drip")["status"] == "handed-off"



def orchestrator_moved_to(fake, monkeypatch, tmp_path, ws="w3", socket="/tmp/new.sock"):
    """The fc-postiz chat came back in another Herdr session: its old workspace and folder are gone."""
    r = reg()
    r.data["herdr_socket"] = "/tmp/old.sock"
    r.data["cwd"] = str(tmp_path / "old-folder")
    for w in r.data["workers"]:
        w["cwd"] = str(tmp_path / "old-folder" / "sub")
    r.save()
    new = tmp_path / "new-folder"
    new.mkdir()
    fake.seed(workspaces={ws: {"label": "x"}},
              tabs={f"{ws}:t1": {"label": "1", "workspace_id": ws, "pane_id": f"{ws}:p1"}},
              agents=[{"agent": "claude", "pane_id": f"{ws}:p1", "tab_id": f"{ws}:t1", "workspace_id": ws,
                       "cwd": str(new), "agent_status": "working",
                       "agent_session": {"kind": "id", "value": "orch-sid"}}])
    monkeypatch.setenv("HERDR_SOCKET_PATH", socket)
    monkeypatch.setenv("HERDR_WORKSPACE_ID", ws)
    monkeypatch.setenv("HERDR_PANE_ID", f"{ws}:p1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "orch-sid")
    return new


def test_adopt_by_the_orchestrator_itself_points_a_moved_hive_at_its_new_home(fake, orch, tmp_path, monkeypatch, capsys):
    spawn(orch)
    new = orchestrator_moved_to(fake, monkeypatch, tmp_path)
    capsys.readouterr()
    assert cli.main(["adopt", "fc-postiz"]) == 0
    assert "moved fc-postiz" in capsys.readouterr().out
    r = reg()
    assert r.data["workspace_id"] == "w3" and r.data["herdr_socket"] == "/tmp/new.sock"
    assert r.data["orchestrator"]["pane_id"] == "w3:p1" and r.data["orchestrator"]["session_id"] == "orch-sid"
    assert r.data["cwd"] == str(new) and r.worker("drip")["cwd"] == str(new / "sub")
    assert fake.world()["workspaces"]["w3"]["label"] == "◆ fc: postiz"
    assert cli.main(["adopt", "fc-postiz"]) == 0 and "already" in capsys.readouterr().out


def test_spawn_from_a_moved_orchestrator_rehomes_first(fake, orch, tmp_path, monkeypatch, capsys):
    new = orchestrator_moved_to(fake, monkeypatch, tmp_path)
    w = spawn(orch, "Next")
    assert w["tab_id"].startswith("w3:") and w["cwd"] == str(new)
    assert "moved fc-postiz" in capsys.readouterr().out


def test_rehome_refuses_while_workers_still_run_in_the_old_herdr_session(fake, orch, tmp_path, monkeypatch, capsys):
    spawn(orch)
    drip_sid = reg().worker("drip")["session_id"]
    orchestrator_moved_to(fake, monkeypatch, tmp_path)
    world = fake.world()
    world["agents"].append({"agent": "claude", "pane_id": "w1:p9", "agent_status": "idle",
                            "agent_session": {"kind": "id", "value": drip_sid}})
    fake.seed(agents=world["agents"])  # the fake serves both sockets, so Drip looks live in the old one
    assert cli.main(["adopt", "fc-postiz"]) == 1
    assert "another Herdr session" in capsys.readouterr().err
    assert reg().data["workspace_id"] == "w1"


def test_init_from_a_moved_orchestrator_points_to_adopt(fake, orch, tmp_path, monkeypatch, capsys):
    spawn(orch)
    orchestrator_moved_to(fake, monkeypatch, tmp_path)
    assert cli.main(["init", "other"]) == 1
    assert "hive adopt fc-postiz" in capsys.readouterr().err


def busy_home(fake, monkeypatch):
    """The queen chat starts in w1, a workspace with five other chats in it."""
    monkeypatch.setenv("HERDR_WORKSPACE_ID", "w1")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "orch-sid")
    tabs = {f"w1:t{i}": {"label": f"chat {i}", "workspace_id": "w1", "pane_id": f"w1:p{i}"} for i in range(1, 6)}
    fake.seed(workspaces={"w1": {"label": "pink ladies"}}, tabs=tabs,
              agents=[{"agent": "claude", "pane_id": "w1:p1", "tab_id": "w1:t1", "agent_status": "working",
                       "agent_session": {"kind": "id", "value": "orch-sid"}}])
    assert cli.main(["init", "fc: postiz"]) == 0


def finish(tmp_path, label="Drip"):
    (tmp_path / "h.txt").write_text(f"HIVE HANDOFF {label}")
    assert cli.main(["handoff", label, "--file", str(tmp_path / "h.txt")]) == 0
    assert cli.main(["close", label]) == 0


def test_closing_the_last_bee_takes_the_queen_home(fake, monkeypatch, tmp_path, capsys):
    busy_home(fake, monkeypatch)
    hive_ws = reg().data["workspace_id"]
    brief = tmp_path / "b.md"
    brief.write_text("x")
    for label in ("Drip", "Copy"):
        assert cli.main(["spawn", label, "--model", "opus", "--why", "x", "--brief", str(brief)]) == 0
    assert reg().worker("drip")["tab_id"].startswith(hive_ws + ":")
    finish(tmp_path, "Drip")
    assert reg().data["workspace_id"] == hive_ws  # Copy is still open
    capsys.readouterr()
    finish(tmp_path, "Copy")
    assert "moved back to workspace w1" in capsys.readouterr().out
    r, world = reg(), fake.world()
    assert r.data["workspace_id"] is None and hive_ws not in world["workspaces"]
    assert world["tabs"][r.data["orchestrator"]["tab_id"]] == {"label": "chat 1", "workspace_id": "w1",
                                                              "pane_id": r.data["orchestrator"]["pane_id"]}
    assert world["workspaces"]["w1"]["label"] == "pink ladies"


@pytest.mark.parametrize("recorded, expected", [("◆ earlier hive", "earlier hive"), (None, "fc: postiz")])
def test_the_queen_comes_home_without_the_hive_mark(fake, monkeypatch, tmp_path, recorded, expected):
    busy_home(fake, monkeypatch)
    r = reg()
    r.data["home"]["tab_label"] = recorded
    r.save()
    brief = tmp_path / "b.md"
    brief.write_text("x")
    cli.main(["spawn", "Drip", "--model", "opus", "--why", "x", "--brief", str(brief)])
    finish(tmp_path)
    r = reg()
    assert fake.world()["tabs"][r.data["orchestrator"]["tab_id"]]["label"] == expected


def test_a_solo_queen_loses_a_mark_left_from_an_earlier_hive(fake, orch, tmp_path):
    r = reg()
    r.data["home"].update(tab_label="◆ earlier", workspace_label="◆ earlier")
    r.save()
    spawn(orch)
    finish(tmp_path)
    assert fake.world()["workspaces"]["w1"]["label"] == "earlier"
    assert fake.world()["tabs"]["w1:t1"]["label"] == "earlier"


def test_spawning_from_home_moves_the_queen_out_again(fake, monkeypatch, tmp_path, capsys):
    busy_home(fake, monkeypatch)
    brief = tmp_path / "b.md"
    brief.write_text("x")
    cli.main(["spawn", "Drip", "--model", "opus", "--why", "x", "--brief", str(brief)])
    finish(tmp_path)
    assert cli.main(["spawn", "Next", "--model", "opus", "--why", "x", "--brief", str(brief)]) == 0
    r = reg()
    assert r.data["workspace_id"] not in (None, "w1")
    assert r.worker("next")["tab_id"].startswith(r.data["workspace_id"] + ":")
    assert r.data["orchestrator"]["tab_id"].startswith(r.data["workspace_id"] + ":")


def test_a_solo_queen_stays_put_and_gets_its_names_back(fake, orch, tmp_path, capsys):
    assert fake.world()["workspaces"]["w1"]["label"] == "◆ fc: postiz"
    spawn(orch)
    capsys.readouterr()
    finish(tmp_path)
    assert "old names back" in capsys.readouterr().out
    assert fake.world()["workspaces"]["w1"]["label"] == "old"
    assert fake.world()["tabs"]["w1:t1"]["label"] == "1"
    spawn(orch, "Next")
    assert fake.world()["workspaces"]["w1"]["label"] == "◆ fc: postiz"
    assert not any(c[:2] == ["pane", "move"] for c in fake.calls())


def test_queen_stays_when_its_home_workspace_is_gone(fake, monkeypatch, tmp_path, capsys):
    busy_home(fake, monkeypatch)
    hive_ws = reg().data["workspace_id"]
    brief = tmp_path / "b.md"
    brief.write_text("x")
    cli.main(["spawn", "Drip", "--model", "opus", "--why", "x", "--brief", str(brief)])
    world = fake.world()
    world["workspaces"].pop("w1")
    world["tabs"] = {k: v for k, v in world["tabs"].items() if v["workspace_id"] != "w1"}
    fake.seed(**world)
    capsys.readouterr()
    finish(tmp_path)
    assert "is gone, so the queen stays" in capsys.readouterr().out
    assert reg().data["workspace_id"] == hive_ws


@pytest.fixture
def herdr_server(monkeypatch):
    """A stand-in for the Herdr socket API; returns the requests it received. Fails them if error is set."""
    folder = tempfile.mkdtemp(dir="/tmp")  # unix socket paths have a short length limit
    path = os.path.join(folder, "s.sock")
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(path)
    listener.listen()
    server = SimpleNamespace(requests=[], error=None)

    def serve():
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            with conn:
                server.requests.append(json.loads(conn.makefile().readline()))
                reply = {"error": server.error} if server.error else {"result": {"type": "workspace_list"}}
                conn.sendall((json.dumps({"id": "hive", **reply}) + "\n").encode())

    threading.Thread(target=serve, daemon=True).start()
    monkeypatch.setenv("HERDR_SOCKET_PATH", path)
    yield server
    listener.close()
    shutil.rmtree(folder)


def seed_busy_workspace_then_another(fake, monkeypatch):
    """This chat in w1, which holds another tab too, with an unrelated workspace w2 below it."""
    monkeypatch.setenv("HERDR_WORKSPACE_ID", "w1")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "orch-sid")
    fake.seed(workspaces={"w1": {"label": "old"}, "w2": {"label": "next"}},
              tabs={"w1:t1": {"label": "1", "workspace_id": "w1", "pane_id": "w1:p1"},
                    "w1:t2": {"label": "2", "workspace_id": "w1", "pane_id": "w1:p2"},
                    "w2:t1": {"label": "3", "workspace_id": "w2", "pane_id": "w2:p1"}},
              agents=[{"agent": "claude", "pane_id": "w1:p1", "tab_id": "w1:t1", "agent_status": "working",
                       "agent_session": {"kind": "id", "value": "orch-sid"}}])


def test_new_hive_workspace_opens_just_below_the_one_it_came_from(fake, monkeypatch, herdr_server):
    seed_busy_workspace_then_another(fake, monkeypatch)
    assert cli.main(["init", "paired"]) == 0
    new = reg_of("paired").data["workspace_id"]
    assert [(q["method"], q["params"]) for q in herdr_server.requests] == [
        ("workspace.move", {"workspace_id": new, "insert_index": 1})]


def test_hive_workspace_is_left_alone_when_already_below(fake, monkeypatch, herdr_server):
    seed_busy_workspace_then_another(fake, monkeypatch)
    world = fake.world()
    del world["workspaces"]["w2"], world["tabs"]["w2:t1"]
    fake.seed(**world)
    assert cli.main(["init", "paired"]) == 0
    assert herdr_server.requests == []


def test_failing_to_place_the_workspace_warns_and_carries_on(fake, monkeypatch, herdr_server, capsys):
    seed_busy_workspace_then_another(fake, monkeypatch)
    herdr_server.error = {"code": "workspace_move_failed", "message": "insert_index 1 is out of bounds"}
    assert cli.main(["init", "paired"]) == 0
    assert "stays at the end of the list, not under w1: workspace.move: insert_index 1" in capsys.readouterr().err
    assert reg_of("paired").data["workspace_id"] != "w1"


def test_a_workspace_that_closed_in_the_move_gives_up_its_slot(fake, herdr_server):
    from hive.herdr import Herdr
    fake.seed(workspaces={"w2": {"label": "b"}, "w3": {"label": "c"}, "w9": {"label": "new"}}, tabs={}, agents=[])
    Herdr().place_below("w9", "w1", ["w1", "w2", "w3"])
    assert herdr_server.requests[0]["params"] == {"workspace_id": "w9", "insert_index": 0}
