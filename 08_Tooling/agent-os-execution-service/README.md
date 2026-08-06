# Agent OS Execution Service — WSC6B1 (package contract: WSC6B4A, PILOT-VALIDATION #723, AOS-CHATGPT2 #918)

This package has two clearly separated classes of surface. The separation *is* the authority boundary, so read it before relying on either.

**Pure-local, non-executing surfaces.** Request validation, repository inspection, result projection, serialization, plan selection, validation command planning, and deterministic executor routing. WSC6B1 is the immutable, read-only request and inspection core: it validates a bounded request, invokes one supplied inspector snapshot at most once, verifies exact repository identities, and returns an immutable result with a redacted public projection. Command planning maps allowlisted command strings onto fixed argv. Executor routing consumes supplied structured capability and identity evidence and selects only an execution surface. None of these surfaces runs a command, dispatches to a runtime, mutates a repository, or authorizes anything.

**Execution-composition surface (shipped in `0.3.0` under #697).** `execution_composition.compose_and_run_validation(...)` *can* dispatch validation, and this package therefore is not execution-incapable. It consumes an exact `ExecutionServiceRequest`, an exact `ValidationCommandPlan`, caller-supplied `ExecutionAuthorizationEvidence`, caller-supplied evaluated time, a canonical `SingleIssuePilotInput`, and a canonical `ConcreteRuntimeConfiguration`. It revalidates request, plan, authorization, and configuration identity — fingerprint, repository, expected SHA, plan and validation-plan IDs, argv-to-`FrozenTestCommand` matching, and `ConcreteRuntimeConfiguration.verify(...)` — and only once every one of those checks passes does it delegate **exactly once** to the canonical validation-only Workflow Scheduler entrypoint `run_concrete_runtime_entrypoint_with_validation_evidence(...)`, which reaches a process-capable runtime. Any identity mismatch, unsupported profile, expired authorization, or unexpected return shape fails closed to bounded `manual-review` / `infrastructure-failure` evidence before any process runs.

Building a command plan or selecting an executor route never reaches that surface and never satisfies its preconditions. Planning or routing does not supply, imply, weaken, or stand in for execution authorization: a caller must additionally pass authorization evidence and runtime configuration that clear their own existing checks.

Validation-only mode, as exposed by the Workflow Scheduler contract this package consumes, supplies no executor, supplies no executor argv, constructs no `PosixProcessExecutor`, and creates no no-op or synthetic executor. Any validation execution built on this contract must use only exact fixed argv already bound by `ValidationCommandPlan`; remain local and bounded; run each command at most once; introduce no retry; publish nothing; and reuse the existing Workflow Scheduler lease, worktree, validation, containment, cleanup, release, quarantine, and evidence-return lifecycle instead of creating a new one.

Execution authorization, route selection, command execution, validation success, review status, Ready-for-Review, and merge authorization are and remain separate states; no version of this package contract collapses them.

## Public capabilities and authority boundary

- `inspect_repository`
- `verify_repository_state`
- deterministic executor-route selection and non-executing handoff construction

An accepted result, a built command plan, or a selected route means only that the supplied inputs satisfied that surface's checks. None authorizes edits, commands, commits, pushes, pull-request readiness, merge, deployment, another invocation, or external mutation.

## Executor routing — AOS-CHATGPT2 (#918)

`executor_routing.py` is a pure, deterministic router for work that upstream Agent OS contracts have already selected and authorized. Executable-lane selection decides **what work may proceed**; executor routing decides only **which execution surface receives that already-approved work**.

The route vocabulary is closed:

- `chatgpt-connector-native`
- `chatgpt-governed-runner`
- `external-coding-agent-fallback`
- `human-decision-required`

The finite routing-only `ExecutorCapability` vocabulary is also closed: `checkout`, `isolated-worktree`, `dependency-installation`, `process-execution`, `compile-or-lint`, `test-execution`, `runtime-inspection`, `generated-artifact-inspection`, `multi-file-implementation`, `git-reconciliation`, `exact-head-validation`, and `checkpointed-resume`. This enum is not a reusable-capability registry, an authorization model, an operating-mode model, a Scheduler capability framework, a validation planner, or dynamic provider discovery.

The public model surface is deliberately small:

- `ExecutorRouteDecision` records the deterministic route, finite reasons, rejected lower-cost routes, supplied routing flags, bounded opaque upstream identities, authority projections, timestamps, invalidation conditions, and a content-addressed decision identity.
- `ExecutorHandoff` is one shared immutable handoff for governed-runner and explicit external-fallback destinations. Connector-native and human-decision routes cannot produce a handoff.

The router references existing request, authorization, validation-plan, operating-mode, lane-selection, repository-state, worktree, exact-head package, environment, checkpoint, resume, and Workflow Scheduler evidence only through bounded opaque identity strings. It validates syntax, presence, ordering, equality, and consistency; each canonical owner remains responsible for validating the semantic object behind its identity. No upstream concrete evidence model is imported or duplicated.

Routing precedence is fixed:

1. Ambiguous authority, ownership, source of truth, target, or scope; an excluded surface; stale or contradictory evidence; or an irreversible/uncertain mutation routes immediately to human decision.
2. An empty required-capability tuple selects connector-native even when other surfaces are available.
3. Non-empty requirements select the governed runner when it is available and supports every required capability.
4. External fallback is available only when the runner is unavailable or insufficient **and** fallback is both available and explicitly permitted.
5. Otherwise the result is human decision with finite fail-closed reasons.

Route selection never creates or widens authority. Authority defaults false, and human-decision results reduce operational authority to false. The module reads no host clock, performs no capability discovery, invokes no runner or provider, creates no checkout or checkpoint, and performs no filesystem, subprocess, network, GitHub, workflow, credential, persistence, production, or external-system operation.

The proposed aggregate `ExecutorCapabilityEvidence`, `GovernedRunnerHandoff`, and `ExternalExecutorHandoff` contracts were retired before implementation; they are neither implemented nor exported.

## Request and fingerprint contracts

`ExecutionServiceRequest` is frozen, slotted, keyword-only, and deterministically fingerprinted. It binds schema, request identity and revision, canonical UTC creation/expiry, repository and actor identities, capability, base/ref/SHA identities, sorted non-overlapping repository-relative POSIX paths, bounded inspection limits, evidence visibility, and finite invalidation conditions.

The caller supplies `evaluated_at`; the service never reads the host clock. A request is current only when `created_at <= evaluated_at < expires_at`.

Exact built-in tuples, strings, integers, enums, and canonical evidence objects are required. Booleans are not integers, and custom mappings or iterable subclasses are not coerced.

Request and result fingerprints use versioned domain-separated canonical JSON and SHA-256. Each fingerprint field is excluded from its own payload, and copied fingerprints on altered content fail validation.

## Validation command planning

`build_validation_command_plan(request, validation_plan, *, evaluated_at)` is the only public planning entry point. It maps validation-plan command strings onto fixed argv through one immutable, in-process `MappingProxyType` allowlist. There is no shell, no parsing, no alias, no user-supplied argv, and no path outside the allowlisted commands. Unregistered commands, duplicate commands, counts above the plan ceiling, identity or SHA mismatches, expired requests, fingerprint mismatches, and manual-review plans all fail closed with bounded errors.

`validate_validation_command_plan(plan)` (#804) is a total, pure, publicly exported check: it never raises, and it returns a sorted tuple of bounded reason codes (empty means valid). It checks exact type, schema and registry versions, the paired validation-plan schema, a positive exact revision, bounded identity fields, an exact entry tuple, profile/operation agreement, empty static plans, nonempty executable plans, canonical registry argv membership, duplicate argv, canonical argv ordering for positive-PR plans, and serialized-size bounds. `serialize_validation_command_plan` and `validation_command_plan_id` now reject every reason this validator returns — including unregistered argv and an operation/profile mismatch, with no exemption — while remaining byte-for-byte and identity-for-identity unchanged for every valid builder-produced plan. The check reads the existing private `_COMMAND_REGISTRY` for argv membership only; it never exposes, copies, mutates, or version-bumps it.

Two plan types are accepted, dispatched by exact type — never by inference:

- **Positive-PR** (`ValidationPlan`): unchanged. `static` plans produce no entries; `focused` and `aggregate` plans produce argv entries sorted by argv. Payloads and `command-plan:` identities are byte-for-byte and identity-for-identity what they were before #723. Allowlisting an additional exact command is purely additive, so `COMMAND_REGISTRY_VERSION` stays `1.0` and existing identities remain stable.
- **Pre-PR** (`PrePrValidationPlan`, defined in `scripts/agent_os_remote_validation/models.py`): planning for validation-only candidate #726, which has no pull request. A missing pull request is never represented as `0`, a dummy PR, a copied identity, or an unbound mutable branch.

The pre-PR branch binds the plan's immutable `PrePrValidationSubject` to the request and rejects any drift in repository, issue identity (`issue:<issue_number>`), base branch, base SHA, branch, expected source SHA, allowed scope, forbidden scope, request fingerprint, ordered command identities, or the 30-second per-command and 300-second total validation ceilings. Entry order follows the subject's declared ordered command identities rather than argv order. `validation_plan_id` carries the domain-separated `pre-pr-validation-plan:` identity, so pre-PR and positive-PR command plans are never confusable.

Planning is deterministic and pure-local: same inputs, same payload, same identity. It performs no network, subprocess, filesystem, Git, workflow, remote-build, credential, provider, persistence, or retry behavior, and `execution_authorized`, `merge_authorized`, and `side_effects_performed` are fixed `False` on every command plan it returns.

## Inspector and repository-state boundaries

`RepositoryInspector` is injected. The service validates before inspection, invokes `inspect(request)` zero times for rejected requests and at most once otherwise, performs no retry or fallback scan, accepts one exact immutable observation, recomputes file and byte counts, and rejects the whole observation when evidence is malformed, contradictory, stale, unauthorized, or excessive.

Ordinary inspector failures return bounded `service_unavailable` results without raw exception text. `KeyboardInterrupt`, `SystemExit`, and `GeneratorExit` propagate.

State verification reuses public contracts from `scripts.agent_os_execution_capabilities`: `RepositoryIdentity`, `RepositoryStateEvidence`, `RepositoryStateValidationResult`, and `validate_repository_state_evidence`. Only canonical `RepositoryStateEvidence` objects are delegated; raw mappings and custom objects are never passed to the canonical validator. Expected repository, base ref/SHA, head ref/SHA, requested SHA, and contract fingerprint are supplied explicitly, and acceptance requires canonical outcome `valid`.

## Evidence, projection, and ceilings

Private evidence remains in immutable memory records, is excluded from ordinary representations, and is retained only under `include-private`. There is no locator or durable evidence store.

`project_public_result()` uses an explicit allowlist, not generic recursive serialization. Private evidence and raw exceptions are excluded; public summaries are bounded and rescanned for secret-like markers. No raw JSON parser is exposed.

Fixed ceilings cover path count/length, inspected file count/bytes, evidence item count and bytes, text length, reason count, command count, command-plan serialized size, routing capability count, route-reason count, opaque identity length, handoff path count, and return-evidence/stop-condition count. Requested limits must be positive exact integers within those ceilings. These are deterministic contract limits, not CPU or memory enforcement.

## Explicit non-capabilities

No surface in this package contains a shell, command parsing, alias expansion, user-supplied argv, retry, persistence, network, credentials, package installation, GitHub API/CLI runtime behavior, MCP/HTTP transport, listener, daemon, hosting, infrastructure, deployment, live pilot, concurrency control, or external write.

The request, inspection, projection, serialization, selection, command-planning, and executor-routing surfaces additionally perform no subprocess execution, no live Git or filesystem mutation, and no Workflow Scheduler dispatch.

Subprocess execution, worktree, lease, cleanup, and quarantine are reachable only through the #697 composition surface described above, only by delegation to the canonical Workflow Scheduler runtime, and only after separately supplied execution authorization and runtime configuration clear their existing checks. This package owns no second runner, executor, lease, scheduler, or command loop of its own.

#723 adds pre-PR command binding only. It authorizes no execution and no merge; candidate #726 has not been run; and Scheduler concurrency is unchanged. #918 adds routing and handoff evidence only; it invokes no execution surface.

## Validation

From the repository root:

```bash
PYTHONPATH=08_Tooling/agent-os-execution-service/src python -m pytest -q \
  08_Tooling/agent-os-execution-service/tests/test_executor_routing.py
python -m pytest tests/agent_os_remote_validation/test_selector.py -q
PYTHONPATH=08_Tooling/agent-os-execution-service/src python -m pytest \
  08_Tooling/agent-os-execution-service/tests -q
python -m compileall -q scripts/agent_os_remote_validation \
  08_Tooling/agent-os-execution-service/src
python -m pytest 08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py -q
bash 07_Agent_Tests/validate-repo-structure.sh
./scripts/validate-all.sh
```

## Deferred phases and rollback

WSC6B2 covered command registry/planning. WSC6B3 covers process execution, worktree, lease, cleanup, and quarantine. WSC6B4A established the truthful public package contract required before #697 added governed local validation composition. #723 adds pre-PR command binding only; authorizing and running the #726 pilot remains a separate decision. #918 adds deterministic execution-surface routing and immutable handoff evidence only; transport, runner invocation, dynamic capability discovery, automatic retry/switching, hosting, authentication, credentials, persistence, deployment, and live execution remain separate and unauthorized.

Rollback for #918 is reverting `executor_routing.py`, its package exports and focused tests, this README update, the changelog entry, and the module-version records. It created no service, daemon, infrastructure, credential, workflow setting, production data, lease, worktree, checkpoint record, evidence store, or external state. Rollback for #723 remains reverting the pre-PR branch in `command_planning.py`, the added registry entry, the pre-PR models and selector functions in `scripts/agent_os_remote_validation/`, the added focused rule in `validation_profiles.yml`, the tests, package exports, documentation, and version records. Leases, worktrees, and quarantine records can exist only from an authorized run of the #697 composition surface, which is rolled back through the Workflow Scheduler's own cleanup, release, and quarantine lifecycle rather than by this package.
