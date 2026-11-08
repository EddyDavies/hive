# hive spawn --on <machine>: remote bees on herdr-core

Date: 2026-11-08. Branch `hive-on-machine`.

## Why

A bee that must outlive the Mac (overnight runs, travel, memory heavy work) runs on a box such as the Pally workbox. herdr-core (`hc`) already starts programs on a saved SSH machine, reports Claude Code's status, waits on it, reads and writes its files, and lets a person attach. hive only has to drive it and mirror the result into the Mac registry.

## Shape

- Local bees are unchanged: Herdr TUI tabs, SendMessage handoffs.
- A remote bee is an hc terminal on the machine named by `--on`. `--cwd` is required and must be an absolute remote path.
- Launch: `hc run --bg --outlive-parent --on <machine> --cwd <cwd> --name <slug> bash -lc 'exec claude <claude_args> <kickoff>'`. `bash -lc` loads the box profile (Claude token, PATH).
- The brief goes over with `hc file write --on` to `<remote home>/.local/state/hive/<queen slug>/briefs/<slug>.md`; the remote home comes from `hc exec --on <machine> sh -c 'echo $HOME'` once per spawn.
- The remote kickoff carries the HIVE HANDOFF format itself and names the handoff file `<remote home>/.local/state/hive/<queen slug>/handoffs/<slug>.txt`, because the box has no hive-bee skill and no queen to message.
- After launch hive polls `hc get` for a status. If none arrives in 20 s and the screen shows the folder trust prompt, it presses down and enter, then waits up to 30 s for `working`. Otherwise the spawn fails with the screen tail in the error and the terminal is removed.
- Each remote bee also gets a Mac tab in the hive workspace running `hc attach <address>`, labelled `o> <label> @<machine>`, so Eddy can see it and take over.
- `hive sync` and `hive status` read `hc get` for remote bees: `finished` or not found means detached; when the remote handoff file exists it is recorded as the bee's handoff (status handed-off).
- `hive wait <label>` runs `hc wait <address>` (returns on done, blocked, exit or timeout), syncs, then prints the recorded handoff, the blocked screen tail, or "still working".
- `hive close` refuses while `hc get` says working, then `hc kill`, `hc rm` and closes the Mac tab. `hive restore` runs `claude --resume <session id>` through hc on the same machine and cwd and reopens the attach tab.

## Files

| File | Change |
|---|---|
| `hive/hc.py` (new) | `Hc` wrapper: machines, home, write_file, read_file, start, get, wait, screen, keys, kill, rm. JSON parsing, `HcError` with hc's kind and message. |
| `hive/herdr.py` | `pane_run(pane_id, command)` for the attach tab. |
| `hive/registry.py` | `new_worker` gains `machine`, `address`, `remote_brief`, `remote_handoff`. |
| `hive/cli.py` | `spawn --on`, `remote_kickoff`, `settle_remote`, `sync_remote`, `cmd_wait`, remote branches in `tab_label`, `sync`, `cmd_status`, `cmd_close`, `restore_one`; parser entries. |
| `tests/bin/hc` (new) | Fake hc: logs argv, serves a seeded world (machines, home, files, terminals, screens, wait reply). |
| `tests/bin/herdr` | `pane run`. |
| `tests/conftest.py` | Fake hc env in the `fake` fixture. |
| `tests/test_remote.py` (new) | Spawn record and calls, cwd and machine checks, trust dialog, failed settle, sync mirroring, wait output, close rules, restore. |
| `skills/hive-queen/SKILL.md`, `README.md` | Remote bees section and usage lines. |

## Tests first

Deterministic contracts: the worker record and the hc calls a spawn makes; refusal without an absolute cwd or with an unknown machine; trust dialog cleared with keys; failed settle leaves a failed record and no terminal or tab; sync records a remote handoff and detaches a finished terminal; wait prints the handoff or the blocked screen; close refuses while working and otherwise kills, removes and closes the tab; restore resumes on the machine.

## Live check

Against hc machine `pally-workbox`: a brief that creates one file under `/home/ubuntu/hive-trial` and writes its handoff; `hive wait` returns the handoff text; `hive close` kills and removes the terminal; the remote folder and the Mac tab are cleaned up.
