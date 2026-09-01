# Tool-Discovery Continuation Conformance

## Purpose

Prevent an already-authorized finite Agent OS mission from being silently abandoned after successful tool, schema, connector-action, or capability discovery, or falsely handed to the repository owner when bounded canonical diagnostic evidence remains internally discoverable.

This is a ChatGPT execution-interface conformance contract. It composes the existing same-lineage continuation semantics owned by #1237, finite-mission terminal reconciliation used by the ChatGPT Orchestrator and #1524, red-CI diagnostic boundedness owned by completed #1251, and semantic no-progress coordination owned by #1200. It does not create a second executor router, workflow engine, mission store, retry framework, Scheduler, CI framework, or authorization model.

## Canonical invariant

```text
successful tool/capability discovery
+ unfinished authorized mission
!= terminal state
```

Discovery is intermediate evidence only. Loading or selecting a tool schema, connector action, execution capability, or candidate route does not complete the user's requested mission.

For red-CI diagnosis, insufficient output from one diagnostic action is likewise surface-specific evidence, not mission failure:

```text
one insufficient diagnostic read
+ another bounded canonical GitHub evidence route known or discoverable
!= BLOCKED_DIAGNOSTIC_SURFACE
```

The repository owner must not be used as a manual copy/paste transport for CI evidence that an already-authorized connected GitHub surface can still retrieve internally.

## Required transition

After successful discovery, the execution interface must do exactly one of the following before presenting the mission as terminal:

1. continue to the next currently authorized operation in the same lineage; or
2. return an explicit terminal blocker naming the controlling owner/reason and the clearing condition.

A silent stop is not a terminal classification.

When several schemas/actions must be discovered sequentially, each discovery remains intermediate until an admitted operation executes or a terminal blocker is produced.

### Red-CI diagnostic reroute

When an authorized red-CI diagnosis receives insufficient output from one route, consume #1237 and completed #1251 rather than externalizing ordinary evidence transport to the user:

1. preserve the existing PR/branch/checkpoint lineage;
2. reacquire the exact current PR head before consuming head-bound diagnostic evidence;
3. boundedly inspect another already-authorized canonical GitHub evidence route when one is known or discoverable, including exact-head workflow/check-run metadata and annotation/equivalent diagnostic detail when the execution surface exposes it;
4. do not retry the same unsupported route indefinitely; coordinate repeated equivalent no-progress with #1200;
5. emit `BLOCKED_DIAGNOSTIC_SURFACE` only after the bounded alternatives are exhausted or the remaining required diagnostic capability is genuinely unavailable.

A genuine integration blocker must name the unavailable capability and its owning integration surface. It must not assign the repository owner a copy/paste task merely because the active connector cannot expose diagnostic detail that exists in canonical GitHub state.

## Authorization boundary

Continuation preserves only the authority already applicable to the mission. Discovery never grants repository write, merge, issue closure, review-thread resolution, workflow/protected-setting mutation, credentials/IAM, production, external write, governed-field mutation, or another excluded surface.

If the next operation is not authorized, stop explicitly at that authorization boundary. If the selected surface is incapable, apply #1237 execution-surface reroute/same-lineage semantics. If the same effective blocker/recovery transition repeats, coordinate with #1200 semantic no-progress handling rather than creating a retry loop.

A user interruption or cancellation is an explicit terminal event and may stop continuation.

## Live regressions

The 2026-09-01 #1573 reproduction is canonical evidence for discovery continuation:

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

The 2026-09-01 PR #1582 reproduction is canonical evidence for diagnostic reroute and false-owner-handoff prevention:

```text
exact PR/head/run/job known
-> workflow-job log read returns insufficient step output
-> exact-head check-run collection remains readable
-> failed check metadata proves annotations_count > 0
-> diagnosis is not yet terminal
```

Expected:

```text
same inputs
-> inspect bounded alternate canonical GitHub evidence automatically
-> retrieve annotation/equivalent actionable detail when exposed
OR
-> after bounded alternatives are exhausted, report the missing connector capability as an integration blocker
-> never ask the repository owner to manually transport evidence still internally retrievable
```

If execution cannot continue, the response must contain the explicit blocker and clearing condition.

## Ownership

- #1237 remains canonical for execution-interface reroute and same-lineage continuation.
- completed #1251 remains canonical for red-CI checkpoint, bounded diagnostic switching, and exact-head freshness.
- #1524 remains canonical for terminal investigation/question reconciliation.
- #1200 remains canonical for repeated semantic no-progress recovery loops.
- #1608 remains canonical for silent post-discovery mission abandonment.
- #1614 adds only false-owner-handoff conformance when alternate diagnostic evidence remains internally discoverable.
- ChatGPT Orchestrator consumes this conformance rule; GitHub Service Agent remains the sole repository writer.

## External enforcement boundary

Repository policy and fixtures can define and test these invariants, but they cannot force the native ChatGPT product/tool loop to emit another tool call or add a connector action that the active GitHub integration does not expose. If repository conformance passes while the live interface still stops after discovery, falsely hands diagnostic transport to the owner, or cannot read known failed-check annotations/equivalent detail, classify the remaining defect as execution-interface/connector integration work under #1237/#1614 rather than adding repository runtime machinery.

## Version

0.2.0
