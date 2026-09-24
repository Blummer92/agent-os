# Agent OS Issue Label Checker

Local, fixture-first tooling for issue taxonomy evidence, safe application planning,
and bounded pull-request label reconciliation.

## Governed legacy issue migration

`legacy_migration.py` provides the bounded migration path for pre-tiered free-form
Agent OS issue bodies. It does not parse arbitrary prose into readiness metadata and it
does not write to GitHub. A caller supplies explicit canonical evidence for tier, owner,
readiness, source of truth, and external-write boundary (plus optional work type). Missing,
conflicting, or ambiguous evidence returns `manual-review` with named reason codes.

Successful migration preserves the legacy prose and appends the canonical tiered metadata
block **last**. The migrated body is then consumed by the existing
`parse_issue_form_body()` and `reconcile_issue_labels()` path; the migration helper never
becomes a second readiness authority, selector, or label writer. Already-tiered bodies are
returned unchanged. Rendering metadata last prevents historical/trailing prose from being
absorbed into the final canonical field.

This utility produces migration evidence only (`mutation_performed=false`,
`write_authorized=false`). Any issue-body mutation and managed-label reconciliation remain
separately authorized GitHub operations under the existing lifecycle contracts.

## Pull-request lifecycle evidence

Managed PR lifecycle labels were retired as required Agent OS state by #2904. PR lifecycle decisions consume canonical GitHub Draft/Ready state, exact head identity, authoritative validation, branch freshness/conflicts, review threads, and terminal state directly. This package no longer owns a PR-label planner, reconciler, or connected PR-label lifecycle.

Issue-label tooling remains unchanged and continues to own Agent OS issue classification/readiness projection.

## Governed stale-branch refresh

`scripts/agent_os_issue_labels/pr_branch_refresh.py` is the bounded #1187 seam for an
eligible `branch:behind` PR. Behind state is evidence, not mutation authority. Callers
must provide current explicit refresh authorization, exact base/head/current-main IDs,
allowed and forbidden path evidence, and required validation command identities.

The provider owns concrete rebase transport. Exactly one rebase attempt is admitted.
Moved head/base evidence, conflicted or unknown state, stale authorization, scope drift,
remote-head mismatch, ambiguous transport, or failure to prove `branch:current` all
fail closed. There is no merge-main fallback, automatic retry, Update Branch setting
change, or revival of retired connector-only #568 behavior.

A successful refresh creates a new exact head and invalidates prior validation, tested-SHA, branch-freshness, review/approval applicability, merge authorization, candidate-runtime, and Ready-for-Review evidence. Scope is rechecked before validation. Post-refresh order is fixed: prove the new head and scope; run required validation; then prove `branch:current` against the same current-main identity.

If `main` moves before final proof, the result is stale and no second refresh occurs. Failing validation grants no Ready-for-Review, merge, closure, workflow, repository-setting, production, or external system authority.

## Production branch-refresh composition

`scripts/agent_os_issue_labels/pr_branch_refresh_provider.py` is the GH-LIFE4 / #1365
production composition behind #1187's existing `PullRequestBranchRefreshProvider`
protocol. It does not replace #1187 admission, scope checking, validation ordering, or final `branch:current` proof.

`GitHubPullRequestBranchRefreshBackingProvider` uses one already-authenticated
PyGithub-compatible client to reacquire the exact PR head/base/main identities,
mergeability and changed paths. It never acquires
credentials. Review-thread evidence and required validation remain injected from their
existing canonical owners. Read failures become `unknown`/unavailable/blocking evidence
so they cannot produce refresh or lifecycle authority.

Immediately before preparation the provider reacquires the exact PR branch evidence.
Because #1187's `expected_base_sha` is the admitted current base/main identity rather
than a historical merge-base, the provider derives the exact merge-base from the bound
head and admitted main with fixed Git argv. It then performs one fixed local
`git rebase --no-autostash --onto <admitted-main> <merge-base> <expected-head>` and
proves the resulting detached `HEAD` commit identity. Caller-supplied Git flags, shell
text, refspecs, and arbitrary commands are never accepted. The separate #1381 transport
authorization is checked before local preparation begins.

The remote non-fast-forward write remains exclusively #1381-owned. The provider builds
one `ExpectedHeadBranchUpdateRequest` and delegates to
`update_branch_with_expected_head(...)`, which performs the exact expected-old-head
force-with-lease mutation and post-write verification. A moved head/base/main, missing
merge-base, failed rebase, unproven rebased head, rejected expected-head update, or
ambiguous mutation fails closed. Neither local preparation nor remote mutation is
retried, and there is no plain force push, merge-main fallback, protected-branch path,
or second refresh lifecycle.

`run_production_pull_request_branch_refresh(...)` is the production caller: it composes
the live GitHub backing and concrete provider, passes through the existing #1187
request authorization unchanged, and delegates exactly once to
`refresh_pull_request_branch(...)`.

## Canonical PR refresh entrypoint

`refresh_pr(...)` in `pr_branch_refresh_operator.py` is the single operator-facing
PR-refresh facade exported from `scripts.agent_os_issue_labels`. A governed caller
supplies only the target PR, admitted head/main identities, existing authorization
evidence, bounded path scope, label-write authority, repository root, invocation ID,
and environment. The facade fixes canonical base branch `main` and the closed validation
profile internally, then delegates exactly once through the existing #1400 operator,
#1365 production composition, #1187 lifecycle, and #1381 expected-head transport.

Conceptually:

```python
from scripts.agent_os_issue_labels import refresh_pr

receipt = refresh_pr(
    repository="Blummer92/agent-os",
    pr_number=1363,
    expected_head_sha="<authorized-head-sha>",
    current_main_sha="<authorized-main-sha>",
    authorization_id="<governed-authorization-id>",
    authorization_current=True,
    branch_refresh_authorized=True,
    allowed_changed_paths=("path/to/authorized/file.py",),
    forbidden_paths=(".github/workflows/example.yml",),
    repository_root="/repo",
    invocation_id="<invocation-id>",
    environment={"GITHUB_TOKEN": "<runtime-provided-token>"},
)
```

`request != authorization`: naming a PR or calling `refresh_pr(...)` never grants,
renews, manufactures, or rebinds refresh authority. Missing or stale authorization,
moved head/main evidence, conflicted/unknown state, or scope drift fails closed through
the existing contracts. The facade does not accept provider, runner, review-reader,
validation-executor, transport, Git argv, or validation-command objects from callers.

The returned immutable receipt projects the admitted main, old/new heads, authorization
identity/consumption, mutation count, validation status, final-current
proof, reason codes/blockers, rollback posture, and side-effect evidence. It grants no
Ready-for-Review, merge, issue-closure, workflow, repository-setting, credential,
production, or external-system authority.

Complexity target for #1402:

- before: operator handoffs exposed `PullRequestBranchRefreshRequest` plus provider,
  runner, review-reader, validation, production-caller, and transport composition;
- after: public governed PR-refresh entrypoints = 1 (`refresh_pr`);
- caller-owned provider/runner/review/validation composition = 0;
- canonical refresh algorithm owners remain unchanged (#1187/#1381/#1365/#1400).

This consolidation targets operator/API cognitive complexity only; it does not claim
runtime or compute savings.

## Issue-label tooling

The checker reads Agent OS issue-form output and the declarative label map, computes
expected labels, compares them with supplied labels, and renders an IA-style report.
The side-effect-free issue planner consumes an issue body, current labels, and an exact
repository-label catalog; its initial policy may approve only missing `agent-os`.

## Read-only workflows

Existing issue-label workflows remain read-only. #2904 adds no workflow for PR labels or branch refresh.

## Validation

```bash
python -m pytest tests/agent_os_issue_labels/test_legacy_migration.py -q
python -m pytest tests/agent_os_issue_labels/test_pr_branch_refresh_operator.py -q
python -m pytest tests/agent_os_issue_labels/test_pr_branch_refresh.py -q
python -m pytest tests/agent_os_issue_labels/test_pr_branch_refresh_provider.py -q
python -m pytest tests/agent_os_github_git_objects/test_branch_update.py -q
python -m pytest tests/agent_os_issue_labels/test_github_service_agent_draft_pr_contract.py -q
python -m pytest tests/agent_os_issue_labels -q
```

Repository acceptance still requires the executable `Agent OS Validation Gate`,
including repository structure validation, authoritative exact-head aggregate, and
required PR review checks.

## Boundary

Lifecycle and branch-refresh helpers report bounded evidence only. They grant no merge,
Ready-for-Review, closure, workflow, repository-setting, production, or external-system
authority. Follow the canonical write-authorization and excluded-surface policies above.
