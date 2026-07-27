# Agent OS Execution Service — WSC6B1

WSC6B1 is the immutable, pure-local, read-only request and inspection core for a future Agent OS Execution Service. It validates a bounded request, invokes one supplied inspector snapshot at most once, verifies exact repository identities, and returns an immutable result with a redacted public projection.

It does **not** execute commands or authorize later work.

## Public capabilities

- `inspect_repository`
- `verify_repository_state`

An accepted result means only that the supplied read-only request and observation satisfied this package's checks. It does not authorize edits, commands, commits, pushes, pull requests, readiness, merge, deployment, another invocation, or any external mutation.

## Request contract

`ExecutionServiceRequest` is frozen, slotted, keyword-only, and deterministically fingerprinted. Authority-bearing values are explicit:

- schema, request identity, revision, creation, expiry, and caller-supplied evaluation time;
- canonical repository identity and owner/actor identities;
- capability, base branch/SHA, requested ref, and expected SHA;
- sorted non-overlapping allowed and forbidden repository-relative POSIX paths;
- requested file and byte limits bounded by fixed service ceilings;
- evidence visibility and finite invalidation conditions.

Timestamps use canonical UTC seconds (`YYYY-MM-DDTHH:MM:SSZ`). The service never reads the host clock. A request is current only when:

```text
created_at <= evaluated_at < expires_at
```

Exact built-in tuples, strings, integers, enums, and canonical evidence objects are required at the public boundary. Booleans are not accepted as integers. Custom mappings and iterable subclasses are not coerced.

## Fingerprints

Request and result fingerprints use versioned domain-separated canonical JSON and SHA-256. A fingerprint field is excluded from its own payload. Supplying a valid fingerprint copied from altered content fails construction.

Request fingerprints bind the complete authority contract. Result fingerprints bind the evaluated request identity, status, finite reasons, observed identities and counts, evidence retained by policy, public summary, and the literal `side_effects_performed=false` invariant.

## Inspector boundary

`RepositoryInspector` is injected. The service:

1. fully validates the request before inspection;
2. invokes `inspect(request)` zero times for rejected requests and at most once for valid requests;
3. performs no retry or fallback scan;
4. accepts only one exact immutable `RepositoryInspectionObservation`;
5. recomputes file and byte counts from immutable file records;
6. rejects the whole observation on malformed, contradictory, stale, unauthorized, or excessive evidence.

The inspector cannot expand owner, actor, capability, path, ref, SHA, limit, expiry, visibility, reason, status, or fingerprint authority.

Ordinary inspector failures return a fixed `service_unavailable` result without exception text. `KeyboardInterrupt`, `SystemExit`, and `GeneratorExit` propagate.

## Canonical repository-state reuse

State verification reuses the public contracts from `scripts.agent_os_execution_capabilities`:

- `RepositoryIdentity`
- `RepositoryStateEvidence`
- `RepositoryStateValidationResult`
- `validate_repository_state_evidence`

Only an already canonical `RepositoryStateEvidence` object is delegated. Raw mappings and custom objects are never passed to the canonical validator. Applicable expected repository, base ref/SHA, head ref/SHA, requested SHA, and contract-fingerprint bindings are supplied explicitly. Acceptance requires the canonical validator outcome `valid`; detailed internal reasons are mapped into WSC6B1's smaller public reason vocabulary.

## Evidence and public projection

Private evidence is held only in immutable in-memory records, is excluded from ordinary representations, and is retained in a result only when the request uses `include-private`. There is no private evidence locator and no durable evidence store.

`project_public_result()` uses an explicit allowlist. It does not use `dataclasses.asdict()` or generic recursive serialization. Private evidence and raw exceptions are excluded. The generated public summary is bounded and rescanned for secret-like markers.

No raw JSON parser is exposed by WSC6B1.

## Fixed ceilings

The package defines fixed ceilings for:

- path count and path length;
- inspected file count and total inspected bytes;
- evidence item count, per-item bytes, and total evidence bytes;
- text length and reason count.

Requested limits must be positive exact integers and cannot exceed the service ceilings. These are deterministic contract limits; they are **not** CPU or memory enforcement.

## Explicit non-capabilities

WSC6B1 contains no:

- subprocess, shell, executable, argv, or environment handling;
- process runner or command registry;
- live Git or filesystem mutation;
- worktree, lease, cleanup, or quarantine composition;
- retry or fallback inspection;
- persistence or evidence store;
- network, GitHub API/CLI, package installation, credentials, or secrets;
- MCP/HTTP transport, listener, daemon, hosting, infrastructure, or deployment;
- Workflow Scheduler dispatch, live pilot, concurrency change, or external write.

CPU and memory enforcement are not claimed.

## Validation

From the repository root:

```bash
PYTHONPATH=08_Tooling/agent-os-execution-service/src \
  python -m pytest \
  08_Tooling/agent-os-execution-service/tests/test_request_validation.py \
  08_Tooling/agent-os-execution-service/tests/test_read_only_service.py -q

python -m compileall -q \
  08_Tooling/agent-os-execution-service/src \
  08_Tooling/agent-os-execution-service/tests

python -m pytest \
  08_Tooling/workflow-scheduler/tests/test_single_issue_pilot.py \
  08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py -q

bash 07_Agent_Tests/validate-repo-structure.sh
./scripts/validate-all.sh
```

## Deferred phases

- WSC6B2: command registry and command planning
- WSC6B3: process execution, worktree, lease, cleanup, and quarantine composition
- Later authorization: transport, hosting, authentication, credentials, persistence, deployment, and live pilot work

Do not create or begin those phases until WSC6B1 is reviewed and merged under separate authorization.

## Rollback

Revert the isolated `08_Tooling/agent-os-execution-service/` package. WSC6B1 creates no service, daemon, infrastructure, credential, workflow, setting, lease store, evidence store, production data, or external state that requires separate rollback.
