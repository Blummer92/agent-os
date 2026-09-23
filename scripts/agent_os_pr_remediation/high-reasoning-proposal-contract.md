# High-Reasoning Proposal Contract

## Purpose

`high_reasoning_proposal.py` fulfills the existing `high-reasoning-required` compute classification with one bounded proposal-only seam. It consumes frozen caller-supplied evidence and one injected provider-neutral adapter, then deterministically accepts or rejects exactly one `execution` or `repair` proposal.

The capability is planning evidence only. It does not execute commands, edit source, write GitHub, run validation, mutate Ready-for-Review state, merge, close issues, change workflows or credentials, operate production systems, or perform external writes.

## Inputs

`ProposalRequest` binds the proposal to the applicable frozen evidence: repository and issue/PR/invocation identity, exact source and observed SHA, base identity, objective and non-goals, allowed and forbidden paths, required validation, prohibited changes, known blockers, changed-path evidence, the existing compute route, supplied authorization evidence, proposal type, contract versions, source fingerprints, normalized failure/review evidence references, provider capability requirements, and conflicting-human-evidence state.

Malformed inputs are rejected by construction. A non-`high-reasoning-required` route, stale source, missing/stale/ambiguous authorization evidence, or conflicting human evidence prevents provider invocation and fails closed to `needs-decision` or `manual-review`.

## Provider boundary

`ProposalAdapter` is an injected protocol only. The repository contains no provider implementation, credential lookup, network transport, daemon, retry loop, or default vendor. Provider and model identity are retained only as evidence.

Normal tests use deterministic fake adapters. Provider unavailability returns `needs-decision` and never fabricates success.

## Deterministic verification

Provider output is untrusted until all checks succeed. The verifier requires:

- exact supported schema and bounded canonical JSON;
- exact request-fingerprint and proposal-type binding;
- all authority and side-effect fields explicitly false;
- exact repair evidence references for repair proposals;
- frozen non-goals, prohibited changes, blockers, and required validation preserved;
- proposed and step target paths contained in allowed scope and outside forbidden paths;
- structured finite step actions with no shell-like control content or arbitrary command field;
- executor requirements limited to the existing four routes: `chatgpt_connector`, `governed_runner`, `external_fallback`, and `human_decision`;
- explicit rollback, insufficiency, expiry, and invalidation evidence; and
- canonical serialization plus a stable content-derived plan ID.

A malformed, oversized, stale, scope-expanding, authority-inventing, executable, or otherwise conflicting response produces no usable plan.

## Immutability and invalidation

Accepted plans are frozen dataclasses. Their `request_fingerprint` binds all request evidence. `evaluate_plan_currentness()` invalidates the plan when any bound material changes, including source/head, objective/non-goals, scope, changed paths, required tests, blockers, authorization evidence, compute classification, contract versions, source/failure evidence, provider capability requirements, or conflicting human evidence.

A stale plan remains evidence only and is never refreshed into authority.

## Executor compatibility

This capability does not select or add an executor route. It only verifies that proposed route requirements are a subset of the existing four-route ladder. Downstream execution remains separately governed by the canonical executor-routing contract and existing Scheduler / Execution Service lifecycle.

## Validation

Focused validation:

```bash
python -m pytest tests/agent_os_pr_remediation/test_high_reasoning_proposal.py
```

The fixture-first tests cover valid ExecutionPlan and RepairPlan proposals, deterministic identity, no-invocation gates, stale evidence, scope and forbidden-surface violations, fifth-route injection, authority claims, shell/command injection, malformed/oversized/unknown schema output, conflicting human evidence, provider unavailability, evidence/source invalidation, offline dependency boundaries, and exact four-route compatibility.
