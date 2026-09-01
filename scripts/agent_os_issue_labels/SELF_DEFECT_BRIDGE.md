# Self-Defect Triage Bridge

## Purpose

Issue #1621 adds only the thin projection between self-observed Agent OS contract
violations and the existing GitHub issue/continuation machinery.

It does not create another recovery fingerprint, router, retry framework, mission
store, GitHub client, authorization model, or background bug scanner.

## Existing owners

- #1200 owns semantic no-progress/recovery fingerprints and repeated recovery.
- #1237 owns execution-surface reroute and same-lineage continuation.
- #1524 owns terminal investigation reconciliation.
- #1608 owns silent mission abandonment after successful tool discovery.
- #1611 owns bounded GitHub Actions failure-evidence retrieval.
- GitHub Service Agent remains the sole GitHub mutation owner.

## Pure projection

`scripts.agent_os_issue_labels.self_defect` consumes already-bounded evidence:

1. a self-observed behavior classification;
2. the canonical governing contract and stable failure signature;
3. bounded issue-search candidates supplied by the integration surface; and
4. prior mutation identities from the active finite lineage when available.

It returns one non-mutating decision:

- no meta-bug;
- route through the existing capability owner;
- explicit authority/governance stop;
- manual review;
- harden one existing canonical issue; or
- create one focused issue through GitHub Service Agent.

The module never searches GitHub and never writes GitHub itself. The execution
interface performs the bounded search, and the existing GitHub Service Agent
write path performs any authorized mutation.

## Deduplication identity

#1200 remains canonical for recovery-state identity. When a self-defect is not a
recovery transition, this bridge uses a deliberately narrower adjacent identity:

```text
repository + governing contract + stable failure signature
```

Observed prose, PR number, timestamps, and incidental wording are excluded so the
same root cause across several reproductions converges. A different stable failure
signature remains distinct even when wording is similar.

Multiple matching canonical issue candidates fail to manual review rather than
choosing by title or search order.

## Idempotency and recursion

The bridge derives a mutation identity from the semantic defect identity plus the
selected mutation target (`issue:<number>` or `issue:create`). A mutation identity
already recorded in the active lineage makes the next equivalent mutation a
no-op while allowing the original mission to continue when it remains actionable.

Failure of the external GitHub mutation is not fed recursively back into this
planner as another defect in the same mutation lineage. The writer/integration
surface must return its explicit blocker instead.

## Continuation

Issue hardening or creation is intermediate evidence, not terminal mission
completion. When the original mission remains authorized, in scope, and
otherwise actionable, the integration surface returns control to #1237/#1524 and
the ChatGPT Orchestrator continuation path without requiring another owner prompt.

The projection never grants merge, issue closure, Ready-for-Review, workflow or
protected-setting mutation, credentials/IAM, production, external writes, or any
other excluded authority.

## External enforcement boundary

Repository code can make the classification/deduplication/handoff decision
machine-testable, but it cannot force the native ChatGPT product loop to search,
mutate GitHub, or emit another tool call. Live enforcement remains an execution-
interface integration responsibility. If repository tests pass while live
behavior still stops after recording a non-blocking side defect, treat that as
integration evidence rather than adding repository runtime machinery.
