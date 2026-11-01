# Build your own hive

A build prompt. Paste this whole file into Claude Code (or any coding agent) and say "build this". It describes a small tool that lets one queen chat spawn bee chats in their own terminal tabs, collect their results, close them on purpose, and reopen any of them later with the conversation intact.

The original is about 500 lines of stdlib Python plus two skill files. Expect an afternoon.

## The idea in five lines

1. One **queen** chat holds the plan. It never does bulk work itself.
2. It spawns **bees**, each a fresh Claude Code session in its own labelled tab, on the model the work needs.
3. Every bee gets a written **brief** and answers with a structured **handoff**.
4. Finishing is not a reason to close. The queen closes a bee only when it is complete, no longer relevant, and not worth a human look.
5. Every session id is written to disk **before** the tab opens, so anything ever spawned can be resumed later.

## What you need

- Claude Code CLI, with the `SendMessage` and `ListAgents` tools available to sessions (this is how chats talk to each other).
- A terminal multiplexer you can script. The original uses Herdr. tmux, Zellij, WezTerm or kitty all work; see "Swapping the multiplexer" below.
- Python 3.11+ and uv. No third party runtime dependencies.

## Parts

| Part | Job |
|---|---|
| `hive/registry.py` | Durable JSON state, one file per queen, atomic writes |
| `hive/herdr.py` | Thin wrapper over the multiplexer CLI; the only place that shells out |
| `hive/cli.py` | The commands, built on the two above |
| `skills/hive-queen/SKILL.md` | Teaches the central chat how to run the hive |
| `skills/hive-bee/SKILL.md` | Teaches a bee how to work and report |
| `install.sh` | `uv tool install --editable .` and symlink both skills into `~/.claude/skills/` |
| `tests/` | pytest, with a fake multiplexer binary put first on PATH |

Rule that keeps it clean: chats talk over SendMessage, and only the `hive` CLI touches the multiplexer.

## Commands

```
hive init "<label>" --name "<this chat's SendMessage name>" [--model fable]
hive spawn "<label>" --model opus|fable --why "<one line>" --brief <file> [--cwd <dir>]
hive handoff "<label>" --file <file|->
hive mark-review "<label>" --reason "..."
hive close "<label>" [--force]
hive status
hive ls
hive sync
hive restore [<orch>] [<label>...] [--all] [--every]
```

Every command also takes `--orch <slug>`. Without it, the queen is whichever registry owns the current workspace id.

### init

Run by the queen chat in its own pane. Reads the workspace id and pane id from the environment, finds its own Claude session id by matching its pane in the multiplexer's agent list, writes the registry, then renames the workspace and its own tab to `◆ <label>`. It adopts the workspace it is already in and never creates one. It refuses if that workspace already belongs to another registry.

### spawn

Order matters here:

1. Check the brief file exists. Generate a uuid for the session.
2. Copy the brief to `<state dir>/<orch slug>/briefs/<worker slug>.md`.
3. Write the bee to the registry with status `starting`. Save.
4. Create the tab in the queen's workspace, labelled `o> <label>` or `f> <label>`. Save the tab and pane ids.
5. Start Claude in that pane: `claude --session-id <uuid> --name "<label>" --model <model id>`.
6. Type one kickoff prompt into the pane (text below).
7. Status `live`. Save.

If any multiplexer call fails, mark the bee `failed`, store the error text, save, and exit non zero. No silent retries.

Kickoff prompt:

```
You are a hive worker named "<label>". Load the hive-bee skill now. Your orchestrator's SendMessage name is "<orchestrator name>". Your brief is at <path>. Read it and start.
```

This is the only time the tool types into a bee's terminal. A fresh bee has no SendMessage peer yet, so the first message has to arrive this way. Everything after is SendMessage.

### handoff, mark-review, close

- `handoff` stores the bee's report verbatim with a timestamp and sets status `handed-off`. Empty text is an error.
- `mark-review` sets status `review`, stores the reason, and renames the tab with a `👀 ` prefix.
- `close` refuses without a recorded handoff (unless `--force`) and refuses while the agent reports `working`. It closes the tab only if the tab still exists, sets status `closed`, and keeps every other field. A closed bee is still restorable.

### status, ls, sync

- `status` prints one line per bee: status, model, label, tab id, and the first content line of the handoff.
- `ls` prints one line per queen with bee counts by status.
- `sync` compares the registry with the live agent list. A bee that was `live`, `handed-off` or `review` and whose session is no longer live becomes `detached`. Live bees get their tab and pane ids refreshed.

### restore

- Workspace gone: create it with the saved label and cwd, then resume the queen in it with `claude --resume <orchestrator session id>`.
- Workspace present but queen not live: new tab, resume the queen there.
- Default set: every bee not `closed`. `--all` includes closed. Naming labels restores just those.
- Each bee: new tab with its saved label, then `claude --resume <uuid> --name "<label>" --model <model id>`.
- A bee whose session id is already live is skipped, never duplicated.
- `--every` does this for every registry on disk, for the day the whole multiplexer state is wiped.

## Registry

One file per queen at `~/.local/state/hive/<orch-slug>.json` (override with `HIVE_STATE_DIR`).

```json
{
  "label": "postiz rollout",
  "workspace_id": "ws_3",
  "cwd": "/path/to/repo",
  "orchestrator": {
    "name": "postiz-rollout",
    "session_id": "<uuid>",
    "model": "fable",
    "pane_id": "p_1",
    "tab_id": "t_1"
  },
  "workers": [
    {
      "label": "drip copy",
      "slug": "drip-copy",
      "model": "opus",
      "why": "bounded copy task",
      "session_id": "<uuid>",
      "cwd": "/path/to/repo",
      "brief": "/Users/me/.local/state/hive/postiz-rollout/briefs/drip-copy.md",
      "status": "starting | live | handed-off | review | detached | closed | failed",
      "tab_id": "t_7",
      "pane_id": "p_9",
      "handoff": { "text": "...", "at": "<iso time>" },
      "error": null,
      "created_at": "<iso time>",
      "updated_at": "<iso time>"
    }
  ],
  "created_at": "<iso time>",
  "updated_at": "<iso time>"
}
```

Writes are atomic: write a temp file in the same directory, then `os.replace` onto the real path. If the write fails, delete the temp file and leave the old registry untouched.

Slug rule (agent names in the multiplexer): lowercase, runs of anything outside `[a-z0-9]` become `-`, must start with a letter (prefix `w-` if not), max 32 characters, deduplicated with `-2`, `-3`. Bees can be looked up by label or slug.

## Model split

Map short names to model ids in one dict so they are easy to change:

```python
MODEL_IDS = {"opus": "claude-opus-5-5", "fable": "claude-fable-5-1"}
```

- **Strong model** (fable here) when the bee's core output is a decision: architecture, tradeoffs, reconciling conflicting evidence, final review, tone sensitive writing.
- **Cheaper model** (opus here) for everything bounded: research scans, inventories, implementing a written plan, tests, bulk edits, data pulls.
- Unsure: the cheaper one. A bee that hits a judgement wall says so and asks to be spawned again on the strong model.

`--why` is required on spawn so the reason for the choice is on record.

## Multiplexer calls the wrapper needs

The original shells out to these and parses JSON from stdout. Any call with a non zero exit, unparseable output, or an `error` key raises with the multiplexer's own message.

```
herdr tab create --workspace <ws> --label <label> --cwd <dir>     -> tab id, root pane id
herdr tab close <tab>
herdr tab rename <tab> <label>
herdr tab list
herdr workspace create --label <label> --cwd <dir>                -> workspace id, tab id, root pane id
herdr workspace rename <ws> <label>
herdr workspace list
herdr agent start <name> --kind claude --pane <pane> --timeout 60000 -- <claude args>
herdr agent prompt <name> <text>
herdr agent list                                                  -> name, pane, tab, cwd, status, session id
```

Environment read: `HERDR_ENV` (must be `1`), `HERDR_WORKSPACE_ID`, `HERDR_PANE_ID`.

### Swapping the multiplexer

Keep the wrapper's method names and change only its insides. With tmux for example: a workspace is a session, a tab is a window, `agent start` is `send-keys "claude ..." Enter`, and `agent prompt` is another `send-keys`. The one thing tmux will not give you is the Claude session id of a live pane or a `working` status. Two fixes: track liveness yourself by checking whether the window still exists, and have the queen pass its own session id to `hive init` as a flag.

## Skill: hive-queen

Save as `skills/hive-queen/SKILL.md`.

````markdown
---
name: hive-queen
description: Use when the user asks this chat to orchestrate other chats, spawn workers or new chats in tabs, act as the central or orchestrator chat, or restore a set of chats they closed. Covers spawning labelled worker chats with the right model, reading their SendMessage handoffs, deciding when to close them, and reopening everything later.
---

# hive queen

You are the central chat. Workers do bounded work in their own tabs; you hold the plan, judge their results, and decide when each one closes. The `hive` CLI does every tab operation. You never call the multiplexer yourself.

Talk to workers with SendMessage (their name is their label). Workers talk to you with SendMessage.

## Start

Once per orchestrator:

```
ListAgents                       # find this chat's own name as others see it
hive init "<short label>" --name "<that name>"
```

`init` adopts the workspace you are already in, so start in a fresh workspace if you want it clean. `hive status` shows your workers, `hive ls` shows every orchestrator on record.

## Spawn a worker

1. Choose the model:
   - **fable** when the worker's core output is a decision: architecture, tradeoffs, reconciling conflicting evidence, final review, tone sensitive writing.
   - **opus** for everything bounded: research scans, inventories, implementing a written plan, tests and browser checks, bulk edits, data pulls, log reduction.
   - Unsure: opus. A worker that hits a judgement wall will ask you to spawn it again on fable.
2. Write a brief as if the worker knows nothing: repo path and exact objective; files in and out of scope; evidence to return (paths, line refs, commands run, diffs, uncertainty); how to verify; stop conditions (code does not match the brief, a command fails after one retry, the task needs out of scope files). Save it in your scratchpad.
3. Spawn:

```
hive spawn "<label>" --model opus|fable --why "<one line>" --brief <file> [--cwd <dir>]
```

Labels are 2 to 4 plain words that say what the work is (`drip copy`, `pricing review`), so the user can find the tab.

Spawn independent slices in parallel. Keep tightly coupled work in one worker or with you.

## Handoffs

A worker finishes by sending you:

```
HIVE HANDOFF <label>
complete: yes|no (...)
review_worthy: yes|no (...)
summary: ...
artifacts: ...
open: ...
```

Record it verbatim straight away: write it to a scratch file and run `hive handoff "<label>" --file <file>`. Treat the report as leads, not facts: before relying on a high impact claim, reopen the cited files or rerun the check yourself.

## Closing: deliberate, never automatic on "done"

| complete | no longer relevant (your call) | review_worthy | do |
|---|---|---|---|
| yes | yes | no | `hive close "<label>"` and tell the user in one line |
| yes | yes | yes | `hive mark-review "<label>" --reason "..."`, then ask the user: "close <label>? worth a look because ...". Close only on their yes. |
| no, or still relevant | | | leave it open |

"No longer relevant" means nothing still planned will send it more work and its context is now captured in your handoff record. If you might message it again, it stays open. `hive close` refuses without a recorded handoff and while the worker is working; do not reach for `--force` unless the user asked.

Batch the review questions: when several workers await review, ask about them together.

## Restore

```
hive restore                     # this queen: every bee not closed
hive restore <orch> <label>...   # specific bees, including closed ones
hive restore --all               # include closed bees
hive restore --every             # every queen, after everything was wiped
```

Already open chats are skipped, never duplicated.

## Do not

- Close a worker because it said it is done.
- Type into a worker's terminal after spawn; use SendMessage.
- Spawn fable for bounded execution, or opus for the final judgement you owe the user.
````

## Skill: hive-bee

Save as `skills/hive-bee/SKILL.md`.

````markdown
---
name: hive-bee
description: Use when your first prompt says you are a hive worker, or names an orchestrator chat you report to. Covers reading your brief, working inside its scope, reporting back with a HIVE HANDOFF over SendMessage, and staying open afterwards.
---

# hive worker

An orchestrator chat spawned you in your own tab to do one slice of work. Your kickoff prompt gave you your label, the orchestrator's SendMessage name, and the path of your brief.

## Work

1. Read the brief in full. It is your whole scope.
2. Do the work. Stay inside the brief's files and objective.
3. Stop and report instead of improvising when: the code or data does not match the brief; a command fails after one sensible retry; the task needs files outside scope; the work turns out to be mostly judgement you were not asked to make (say so, and suggest the orchestrator spawn this again on fable).
4. Questions for the orchestrator go by SendMessage, one message, specific. Keep working on anything the answer does not block.

## Report

When you are finished, or stopped, send exactly one SendMessage to the orchestrator:

```
HIVE HANDOFF <your label>
complete: yes|no (what remains, if no)
review_worthy: yes|no (why the user might want to look at this tab themselves)
summary: <3 to 6 lines: what you did and what you found>
artifacts: <paths, urls, commits; or none>
open: <loose ends, risks, things you could not verify; or none>
```

review_worthy is yes when the user would plausibly want to scroll this conversation: visual output to eyeball, a judgement call you made, surprising findings, anything irreversible you did. Otherwise no.

Evidence over adjectives: file paths with line numbers, the commands you ran and their result, exact failures.

## After the handoff

Stay open and idle. Never close your own tab or exit; the orchestrator (or the user) decides when you close, and you may get follow up work by SendMessage. If you do, finish it and send a fresh HIVE HANDOFF.
````

## Decisions to make before you build

- **Permissions for bees.** Unattended bees stall on the first permission prompt. The original starts every bee with `--dangerously-skip-permissions`, which suits a machine where every session already runs that way. If that is not you, give bees an allowlist in settings instead, and accept that some will pause and wait.
- **Model names.** Swap the two entries in `MODEL_IDS` for whatever pair you use.
- **One workspace per queen** is assumed: queen in tab 1, one tab per bee.

## Tests to ask for

Put a fake multiplexer script first on PATH. It logs its argv to a file and answers canned JSON from a state file. Then cover:

1. Slug rules: letter start, 32 character cap, dedupe of labels that slug the same (`Drip copy` and `drip-copy`).
2. Atomic save: a failed write leaves the old registry file intact.
3. Spawn writes the registry before the tab is created, and builds the right `claude` arguments.
4. A failed spawn marks the bee `failed` and exits non zero.
5. Close refuses without a handoff, and refuses while the agent is `working`.
6. `mark-review` renames the tab with the 👀 prefix.
7. Restore skips live session ids, uses `--resume`, and rebuilds the workspace when it is missing.
8. Sync marks vanished bees `detached`.
9. Running outside the multiplexer gives a clear error before the registry changes.

Then one live smoke test: init in a scratch workspace, spawn one cheap bee with a two line brief, receive its handoff, close it, restore it, confirm the same session id resumed.

## Out of scope for v1

Non Claude bees, cross machine use, automatic spawning on the stronger model, a dashboard.
