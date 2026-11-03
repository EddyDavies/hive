"""A resumed claude chat keeps how it ran (model, name, permission mode) and
is never resumed into a session that is already open in another pane."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from herdr_undo_close import relaunch

ARGV = ["claude", "--session-id", "old", "--name", "linear hygiene", "--model", "claude-opus-5-5",
        "--dangerously-skip-permissions", "--print", "do the thing"]
CONFIG = {"restore_process": True, "relaunch_agents": True, "relaunch_programs": []}


class FakeApi(object):
    def __init__(self, responses):
        self.responses = responses

    def call(self, method, params):
        r = self.responses.get(method)
        if isinstance(r, Exception):
            raise r
        return r or {}


class ResumeFlagsTest(unittest.TestCase):
    def test_keeps_model_name_and_permission_flags_and_drops_session_and_prompt(self):
        self.assertEqual(relaunch.kept_claude_flags(ARGV),
                         ["--name", "linear hygiene", "--model", "claude-opus-5-5", "--dangerously-skip-permissions"])

    def test_keeps_flags_written_with_equals(self):
        self.assertEqual(relaunch.kept_claude_flags(["claude", "--model=opus", "--resume=abc"]), ["--model=opus"])

    def test_resume_command_carries_the_flags_then_the_session(self):
        plan = relaunch.relaunch_plan({"kind": "agent", "agent": "claude", "session_id": "s1",
                                       "flags": ["--model", "opus", "--dangerously-skip-permissions"]}, CONFIG)
        self.assertEqual(plan["command"], ["claude", "--model", "opus", "--dangerously-skip-permissions", "-r", "s1"])

    def test_intent_reads_flags_from_the_claude_process_not_its_helpers(self):
        info = {"process_info": {"shell_pid": 1, "foreground_processes": [
            {"pid": 2, "argv0": "node", "argv": ["node", "mcp.js", "--model", "x"]},
            {"pid": 3, "argv0": "claude", "argv": ARGV}]}}
        intent = relaunch.build_pane_intent(FakeApi({"pane.process_info": info}),
                                            {"pane_id": "w1:p1", "agent": "claude",
                                             "agent_session": {"kind": "id", "value": "s1"}})
        self.assertEqual(intent["session_id"], "s1")
        self.assertIn("--dangerously-skip-permissions", intent["flags"])

    def test_a_failed_process_read_still_resumes_plainly(self):
        intent = relaunch.build_pane_intent(FakeApi({"pane.process_info": RuntimeError("gone")}),
                                            {"pane_id": "w1:p1", "agent": "claude",
                                             "agent_session": {"kind": "id", "value": "s1"}})
        self.assertNotIn("flags", intent)
        self.assertEqual(relaunch.relaunch_plan(intent, CONFIG)["command"], ["claude", "-r", "s1"])


class LiveSessionTest(unittest.TestCase):
    def test_a_session_open_in_another_pane_is_not_resumed_again(self):
        plan = relaunch.relaunch_plan({"kind": "agent", "agent": "claude", "session_id": "s1"}, CONFIG)
        live = relaunch.live_agent_sessions(FakeApi({"agent.list": {"agents": [
            {"pane_id": "w2:p4", "agent_session": {"kind": "id", "value": "s1"}}]}}))
        relaunch.refuse_live_sessions([plan], live)
        self.assertFalse(plan["allowed"])
        self.assertIsNone(plan["command"])
        self.assertIn("w2:p4", relaunch.describe_skipped(plan))

    def test_a_closed_session_still_resumes(self):
        plan = relaunch.relaunch_plan({"kind": "agent", "agent": "claude", "session_id": "s1"}, CONFIG)
        relaunch.refuse_live_sessions([plan], {"other": "w2:p4"})
        self.assertTrue(plan["allowed"])


if __name__ == "__main__":
    unittest.main()
