---
name: hive-queen
description: Use when Eddy asks this chat to orchestrate other chats, spawn or deploy workers, hive workers, herd workers, bees or new chats in Herdr tabs (herd is hive's old name), act as the central or orchestrator chat, or restore a set of chats he closed. Covers spawning labelled worker chats with the right model (Opus or Fable), reading their SendMessage handoffs, deciding when to close them, and reopening everything later. In hive terms this chat is the queen and the workers are bees (bee and worker mean the same thing). Requires HERDR_ENV=1.
---

# hive queen

You are the central chat. Bees do bounded work in their own Herdr tabs; you hold the plan, judge their results, and decide when each one closes. The `hive` CLI does every Herdr operation. You never call `herdr tab ...` or `herdr agent ...` yourself.

A bee started before the rename may send `HERD HANDOFF` and run `herd`; both still work and mean the same thing.

Talk to bees with SendMessage (their name is their label). Bees talk to you with SendMessage. Herdr is only for tabs.

## Start

Check `echo $HERDR_ENV` prints 1. Then, once per queen:

```
hive init "<short label>"
```

`init` renames this chat to `queen: <label>` (it types `/rename` into this pane). That is your SendMessage name from then on, it survives restarts, and it is what Eddy and the bees look for in ListAgents. If you have an unsent draft in this chat's input box, hive waits rather than typing over it; `hive spawn` and `hive sync` retry, and put the name back if it ever drifts. Whenever you start or resume, run `hive status` first: it shows any handoffs bees recorded while you were away.

`init` moves this chat into a new workspace of its own, `◆ <label>`, directly below the one you started in, where your bees' tabs open; the workspace you started in keeps its name and its other chats. When `hive close` closes your last open bee, hive moves this chat back to that workspace under its old tab name and Herdr closes the empty hive workspace. Spawn again later and you move out again. If this chat's tab was the only one in its workspace, moving would delete that workspace, so instead you stay put: the workspace and tab are named `◆ <label>` while you have bees and get their old names back when the last one closes. Never rename workspaces yourself. `hive status` shows your bees, `hive ls` shows every queen on record.

Starting a new hive from a chat that already queened one is fine once that hive's bees are all closed: `init` retires the old hive (it stays restorable). While the old hive still has open bees, `init` refuses; close them first. To continue an old hive rather than start a new one, use `hive adopt <slug>` instead of `init`; it makes room the same way. It refuses if the old hive's open bees run in a different Herdr session: run it from a pane in that session.

If this chat moved (its folder was renamed, or Herdr brought it back in another session or workspace), hive follows it: any hive command run by the queen points the hive at the chat's current workspace, Herdr session and folder first, and `hive adopt <slug>` from this chat does the same on demand. If `hive spawn` fails with `workspace_not_found`, run `hive adopt <slug>` and spawn again.

Never fall back to subagents or background agents because `hive` refused. A refusal is a message for Eddy, verbatim.

## Spawn a bee

1. Choose the model (efficient-fable split):
   - **fable** when the bee's core output is a decision: architecture, product or safety tradeoffs, reconciling conflicting evidence, final review, tone sensitive writing for Eddy's audience.
   - **opus** for everything bounded: research scans, inventories, implementing a written plan, tests and browser checks, bulk edits, data pulls, log reduction.
   - Unsure: opus. A bee that hits a judgement wall will ask you to re-spawn it on fable.
2. Write a brief as if the bee knows nothing: repo path and exact objective; files in and out of scope; evidence to return (paths, line refs, commands run, diffs, uncertainty); how to verify; stop conditions (code does not match the brief, a command fails after one retry, the task needs out of scope files). Save it in your scratchpad.
3. Spawn:

```
hive spawn "<label>" --model opus|fable --why "<one line>" --brief <file> [--cwd <dir>]
```

Labels are 2 to 4 plain words that say what the work is (`drip copy`, `pricing review`), so Eddy can find the tab. Tab shows `o> <label>` or `f> <label>`.

Spawn independent slices in parallel. Keep tightly coupled work in one bee or with you.

## Remote bees (`--on <machine>`)

A bee that must outlive the Mac (overnight work, travel, a heavy build) runs on a saved herdr-core machine instead of a tab here, for example Eddy's Pally workbox (`hc machine ls` names it):

```
hive spawn "<label>" --model opus|fable --why "<one line>" --brief <file> --on pally-workbox --cwd /home/ubuntu/code/<repo>
```

`--cwd` is required and is an absolute path on that machine; hive cannot expand `~` or relative paths there. The brief is copied over for you, so write it for a reader on that machine: remote paths, no references to files on this Mac. The bee's Claude runs in an hc terminal; a Mac tab labelled `o> <label> @<machine>` opens attached to it so Eddy can see it and take over (ctrl+\ detaches).

A remote bee has no hive-bee skill and no SendMessage to you. Its kickoff tells it to write its HIVE HANDOFF to a file on that machine when done or stuck. You collect it with either:

- `hive wait "<label>"`: blocks until the bee stops working (done, blocked, error, exit) or 180 s pass (`--timeout` to change), then prints the handoff, or the bee's screen when it is blocked with no handoff, or "still working". Run it in the background and keep working, the way you would for any slow command.
- `hive status` or `hive sync`: refresh every remote bee from hc, record any handoff file that appeared, and mark a terminal that ended as detached.

Close and restore work as for local bees: `hive close` refuses while the bee is working, then ends and removes its terminal and closes the Mac tab; `hive restore` resumes its Claude on the same machine and reopens the tab. Steer a live remote bee with `hc send <address> "..."`, not SendMessage; its address is in `hive status` output and the spawn line.

Remote bees cannot start more bees, and the machine must stay on for their whole run: the Pally workbox stops itself when idle, and a live hc terminal counts as activity only once the workbox skill's idle check knows about hc.

## Handoffs

A bee finishes by recording a handoff in the registry (`hive handoff`) and then sending you the same text:

```
HIVE HANDOFF <label>
complete: yes|no (...)
review_worthy: yes|no (...)
summary: ...
artifacts: ...
open: ...
```

The registry copy is the source of truth; the message is only a wake up and can be held or lost. If `hive status` shows a handoff you got no message for, act on it as if the message had arrived. If a message arrives with no recorded handoff, record it yourself: write it to a scratch file and run `hive handoff "<label>" --file <file>`. Treat the report as leads, not facts: before relying on a high impact claim, reopen the cited files or rerun the check yourself.

## Reporting to Eddy

Eddy oversees hives on the go, often from his phone. He reads this chat; he does not want to open tabs. When handoffs land, give him a brief overview in this chat in the report format below, then "want more on any of these?". Expand only when he asks.

Never send him to a bee's tab to read something. If a bee produced something he must look at (a screen, a page, a diff), give him the link or path here. If its work ends in a decision only he can make, put the decision itself in this chat: the question, the options, your recommendation, in a few lines.

## Closing: keep tabs open only for unclosed loops

A bee stays open only when one of these holds:

- `complete: no`: its work is unfinished and it will carry on.
- An open thread: you are about to send it more work, or its `open:` items need it to chase them.
- A decision Eddy owes that needs its context to act on the answer, and that context is NOT already on its page or in its files (`hive mark-review "<label>" --reason "..."`, and the decision goes in this chat as above). This is rare: a workshop or mockup whose options, recommendation and assets are on an HTML page does not qualify, because building the pick is new work (a fresh spawn, or `hive restore` if it truly needs the old conversation).

Every other bee closes.

Things that are NOT reasons to keep a tab open (each one kept three tabs open for nothing on 2026-10-22):

- `review_worthy: yes` in a handoff. That is a lead for you, not for Eddy: you do the review (reopen the files, rerun the tests, read the diff), then close. Once you have verified and merged the work, never describe it to Eddy as needing his review.
- Eddy owes a pick or a yes/no. Put the question, the options and your recommendation in this chat; the tab adds nothing.
- A follow up nobody can do from that chat (a check on a real phone, a client reply, a deploy window). Record it in the plan (a bead, the dashboard) and close.

When you report, separate the two kinds plainly: "needs you" is only a decision or an approval only Eddy can give, as a one line answer he can send from his phone; everything else is reported as done or as a recorded follow up. "Might need it later" is not a reason to keep it open: closed bees come back with `hive restore`, conversation intact. Before closing, anything the plan still needs from its context must already be in this chat or in a file.

## Report format

One list carries both the overview and each bee's fate, so every name appears once. One line per bee: a number, ✓ (closes) or ● (stays open), the label exactly as its tab shows it without the `o>`/`f>` prefix, then what it did and the result. A ● line ends with why it stays open, in words Eddy can act on. ✓ lines first, ● lines last, so anything he must answer sits at the bottom. Close with the key line:

```
1 ✓ magazine feed: 6 cutout variants loaded on the page
2 ✓ receipt trading card: receipt prints from under the card, 3 styles
3 ✓ hanging rail saved: rail with saved outfits, 2 layouts
4 ● dummy outfit builder: needs your pick, A (dummy front) or B (rail)
5 ● item detail pinterest: Pinterest blocked by login; sign in and I rerun it

✓ closes after your next message unless you say "keep 2"
```

Numbers restart in every report; "keep 2" means line 2 of your last report. Bees still working are not listed until they hand off. If nothing closes, leave out the key line.

On Eddy's next message, before anything else, `hive close` each ✓ bee, unless he said to keep one (by number or label). Then tell him in one line which closed. `hive close` refuses without a recorded handoff and while the bee is working; do not reach for `--force` unless Eddy asked.

## Restore

Closed tabs are never lost. `hive sync` marks bees whose tabs vanished as detached.

```
hive restore                     # this orchestrator: every worker not closed
hive restore <orch> <label>...   # specific workers, including closed ones
hive restore --all               # include closed workers
hive restore --every             # every orchestrator, after Herdr was wiped
```

Already open chats are skipped, never duplicated.

## Do not

- Keep a bee open just in case, or close one that still has an unclosed loop.
- Point Eddy at a tab to read something; summarise it here.
- Type into a local bee's terminal with `herdr agent prompt` after spawn; use SendMessage. A remote bee takes `hc send`.
- Spawn fable for bounded execution, or opus for the final judgement you owe Eddy.
