# Agent OS Execution Service — WSC6B1 (package contract: WSC6B4A)

WSC6B1 is the immutable, pure-local, read-only request and inspection core for a phased Agent OS Execution Service. It validates a bounded request, invokes one supplied inspector snapshot at most once, verifies exact repository identities, and returns an immutable result with a redacted public projection. It does **not** execute commands or authorize later work in this package version.

This package is phased. A later, separately authorized composition layer (tracked as #697) may consume:

- an exact `ExecutionServiceRequest`;
- an exact `ValidationCommandPlan`;
- caller-supplied execution authorization;
- caller-supplied Workflow Scheduler runtime configuration;
- the canonical Workflow Scheduler validation-only runtime;
- the exact retained `FrozenTestValidationResult`.

Any later validation execution built on this contract must:

- use only exact fixed argv already bound by `ValidationCommandPlan`;
- remain local and bounded;
- run each command at most once;
- introduce no retry;
- publish nothing;
- reuse the existing Workflow Scheduler lease, worktree, validation, containment, cleanup, release, quarantine, and evidence-return lifecycle instead of creating a new one.

Validation-only mode, as exposed by the current Workflow Scheduler contract this package may later consume, supplies no executor, supplies no executor argv, constructs no `PosixProcessExecutor`, and creates no no-op or synthetic executor.

Execution authorization, command execution, validation success, review status, Ready-for-Review, and merge authorization are and remain separate states; no version of this package contract collapses them.

This issue (WSC6B4A) changes package contract and documentation only. It adds no executable composition function, and continues to leave unsupported: AI invocation or repair prompting, retries, issue selection/scheduling/concurrency, persistence, credentials or network access, package installation, GitHub/workflow/provider mutation, deployment, merge, and production writes.

## Public capabilities and authority boundary

- `inspect_repository`
- `verify_repository_state`

An accepted result means only that the supplied request and observation satisfied this package's checks. It does not authorize edits, commands, commits, pushes, pull-request readiness, merge, deployment, another invocation, or external mutation.

## Request and fingerprint contracts

`ExecutionServiceRequest` is frozen, slotted, keyword-only, and deterministically fingerprinted. It binds schema, request identity and revision, canonical UTC creation/expiry, repository and actor identities, capability, base/ref/SHA identities, sorted non-overlapping repository-relative POSIX paths, bounded inspection limits, evidence visibility, and finite invalidation conditions.

The caller supplies `evaluated_at`; the service never reads the host clock. A request is current only when `created_at <= evaluated_at < expires_at`.

Exact built-in tuples, strings, integers, enums, and canonical evidence objects are required. Booleans are not integers, and custom mappings or iterable subclasses are not coerced.

Request and result fingerprints use versioned domain-separated canonical JSON and SHA-256. Each fingerprint field is excluded from its own payload, and copied fingerprints on altered content fail validation.

## Inspector and repository-state boundaries

`RepositoryInspector` is injected. The service validates before inspection, invokes `inspect(request)` zero times for rejected requests and at most once otherwise, performs no retry or fallback scan, accepts one exact immutable observation, recomputes file and byte counts, and rejects the whole observation when evidence is malformed, contradictory, stale, unauthorized, or excessive.

Ordinary inspector failures return bounded `service_unavailable` results without raw exception text. `KeyboardInterrupt`, `SystemExit`, and `GeneratorExit` propagate.

State verification reuses public contracts from `scripts.agent_os_execution_capabilities`: `RepositoryIdentity`, `RepositoryStateEvidence`, `RepositoryStateValidationResult`, and `validate_repository_state_evidence`.

Only canonical `RepositoryStateEvidence` objects are delegated. Raw mappings and custom objects are never passed to the canonical validator. Expected repository, base ref/SHA, head ref/SHA, requested SHA, and contract fingerprint are supplied explicitly. Acceptance requires canonical outcome `valid`.

## Evidence, projection, and ceilings

Private evidence remains in immutable memory records, is excluded from ordinary representations, and is retained only under `include-private`. There is no locator or durable evidence store.

`project_public_result()` uses an explicit allowlist, not generic recursive serialization. Private evidence and raw exceptions are excluded; public summaries are bounded and rescanned for secret-like markers. No raw JSON parser is exposed.

Fixed ceilings cover path count/length, inspected file count/bytes, evidence item count and bytes, text length, and reason count. Requested limits must be positive exact integers within those ceilings. These are deterministic contract limits, not CPU or memory enforcement.

## Explicit non-capabilities

WSC6B1 contains no command registry, subprocess or shell execution, live Git or filesystem mutation, worktree, lease, cleanup, quarantine, retry inspection, persistence, network, GitHub API/CLI runtime behavior, package installation, credentials, MCP/HTTP transport, listener, daemon, hosting, infrastructure, deployment, Workflow Scheduler dispatch, live pilot, concurrency change, or external write.

## Validation

From the repository root:

```bash
PYTHONPATH=08_Tooling/agent-os-execution-service/src python -m pytest \
  08_Tooling/agent-os-execution-service/tests/test_request_validation.py \
  08_Tooling/agent-os-execution-service/tests/test_read_only_service.py -q
python -m compileall -q 08_Tooling/agent-os-execution-service/src \
  08_Tooling/agent-os-execution-service/tests
python -m pytest 08_Tooling/workflow-scheduler/tests/test_single_issue_pilot.py \
  08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py -q
bash 07_Agent_Tests/validate-repo-structure.sh
./scripts/validate-all.sh
```

## Deferred phases and rollback

WSC6B2 covers command registry/planning. WSC6B3 covers process execution, worktree, lease, cleanup, and quarantine. WSC6B4A (this update) establishes the truthful public package contract and version required before #697 may add governed local validation composition; it adds no executable composition itself. Transport, hosting, authentication, credentials, persistence, deployment, and live pilots require later authorization. Do not begin execution composition until this package contract is reviewed and merged and a separate implementation issue is explicitly authorized.

Rollback is reverting the README, package metadata version, runtime version constant, changelog entry, and module-version entry changed by WSC6B4A. This package creates no service, daemon, infrastructure, credential, workflow setting, production data, lease store, evidence store, or external state requiring separate rollback.
