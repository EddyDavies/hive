import json

import pytest

from herd import reaper

STARTED = "INFO herdr::server::headless::bootstrap: herdr server started api_socket=x\n"


def conn(cid):
    return f"INFO herdr::server::headless: client connected client_id={cid} cols=1\n"


def det(cid):
    return f"INFO herdr::server::headless: client detached client_id={cid}\n"


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Fake herdr: sessions with server logs and agent lists; records stops."""
    monkeypatch.setenv("HERD_STATE_DIR", str(tmp_path / "state"))
    w = {"sessions": {}, "stopped": []}

    def add(name, log=STARTED, agents=("idle",)):
        d = tmp_path / name
        d.mkdir()
        (d / "herdr-server.log").write_text(log)
        w["sessions"][name] = {"name": name, "running": True, "session_dir": str(d),
                               "socket_path": str(d / "herdr.sock"), "agents": None if agents is None else list(agents)}

    def fake(*args, socket=None):
        if args[:2] == ("session", "list"):
            return {"sessions": [{k: v for k, v in s.items() if k != "agents"} for s in w["sessions"].values()]}
        if args[:2] == ("agent", "list"):
            s = next(s for s in w["sessions"].values() if s["socket_path"] == socket)
            if s["agents"] is None:
                raise RuntimeError("socket gone")
            return {"result": {"agents": [{"agent_status": a} for a in s["agents"]]}}
        if args[:2] == ("session", "stop"):
            w["stopped"].append(args[2])
            return {}
        raise AssertionError(args)

    monkeypatch.setattr(reaper, "herdr", fake)
    w["add"] = add
    return w


def test_counts_only_clients_since_the_last_server_start(tmp_path):
    log = tmp_path / "l"
    log.write_text(STARTED + conn(2) + STARTED + conn(2) + det(2) + conn(4))
    assert reaper.attached_clients(log) == 1
    log.write_text(STARTED + conn(2) + STARTED)
    assert reaper.attached_clients(log) == 0


def test_stops_only_after_the_grace_period(world):
    world["add"]("rb", log=STARTED + conn(2) + det(2))
    assert reaper.reap(now=1000) == []
    assert reaper.reap(now=1000 + reaper.GRACE - 1) == []
    assert reaper.reap(now=1000 + reaper.GRACE) == ["rb"]
    assert world["stopped"] == ["rb"]


def test_attaching_or_working_resets_the_clock(world):
    world["add"]("fc")
    reaper.reap(now=0)
    world["sessions"]["fc"]["agents"] = ["idle", "working"]
    reaper.reap(now=100)
    world["sessions"]["fc"]["agents"] = ["idle"]
    assert reaper.reap(now=200) == []  # quiet again: the clock restarts here
    assert reaper.reap(now=200 + reaper.GRACE - 1) == []
    assert reaper.reap(now=200 + reaper.GRACE) == ["fc"]


@pytest.mark.parametrize("log,agents", [
    (STARTED + conn(2), ("idle",)),     # a window is attached
    (STARTED, ("idle", "unknown")),     # an agent herdr cannot classify
    (STARTED, None),                    # agent list unreadable
    ("no start line\n", ("idle",)),     # log without a server start
])
def test_keeps_sessions_in_use_or_unreadable(world, log, agents):
    world["add"]("ple", log=log, agents=agents)
    assert reaper.reap(now=0) == [] and reaper.reap(now=10 * reaper.GRACE) == []


def test_skips_the_default_session(world):
    world["add"]("default")
    reaper.reap(now=0)
    assert reaper.reap(now=10 * reaper.GRACE) == []


def test_dry_run_stops_nothing_and_keeps_no_clock(world, tmp_path):
    world["add"]("rb")
    assert reaper.reap(dry_run=True, now=0) == []
    assert not (tmp_path / "state" / "reaper.json").exists()
    assert world["stopped"] == []
