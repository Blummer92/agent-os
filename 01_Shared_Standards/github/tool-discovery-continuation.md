# Tool-Discovery Continuation Conformance

## Purpose

Prevent an already-authorized finite Agent OS mission from being silently abandoned after successful tool, schema, connector-action, or capability discovery.

This is a ChatGPT execution-interface conformance contract. It composes the existing same-lineage continuation semantics owned by #1237, finite-mission terminal reconciliation used by the ChatGPT Orchestrator and #1524, and semantic no-progress coordination owned by #1200. It does not create a second executor router, workflow engine, mission store, retry framework, Scheduler, or authorization model.

## Canonical invariant

```text
successful tool/capability discovery
+ unfinished authorized mission
!= terminal state
```

Discovery is intermediate evidence only. Loading or selecting a tool schema, connector action, execution capability, or candidate route does not complete the user's requested mission.

## Required transition

After successful discovery, the execution interface must do exactly one of the following before presenting the mission as terminal:

1. continue to the next currently authorized operation in the same lineage; or
2. return an explicit terminal blocker naming the controlling owner/reason and the clearing condition.

A silent stop is not a terminal classification.

When several schemas/actions must be discovered sequentially, each discovery remains intermediate until an admitted operation executes or a terminal blocker is produced.

## Authorization boundary

Continuation preserves only the authority already applicable to the mission. Discovery never grants repository write, merge, issue closure, review-thread resolution, workflow/protected-setting mutation, credentials/IAM, production, external write, governed-field mutation, or another excluded surface.

If the next operation is not authorized, stop explicitly at that authorization boundary. If the selected surface is incapable, apply #1237 execution-surface reroute/same-lineage semantics. If the same effective blocker/recovery transition repeats, coordinate with #1200 semantic no-progress handling rather than creating a retry loop.

A user interruption or cancellation is an explicit terminal event and may stop continuation.

## Live regression

The 2026-09-01 #1573 reproduction is canonical evidence for this contract:

```text
owner: Complete the handoff
-> authorized mission established
-> GitHub commit-related schema discovered
-> GitHub log-related schema discovered
-> required GitHub capability available
-> no GitHub operation executed
-> no blocker reported
-> execution silently stopped
```

Expected:

```text
same inputs
-> discovery succeeds
-> next admitted GitHub operation executes without another user message
```

If execution cannot continue, the response must instead contain the explicit blocker and clearing condition.

## Ownership

- #1237 remains canonical for execution-interface reroute and same-lineage continuation.
- #1524 remains canonical for terminal investigation/question reconciliation.
- #1200 remains canonical for repeated semantic no-progress recovery loops.
- ChatGPT Orchestrator consumes this conformance rule; GitHub Service Agent remains the sole repository writer.

## External enforcement boundary

Repository policy and fixtures can define and test this invariant, but they cannot force the native ChatGPT product/tool loop to emit another tool call. If repository conformance passes while the live interface still silently stops after discovery, classify the remaining defect as execution-interface integration work under #1237 rather than adding repository runtime machinery.

## Version

0.1.0
