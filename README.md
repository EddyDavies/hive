# herd

A shepherd Claude chat spawns labelled sheepdog chats in Herdr tabs, reads their SendMessage handoffs, closes them only on a deliberate decision, and can reopen any of them later with the conversation intact.

- Design: `docs/specs/2026-09-25-herd-design.md`
- Skills: `skills/herd-shepherd`, `skills/herd-sheepdog`
- State: `~/.local/state/herd/<orchestrator>.json` (override with `HERD_STATE_DIR`)

## Install

```
./install.sh        # uv tool install --editable, links both skills into ~/.claude/skills
```

## Use (from the shepherd chat, inside a Herdr pane)

```
herd init "fc: postiz rollout"   # moves to a new workspace if this one belongs to a herd still in use
herd adopt fc-postiz-rollout      # or: become an existing herd's orchestrator
herd spawn "drip copy" --model opus --why "bounded copy" --brief brief.md
herd status
herd handoff "drip copy" --file handoff.txt
herd close "drip copy"          # refuses without a handoff or while working
herd restore [--all | --every]
```

## Reaper

Closing a Herdr window leaves its server, and every Claude in it, running. `herd reap` stops any session that has had no client attached and no agent working for 10 minutes; `herdr --session <name>` later resumes every chat from the ids Herdr saved.

```
herd reap --install     # launchd job, runs every 60s (~/Library/LaunchAgents/com.eddydavies.herd-reaper.plist)
herd reap --dry-run     # what each running session would get
herd reap --uninstall
```

Stops are logged to `~/.local/state/herd/reaper.log`. `HERD_REAP_GRACE` (seconds, default 600) and `HERD_REAP_SKIP` (comma separated, default `default`) tune it. Anything it cannot read (server log, agent list) counts as in use.

## Test

```
uv run --group dev pytest
```
