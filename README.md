# hive

A queen Claude chat spawns labelled bee chats in Herdr tabs, reads their SendMessage handoffs, closes them only on a deliberate decision, and can reopen any of them later with the conversation intact.

The two roles: the **queen** leads, the **bees** (workers) do the work. Not related to aden-hive/hive, a separate agent runtime that also uses queens.

- Design: `docs/specs/2026-09-25-hive-design.md`
- Skills: `skills/hive-queen`, `skills/hive-bee`
- State: `~/.local/state/hive/<queen>.json`, or `~/.local/state/herd/` on machines set up before the rename (override with `HIVE_STATE_DIR`)

## Install

```
./install.sh        # uv tool install --editable, links both skills into ~/.claude/skills
```

## Use (from the queen chat, inside a Herdr pane)

```
hive init "fc: postiz rollout"   # moves to a new workspace if this one belongs to a hive still in use
hive adopt fc-postiz-rollout      # or: become an existing hive's orchestrator
hive spawn "drip copy" --model opus --why "bounded copy" --brief brief.md
hive status
hive handoff "drip copy" --file handoff.txt
hive close "drip copy"          # refuses without a handoff or while working
hive restore [--all | --every]
```

## Reaper

Closing a Herdr window leaves its server, and every Claude in it, running. `hive reap` stops any session that has had no client attached and no agent working for 10 minutes; `herdr --session <name>` later resumes every chat from the ids Herdr saved.

```
hive reap --install     # launchd job, runs every 60s (~/Library/LaunchAgents/com.eddydavies.hive-reaper.plist)
hive reap --dry-run     # what each running session would get
hive reap --uninstall
```

Stops are logged to `~/.local/state/hive/reaper.log`. `HIVE_REAP_GRACE` (seconds, default 600) and `HIVE_REAP_SKIP` (comma separated, default `default`) tune it. Anything it cannot read (server log, agent list) counts as in use.

## Test

```
uv run --group dev pytest
```
