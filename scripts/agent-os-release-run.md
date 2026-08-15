# Agent OS Release Run

`agent-os-release-run.py` is the deterministic, offline policy/state evaluator for the governed release lifecycle in #903. It does not call GitHub, merge, close issues, rerun workflows, dismiss reviews, delete branches, enable auto-merge, or change protected settings.

## Contract

An operator or connector gathers fresh GitHub evidence, writes it as JSON, and runs:

```bash
python scripts/agent-os-release-run.py evidence.json
```

Required operator inputs are repository, pull request number, issue number, expected head SHA, bounded changed-file scope, authorized merge method, and required check names. Observed evidence includes the current head, PR/issue state, changed files, check conclusions, review state, and explicit authorization flags.

The machine emits one bounded JSON object with schema identity, repository/PR/issue identity, expected and observed head, phase, classification, states, changed files, checks, review summary, authorization flags, next action, blockers, and recorded side effects.

Classifications are `READY_FOR_MERGE_AUTHORIZATION`, `NEEDS_FIX`, and `BLOCKED`. Green evidence never creates authorization.

## Phases

`preflight` -> `exact-head-validation` -> `review-conversation-gate` -> `ready-for-review` -> `release-review` -> `merge-authorization-pause` -> `merge` -> `post-merge-verification` -> `issue-closure-authorization-pause` -> `issue-closure`.

The evaluator collapses already-proven read-only phases into the next protected boundary. Any head drift, scope drift, non-success required check, requested-changes review, or unresolved blocking thread fails closed.

Merge requires `merge_authorized=true` and must be performed by the GitHub Service Agent at the expected head with the separately approved method. Issue closure requires `issue_closure_authorized=true`; a completion comment must be recorded before closure.

## Mobile usage

Use the reusable prompt in `03_Templates/prompts/agent-os-release-run.md`. Supply the PR number, issue number, expected head, allowed scope, merge method, and required checks. The orchestrator should continue through read-only/already-authorized phases and return only the next genuine blocker or compact authorization request.

## Desktop usage

Gather the same evidence with the GitHub connector or CLI, save it to `evidence.json`, run the command above, and use the emitted `next_action` as the only permitted transition. Reacquire live evidence after every write.

## Safety

This tool is evidence evaluation, not a privileged release bot. It never infers merge or issue-closure authority. Workflow reruns, review dismissal, branch deletion, auto-merge, bypass, protected settings, credentials, production, billing, and external-system writes remain separately unauthorized.
