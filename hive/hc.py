"""Thin wrapper over the `hc` CLI (herdr-core), for bees that run on another machine.
Piped output is JSON except for run, exec, read and file read, which print text. Every
error is raised as HcError with hc's own kind and message."""

import json
import shutil
import subprocess
from pathlib import Path


class HcError(Exception):
    def __init__(self, msg, kind=None):
        super().__init__(msg)
        self.kind = kind


def _error(stderr: str, stdout: str, code: int) -> HcError:
    for text in (stderr, stdout):
        try:
            body = json.loads(text.strip().splitlines()[-1])
        except (ValueError, IndexError):
            continue
        if isinstance(body, dict) and "error" in body:
            e = body["error"]
            return HcError(e.get("message") or f"exit {code}", e.get("kind"))
    return HcError(stderr.strip() or stdout.strip() or f"exit {code}")


class Hc:
    TIMEOUT = 120  # seconds for one hc command; wait passes its own longer timeout

    def __init__(self):
        self.bin = shutil.which("hc") or str(Path.home() / ".local/bin/hc")

    def run(self, *args: str, stdin: str = None, timeout: int = None) -> subprocess.CompletedProcess:
        try:
            return subprocess.run([self.bin, *args], capture_output=True, text=True, input=stdin,
                                  timeout=timeout or self.TIMEOUT)
        except FileNotFoundError:
            raise HcError("hc (herdr-core) is not installed; see https://herdr.dev/core/")
        except subprocess.TimeoutExpired:
            raise HcError(f"hc {' '.join(args[:2])}: no answer in {timeout or self.TIMEOUT}s")

    def text(self, *args: str, stdin: str = None, timeout: int = None) -> str:
        p = self.run(*args, stdin=stdin, timeout=timeout)
        if p.returncode != 0:
            raise _error(p.stderr, p.stdout, p.returncode)
        return p.stdout

    def call(self, *args: str, timeout: int = None) -> dict:
        p = self.run(*args, timeout=timeout)
        if p.returncode != 0:
            raise _error(p.stderr, p.stdout, p.returncode)
        try:
            return json.loads(p.stdout)
        except ValueError:
            raise HcError(f"hc {' '.join(args[:2])}: not JSON: {p.stdout.strip()[:200]}")

    def machines(self) -> list:
        return self.call("machine", "ls").get("machines", [])

    def home(self, machine: str) -> str:
        return self.text("exec", "--on", machine, "sh", "-c", "echo $HOME").strip()

    def write_file(self, machine: str, path: str, data: str) -> None:
        self.text("file", "write", "--on", machine, path, stdin=data)

    def read_file(self, machine: str, path: str):
        """The file's text, or None when it does not exist yet."""
        try:
            return self.text("file", "read", "--on", machine, path)
        except HcError as e:
            if e.kind == "not_found":
                return None
            raise

    def start(self, machine: str, cwd: str, name: str, argv: list) -> str:
        """Start a program in a background terminal on `machine`; returns its address (`machine/t7`)."""
        r = self.call("run", "--bg", "--outlive-parent", "--on", machine, "--cwd", cwd, "--name", name, "--", *argv)
        return r["address"]

    def get(self, address: str):
        """The terminal's record, or None when hc no longer knows it."""
        try:
            return self.call("get", address)
        except HcError as e:
            if e.kind == "not_found":
                return None
            raise

    def status(self, record) -> str:
        """working, done, blocked, error, idle; "finished" for an ended terminal; "" while nothing is reported."""
        if record is None or record.get("state") == "finished":
            return "finished"
        return ((record.get("status") or {}).get("state")) or ""

    def wait(self, address: str, timeout: int) -> dict:
        return self.call("wait", address, "--timeout", str(timeout), timeout=timeout + 30)

    def screen(self, address: str, lines: int = 0) -> str:
        return self.text("read", address, "--lines", str(lines))

    def keys(self, address: str, *keys: str) -> None:
        self.call("keys", address, *keys)

    def kill(self, address: str) -> None:
        try:
            self.call("kill", address)
        except HcError as e:
            if e.kind not in ("not_found", "finished"):
                raise

    def rm(self, address: str) -> None:
        try:
            self.call("rm", address)
        except HcError as e:
            if e.kind != "not_found":
                raise
