# Agent OS PR Review Remediation CLI

## Purpose

This package exposes one pure-local, read-only operator CLI that composes the
canonical PRR1 normalization/preflight, PRR2 remediation planning, and PRR3
validation/thread-resolution eligibility contracts.

It evaluates supplied evidence only. It does not fetch GitHub, edit source,
execute remediation or validation, invoke a model, resolve threads, merge, or
perform any external write.

## Command

```bash
python -m scripts.agent_os_pr_remediation.cli \
  --input tests/fixtures/agent_os_pr_remediation/e2e.json \
  --format json
```

Use `--format text` for a concise operator summary. JSON is the canonical
machine-readable output.

## Input Envelope

The JSON file supplies:

- `snapshot`: PRR1 pull-request snapshot evidence;
- `review_threads`: PRR1 review-thread evidence;
- `expected_head`: exact head expected by preflight;
- `allowed_files`: authorized file scope;
- `draft_allowed`: Draft compatibility flag;
- `candidates`: PRR2 finding-candidate payloads;
- optional `failure_evidence` and `repair_handoff` payloads;
- `changed_files`: final supplied implementation file evidence;
- `finding_fixes`: exact finding-fix evidence;
- `validation_evidence`: canonical validation bindings;
- `current_head_sha`: current PR head supplied to PRR3; and
- `final_captured_head_sha`: final head capture supplied to PRR3.

Evidence provenance remains the caller's responsibility. Use fresh exact-head
GitHub evidence when evaluating a live pull request.

## Output Envelope

The CLI emits one deterministic envelope containing:

- `preflight`: exact-head, PR-state, Draft, scope, and thread-evidence checks;
- `remediation_plan`: PRR2 findings, tasks, blockers, and compute routes; and
- `resolution_plan`: PRR3 validation states, reason codes, and suggested actions.

Every authority and side-effect field remains false.

## Interpretation

`no-model` is the default compute route. `small-model-eligible`,
`high-reasoning-required`, and `manual-decision-required` are routing evidence,
not execution authority.

Validation states include planned, passed, failed, unavailable, incomplete,
stale, final-head mismatch, and manual-review-required. Focused success with
aggregate validation pending is not final success.

Suggested actions are `eligible-to-resolve`, `leave-open`,
`request-more-evidence`, `route-out-of-scope`, or `manual-decision-required`.

`eligible-to-resolve` is evidence only. It does not authorize or perform review
thread resolution, source edits, merge, auto-merge, issue closure, production
activation, external writes, or any other excluded surface.

## Fail-Closed Cases

The CLI rejects malformed, unknown, conflicting, or oversized input. A moved
expected head remains visible as failed preflight evidence. Stale validation,
out-of-scope findings, incomplete evidence, conflicts, and manual decisions keep
resolution eligibility false.

When evidence is stale, capture fresh PR/thread/head/file evidence through the
GitHub Service Agent and rerun the CLI with a new local input envelope.

## GitHub Write Handoff

The CLI never applies GitHub writes. Any separately authorized source change,
thread mutation, PR update, merge, or issue lifecycle action remains owned by the
GitHub Service Agent under the governing Agent OS authorization rules.

## Validation

Run the focused PRR4 tests with:

```bash
python -m pytest tests/agent_os_pr_remediation/test_cli.py
```

Repository acceptance still requires the normal exact-head aggregate validation
and review checks on the pull request.
