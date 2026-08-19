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

## Boundary

No second router, runner, Scheduler, capability registry, environment-health
model, dependency framework, retry loop, or prose-to-shell parser. #918 remains
the executor-route owner, #1197 the dependency/runtime readiness owner, #1201
the cross-surface currentness owner, #1237 the same-lineage continuation owner,
and #1077 the pre-PR validation owner. Nothing here weakens pre-PR validation or
permits a Draft PR opened merely to obtain a runtime.

## Rollback

Remove `scripts/agent_os_execution_interface/pre_pr_runtime_compatibility.py`,
`tests/agent_os_execution_interface/test_pre_pr_runtime_compatibility.py`, the
`scripts/README.md` entry, and this note. Existing executor routes, dependency
readiness, environment-health evidence, Scheduler/checkpoint lineage, branches,
PRs, and external environments are untouched.

Tests: `tests/agent_os_execution_interface/test_pre_pr_runtime_compatibility.py`.
