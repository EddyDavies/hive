"""Durable record of every queen and the bees it spawned.

One JSON file per queen in the state dir. Written before any tab
opens, so a crash never loses a session id.
"""

import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


class RegistryError(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def state_dir() -> Path:
    old = Path.home() / ".local/state/herd"  # machines set up before the rename keep their records there
    d = Path(os.environ.get("HIVE_STATE_DIR") or (old if old.exists() else Path.home() / ".local/state/hive"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def slugify(text: str, taken=()) -> str:
    """Herdr agent name rules: [a-z][a-z0-9_-]{0,31}, unique."""
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "worker"
    if not base[0].isalpha():
        base = "w-" + base
    base = base[:32].rstrip("-")
    slug, n = base, 2
    while slug in taken:
        suffix = f"-{n}"
        slug = base[: 32 - len(suffix)].rstrip("-") + suffix
        n += 1
    return slug


class Registry:
    def __init__(self, slug: str, data: dict):
        self.slug = slug
        self.data = data

    @property
    def path(self) -> Path:
        return state_dir() / f"{self.slug}.json"

    @classmethod
    def create(cls, label: str, workspace_id: str, cwd: str, orchestrator: dict) -> "Registry":
        slug = slugify(label)
        if (state_dir() / f"{slug}.json").exists():
            raise RegistryError(f"a queen named {slug!r} already exists")
        return cls(slug, {
            "label": label,
            "workspace_id": workspace_id,
            "cwd": cwd,
            "orchestrator": orchestrator,
            "workers": [],
            "created_at": now(),
        })

    @classmethod
    def load(cls, slug: str) -> "Registry":
        path = state_dir() / f"{slug}.json"
        if not path.exists():
            raise RegistryError(f"no queen named {slug!r} (see: hive ls)")
        return cls(slug, json.loads(path.read_text()))

    @classmethod
    def all(cls) -> list:
        # reaper.json is the reaper's own state, not a hive.
        return [cls.load(p.stem) for p in sorted(state_dir().glob("*.json")) if p.name != "reaper.json"]

    @classmethod
    def find_by_workspace(cls, workspace_id: str, herdr_socket=None):
        """Workspace ids are only unique within one Herdr server, so a recorded socket must match too."""
        for r in cls.all():
            if r.data.get("workspace_id") != workspace_id:
                continue
            if r.data.get("herdr_socket") and herdr_socket and r.data["herdr_socket"] != herdr_socket:
                continue
            return r
        return None

    def worker(self, name: str):
        """A slug match wins; otherwise the newest record with that label that did not fail to spawn
        (older hives can hold a failed record and its retry under one label)."""
        key = name.strip().lower()
        for w in self.data["workers"]:
            if w["slug"] == key and w.get("status") != "failed":
                return w
        matches = [w for w in self.data["workers"] if w["slug"] == key or w["label"].lower() == key]
        live = [w for w in matches if w.get("status") != "failed"]
        return (live or matches)[-1] if matches else None

    def save(self) -> None:
        self.data["updated_at"] = now()
        fd, tmp = tempfile.mkstemp(dir=state_dir(), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, self.path)
        except BaseException:
            os.unlink(tmp)
            raise


def new_worker(reg: Registry, label: str, model: str, why: str, cwd: str, brief: str) -> dict:
    taken = {w["slug"] for w in reg.data["workers"]}
    return {
        "label": label,
        "slug": slugify(label, taken),
        "model": model,
        "why": why,
        "session_id": str(uuid.uuid4()),
        "cwd": cwd,
        "brief": brief,
        "status": "starting",
        "tab_id": None,
        "pane_id": None,
        "machine": None,  # hc machine name for a remote bee
        "address": None,  # its hc terminal, machine/t7
        "remote_brief": None,
        "remote_handoff": None,
        "handoff": None,
        "error": None,
        "created_at": now(),
        "updated_at": now(),
    }
