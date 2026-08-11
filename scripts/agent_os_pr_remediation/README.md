# Agent OS PR Review Remediation CLI

## Purpose

This package exposes pure-local, read-only contracts for PR review remediation and CI evidence recovery. It evaluates supplied evidence only: it does not fetch GitHub, edit source, execute remediation or validation, resolve threads, merge, or perform external writes.

## PR Review Remediation CLI

```bash
python -m scripts.agent_os_pr_remediation.cli --input tests/fixtures/agent_os_pr_remediation/e2e.json --format json
```

The input composes PR snapshot/thread evidence, exact-head preflight, remediation candidates, changed-file/fix evidence, validation bindings, and final head capture. JSON output contains deterministic preflight, remediation, and resolution plans. Every authority and side-effect field remains false.

## CI Evidence Recovery Contract

`ci_evidence_recovery.py` plans how a caller should recover the first actionable GitHub Actions failure without assuming `gh` or Cloud Shell is available. It is a planner only; it performs no network, CLI, retry, repository, or external-system operation.

Each plan binds repository, PR number, full 40-character head SHA, workflow run ID, run attempt, and optional failing job ID. A moved head or superseded run attempt fails closed before recovered evidence can be used for attribution.

The ordered recovery paths are structured evidence, direct Actions-log access, `gh` run logs, failing-job logs, an approved alternate environment, and finally a user handoff. A caller supplies observations from attempted paths; the planner deterministically selects the next path or marks evidence usable.

Machine-readable failure reasons distinguish CLI unavailable/unauthenticated, insufficient permission, credential conflict, wrong host, rate limiting, in-progress runs, attempt/head mismatches, run/job log failures, incomplete log association, transient network failure, expired environment, disk exhaustion, and exhausted evidence recovery.

Rate-limit and transient-network observations may retry the same path only within the caller-supplied retry budget. Other failures advance to the next untried path. Run-in-progress waits rather than masquerading as a retrieval failure. Whole-run failure can advance to job-level recovery. Incomplete step association may still retain an actionable failure.

Even successful recovery sets only `evidence_usable_for_attribution`. `repair_authorized`, `external_write_authorized`, and `side_effects_performed` remain false. Attribution and any repair authorization stay in their separately governed stages.

## Fail-Closed Cases

Malformed identity, stale exact head, obsolete run attempt, invalid reason codes, duplicate recovery paths, and invalid retry state are rejected or produce non-usable evidence. If all governed paths are exhausted without an actionable failure, the plan requires a user handoff and reports `evidence-unavailable`; it never invents a repository defect.

## GitHub Write Handoff

Any separately authorized source change, thread mutation, PR update, merge, issue lifecycle action, credential change, or workflow change remains owned by the appropriate Agent OS owner. Recovery planning itself grants none of those authorities.

## Validation

Focused tests:

```bash
python -m pytest tests/agent_os_pr_remediation/test_ci_evidence_recovery.py
python -m pytest tests/agent_os_pr_remediation
```

Repository acceptance still requires normal exact-head aggregate validation and review checks on the pull request.
