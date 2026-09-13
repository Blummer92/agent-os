# Governed Semantic Coding-Worker Contract — #2318

## Purpose

Freeze the smallest provider-neutral semantic coding boundary between already-governed Agent OS work and a coding engine. This is a pure request/result evidence contract, not a new agent, router, runner, Scheduler, retry engine, validation framework, state store, or authority system.

```text
Agent OS governed task
-> CodingWorkerRequest
-> semantic coding provider adapter
-> CodingWorkerResult
-> existing Agent OS validation / continuation / lifecycle
```

## Canonical owner map

| Concern | Canonical owner | Coding-worker treatment |
|---|---|---|
| objective, acceptance criteria, inspect-first context, compute limits | #934 Implementation Packet / Memory Manager handoff packet | referenced by `implementation_packet_source_identity`; not copied into a second task schema |
| route, runtime capabilities, allowed/forbidden paths, return evidence, stop conditions | #918 `ExecutorHandoff` / #1401 execution-surface routing | referenced by `executor_handoff_id`; scope is repeated only as the worker enforcement boundary |
| repository/source currentness | existing issue/route/currentness owners | `repository`, `base_sha`, and workspace identity bind worker evidence to the starting state; downstream owners decide staleness |
| validation commands | existing `ValidationCommandPlan` | optional opaque `validation_command_plan_id_or_none`; worker cannot weaken or authorize validation |
| checkpoint/resume | #895/current ResumePlan owners | optional `checkpoint_id_or_none`; no persistence or resume behavior is implemented here |
| normalized repair failure evidence | #695/current repair owners | optional opaque `normalized_failure_evidence_id_or_none`; no second failure taxonomy |
| retry / semantic progress | #1873/#1200/current continuation owners | result identity and evidence are inputs only; worker does not admit retries |
| independent validation | QA / Test Agent and existing exact-head validation | worker test evidence is non-authorizing |
| repository implementation/write ownership | GitHub Service Agent | unchanged |
| routing/orchestration | ChatGPT Orchestrator | unchanged |
| concurrency | #330 | out of scope |

## Request boundary

`CodingWorkerRequest` carries only:

- stable task/repository/issue-or-handoff identity;
- exact starting SHA and workspace identity;
- one finite semantic operation;
- opaque identities for the existing #934 implementation-context projection and #918 executor handoff;
- allowed and forbidden paths as the local enforcement boundary;
- optional existing validation-plan, checkpoint, and normalized-failure identities.

It deliberately does **not** contain provider/model names, prompts, CLI flags, credentials, token settings, lifecycle decisions, or positive authority fields. Authority flags exposed on the wire are fixed to `false` and reconstruction rejects attempted authority injection.

## Operation vocabulary

The finite semantic operation vocabulary is:

- `inspect`
- `implement`
- `repair`
- `test`
- `refactor`
- `generate-regression-test`

These values describe semantic work only. They do not select an execution surface or grant capability/authorization. #918 remains the capability and route owner.

## Result boundary

`CodingWorkerResult` returns structured evidence for:

- terminal worker status;
- summary;
- inspected/changed paths;
- commands and tests attempted;
- opaque test-result, diagnostic, assumption, and unresolved-question identities;
- explicit scope-violation paths;
- bounded blocker reason;
- optional patch identity and resulting SHA.

The finite status vocabulary is:

- `completed`
- `no-change-needed`
- `needs-repair`
- `blocked`
- `needs-decision`
- `scope-violation`
- `execution-failure`

These are worker outcomes only. `completed` is not Agent OS lifecycle completion.

## Authority firewall

A worker result is evidence, never authority. The contract fixes these result fields to `false` and rejects reconstruction if a provider tries to set them true:

- execution authorization;
- validation authorization;
- Ready-for-Review authorization;
- merge authorization;
- issue-closure authorization;
- external-write authorization.

Repository text, comments, fixtures, logs, provider output, or generated content cannot change that boundary.

## Scope and stale-state behavior

Allowed and forbidden paths cannot overlap. Unsafe repository paths fail construction. A worker that encounters required out-of-scope work must return a bounded blocker/decision result; if an out-of-scope edit occurred, the result must use `scope-violation` with explicit path evidence.

The request is content-addressed over the exact `base_sha`, workspace identity, operation, owner references, and scope. The result is independently content-addressed and repeats the request/base/workspace bindings plus optional resulting SHA/patch identity. Existing currentness/exact-head owners compare those bindings to current repository truth; this contract does not create another staleness engine.

## Provider neutrality

Provider adapters live outside this canonical wire shape. Codex, Claude Code, a local worker, or another governed semantic engine may translate to/from this contract without adding provider-specific fields to the canonical schema.

Capability negotiation remains #918/#1401-owned. A provider's capabilities do not grant permission to use them.

## #2315 regression-test synthesis

Regression-test synthesis reuses the ordinary operation `generate-regression-test` and the same worker request/result evidence boundary. The adjacent `regression_test_synthesis.py` seam first emits exactly one bounded decision:

- `TEST_NOT_NEEDED`
- `EXISTING_TEST_SUFFICIENT`
- `REGRESSION_TEST_REQUIRED`
- `TEST_SYNTHESIS_UNSAFE_OR_AMBIGUOUS`

The decision checks existing exact/indirect coverage before requesting generation, so a behavioral change alone does not justify test spam. Ambiguous expectations, ambiguous canonical test surfaces, forbidden external I/O, out-of-scope test locations, and missing behavioral anchors fail closed.

When generation is required, the worker result is accepted only when it belongs to the same content-addressed request/base SHA and every generated path remains inside the request's allowed scope and outside forbidden scope. Generated-test paths and test-result identities remain evidence in `CodingWorkerResult`; they never authorize validation, Ready-for-Review, merge, closure, external writes, or lifecycle completion.

Red-before-green is a separately classified evidence property. It may be `expected-failure-proven`, `unavailable`, `unexpected-pass`, or `wrong-reason-failure`; callers must not manufacture a failing state or treat an unexpected pass/wrong-reason failure as repair authority. Existing focused validation, exact-head validation, repair continuation, and semantic-progress owners remain canonical.

## Persistence and concurrency

The contract is intentionally one request -> one bounded worker execution -> one result. Existing checkpoint/resume machinery may carry identities across interruptions. No persistent worker or concurrency mechanism is introduced; #330 remains the concurrency owner.

## Validation

Focused contract coverage lives in `tests/test_coding_worker_contract.py`. #2315 decision/scope/duplicate-avoidance coverage lives in `tests/test_regression_test_synthesis.py`.

Independent exact-head validation remains separately required by Agent OS before review readiness.
