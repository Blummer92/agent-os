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

## Boundaries

Continuity grants no new implementation, merge, closure, workflow, protected-setting, credential, production, or external-write authority. This contract creates no persistent autonomous task engine, hidden mission database, second issue tracker, poller, or background worker.

## Regression fixture

`keep working on PPUX issues` followed by a handoff and a new chat must reacquire the latest unfinished PPUX target instead of requiring the owner to restate the mission.

## Version

0.1.0
