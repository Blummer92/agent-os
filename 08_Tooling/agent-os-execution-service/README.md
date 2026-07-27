# Agent OS Execution Service — WSC6B1

WSC6B1 is the immutable, pure-local, read-only request and inspection core for a future Agent OS Execution Service. It validates a bounded request, invokes one supplied inspector snapshot at most once, verifies exact repository identities, and returns an immutable result with a redacted public projection. It does **not** execute commands or authorize later work.

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

WSC6B2 covers command registry/planning. WSC6B3 covers process execution, worktree, lease, cleanup, and quarantine. Transport, hosting, authentication, credentials, persistence, deployment, and live pilots require later authorization. Do not begin those phases until WSC6B1 is reviewed and merged.

Rollback is reverting the isolated `08_Tooling/agent-os-execution-service/` package. WSC6B1 creates no service, daemon, infrastructure, credential, workflow setting, production data, lease store, evidence store, or external state requiring separate rollback.
