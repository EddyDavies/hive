import json

import pytest

from hive import registry as reg


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("HIVE_STATE_DIR", str(tmp_path))
    return tmp_path


def test_slugify_rules():
    assert reg.slugify("Drip copy") == "drip-copy"
    assert reg.slugify("fc: Postiz rollout!") == "fc-postiz-rollout"
    assert reg.slugify("2nd pass") == "w-2nd-pass"
    assert len(reg.slugify("x" * 80)) == 32
    assert reg.slugify("drip-copy", taken={"drip-copy"}) == "drip-copy-2"
    assert reg.slugify("drip copy", taken={"drip-copy", "drip-copy-2"}) == "drip-copy-3"


def test_round_trip_and_lookup(state):
    r = reg.Registry.create("fc: postiz", workspace_id="w1", cwd="/x",
                            orchestrator={"name": "orch", "session_id": "s0", "model": "fable"})
    w = reg.new_worker(r, "Drip copy", model="opus", why="bounded copy", cwd="/x", brief="/b.md")
    r.data["workers"].append(w)
    r.save()
    again = reg.Registry.load("fc-postiz")
    assert again.worker("drip copy")["session_id"] == w["session_id"]
    assert again.worker("drip-copy") is not None
    assert reg.Registry.find_by_workspace("w1").slug == "fc-postiz"
    assert [x.slug for x in reg.Registry.all()] == ["fc-postiz"]


def test_new_worker_slug_dedupes_against_existing(state):
    r = reg.Registry.create("o", workspace_id="w1", cwd="/x", orchestrator={})
    r.data["workers"].append(reg.new_worker(r, "Drip copy", model="opus", why="", cwd="/x", brief=""))
    second = reg.new_worker(r, "drip-copy", model="opus", why="", cwd="/x", brief="")
    assert second["slug"] == "drip-copy-2"


def test_create_refuses_duplicate_slug(state):
    reg.Registry.create("o", workspace_id="w1", cwd="/x", orchestrator={}).save()
    with pytest.raises(reg.RegistryError):
        reg.Registry.create("o", workspace_id="w2", cwd="/x", orchestrator={})


def test_atomic_save_keeps_old_file_on_failure(state, monkeypatch):
    r = reg.Registry.create("o", workspace_id="w1", cwd="/x", orchestrator={})
    r.save()
    before = (state / "o.json").read_text()
    r.data["label"] = "changed"

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(reg.json, "dump", boom)
    with pytest.raises(OSError):
        r.save()
    assert (state / "o.json").read_text() == before
    assert json.loads(before)["label"] == "o"
    assert not list(state.glob("*.tmp"))
