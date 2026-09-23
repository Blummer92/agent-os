# Shadow Issue Selection — Phase 1 (#2832)

## Purpose

`shadow_issue_selection.py` is the Phase-1 read-only composition seam for selecting one **next executable issue under the existing canonical selector semantics**.

It does not define a priority policy and does not claim that the selected issue is the “best,” “most important,” or “highest-value” issue.

## Composition

```text
paginated GitHub issue reader
-> scan_connected_issues(state=open)
-> caller-supplied canonical mission/request narrowing
-> bounded candidate cohort
-> caller-supplied CandidateIssueEvidence
-> existing select_executable_lanes(...)
-> reacquire selected issue
-> issue_source_revision currentness check
-> read-only ShadowIssueSelectionResult
```

The scanner remains the population/completeness owner. Pull requests are excluded by the existing `GitHubIssuePageSource` adapter. The composition never uses connected issue search as evidence that the whole backlog was exhausted.

## Candidate bound

The existing `ExecutableLaneSelection` contract accepts at most 64 candidates.

This seam does not:
- silently truncate a larger cohort;
- compare chunk-local winners as if they were globally equivalent;
- introduce AI ranking, age-based ranking, popularity, or another priority system.

If canonical mission/request constraints still leave more than 64 open candidates, the result is `shadow-selection.candidate-population-too-broad` with no selected issue.

## Canonical evidence only

Operational state is supplied only through the existing `CandidateIssueEvidence` contract.

The seam does not derive lifecycle stage, primary-PR claims, dependency state, validation state, authorization, or freshness from:
- scanner rows;
- labels;
- issue prose;
- timestamps;
- issue number.

Missing candidate evidence returns `shadow-selection.candidate-evidence-incomplete`.

## Revision identity

Two revision identities remain deliberately separate:

- `IssueOperationalState.source_revision` is the lowercase 40-character repository commit SHA.
- the scanned/current issue-content revision is `github-issue-v1:<sha256>` from `issue_source_revision(...)`.

For every bounded candidate:
1. the paginated source must expose the canonical issue revision produced by the existing provider;
2. that scanned issue revision must already be preserved in the candidate's `IssueOperationalState.evidence_ids`;
3. all supplied candidate states must agree on one repository source revision.

These joins detect stale or mismatched evidence without creating another freshness authority.

## Selected-issue reacquisition

After `select_executable_lanes(...)` selects one lane, the seam performs one single-issue read through the existing `LiveIssueReader` protocol and recomputes the current issue revision.

If the selected issue:
- cannot be read;
- is malformed;
- or no longer matches the scanned issue revision,

the result is `replan-required`, never execution.

## Output semantics

A successful result means:

> next executable under current canonical selector semantics

It does not mean:
- highest priority;
- highest value;
- most urgent;
- best issue.

Existing selector tie-breaking remains unchanged and is reported as selector behavior only.

## Authority and side effects

`ShadowIssueSelectionResult.execution_authorized` and `side_effects_performed` are fixed `false`.

The module:
- exposes read protocols only;
- invokes no CKR6 or execution path;
- performs no GitHub mutation;
- creates no branch, PR, label, comment, merge, or closure;
- does not dispatch Scheduler or workflow execution;
- does not access credentials, production, or external systems.

## Fail-closed reasons

Phase 1 returns explicit no-selection or replan outcomes for:
- incomplete population retrieval;
- empty candidate population;
- candidate not present in the complete scanned population;
- candidate cohort above 64;
- missing canonical candidate evidence;
- candidate repository mismatch;
- missing canonical issue revision;
- candidate issue-revision mismatch;
- conflicting repository revisions across candidate evidence;
- no executable lane from the existing selector;
- selected-issue reacquisition failure;
- selected-issue content drift after the scan.

## Validation

Focused validation:

```bash
PYTHONPATH=08_Tooling/agent-os-execution-service/src python -m pytest -q \
  08_Tooling/agent-os-execution-service/tests/test_shadow_issue_selection.py
```

The execution-service focused suite remains the canonical branch validation surface for this package.

Ready-for-Review still requires the repository's current exact-head aggregate admission.

## Phase boundary

Phase 1 is complete only when:
- the read-only composition seam is green;
- the bounded real-backlog shadow canary is proven;
- exact-head validation required by repository policy is satisfied.

Host/CKR6 consumption remains a separate downstream integration concern under #2682.

Selection-helper retirement remains downstream under #1729 and requires separate replacement/retirement evidence.