# Agent OS Release Run

`agent-os-release-run.py` is the deterministic, offline policy/state evaluator for the governed release lifecycle in #903. It does not call GitHub, merge, close issues, rerun workflows, dismiss reviews, delete branches, enable auto-merge, or change protected settings.

## Contract

An operator or connector gathers fresh GitHub evidence, writes it as JSON, and runs:

```bash
python scripts/agent-os-release-run.py evidence.json
```

Required evidence includes repository, pull request number, issue number, expected and observed head SHA, bounded changed-file scope, authorized merge method, observed check conclusions, the canonical required-check set, and the identity of the authoritative aggregate validation check.

The canonical required-check set is source-backed evidence, not a caller-controlled shortcut. If it is missing, if the authoritative aggregate identity is unavailable, or if an observed required check is omitted from the supplied check results, the evaluator blocks. Unrelated green checks never substitute for the required aggregate lane.

The machine emits one bounded JSON object with schema identity, repository/PR/issue identity, expected and observed head, phase, classification, states, changed files, checks, canonical check identity, review summary, authorization flags, next action, blockers, validation-failure classification when available, and recorded side effects.

Classifications are `READY_FOR_MERGE_AUTHORIZATION`, `NEEDS_FIX`, and `BLOCKED`. Green evidence never creates authorization.

## Validation failure classification

The release evaluator reuses the completed #988 deterministic classifier from `scripts/agent_os_issue_acceptance/validation_failure_classifier.py`. It does not parse provider logs or invent root cause.

For a failed required validation check, supply bounded `validation_failure_evidence` only when current source evidence is available. The #988 result controls release interpretation:

- `pr_regression` -> `NEEDS_FIX`, limited to the already-authorized issue scope;
- `inherited_main_failure` -> `BLOCKED`, without contaminating the feature PR;
- `ci_infrastructure_configuration_failure` -> `BLOCKED`; required validation remains unsatisfied;
- `insufficient_evidence_needs_decision` or absent/malformed failure evidence -> `BLOCKED`.

A red check caused by runner setup, network failure, action failure, or another condition that prevented the aggregate command from running is therefore not reported as a code regression. It still cannot satisfy Ready-for-Review or release review.

Pending, missing, stale, `not_triggered`, cancelled, timed-out, unexpectedly skipped, failed, and unknown required checks remain explicit non-success states. Only a successful authoritative aggregate bound to the exact current head can satisfy that gate under the current Testing And Release / Safe Implementation Lane contract.

#694 remains the owner of future provider-neutral failure normalization. This release evaluator consumes bounded facts and #988 classification; it does not duplicate #694.

## Phases

`preflight` -> `exact-head-validation` -> `review-conversation-gate` -> `ready-for-review` -> `release-review` -> `merge-authorization-pause` -> `merge` -> `post-merge-verification` -> `issue-closure-authorization-pause` -> `issue-closure`.

The evaluator collapses already-proven read-only phases into the next protected boundary. Head drift, scope drift, missing/non-success canonical checks, requested-changes review, or unresolved blocking threads fail closed.

Merge requires `merge_authorized=true` and must be performed by the GitHub Service Agent at the expected head with the separately approved method. Issue closure requires `issue_closure_authorized=true`; a completion comment must be recorded before closure.

## Mobile usage

Use the reusable prompt in `03_Templates/prompts/agent-os-release-run.md`. Supply the PR number, issue number, expected head, allowed scope, merge method, source-backed canonical required-check set, authoritative aggregate identity, observed checks, and any bounded #988 failure evidence. The orchestrator should continue through read-only/already-authorized phases and return only the next genuine blocker or compact authorization request.

## Desktop usage

Gather the same evidence with the GitHub connector or CLI, save it to `evidence.json`, run the command above, and use the emitted `next_action` as the only permitted transition. Reacquire live evidence after every write.

## Safety

This tool is evidence evaluation, not a privileged release bot. It never infers merge or issue-closure authority. Workflow reruns, review dismissal, branch deletion, auto-merge, bypass, protected settings, required-check configuration, credentials, production, billing, and external-system writes remain separately unauthorized.
