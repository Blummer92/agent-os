# Pre-PR runtime capability routing (#1278)

## Failure removed

```text
ready Tier-1 issue -> bounded implementation authored on the existing branch
-> issue declares a package developer loop before Draft PR
-> a surface with only generic code-edit or GitHub read/write capability is entered
-> required pre-PR checks cannot execute truthfully
-> late manual handoff after implementation is already complete
```

Hard invariant:

```text
surface has generic code-edit or GitHub read/write capability
!=
surface can satisfy this issue's declared developer-loop runtime
```

A bare `node` or `python` executable is never proof that the declared package
runtime, dependencies, and test loop are usable.

## Resolved path

```text
existing #1197 RequiredEnvironmentSpec + DependencyReadinessEvidence
-> project_pre_pr_runtime_capabilities (this adapter)
-> existing #918 ExecutorCapability requirements + evidence flags
-> existing #918 select_executor_route
-> existing #1237 same-lineage continuation when a capable approved route exists
-> existing #1077 pre-PR developer-loop validation
```

The adapter is a pure projection. It selects no route, reads no clock, and
performs no filesystem, subprocess, network, GitHub, or external operation.

## Requirement source

Requirements are read only from already-normalized contracts: the #1197
`RequiredEnvironmentSpec` (ecosystem, package root, runtime requirement,
manifest/lock identity, install mode, approved source, and
`required_validation_command_ids`) joined with the current #1197
`DependencyReadinessEvidence`. Issue prose is never parsed into shell or
install authority; a spec without normalized validation command identities is
rejected rather than guessed.

## Projected capabilities

Every executable pre-PR developer loop always requires `checkout`,
`isolated-worktree`, `process-execution`, `runtime-inspection`,
`test-execution`, and `exact-head-validation`. `dependency-installation` is
added only when existing #1197 evidence reports `preparation-required`.

## Dispositions

| #1197 / evidence condition | Existing #918 route outcome |
| --- | --- |
| capable approved runner proves every required capability | governed runner selected |
| connector read/write only, no runtime capability | `human-decision-required`, missing-capability + no-capable-route reasons |
| preparation required | `dependency-installation` added; existing #1197 preparation owns the step |
| readiness evidence expired | existing `evidence_stale` input, fail closed |
| identity/status contradiction | existing `evidence_contradictory` input, fail closed |

The projection reports `execution_authorized`, `github_writes_authorized`,
`external_writes_authorized`, `merge_authorized`, and
`side_effects_performed` as permanently false.

## Production consumption (#1325)

#1325 does not add another projection or route. It makes governed handoff
publication a real consumer of this existing adapter for the exact operation
`pre-pr-developer-loop`.

Before any handoff, route decision, restart capsule, ResumePlan, or invocation
descriptor is persisted, `publish_governed_handoff(...)` recomputes this #1278
projection from the already-supplied current `RequiredEnvironmentSpec` and
`DependencyReadinessEvidence`. The route's existing required capabilities are
passed as `base_required_capabilities`, so operation-specific capabilities are
preserved while any missing mandatory pre-PR runtime capability is added by the
canonical projection and therefore detected as a mismatch.

Publication fails closed when any of these bindings differ:

- projected required capabilities;
- `evidence_stale`;
- `evidence_contradictory`; or
- the current environment-health evidence identity.

The existing #918 route gate still runs first. Only
`chatgpt-governed-runner` may publish a governed pre-PR handoff; connector-native,
fallback, and human-decision routes remain non-publishable through the existing
`route-not-governed-runner` boundary. Non-pre-PR publication does not invoke this
additional binding check.

This closes the repository integration gap without changing any final-validation
provider or trigger. Local or VM developer-loop success remains non-final; the
existing testing/release standard still requires an authoritative exact-head
aggregate before Ready-for-Review.

Current `main` documents `Agent OS Validation Gate` as the repository-visible
compatibility/validation path and Cloud Build as a supplemental Linux validation
surface. #1325 intentionally leaves that relationship unchanged. Making Cloud
Build the exclusive Ready-for-Review final gate would require a separate
governed workflow/project-settings decision and is not implied by this change.

#1251 remains the separate owner of recoverable red-CI checkpoint,
classification, same-lineage repair, focused revalidation, and exact-head
aggregate continuation. Its lifecycle change was approved by the repository
owner on 2026-08-21; #1325 does not implement or duplicate that lifecycle.

## Boundary

No second router, runner, Scheduler, capability registry, environment-health
model, dependency framework, retry loop, or prose-to-shell parser. #918 remains
the executor-route owner, #1197 the dependency/runtime readiness owner, #1201
the cross-surface currentness owner, #1237 the same-lineage continuation owner,
#1251 the red-CI continuation owner, and #1077 the pre-PR validation owner.
Nothing here weakens pre-PR validation or permits a Draft PR opened merely to
obtain a runtime. Final-validation provider/trigger policy is unchanged.

## Rollback

For #1278 itself, remove
`scripts/agent_os_execution_interface/pre_pr_runtime_compatibility.py`,
`tests/agent_os_execution_interface/test_pre_pr_runtime_compatibility.py`, the
`scripts/README.md` entry, and this note.

For #1325 only, revert the projection-binding check in
`08_Tooling/agent-os-execution-service/src/agent_os_execution_service/handoff_publication.py`,
remove
`08_Tooling/agent-os-execution-service/tests/test_pre_pr_handoff_publication_binding.py`,
and revert this production-consumption section. Existing executor routes,
dependency readiness, environment-health evidence, Scheduler/checkpoint lineage,
final-validation providers/triggers, branches, PRs, and external environments
are untouched.

Tests:

- `tests/agent_os_execution_interface/test_pre_pr_runtime_compatibility.py`
- `08_Tooling/agent-os-execution-service/tests/test_pre_pr_handoff_publication_binding.py`
