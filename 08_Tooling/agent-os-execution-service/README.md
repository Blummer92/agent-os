# Agent OS Execution Service — WSC6B1 (package contract: WSC6B4A, PILOT-VALIDATION #723)

WSC6B1 is the immutable, pure-local, read-only request and inspection core for a phased Agent OS Execution Service. It validates a bounded request, invokes one supplied inspector snapshot at most once, verifies exact repository identities, and returns an immutable result with a redacted public projection. It also plans — but never runs — validation commands.

A later, separately authorized composition layer (#697) may consume an exact `ExecutionServiceRequest`, an exact `ValidationCommandPlan`, caller-supplied execution authorization, caller-supplied Workflow Scheduler runtime configuration, the canonical validation-only runtime, and the exact retained `FrozenTestValidationResult`. Any later validation execution built on this contract must use only exact fixed argv already bound by `ValidationCommandPlan`; remain local and bounded; run each command at most once; introduce no retry; publish nothing; and reuse the existing Workflow Scheduler lease, worktree, validation, containment, cleanup, release, quarantine, and evidence-return lifecycle instead of creating a new one.

Validation-only mode, as exposed by the current Workflow Scheduler contract this package may later consume, supplies no executor, supplies no executor argv, constructs no `PosixProcessExecutor`, and creates no no-op or synthetic executor.

Execution authorization, command execution, validation success, review status, Ready-for-Review, and merge authorization are and remain separate states; no version of this package contract collapses them.

## Public capabilities and authority boundary

- `inspect_repository`
- `verify_repository_state`

An accepted result or a built command plan means only that the supplied inputs satisfied this package's checks. Neither authorizes edits, commands, commits, pushes, pull-request readiness, merge, deployment, another invocation, or external mutation.

## Request and fingerprint contracts

`ExecutionServiceRequest` is frozen, slotted, keyword-only, and deterministically fingerprinted. It binds schema, request identity and revision, canonical UTC creation/expiry, repository and actor identities, capability, base/ref/SHA identities, sorted non-overlapping repository-relative POSIX paths, bounded inspection limits, evidence visibility, and finite invalidation conditions.

The caller supplies `evaluated_at`; the service never reads the host clock. A request is current only when `created_at <= evaluated_at < expires_at`.

Exact built-in tuples, strings, integers, enums, and canonical evidence objects are required. Booleans are not integers, and custom mappings or iterable subclasses are not coerced.

Request and result fingerprints use versioned domain-separated canonical JSON and SHA-256. Each fingerprint field is excluded from its own payload, and copied fingerprints on altered content fail validation.

## Validation command planning

`build_validation_command_plan(request, validation_plan, *, evaluated_at)` is the only public planning entry point. It maps validation-plan command strings onto fixed argv through one immutable, in-process `MappingProxyType` allowlist. There is no shell, no parsing, no alias, no user-supplied argv, and no path outside the allowlisted commands. Unregistered commands, duplicate commands, counts above the plan ceiling, identity or SHA mismatches, expired requests, fingerprint mismatches, and manual-review plans all fail closed with bounded errors.

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

Fixed ceilings cover path count/length, inspected file count/bytes, evidence item count and bytes, text length, reason count, command count, and command-plan serialized size. Requested limits must be positive exact integers within those ceilings. These are deterministic contract limits, not CPU or memory enforcement.

## Explicit non-capabilities

This package contains no subprocess or shell execution, live Git or filesystem mutation, worktree, lease, cleanup, quarantine, retry inspection, persistence, network, GitHub API/CLI runtime behavior, package installation, credentials, MCP/HTTP transport, listener, daemon, hosting, infrastructure, deployment, Workflow Scheduler dispatch, live pilot, concurrency change, or external write. It does not execute candidate #726, and it does not change Scheduler concurrency.

## Validation

From the repository root:

```bash
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

WSC6B2 covered command registry/planning. WSC6B3 covers process execution, worktree, lease, cleanup, and quarantine. WSC6B4A established the truthful public package contract required before #697 added governed local validation composition. #723 adds pre-PR command binding only; authorizing and running the #726 pilot remains a separate decision. Transport, hosting, authentication, credentials, persistence, deployment, and live pilots require later authorization.

Rollback for #723 is reverting the pre-PR branch in `command_planning.py`, the added registry entry, the pre-PR models and selector functions in `scripts/agent_os_remote_validation/`, the added focused rule in `validation_profiles.yml`, the tests, the package exports, this README, and the version and changelog records. This package creates no service, daemon, infrastructure, credential, workflow setting, production data, lease store, evidence store, or external state requiring separate rollback.
