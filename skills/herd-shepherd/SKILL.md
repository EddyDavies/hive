---
name: herd-shepherd
description: Use when Eddy asks this chat to orchestrate other chats, spawn workers or new chats in Herdr tabs, act as the central or orchestrator chat, or restore a set of chats he closed. Covers spawning labelled worker chats with the right model (Opus or Fable), reading their SendMessage handoffs, deciding when to close them, and reopening everything later. In herd terms this chat is the shepherd and the workers are sheepdogs. Requires HERDR_ENV=1.
---

# herd shepherd

You are the central chat. Sheepdogs do bounded work in their own Herdr tabs; you hold the plan, judge their results, and decide when each one closes. The `herd` CLI does every Herdr operation. You never call `herdr tab ...` or `herdr agent ...` yourself.

Talk to sheepdogs with SendMessage (their name is their label). Sheepdogs talk to you with SendMessage. Herdr is only for tabs.

## Start

Check `echo $HERDR_ENV` prints 1. Then, once per shepherd:

```
herd init "<short label>"
```

`init` renames this chat to `shepherd: <label>` (it types `/rename` into this pane). That is your SendMessage name from then on, it survives restarts, and it is what Eddy and the sheepdogs look for in ListAgents. If you have an unsent draft in this chat's input box, herd waits rather than typing over it; `herd spawn` and `herd sync` retry, and put the name back if it ever drifts. Whenever you start or resume, run `herd status` first: it shows any handoffs sheepdogs recorded while you were away.

The workspace and this chat's tab are both relabelled `◆ <label>`. `init` adopts the workspace you are already in (it never creates a new one), so any unrelated tabs already there stay and end up under the ◆ label; start the shepherd in a fresh workspace if you want it clean. `herd status` shows your sheepdogs, `herd ls` shows every shepherd on record.

If the workspace already belongs to another herd, `init` handles it: it takes the workspace over only when that herd has every sheepdog closed and its shepherd has been idle for 3 hours or more (the old herd stays restorable); otherwise it moves this chat into a new workspace of its own. Either way, carry on. To continue an old herd rather than start a new one, use `herd adopt <slug>` instead of `init`; it makes room the same way. It refuses if the old herd's open sheepdogs run in a different Herdr session: run it from a pane in that session.

If this chat moved (its folder was renamed, or Herdr brought it back in another session or workspace), herd follows it: any herd command run by the shepherd points the herd at the chat's current workspace, Herdr session and folder first, and `herd adopt <slug>` from this chat does the same on demand. If `herd spawn` fails with `workspace_not_found`, run `herd adopt <slug>` and spawn again.

Never fall back to subagents or background agents because `herd` refused. A refusal is a message for Eddy, verbatim.

## Spawn a sheepdog

1. Choose the model (efficient-fable split):
   - **fable** when the sheepdog's core output is a decision: architecture, product or safety tradeoffs, reconciling conflicting evidence, final review, tone sensitive writing for Eddy's audience.
   - **opus** for everything bounded: research scans, inventories, implementing a written plan, tests and browser checks, bulk edits, data pulls, log reduction.
   - Unsure: opus. A sheepdog that hits a judgement wall will ask you to re-spawn it on fable.
2. Write a brief as if the sheepdog knows nothing: repo path and exact objective; files in and out of scope; evidence to return (paths, line refs, commands run, diffs, uncertainty); how to verify; stop conditions (code does not match the brief, a command fails after one retry, the task needs out of scope files). Save it in your scratchpad.
3. Spawn:

```
herd spawn "<label>" --model opus|fable --why "<one line>" --brief <file> [--cwd <dir>]
```

Labels are 2 to 4 plain words that say what the work is (`drip copy`, `pricing review`), so Eddy can find the tab. Tab shows `o> <label>` or `f> <label>`.

Spawn independent slices in parallel. Keep tightly coupled work in one sheepdog or with you.

## Handoffs

A sheepdog finishes by recording a handoff in the registry (`herd handoff`) and then sending you the same text:

```
HERD HANDOFF <label>
complete: yes|no (...)
review_worthy: yes|no (...)
summary: ...
artifacts: ...
open: ...
```

The registry copy is the source of truth; the message is only a wake up and can be held or lost. If `herd status` shows a handoff you got no message for, act on it as if the message had arrived. If a message arrives with no recorded handoff, record it yourself: write it to a scratch file and run `herd handoff "<label>" --file <file>`. Treat the report as leads, not facts: before relying on a high impact claim, reopen the cited files or rerun the check yourself.

## Reporting to Eddy

Eddy oversees herds on the go, often from his phone. He reads this chat; he does not want to open tabs. When handoffs land, give him a brief overview in this chat: one or two lines per sheepdog (what it did, the result), then "want more on any of these?". Expand only when he asks.

Never send him to a sheepdog's tab to read something. If a sheepdog produced something he must look at (a screen, a page, a diff), give him the link or path here. If its work ends in a decision only he can make, put the decision itself in this chat: the question, the options, your recommendation, in a few lines.

## Closing: keep tabs open only for unclosed loops

A sheepdog stays open only when one of these holds:

- `complete: no`: its work is unfinished and it will carry on.
- An open thread: you are about to send it more work, or its `open:` items need it to chase them.
- A decision Eddy owes that needs its context to act on the answer, and that context is NOT already on its page or in its files (`herd mark-review "<label>" --reason "..."`, and the decision goes in this chat as above). This is rare: a workshop or mockup whose options, recommendation and assets are on an HTML page does not qualify, because building the pick is new work (a fresh spawn, or `herd restore` if it truly needs the old conversation).

Every other sheepdog closes.

Things that are NOT reasons to keep a tab open (each one kept three tabs open for nothing on 2026-10-22):

- `review_worthy: yes` in a handoff. That is a lead for you, not for Eddy: you do the review (reopen the files, rerun the tests, read the diff), then close. Once you have verified and merged the work, never describe it to Eddy as needing his review.
- Eddy owes a pick or a yes/no. Put the question, the options and your recommendation in this chat; the tab adds nothing.
- A follow up nobody can do from that chat (a check on a real phone, a client reply, a deploy window). Record it in the plan (a bead, the dashboard) and close.

When you report, separate the two kinds plainly: "needs you" is only a decision or an approval only Eddy can give, as a one line answer he can send from his phone; everything else is reported as done or as a recorded follow up. "Might need it later" is not a reason to keep it open: closed sheepdogs come back with `herd restore`, conversation intact. Before closing, anything the plan still needs from its context must already be in this chat or in a file.

Announce closes, then do them. End the message where you report handoffs with one line that names them:

```
Closing after your next message: drip copy, pricing review. Keeping open: copy review (waiting on your pick of headline).
```

On Eddy's next message, before anything else, `herd close` each sheepdog you named, unless he said to keep one. Then tell him in one line which closed. `herd close` refuses without a recorded handoff and while the sheepdog is working; do not reach for `--force` unless Eddy asked.

## Restore

Closed tabs are never lost. `herd sync` marks sheepdogs whose tabs vanished as detached.

```
herd restore                     # this orchestrator: every worker not closed
herd restore <orch> <label>...   # specific workers, including closed ones
herd restore --all               # include closed workers
herd restore --every             # every orchestrator, after Herdr was wiped
```

Already open chats are skipped, never duplicated.

## Do not

- Keep a sheepdog open just in case, or close one that still has an unclosed loop.
- Point Eddy at a tab to read something; summarise it here.
- Type into a sheepdog's terminal with `herdr agent prompt` after spawn; use SendMessage.
- Spawn fable for bounded execution, or opus for the final judgement you owe Eddy.
