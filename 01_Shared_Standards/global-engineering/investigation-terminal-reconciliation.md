# Investigation Terminal Reconciliation

## Purpose
Prevent a useful intermediate finding from being reported as a completed investigation while material branches of the requested terminal question remain unresolved.

## Scope
This is a bounded conformance projection for read-only Agent OS investigations. It reuses ChatGPT Orchestrator finite-mission reconciliation, #1237 capability rerouting, #1200 no-progress handling, canonical source-of-truth rules, and the Agent Interaction Output Standard. It creates no research agent, workflow engine, persistence service, retry framework, or authority model.

## Material branch
A material branch is a bounded question whose answer can change the supported answer to the user's terminal question. Materiality comes from the requested terminal question, canonical task/issue scope, competing hypotheses needed to discriminate the answer, or newly discovered evidence that materially changes those hypotheses. Adjacent curiosity is not automatically material.

## Terminal classifications
Every material branch must end in exactly one of:

- `resolved-supported`
- `resolved-not-supported`
- `blocked-with-owner-and-clearing-condition`
- `not-applicable-after-evidence`

`untouched` and `in-progress` are intermediate states only.

## Completion invariant

```text
investigation complete
=> every material branch has a terminal classification
=> zero material branches are untouched or in-progress
```

A useful finding, capability discovery, repository clue, or partial ownership answer is progress evidence, not completion evidence.

## Boundedness
Do not expand into exhaustive research. Once authoritative evidence discriminates the terminal question, unrelated branches are not material. A narrow yes/no question may legitimately have one material branch when one authoritative source fully resolves it.

## Blocked branches
A blocked material branch must name the unavailable source/capability/owner and the concrete clearing condition. If another authorized read route remains available, consume #1237 reroute semantics before classifying the branch blocked.

## Final reconciliation
Before rendering a terminal investigation report:

1. enumerate the final material branch set;
2. account for each branch exactly once;
3. prove zero implicit `untouched` branches;
4. preserve unresolved blockers explicitly;
5. answer the original terminal question using only the reconciled evidence.

Repeated identical no-progress states remain owned by #1200.

## Authority boundary
Investigation completion grants no repository write, implementation, merge, closure, protected-setting, production, credential, external-write, or governed-field authority. Discovering an implementation defect produces a bounded owner/handoff recommendation only unless separate current authorization permits implementation.

## Regression anchor
The #1237 ownership investigation is canonical regression evidence: discovering a repository-owned Claude hook did not resolve the remaining live-wiring, test/history, status-currentness, and repository-vs-native ownership branches. The investigation was not terminal until those material branches were reconciled.
