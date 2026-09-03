# Pending CI Continuation Regression

## Live #1619 reproduction

An already-authorized PR repair creates a new exact head `HEAD_B`.

```text
HEAD_B created
-> first exact-head workflow lookup returns zero runs
-> second bounded lookup returns queued validation for HEAD_B
-> later bounded lookup returns a terminal result for HEAD_B
```

Expected behavior:

- zero runs on the first lookup is `ci-not-yet-visible`, not mission completion;
- queued or in-progress exact-head validation is `checks-pending`, not mission completion;
- the same authorized lineage continues without another user prompt;
- stale-head validation never satisfies the current generation;
- terminal green records exact-head evidence and allows normal completion;
- terminal red routes into the existing red-CI continuation owner rather than a generic status handoff;
- if the bounded observation policy expires without a run materializing, return one explicit blocker containing the exact head, bounded-attempt evidence, and the clearing condition.

## Authority boundary

Pending-CI continuation creates no merge, issue-closure, workflow, protected-setting, credential/IAM, production, external-write, or retry authority. It does not create a background worker or polling daemon.