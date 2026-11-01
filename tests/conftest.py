import json
import os
import stat
from pathlib import Path

import pytest

BIN = Path(__file__).parent / "bin"


class Fake:
    def __init__(self, tmp: Path):
        self.log = tmp / "herdr.log"
        self.state = tmp / "herdr.json"

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(l) for l in self.log.read_text().splitlines()]

    def world(self):
        return json.loads(self.state.read_text())

    def seed(self, **world):
        cur = self.world() if self.state.exists() else {}
        cur.update(world)
        self.state.write_text(json.dumps(cur))


@pytest.fixture
def fake(tmp_path, monkeypatch):
    herdr = BIN / "herdr"
    herdr.chmod(herdr.stat().st_mode | stat.S_IXUSR)
    f = Fake(tmp_path)
    monkeypatch.setenv("PATH", f"{BIN}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_HERDR_LOG", str(f.log))
    monkeypatch.setenv("FAKE_HERDR_STATE", str(f.state))
    monkeypatch.setenv("HIVE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setenv("HIVE_CLAUDE_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("HIVE_CLAUDE_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("FAKE_HERDR_FAIL", raising=False)
    return f
