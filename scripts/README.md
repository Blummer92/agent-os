# Agent OS Scripts

Runnable repository-level scripts. Python packages in this directory are
documented by their own modules and the reusable capability registry
(`04_Registry/reusable-capabilities.yml`).

## verify-repo-state.sh

Reusable repository-state verifier. It replaces the Git preflight block that
was previously pasted into Agent OS prompts: prompts now state the contract
("verify branch X against base Y") while the script owns the Git operations,
retries, validation, and evidence output.

```bash
scripts/verify-repo-state.sh [--create-from-base] <branch> [base]
```

Usage, branch-creation policy, dirty-tree policy, examples, and known
limitations are documented in `scripts/verify-repo-state.md`. The stdout
evidence format, stderr logging contract, exit codes, and retry behavior are in
`scripts/verify-repo-state-contract.md`. Tests: `tests/test_verify_repo_state.py`.

## build-chatgpt-checkout-package.sh

Builds one deterministic, exact-head ZIP for offline ChatGPT code-execution
validation, from an explicitly supplied branch, tag, or exact commit SHA. It
reuses `scripts/prepare-issue-worktree.sh` for all checkout/fetch/worktree
behavior rather than duplicating it.

```bash
scripts/build-chatgpt-checkout-package.sh \
  --repository <owner/name> --issue <n> --ref <branch|tag|sha40> \
  --output <absolute .zip path>
```

Syntax, manifest fields, exclusions, and the determinism boundary are documented
in `scripts/build-chatgpt-checkout-package.md`. Tests:
`tests/test_build_chatgpt_checkout_package.py`.

## agent-os-release-run.py

Offline deterministic release-run state evaluator for Issue #903. It consumes freshly reacquired GitHub evidence, reuses #988 validation-failure classification plus #1038 lifecycle-reconciliation and #1187 refresh receipts, binds validation and lifecycle state to the exact current PR head, and returns the next governed lifecycle action without performing GitHub writes itself.

```bash
python scripts/agent-os-release-run.py evidence.json
```

The contract now fails closed on behind/conflicted/unknown freshness, stale validation or reconciliation, unexplained head movement, out-of-band Draft -> Ready, and external merge/closure. Managed lifecycle labels remain non-authoritative derived cache. Contract, mobile/desktop usage, protected authorization pauses, and safety boundaries are documented in `scripts/agent-os-release-run.md`. Tests: `tests/test_agent_os_release_run.py`.

## validate-all.sh

Aggregate local validation runner: structural validation plus every discovered
pytest suite.

```bash
./scripts/validate-all.sh
```

After execution, `TIMING RESULTS` reports observational elapsed time for each
check that already runs through the canonical runner boundary, including
structural validation, optional focused checks, every discovered pytest suite,
and `aggregate total`. Durations are reported in seconds to millisecond display
precision. Timing does not change command selection, command order, failure
handling, overall status, or exit authority. If the runner cannot obtain a safe
timestamp, it reports `unavailable` for that timing rather than changing the
validation result.

The timing instrumentation does not add a second pytest collection or execution
pass. Collection-versus-execution separation is therefore not reported by this
runner unless it can be added later without changing validation behavior.

## agent_os_github_git_objects

Bounded local Git Database adapter for Issue #920. It reads exact commit/tree/blob identities, plans a deterministic operation fingerprint, requires explicit matching confirmation, validates an unattached commit before ref movement, and updates only a non-protected branch with `force=false`. Tests use injected fakes; live execution requires separate authorization. See `scripts/agent_os_github_git_objects/README.md`.

## protected_branch_push_guard.py

Local advisory guard against pushes to protected branches, installed as a
`pre-push` hook. Policy lives in
`01_Shared_Standards/github/protected-branch-governance.md`.

## agent-os-execution-interface-preflight.py

Pre-tool governed-route preflight for #1237, wired from `.claude/settings.json` as Claude Code `UserPromptSubmit` and `PreToolUse` hooks so a governed Agent OS request resolves the existing handoff-discovery/resume path before generic GitHub publish tooling checks local `git`/`gh`. It consumes the existing #1237 locator and introduces no second router, locator, descriptor store, transport, Scheduler, lease, or execution authority.

```bash
scripts/agent-os-execution-interface-preflight.py \
  --repository Blummer92/agent-os --issue 1259 --store-root <path>
```

Contract, outcomes, configuration, boundary, and rollback are documented in
`scripts/agent-os-execution-interface-preflight.md`. Tests:
`tests/agent_os_execution_interface/`.

## agent_os_execution_interface/post_selection_continuation.py

Pure post-selection half of the same #1237 seam. When an already-selected tool/action turns out to be insufficient, it classifies the attempt into #1237's six fixed states and returns the obligations the caller must discharge, so a capable approved alternative is consumed on the same issue/branch/PR/checkpoint/lease lineage instead of being reported as a handoff. It consumes the existing #1039 `ExecutionSurfaceAvailabilityOutcome`, delegates repeated transitions to #1200 and cross-surface evidence to #1201, refuses #1209/#1235/#1251 lifecycles outright, and adds no router, retry engine, Scheduler, registry, or authority. See `scripts/agent-os-post-selection-continuation.md`; tests: `tests/agent_os_execution_interface/test_post_selection_continuation.py`.

## agent_os_execution_interface/pre_pr_runtime_compatibility.py

Pure pre-dispatch projection for #1278. It joins existing #1197
`RequiredEnvironmentSpec`/`DependencyReadinessEvidence` into existing #918
`ExecutorCapability` routing inputs so a declared pre-PR developer loop is never
routed to a surface that only edits code or reads/writes GitHub. It adds no
route, runner, Scheduler, registry, dependency framework, or authority. See
`scripts/agent-os-prepr-runtime-compatibility.md`; tests:
`tests/agent_os_execution_interface/test_pre_pr_runtime_compatibility.py`.

## agent_os_execution_interface/validation_route_preference.py

Pure validation-surface policy projection for #1573. It consumes the existing
#918 `ExecutorRouteDecision` after pre-PR runtime capabilities have already been
projected. For pre-PR developer-loop checks, a capable governed runner or an
explicitly permitted capable fallback is preferred before any user terminal
handoff; PR CI is never used merely to obtain the first execution of a required
pre-PR check. Manual terminal execution is represented only after canonical
routing has found no capable approved automated route and the caller separately
proves manual execution is available and appropriate. For the final full
aggregate, authoritative exact-head CI is preferred when available so the same
aggregate is not redundantly requested from the user. The projection performs no
execution and grants no GitHub, merge, closure, production, or external-write
authority. Tests:
`tests/agent_os_execution_interface/test_validation_route_preference.py`.
