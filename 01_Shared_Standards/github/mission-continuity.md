# Agent OS Mission Continuity

## Purpose

Distinguish completion of one issue from completion of a broader owner-authorized Agent OS mission across handoffs and chat boundaries.

## Contract

A chat boundary is not by itself a mission boundary. When prior explicit owner intent establishes a continuing bounded mission and project context identifies a recoverable handoff target, the execution interface must reacquire live GitHub state before selecting unrelated work.

Rules:

- issue completion does not end a broader mission such as `keep working on PPUX issues`;
- prefer the most recent explicit handoff target while it remains open and eligible;
- if that target is complete, select a next target only when the broader mission explicitly authorizes continuation;
- preserve repository, branch, issue, and PR identity when recoverable;
- competing plausible missions require explicit ambiguity rather than silent selection;
- explicit cancellation, subject change, or replacement mission overrides continuity;
- blocked work remains part of the mission unless the owner reprioritizes it.

Before substantive continuation, canonical GitHub state must be reread. Conversation/project context locates the mission; GitHub determines current repository truth.

## Handoff Continuation

A handoff, evidence comment, bug record, route discovery, or bounded
investigation checkpoint is intermediate while the current authorized issue
still has an admitted repository implementation path.

After persisting a subordinate handoff:

1. read back the handoff target when persistence/currentness matters;
2. reacquire the parent issue and any branch/PR/currentness evidence required
   by the next transition;
3. consume the already-identified capable route or bounded evidence gate; and
4. continue to implementation, validation, and one canonically read-back Draft
   PR when the gate clears.

Do not require the owner to say `complete the handoff`, `make the PR`, or
repeat `work on` merely because the previous operation persisted a handoff.
If the bounded evidence gate does not clear, report the exact current terminal
blocker and its clearing condition instead of rewriting the same handoff.

A previously reported blocker that current evidence proves cleared is no longer
a terminal disposition. Reacquire the parent state and continue the same
authorized lineage rather than returning the stale blocker again.

This continuation does not bypass a genuine compatibility, authorization,
source-of-truth, excluded-surface, or material-decision gate. It also does not
turn a handoff into implementation authority; it consumes only authority already
present in the current parent mission.

## Boundaries

Continuity grants no new implementation, merge, closure, workflow, protected-setting, credential, production, or external-write authority. This contract creates no persistent autonomous task engine, hidden mission database, second issue tracker, poller, or background worker.

## Regression fixture

`keep working on PPUX issues` followed by a handoff and a new chat must reacquire the latest unfinished PPUX target instead of requiring the owner to restate the mission.

## Version

0.2.0
