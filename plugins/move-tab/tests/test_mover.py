"""move_tab drives `herdr pane move` in the right order with the right flags;
tell_overseer never prompts a busy chat. A fake `run` stands in for herdr."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from herdr_move_tab import mover


class FakeHerdr(object):
    def __init__(self, panes, tabs, overseer_status="idle"):
        self.panes = panes
        self.tabs = tabs
        self.calls = []
        self.overseer_status = overseer_status
        self.n = 0
        self.layout = LAYOUT

    def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ("pane", "list"):
            if args[3] == "w9":
                return {"panes": [{"pane_id": "w9:p1", "tab_id": "w9:t1", "agent": "claude",
                                   "agent_status": self.overseer_status,
                                   "terminal_title_stripped": "fixes overseer"}]}
            return {"panes": self.panes}
        if args[:2] == ("pane", "layout"):
            return {"layout": self.layout}
        if args[:2] == ("tab", "list"):
            return {"tabs": self.tabs}
        if args[:2] == ("pane", "move"):
            self.n += 1
            r = {"pane": {"pane_id": "w9:pn%d" % self.n, "tab_id": "w9:tn"}}
            if "--new-workspace" in args:
                r["created_workspace"] = {"workspace_id": "w9"}
            return {"move_result": r}
        return {}


PANES = [{"pane_id": "w1:p1", "tab_id": "w1:t1", "agent": "claude", "agent_session": {"value": "s1"}},
         {"pane_id": "w1:p2", "tab_id": "w1:t1"},
         {"pane_id": "w1:p3", "tab_id": "w1:t2"}]
# w1:p1 on the left (60%), w1:p2 on the right: a side by side split.
LAYOUT = {"area": {"x": 0, "y": 0, "width": 100, "height": 40},
          "panes": [{"pane_id": "w1:p1", "rect": {"x": 0, "y": 0, "width": 60, "height": 40}},
                    {"pane_id": "w1:p2", "rect": {"x": 60, "y": 0, "width": 40, "height": 40}}],
          "splits": [{"direction": "right", "ratio": 0.6, "rect": {"x": 0, "y": 0, "width": 100, "height": 40}}]}
TABS = [{"tab_id": "w1:t1", "label": "aws"}, {"tab_id": "w1:t2", "label": "other"}]


class MoveTabTest(unittest.TestCase):
    def test_keeps_a_side_by_side_split_side_by_side_with_its_ratio(self):
        fake = FakeHerdr(PANES, TABS)
        r = mover.move_tab("w1:t1", workspace_id="w9", run=fake)
        moves = [c for c in fake.calls if c[:2] == ("pane", "move")]
        self.assertEqual(moves[0], ("pane", "move", "w1:p1", "--new-tab", "--workspace", "w9", "--label", "aws",
                                    "--no-focus"))
        self.assertEqual(moves[1], ("pane", "move", "w1:p2", "--tab", "w9:tn", "--split", "right",
                                    "--target-pane", "w9:pn1", "--ratio", "0.6000", "--no-focus"))
        self.assertEqual(len(moves), 2)
        self.assertTrue(r["layout_exact"])
        self.assertEqual(r["panes"][0]["session"], "s1")

    def test_nested_split_rebuilds_as_the_same_tree(self):
        layout = {"area": {"x": 0, "y": 0, "width": 100, "height": 40},
                  "panes": [{"pane_id": "a", "rect": {"x": 0, "y": 0, "width": 60, "height": 40}},
                            {"pane_id": "b", "rect": {"x": 60, "y": 0, "width": 40, "height": 20}},
                            {"pane_id": "c", "rect": {"x": 60, "y": 20, "width": 40, "height": 20}}],
                  "splits": [{"direction": "right", "ratio": 0.6, "rect": {"x": 0, "y": 0, "width": 100, "height": 40}},
                             {"direction": "down", "ratio": 0.5, "rect": {"x": 60, "y": 0, "width": 40, "height": 40}}]}
        t = mover.split_tree(layout)
        self.assertEqual((t["direction"], t["first"]["pane_id"]), ("right", "a"))
        self.assertEqual((t["second"]["direction"], mover.leaves(t["second"])), ("down", ["b", "c"]))

    def test_unreadable_layout_falls_back_to_stacking_and_says_so(self):
        fake = FakeHerdr(PANES, TABS)
        fake.layout = {"area": {"x": 0, "y": 0, "width": 100, "height": 40}, "panes": [], "splits": []}
        r = mover.move_tab("w1:t1", workspace_id="w9", run=fake)
        self.assertFalse(r["layout_exact"])
        self.assertIn("down", [c for c in fake.calls if c[:2] == ("pane", "move")][1])

    def test_new_workspace_takes_the_name_and_keeps_the_tab_label(self):
        fake = FakeHerdr(PANES[2:], TABS)
        r = mover.move_tab("w1:t2", new_workspace_label="later", run=fake)
        move = [c for c in fake.calls if c[:2] == ("pane", "move")][0]
        self.assertIn("--new-workspace", move)
        self.assertEqual(move[move.index("--label") + 1], "later")
        self.assertEqual(move[move.index("--tab-label") + 1], "other")
        self.assertEqual(r["workspace_id"], "w9")
        self.assertTrue(r["layout_exact"])

    def test_refuses_a_move_into_the_same_workspace(self):
        with self.assertRaises(mover.MoveError):
            mover.move_tab("w1:t1", workspace_id="w1", run=FakeHerdr(PANES, TABS))


class TellOverseerTest(unittest.TestCase):
    RESULT = {"workspace_id": "w9", "label": "aws", "panes": [{"new": "w9:pn1", "agent": "claude"}]}

    def test_prompts_an_idle_overseer(self):
        fake = FakeHerdr([], [])
        self.assertEqual(mover.tell_overseer(self.RESULT, run=fake), "told fixes overseer")
        self.assertTrue(any(c[:2] == ("agent", "prompt") for c in fake.calls))

    def test_never_prompts_a_working_overseer(self):
        fake = FakeHerdr([], [], overseer_status="working")
        self.assertIn("busy", mover.tell_overseer(self.RESULT, run=fake))
        self.assertFalse(any(c[:2] == ("agent", "prompt") for c in fake.calls))


if __name__ == "__main__":
    unittest.main()
