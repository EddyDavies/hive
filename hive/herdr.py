"""Thin wrapper over the `herdr` CLI. Every call returns herdr's `result`
object or raises HerdrError with herdr's own message."""

import json
import os
import subprocess
import time


class HerdrError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


class Herdr:
    SHELL_WAIT = 1.0  # seconds between agent start attempts while a new pane's shell is still starting
    SHELL_TRIES = 20

    def __init__(self, socket=None):
        """socket: the Herdr server to talk to (one per named Herdr session); default is this pane's own."""
        if os.environ.get("HERDR_ENV") != "1":
            raise HerdrError("not inside Herdr (HERDR_ENV is not 1); run hive from a Herdr pane")
        self.env = {**os.environ, "HERDR_SOCKET_PATH": socket} if socket else None

    def run(self, *args: str) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(["herdr", *args], capture_output=True, text=True, timeout=120, env=self.env)
        except FileNotFoundError:
            raise HerdrError("herdr binary not found on PATH")

    def call(self, *args: str) -> dict:
        p = self.run(*args)
        body = None
        try:
            body = json.loads(p.stdout) if p.stdout.strip() else None
        except json.JSONDecodeError:
            pass
        if p.returncode != 0 or body is None or "error" in body:
            err = (body or {}).get("error") or {}
            msg = err.get("message") or p.stderr.strip() or p.stdout.strip() or f"exit {p.returncode}"
            raise HerdrError(f"herdr {' '.join(args[:2])}: {msg}", err.get("code"))
        return body.get("result", {})

    def tab_create(self, workspace_id: str, label: str, cwd: str) -> tuple:
        r = self.call("tab", "create", "--workspace", workspace_id, "--label", label, "--cwd", cwd)
        return r["tab"]["tab_id"], r["root_pane"]["pane_id"]

    def tab_close(self, tab_id: str) -> None:
        self.call("tab", "close", tab_id)

    def tab_rename(self, tab_id: str, label: str) -> None:
        self.call("tab", "rename", tab_id, label)

    def tabs(self) -> list:
        return self.call("tab", "list")["tabs"]

    def workspace_create(self, label: str, cwd: str) -> tuple:
        r = self.call("workspace", "create", "--label", label, "--cwd", cwd)
        return r["workspace"]["workspace_id"], r["tab"]["tab_id"], r["root_pane"]["pane_id"]

    def workspace_rename(self, workspace_id: str, label: str) -> None:
        self.call("workspace", "rename", workspace_id, label)

    def workspaces(self) -> list:
        return self.call("workspace", "list")["workspaces"]

    def pane_move_to_new_workspace(self, pane_id: str, label: str) -> dict:
        """Move a pane (and the chat running in it) into a fresh workspace; its ids change."""
        r = self.call("pane", "move", pane_id, "--new-workspace", "--label", label, "--tab-label", label,
                      "--no-focus")["move_result"]
        return {"workspace_id": r["created_workspace"]["workspace_id"], "pane_id": r["pane"]["pane_id"],
                "tab_id": r["pane"]["tab_id"]}

    def pane_move_to_workspace(self, pane_id: str, workspace_id: str, tab_label: str) -> dict:
        """Move a pane into a new tab of an existing workspace. Herdr closes the workspace it left if that
        workspace is now empty, and reports it as closed_workspace_id."""
        r = self.call("pane", "move", pane_id, "--new-tab", "--workspace", workspace_id, "--label", tab_label,
                      "--no-focus")["move_result"]
        return {"pane_id": r["pane"]["pane_id"], "tab_id": r["pane"]["tab_id"],
                "closed_workspace_id": r.get("closed_workspace_id")}

    def agent_start(self, name: str, pane_id: str, claude_args: list) -> None:
        """A freshly created tab's shell can still be starting (slow under load, e.g. several spawns in a row);
        herdr then refuses with agent_pane_busy, so wait for it rather than failing the spawn."""
        for attempt in range(self.SHELL_TRIES):
            try:
                self.call("agent", "start", name, "--kind", "claude", "--pane", pane_id,
                          "--timeout", "60000", "--", *claude_args)
                return
            except HerdrError as e:
                if e.code != "agent_pane_busy" or attempt == self.SHELL_TRIES - 1:
                    raise
                time.sleep(self.SHELL_WAIT)

    def pane_screen(self, pane_id: str) -> str:
        """The pane's visible screen as plain text."""
        p = self.run("pane", "read", pane_id, "--source", "visible", "--format", "text")
        if p.returncode != 0:
            raise HerdrError(f"herdr pane read: {p.stderr.strip() or p.stdout.strip() or f'exit {p.returncode}'}")
        return p.stdout

    def agent_prompt(self, name: str, text: str) -> None:
        self.call("agent", "prompt", name, text)

    def agents(self) -> list:
        return self.call("agent", "list")["agents"]

    def live_sessions(self) -> dict:
        """Claude session id -> agent record, for every live agent herdr sees."""
        out = {}
        for a in self.agents():
            sid = (a.get("agent_session") or {}).get("value")
            if sid:
                out[sid] = a
        return out
