# Agent OS PR Review Remediation CLI

## Purpose

This package exposes pure-local, read-only contracts for PR review remediation and CI evidence recovery. It evaluates supplied evidence only: it does not fetch GitHub, edit source, execute remediation or validation, resolve threads, merge, or perform external writes.

## PR Review Remediation CLI

```bash
python -m scripts.agent_os_pr_remediation.cli --input tests/fixtures/agent_os_pr_remediation/e2e.json --format json
```

The input composes PR snapshot/thread evidence, exact-head preflight, remediation candidates, changed-file/fix evidence, validation bindings, and final head capture. JSON output contains deterministic preflight, remediation, and resolution plans. Every authority and side-effect field remains false.

## CI Evidence Recovery Contract

`scripts/agent_os_pr_remediation/ci_evidence_recovery.py` plans recovery of the first actionable GitHub Actions failure without assuming `gh` or Cloud Shell. It performs no network, CLI, retry, repository, or external-system operation.

Each plan binds repository, PR number, full 40-character head SHA, workflow run ID, run attempt, and optional failing job ID. Every observation carries the same identity and mismatches fail closed.

Recovery paths are:
- structured evidence;
- direct Actions-log access;
- `gh` run logs;
- failing-job logs;
- an approved alternate environment;
- user handoff only after governed paths are exhausted.

Machine-readable reasons distinguish CLI/auth/permission/credential/host failures, rate limits, in-progress runs, stale head or attempt, run/job log failures, incomplete log association, transient network failure, expired environments, disk exhaustion, and exhausted evidence recovery.

Routine diagnostic excerpts are bounded and deterministic:
- minimum target: 50 lines;
- default/initial target: 50 lines;
- routine maximum: 150 lines;
- expansion defaults to 50-line increments and caps at 150 lines;
- when a failing job or step is already known, callers should retrieve the smallest targeted excerpt that can expose the first actionable failure;
- full-run or full-log retrieval is not the routine default;
- retrieval beyond 150 lines is exceptional evidence recovery and remains subject to exact-head/run-attempt provenance and fail-closed behavior.

`diagnostic_excerpt_lines(...)` validates an explicit target and `expand_diagnostic_excerpt_lines(...)` deterministically expands a target without exceeding the routine maximum. `CIEvidenceRecoveryPlan.diagnostic_excerpt_target_lines` records the bounded target selected for the plan. These values are planning evidence only; the pure-local contract does not perform log retrieval itself.

Retry behavior is bounded:
- rate-limit and transient-network failures may retry the same path within budget;
- other failures advance to the next untried path;
- run-in-progress waits instead of becoming a retrieval failure;
- whole-run failure may advance to job-level recovery;
- incomplete step association may retain an actionable failure.

Fail-closed conditions include:
- malformed or mismatched observation identity;
- moved exact head;
- superseded run attempt;
- invalid reason codes or model types;
- duplicate recovery paths;
- invalid retry state;
- diagnostic excerpt targets outside 50–150 lines or non-integer expansion values.

Authority limits are explicit:
- recovery may set only `evidence_usable_for_attribution`;
- `repair_authorized` remains false;
- `external_write_authorized` remains false;
- `side_effects_performed` remains false;
- attribution and repair authorization remain separate governed stages.

If governed paths are exhausted without an actionable failure, the plan requires a user handoff and reports `evidence-unavailable`; it never invents a repository defect.

## GitHub Write Handoff

Any separately authorized source change, thread mutation, PR update, merge, issue lifecycle action, credential change, or workflow change remains owned by the appropriate Agent OS owner. Recovery planning itself grants none of those authorities.

## Validation

Focused tests:

```bash
python -m pytest tests/agent_os_pr_remediation/test_ci_evidence_recovery.py
python -m pytest tests/agent_os_pr_remediation
```

Repository acceptance still requires normal exact-head aggregate validation and review checks on the pull request.
