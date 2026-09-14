# PR #2335 Red-Merge Recovery Evidence

## Purpose

Preserve the canonical recovery evidence for issue #2337 without rewriting the merged #2335 history or weakening Agent OS validation behavior.

## Failed merge lineage

- Parent capability mission: #2283
- Merged PR: #2335
- Exact PR head: `9ebebab1a99e618ae239932dea39f13fe812a640`
- Failed validation run: `34785530832`
- Failed job: `Run aggregate validation` / `103800204067`
- Merge commit now on `main`: `a2a26ed33cb8234b32209a9f2d7ca9414411e463`

The sibling `Run validation plan=success` result never overrides the failed aggregate validation gate.

## Recovery attempt #2339

Recovery PR #2339 was opened from current `main` to reacquire exact-head validation of the merged tree. Its first recovery commit intentionally had the same tree as `main`. GitHub accepted the commit, but the Agent OS Validation Gate correctly rejected the PR during `Compute canonical validation plan` because the pull request changed-file set was empty. Aggregate validation was therefore skipped.

That failure is preserved as a failed-repair attempt. The recovery does **not** change the validation workflow to permit empty PRs. Instead, this evidence file gives #2339 a real bounded change while documenting why the no-diff probe failed.

## Second failed attempt and its root cause

Adding this documentation-only file gave #2339 a real diff, so the authoritative aggregate finally executed on head `462c4efe20e851a5728fda8853fa01a4165fc9c9`:

- Ready-state run: `34787791600` — `Agent OS Validation Gate` = failure
- Failed job: `Run aggregate validation` / `103806332730`, step 9
- Failing package: `root` — `cd <repo> && PYTHONPATH=src python3 -m pytest tests`, exit 1

The earlier Draft run `34787435680` was green only because the aggregate job is gated on `github.event.pull_request.draft == false`. A Draft run therefore never executes the authoritative aggregate, and its green result is not merge evidence for the Ready state.

Three deterministic failures, reproduced locally on the exact head and on plain `main`:

- `tests/test_workflow_scheduler_packaging.py::test_only_the_allowlisted_scripts_module_imports_workflow_scheduler`
- `tests/agent_os_notion_read_request/test_architecture_boundaries.py::test_no_gce_or_workflow_scheduler_dependency[live_executor.py]`
- `tests/agent_os_notion_read_request/test_architecture_boundaries.py::test_no_gce_or_workflow_scheduler_dependency[binding_verification.py]`

Provenance: the defect is inherited from merged `main`, not introduced by this recovery artifact.

- `dc1b5e7` established `test_architecture_boundaries.py`, which forbids any `workflow_scheduler` import in `scripts/agent_os_notion_read_request/`. That commit was green.
- `a9b47b5` added `live_executor.py` with a module-level `workflow_scheduler` import, breaking that boundary and the repository-wide #752/#912 packaging allowlist in `tests/test_workflow_scheduler_packaging.py`.
- `a2a26ed` (PR #2335) added `binding_verification.py` with the same violation, adding the third failure.

So `main` has been red since `a9b47b5`, and the unsafe merge admission let two red merges through, not one.

## Repair

The binding was in the wrong place, not merely mis-tested. `scripts/agent_os_notion_read_request` is a provider-neutral bounded read seam: `execution.py` already takes its Scheduler task executor by injection, and the package's own architecture test keeps the Scheduler an injected caller concern.

The repair moves the `workflow_scheduler` composition out of that package into `src/agent_os_notion_binding/`, following the pattern `agent_os_execution_service.lesson_reader_composition` already uses for the CKR11 lesson reader. `src` is on `PYTHONPATH` for both the aggregate root run and the activation workflow, so no workflow change is required.

No validation semantics were weakened: no test was skipped, relaxed, deleted, or allowlisted, no required-check semantics were altered, and merged #2335 history was not rewritten.

## Failed-repair lesson re-entry

Executed through the existing `activate_repair_retry_lessons` seam against the canonical Lessons Learned data source (read-only, 25 rows retrieved). Recorded for attempt `2339-ready-aggregate-462c4efe`:

- Under the forced `specialized_knowledge_required=True` path: `MANUAL_REVIEW` / `unavailable-or-failed`, mutation blocked. Cause is CKR2's #1520 provenance invariant — most live lesson rows carry no `Source Link`, so they rank unverifiable. Retrieval itself succeeded.
- Classified as a repository-local packaging/boundary repair fully specified by repository-owned contract tests, so the contract's documented `specialized_knowledge_required=False` opt-out applies: `NOT_NEEDED` / `not-material`, mutation admitted.

Lessons materially applied: LL-72 (never relax a contract test to turn a check green), LL-55 and LL-68 (classify aggregate-failure provenance before PR attribution), LL-76, LL-84 and LL-65 (exact-head validation evidence), LL-53 (red status is intermediate evidence), LL-62 (continue the existing lineage), LL-63 (lesson re-entry before a new hypothesis).

## Safety contract

For this recovery lineage:

- a red, cancelled, timed-out, stale, pending, or otherwise non-green required exact-head gate blocks merge;
- a green sibling check cannot mask a failed aggregate check;
- a green Draft run is not merge evidence, because the authoritative aggregate does not run on Draft;
- no historical validation result can be reported as green when canonical GitHub evidence says failure;
- merged #2335 history is not rewritten;
- no Notion, Drive, classroom, credential, production, protected-setting, or other external write is authorized by this recovery artifact;
- #2283 must not resume its live Notion smoke test until the #2335/#2337 recovery lineage has current green validation evidence.

## Regression coverage

Added to the canonical merge-admission owner rather than a second admission framework:

- `tests/agent_os_issue_acceptance/test_merge_authorization.py` — Ready plus failing exact-head aggregate is blocked; a green `Run validation plan` sibling does not offset a failing aggregate; green evidence bound to an earlier Draft-run SHA is not exact-head evidence; only terminal `success` on the exact head is merge evidence.
- `tests/test_agent_os_notion_binding.py` — the composition root stays outside `scripts/`, the bounded read package declares no Scheduler dependency, and the seam preserves its read-only task type, payload copying, and fail-closed credential behavior.

## Rollback

Revert the recovery commit on `agent/2337-repair-red-2335`. That restores `live_executor.py` and `binding_verification.py` to their merged form, removes `src/agent_os_notion_binding/` and the added tests, and returns the lineage to its previous red state. No merged `main` history is affected and no runtime behavior outside this lineage depends on this record.
