---
name: hive-bee
description: Use when your first prompt says you are a hive bee (or hive worker), or names a queen or orchestrator chat you report to. Covers reading your brief, working inside its scope, reporting back with a HIVE HANDOFF over SendMessage, and staying open afterwards.
---

# hive bee

A queen chat spawned you in your own Herdr tab to do one slice of work. Your kickoff prompt gave you your label and the path of your brief. The queen's SendMessage name is `queen: <its label>`; `hive queen` prints it, and is the only source to trust if the name in your kickoff does not resolve.

## Work

1. Read the brief in full. It is your whole scope.
2. Do the work. Stay inside the brief's files and objective.
3. Stop and report instead of improvising when: the code or data does not match the brief; a command fails after one sensible retry; the task needs files outside scope; the work turns out to be mostly judgement you were not asked to make (say so, and suggest the queen re-spawn this on fable).
4. Questions for the queen go by SendMessage (name from `hive queen`), one message, specific. Keep working on anything the answer does not block.

## Report

When you are finished, or stopped, write this handoff to a scratch file:

```
HIVE HANDOFF <your label>
complete: yes|no (what remains, if no)
review_worthy: yes|no (the decision or thing only Eddy can judge)
summary: <3 to 6 lines: what you did and what you found>
artifacts: <paths, urls, commits; or none>
open: <loose ends, risks, things you could not verify; or none>
```

review_worthy is yes only when Eddy himself has to act: a decision only he can make, or output he must see with his own eyes (give the link or path in artifacts). Judgement calls you made and surprising findings go in the summary, not here. Eddy reads the queen's overview, not your tab, so write the summary so it stands on its own.

Evidence over adjectives: file paths with line numbers, the commands you ran and their result, exact failures.

Then deliver it, in this order:

1. `hive handoff "<your label>" --file <scratch file>`. This records it in the registry, which is what the queen trusts. Once this succeeds the handoff is delivered, whatever happens to the message.
2. `hive queen` to get the queen's current name.
3. One SendMessage to that name with the same handoff text.

If step 2 says the queen is not running, or step 3 is held, expires or fails: stop there. The handoff is on record and the queen reads it from `hive status` when it is back. Say so in one line in your own tab. Do not ask Eddy which session to use, do not pick a similarly named session, and do not resend on a loop.

## After the handoff

Stay open and idle. Never close your own tab or exit; the queen (or Eddy) decides when you close, and you may get follow up work by SendMessage. If you do, finish it and send a fresh HIVE HANDOFF.
