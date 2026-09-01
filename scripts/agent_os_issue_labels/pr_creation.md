# Pull Request Creation Admission

Issue #1593 records a lifecycle defect reproduced by PR #1592: the connected GitHub `create_pull_request` operation exposes `draft` as an optional argument whose tool default is `false`. The #1592 caller did not explicitly bind Draft state, so the PR was created non-Draft even though authoritative exact-head aggregate validation was still pending.

Agent OS repository policy requires ordinary implementation PRs to start Draft. `pr_creation.py` is the machine-consumable caller contract for that rule.

## Required caller behavior

Before invoking the connected PR-creation operation, call `decide_pull_request_creation(...)` and pass its `draft` value explicitly. Never omit the connected operation's `draft` argument for Agent OS implementation work.

Ordinary or ambiguous intent returns `draft=True`. An explicit Ready request also returns `draft=True` unless the existing Ready-for-Review prerequisites are all supplied: current Ready-transition authorization, required exact-head validation success, and resolved blockers. Only that complete case returns `draft=False`.

This contract does not change `.github/workflows/agent-os-validation.yml`, create another readiness authority, or grant merge, closure, workflow, protected-setting, production, credential, or external-write authority. Ready-for-Review after Draft creation remains governed by the existing lifecycle transition.

## Regression

The #1592 shape is prevented because omitted readiness intent projects to an explicit `draft=True` argument rather than inheriting the connected operation's unsafe `draft=false` default.
