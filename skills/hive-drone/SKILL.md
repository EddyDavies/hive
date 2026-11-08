---
name: hive-drone
description: Use when Eddy asks to spin off, drone, fork, branch off or "send a drone on" a slice of the current chat so it carries on in its own chat while this one continues, or when your first prompt says you are a hive drone. Covers writing the task, `hive drone launch`, what the drone does on its own, its DRONE REPORT back to the parent, and landing it. Needs no queen. Requires HERDR_ENV=1.
---

# hive drone

A drone is a bee that went on a journey. The chat Eddy is in (the parent) forks itself into a new Herdr tab, `✈ <label>`, beside it. The fork starts with the whole conversation already loaded, so nothing is copied by hand. A short task file says which slice is now the drone's job. The parent goes straight back to the main thread. The drone works alone, records a DRONE REPORT, and pings the parent when it is done.

No queen and no `hive init` are needed: any Claude chat in a Herdr pane can launch drones. Use hive-queen instead when Eddy wants this chat to orchestrate several bees from a written plan.

## Parent: launching a drone

1. Check `echo $HERDR_ENV` prints 1. If not, say so in one line and stop; never fall back to a subagent.
2. Write the task file in your scratchpad. The drone already has the conversation, so the task is about scope, not background:
   - the slice it owns, pointing at the part of the conversation it came from ("point 4 above: how failures land with users");
   - the questions to answer, in Eddy's words where he gave them;
   - what done looks like and where output goes (repo `reports/` HTML per the global rules, a branch, a ticket);
   - what the parent carries on with, so the drone leaves that alone;
   - constraints that apply: spend caps, routing rules (PostHog, Cloudflare, Granola subagents), read-only or not, prod data handling.
3. Launch:

```
hive drone launch "<label>" --task <file> [--model opus|fable]
```

   Labels are 2 to 4 plain words. Model: opus by default; fable when the slice's output is mostly judgement (a product or safety call, a design decision). `--fresh` starts from the task file alone instead of a fork; use it only when the conversation is irrelevant or too large to be useful. A fork always starts in the folder this chat started in, since Claude resumes a chat only from there; name any other folder in the task.
4. Tell Eddy in one line that the drone is off and what it will come back with. Then return to the main thread straight away. Do not wait for it.

When a `DRONE REPORT` arrives by SendMessage, give Eddy a short summary at a natural break in the main thread (not mid-answer): the outcome first, links or paths to anything he must look at, and any decision it needs from him. `hive drone ls` lists open drones with their report summaries; `hive drone show <label>` prints one in full. The registry copy is the source of truth; if `ls` shows a report you got no message for, act on it the same way.

Land a drone once its report is in and nothing is open: `hive drone land <label>` closes its tab (it refuses without a report or while the drone works; `--force` only if Eddy asked). Keep it open when Eddy wants to go into it and question it directly, or when its report says `complete: no` and it is carrying on. Ask which drones to land in the `AskUserQuestion` picker with any other open questions. `hive drone restore <label>` reopens a landed drone with its conversation intact.

## Drone: working alone

Your kickoff says you are a drone and gives your task file. Read it in full; it is your whole scope. Everything earlier in the conversation is background: do not finish the parent's other work, and do not answer questions that were put to the parent.

- Carry the slice through to a result. Make reasonable calls yourself and record them in the report; Eddy is not watching this tab.
- You share a working tree with the parent and maybe other chats. Never edit files the parent is working on. For code changes, use a git worktree per the global rules.
- All the global rules still apply: spend caps, subagent routing, no dashes, HTML for deliverables saved beside the work.
- Stop and report instead of improvising when the task needs out of scope files, a command fails after one sensible retry, or the work turns into a decision only Eddy can make.

## Drone: reporting

Write this to a scratch file:

```
DRONE REPORT <label>
complete: yes|no (what remains, if no)
needs_eddy: yes|no (the decision or thing only Eddy can judge)
summary: <3 to 6 lines: what you did and what you found, standing on its own>
artifacts: <paths, urls, commits; or none>
open: <loose ends, risks, things you could not verify; or none>
```

Evidence over adjectives: file paths with line numbers, the commands you ran and their results, exact failures.

Then:

1. `hive drone report --file <scratch file>`. This records it and prints the parent's current SendMessage name. Once it succeeds, the report is delivered.
2. One SendMessage to that name with the same text.

If the parent is not running, or the message is held or fails, stop there; the report is on record for `hive drone ls`. Do not pick a similarly named session and do not resend in a loop. `hive drone parent` prints the name again if needed.

After the report, stay open and idle. Never close your own tab; the parent or Eddy lands you, and you may get follow up work by SendMessage. If you do, finish it and record a fresh report.
