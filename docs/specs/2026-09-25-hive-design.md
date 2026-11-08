# hive: queen and bee chats on Herdr

Date: 2026-09-25. Status: draft for review.

## Purpose

One queen chat spawns bee chats, each in its own labelled Herdr tab, running the model the work needs. Bees report back over SendMessage. A bee is closed only on a deliberate decision, never because its task finished. Everything that was ever spawned can be reopened with its conversation intact.

## Agreed rules

- Queen runs Fable. Bees default to Opus; a bee runs Fable only when its own work is mostly judgement (efficient-fable split).
- Chats talk over SendMessage. Only the `hive` CLI touches Herdr (tabs, workspaces, agent start).
- One Herdr workspace per queen (option A): queen is tab 1, one tab per bee.
- Personal tooling: code in `~/code/tools/hive`, skills in `~/.claude/skills/`, state in `~/.local/state/hive/`. Nothing in campaign-central.
- Close rule (section 3).

## Section 1: parts

1. **`hive` CLI**, `hive.py`, stdlib only, run through `uv run --script`, symlinked to `~/.local/bin/hive`. All Herdr calls go through it.
2. **Registry**, one JSON file per queen: `~/.local/state/hive/<orch-slug>.json`. Written atomically (temp file + rename) before any tab opens.
3. **Skills**: `hive-queen` (spawn, model choice, handoffs, close table, asking Eddy) and `hive-bee` (who to report to, handoff format, never close yourself). Both live in the repo and are symlinked into `~/.claude/skills/`.

## Section 2: starting a queen and spawning bees

### `hive init "<label>"`

Run by the queen chat inside its own pane. Reads `HERDR_WORKSPACE_ID` and `HERDR_PANE_ID`, looks up its own Claude session id from `herdr agent list` (`agent_session.value`), moves its own pane into a new workspace `◆ <label>` (`herdr pane move --new-workspace`) and places it directly below the workspace it left (the socket API's `workspace.move`, which has no CLI command; failure only warns), recording the home workspace and tab label; when `hive close` closes the last open bee the pane moves back as a new tab with its old label (`pane move --new-tab --workspace`) and Herdr closes the emptied hive workspace; the next spawn moves it out again. A chat whose tab is its workspace's only one stays put instead (moving would close its home) and its workspace and tab names are restored on return (revised 2026-10-28), and writes the registry with the queen's session id, cwd, name and model. The queen chat is renamed to the fixed name `queen: <label>` by typing `/rename` into its pane (works mid-turn; a user-set name is stored in the transcript and survives `claude --resume`, both checked 2026-09-30). Without this Claude derives a new name (cwd plus a random suffix) on every start, which is how handoffs went to a name that no longer existed. `hive spawn` and `hive sync` reapply the name if the chat is running under another one. As a fallback, `hive queen` reads the live name from Claude's own session records (`~/.claude/sessions/<pid>.json`, matched on session id, live pids only). If that workspace already belongs to another registry, init takes it over when that hive is done (every bee closed or failed, and its queen is this chat or not mid-turn; revised 2026-10-24, the 3 hour idle wait moved chats into new workspaces for nothing). A chat that already queens a done hive can init a new one in place: the old hive is retired; the old registry is retired (`workspace_id` null, `retired_at` set; restore rebuilds it in a fresh workspace). Otherwise init moves its own pane into a new workspace (`herdr pane move --new-workspace`). `hive adopt <slug>` makes the current chat an existing registry's queen (old one kept under `previous_orchestrators`), with the same take over or move rule when its workspace belongs to another hive; it refuses when the registry's open bees are live in a different Herdr server, since panes cannot move between servers. Before typing `/rename`, hive reads the queen's screen (`herdr pane read`) and skips the rename while the input box holds a draft or is not visible; the next command retries. Every command finds the chat's own registry by `CLAUDE_CODE_SESSION_ID` before falling back to the workspace, because workspaces change hands and a moved pane keeps stale `HERDR_*` env vars. Chats all run in bypass mode (`permissions.defaultMode` in user settings, so herdr's bare `claude --resume` relaunch keeps it) so cross-session messages are never held for approval. Revised 2026-10-05.

### `hive spawn "<label>" --model opus|fable --brief <file> [--cwd <dir>]`

1. Generate a uuid; write the bee to the registry with status `starting`.
2. `herdr tab create` in the queen's workspace, label `<m>> <label>` (`o>` opus, `f>` fable), cwd defaulting to the queen's.
3. `herdr agent start <slug> --kind claude --pane <pane> -- --session-id <uuid> --name "<label>" --model <model id> --dangerously-skip-permissions`. `<slug>` is the label lowercased to `[a-z0-9-]`, max 32, deduplicated.
4. `herdr agent prompt <slug> "<kickoff>"`, where the kickoff says: load the `hive-bee` skill, your queen is `<name>`, your brief is at `<file>` (copied into `~/.local/state/hive/<orch-slug>/briefs/`).
5. Status `live`. Print the tab id and slug.

Any failed step marks the bee `failed` with the error, prints it, and exits non zero. No silent retries.

### Labels

- Workspace: `◆ <orchestrator label>`, e.g. `◆ fc: postiz rollout`.
- Queen tab: `◆ <orchestrator label>`.
- Bee tab: `<m>> <label>`, e.g. `o> drip copy`, `f> pricing review`. When a bee is awaiting your review, `hive` renames its tab to `👀 o> <label>`.
- Claude session name (what ListAgents and SendMessage show, and what `claude -r` lists): `<label>`.

### Model choice (in `hive-queen`)

Fable when the bee's core output is a decision: architecture, product or safety tradeoffs, reconciling conflicting evidence, final review, anything user facing where tone and judgement matter. Opus for everything bounded: research scans, inventories, implementing a written plan, test runs, bulk edits, data pulls. When unsure, Opus, and the bee may ask the queen to re-spawn on Fable if it hits a judgement wall. The queen states the choice and one-line reason in the registry (`--why`).

## Section 3: handoff and closing

### Handoff

When a bee believes it has finished (or is stuck), it sends the queen one SendMessage:

```
HIVE HANDOFF <label>
complete: yes|no (what remains, if no)
review_worthy: yes|no (why Eddy might want to look)
summary: <3 to 6 lines>
artifacts: <paths, urls, commits>
open: <loose ends, or none>
```

The queen records it verbatim: `hive handoff <label> --file <tmp>` (status `handed-off`). The bee then stays idle in its tab; it never closes itself.

### Close decision (queen)

The queen judges relevance itself (it holds the bigger picture); the bee supplies complete and review_worthy (yes only when Eddy himself must decide or look).

Eddy oversees from his phone, so the queen reports handoffs as a brief overview in its own chat (one or two lines each, more on request) and never sends him to a tab. A bee stays open only for an unclosed loop: `complete: no`, more work about to be sent, or a decision Eddy owes that needs its context (`hive mark-review <label>`, tab gets 👀, decision stated in the queen chat). Every other bee is named in a "Closing after your next message: ..." line and closed with `hive close` on Eddy's next message unless he says keep. Closed bees are restorable, so "might need it later" keeps nothing open.

### `hive close <label>`

Refuses unless a handoff is recorded, or `--force` is given. Refuses if the agent is `working`. Closes the tab with `herdr tab close`, status `closed`, keeps everything else. A closed bee is still restorable.

## Section 4: seeing and restoring

- `hive ls` lists queens; `hive status [<orch>]` lists bees with model, status, tab, age, last handoff line. Default queen is the one owning `HERDR_WORKSPACE_ID`.
- `hive sync` compares the registry with `herdr agent list`: a bee whose tab disappeared without `hive close` becomes `detached` (restorable, flagged).
- `hive restore <orch> [--all | <label>...]`:
  - no workspace for it: `herdr workspace create` with the saved label and cwd; queen tab resumes with `claude --resume <orch id>`.
  - default restores every bee that is not `closed` (live, handed-off, review, detached); `--all` includes closed; labels restore just those.
  - each bee: new tab with its saved label, `herdr agent start ... -- --resume <uuid> --name "<label>" --model <model>`.
  - already open bees are skipped, never duplicated (checked by session id against `herdr agent list`).
- `hive restore --every` restores every queen in the registry, for "I deleted the whole thing".

## Compared with what Herdr already gives

| Need | Herdr CLI and skill today | hive adds |
|---|---|---|
| Open a labelled tab or workspace | `tab create --label`, `workspace create --label` | naming convention, model in label, 👀 review marker |
| Start a Claude in a pane | `agent start --kind claude -- <args>`, waits until ready | pre-assigned `--session-id`, `--name`, `--model`, kickoff prompt |
| Talk to an agent | `agent prompt` types into its terminal, `agent read` scrapes output | SendMessage both ways, structured handoff, no screen scraping |
| Know which conversation a pane holds | `agent list` reports `agent_session` while it is live | durable registry that survives tab, workspace and server loss |
| Reopen closed things | undo-close plugin (our fork f1a06fd) reopens a recently closed tab; Claude resume is off (`relaunch_agents: false`) | restore any bee or whole queen by label, any time later |
| Decide when to close | nothing | handoff plus close table, review prompt to Eddy |
| Pick a model | nothing | Fable vs Opus rule, recorded with a reason |

hive uses Herdr's `agent prompt` exactly once per spawn (the kickoff), because a fresh bee has no SendMessage peer yet. After that, all traffic is SendMessage.

## Named Herdr sessions (separate windows)

Not part of hive v1. `herdr --session <name>` gives a separate persistent server that any new terminal window can attach to (`herdr session attach <name>`). hive could later take `--session` to put a queen in its own window; option A keeps everything in `default` for now.

## Testing

- Unit (pytest via uv): registry read/write and atomic save, slug rules, label formats, argv built for `herdr` and `claude`, close refusals, restore skip logic, using a fake `herdr` on PATH that records calls and returns canned JSON.
- Live smoke (one run, Opus, tiny brief, well under $0.50 of tokens): init in a scratch workspace, spawn one bee that replies with a handoff, close it, restore it, confirm the same session id resumed, clean up the workspace.

## Out of scope for v1

Named Herdr sessions per queen, non-Claude bees (Codex), cross-machine, automatic re-spawn on Fable, a dashboard.
