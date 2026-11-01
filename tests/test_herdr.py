import pytest

from hive.herdr import Herdr, HerdrError


def test_tab_create_returns_ids_and_passes_flags(fake):
    tab, pane = Herdr().tab_create("w1", "opus · drip", "/x")
    assert tab.startswith("w1:t") and pane.startswith("w1:p")
    assert fake.calls()[-1] == ["tab", "create", "--workspace", "w1", "--label", "opus · drip", "--cwd", "/x"]


def test_workspace_create_returns_three_ids(fake):
    ws, tab, pane = Herdr().workspace_create("◆ o", "/x")
    assert tab.startswith(ws + ":t") and pane.startswith(ws + ":p")


def test_agent_start_puts_claude_args_after_double_dash(fake):
    h = Herdr()
    _, pane = h.tab_create("w1", "l", "/x")
    h.agent_start("drip", pane, ["--session-id", "abc"])
    assert fake.calls()[-1] == ["agent", "start", "drip", "--kind", "claude", "--pane", pane,
                                "--timeout", "60000", "--", "--session-id", "abc"]
    assert h.live_sessions()["abc"]["name"] == "drip"


def test_error_json_raises_with_message(fake, monkeypatch):
    monkeypatch.setenv("FAKE_HERDR_FAIL", "tab close")
    with pytest.raises(HerdrError, match="injected failure"):
        Herdr().tab_close("w1:t1")


def test_refuses_outside_herdr(fake, monkeypatch):
    monkeypatch.delenv("HERDR_ENV")
    with pytest.raises(HerdrError, match="not inside Herdr"):
        Herdr()
