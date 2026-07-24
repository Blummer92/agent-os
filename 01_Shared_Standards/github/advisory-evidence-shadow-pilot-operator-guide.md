# Advisory Evidence Shadow-Pilot Operator Guide

Status: governed operator guidance for GEX4B

Parent planning issue: #573  
Completed implementation: #574 / PR #576 / merge `974866e8c6be7418b931aa33e0420d9ce0d1d98b`  
Related publication roadmap: #240  
Downstream gate: #560

## Purpose

This guide explains how an operator reviews GEX4A advisory-render evidence during a bounded shadow pilot.

The shadow pilot is evidence review only. It does not execute implementation commands, publish GitHub status, authorize work, authorize merge, prove freshness, prove provenance, verify attestation, or change Scheduler concurrency.

The canonical implementation lives in `scripts/agent_os_remote_validation/advisory_render.py`.

## Canonical API

The merged public API is:

- `AdvisoryRenderResult`
- `render_advisory_evidence(...)`
- `observe_advisory_evidence_shadow(...)`
- `serialize_advisory_render_result(...)`
- `advisory_render_result_id(...)`

`render_advisory_evidence(...)` accepts one canonical `AdvisoryEvidenceResult`. Arbitrary mappings, logs, event payloads, free-form JSON, and live repository responses are not valid inputs.

Before rendering, the implementation:

1. serializes the GEX3 advisory result through `serialize_advisory_evidence_result(...)`;
2. recomputes its identity through `advisory_evidence_result_id(...)`;
3. rejects the input when the serialized result ID and recomputed result ID disagree.

An operator must not bypass this verification boundary.

## Shadow-pilot workflow

1. Obtain a canonical `AdvisoryEvidenceResult` produced by the governed GEX3 path.
2. Confirm the result is associated with the intended repository and pull request.
3. Render it with `render_advisory_evidence(...)`.
4. Verify the render through `serialize_advisory_render_result(...)` or `advisory_render_result_id(...)`.
5. Review the structured fields and ordered operator-readable lines.
6. Apply the status interpretation in this guide without reclassifying the result.
7. Check every trust-boundary notice.
8. Record only the minimal evidence authorized by the current GitHub issue or PR handoff.
9. Stop when any identity, revision, status, ordering, authority, or scope check is uncertain.

`observe_advisory_evidence_shadow(...)` accepts a tuple of canonical advisory results and returns deterministic in-memory render observations. It rejects duplicate advisory-result identities. Its output is not a live repository observation and is not execution evidence.

## Rendered evidence fields

The render preserves these fields from canonical GEX3 evidence:

- advisory result ID;
- advisory status;
- repository identity;
- pull-request number;
- base branch;
- base SHA;
- source-head SHA;
- tested SHA;
- validation plan ID;
- validation evidence bundle ID;
- runner ID;
- invocation ID;
- ordered command-result IDs;
- ordered command-result terminal statuses;
- bounded reason codes;
- bounded details.

The operator-readable lines are ordered. Do not reorder command-result IDs or terminal statuses. Their order is evidence.

## Revision roles

The three SHA roles are separate and must never be collapsed:

- **Base SHA:** the target branch revision used as the evaluation base.
- **Source-head SHA:** the exact source branch revision proposed by the change.
- **Tested SHA:** the exact revision validated by the supplied evidence. It may equal the source head or may represent a governed synthetic merge revision.

A passing status does not repair a mismatch between these roles. Any unexpected mismatch requires a stop and escalation.

## Status interpretation

The renderer preserves the canonical GEX3 status. Operators must not promote, downgrade, reinterpret, or combine statuses.

### `passed`

The supplied canonical evidence satisfied the GEX3 advisory checks for the bound identities and revisions.

It does not authorize implementation, execution, publication, merge, another run, or a Scheduler concurrency change.

### `failed`

At least one supplied command result ended in a canonical failure state.

Stop progression. Review the bound command-result IDs and statuses through the governed validation evidence. Do not infer missing diagnostics from the render.

### `incomplete`

Required command-result evidence is absent or incomplete.

Stop progression. Missing evidence is not equivalent to failure and is never equivalent to pass.

### `stale`

The advisory evidence no longer matches an explicitly supplied current revision or carries canonical stale evidence.

Stop progression. Timestamps cannot clear staleness. Only fresh evidence bound to explicit current revisions can do so.

### `invalid`

The evidence is malformed, internally inconsistent, mixed across identities or runs, or otherwise fails canonical validation.

Stop progression and treat the evidence as unusable. Do not select a convenient subset of an invalid result.

### `needs-decision`

The canonical evidence requires human or governed policy review, such as manual-review selection or unavailable infrastructure evidence.

Stop automated progression. Record the bounded reason codes and escalate to the issue owner identified by the governing handoff.

## Trust and authority boundaries

Every valid render includes exact non-authority notices:

```text
advisory_only=true
authoritative=false
implementation_authorized=false
execution_authorized=false
merge_authorized=false
attestation_verified=false
freshness_proven=false
provenance_verified=false
side_effects_performed=false
```

These notices are part of the deterministic render contract and may not be deleted, reordered, or rewritten.

A hash or semantic ID provides deterministic content binding only. It does not prove:

- who produced the evidence;
- where the evidence was produced;
- that the environment was trusted;
- that the evidence is current;
- that an attestation was verified;
- that implementation or merge is authorized.

Timestamps are recorded evidence fields elsewhere in the validation chain, but they do not prove freshness. Freshness requires explicit comparison against current revision identities.

## Permitted operator recording

An operator may record only evidence explicitly required by the current governed handoff, typically:

- exact advisory result ID;
- exact render ID;
- status;
- repository and pull-request identity;
- base, source-head, and tested SHAs;
- plan and bundle IDs;
- runner and invocation IDs;
- ordered command-result IDs and statuses;
- bounded reason codes;
- exact workflow run IDs or check outcomes when independently verified;
- the fact that all non-authority notices remained intact.

Do not copy raw command diagnostics, stdout, stderr, environment data, headers, tokens, credentials, or unrelated logs into the render record.

## Publication boundary

Issue #240 remains the canonical owner of Cloud Build result routing and GitHub PR publication.

GEX4 does not own:

- build lookup;
- pull-request resolution;
- comment creation or updating;
- check-run or commit-status publication;
- label mutation;
- artifact publication;
- publication deduplication;
- GitHub credentials or API writes.

A future #240 implementation may reuse the pure renderer. That does not transfer routing or publication ownership to GEX4.

## Storage and retention

The shadow pilot introduces no database, cache, artifact archive, log store, or second source of truth.

Keep evidence only in the canonical GitHub issue or PR location explicitly authorized by the current handoff. Do not create persistent storage merely to retain render output.

## Stop conditions

Stop and route to `status:needs-decision` when any of these conditions occurs:

- the advisory result ID cannot be verified;
- the render ID cannot be verified;
- repository or pull-request identity is wrong or unclear;
- base, source-head, or tested SHA is missing, stale, or unexpectedly mixed;
- ordered result IDs and statuses disagree;
- the status is unsupported or an operator is asked to reclassify it;
- an authority notice is missing, reordered, or altered;
- diagnostics, credentials, secrets, environment data, or arbitrary publication prose appear;
- live reads, external writes, persistence, command execution, Cloud Build execution, or Scheduler execution are required;
- the task overlaps #240 publication ownership;
- the evidence needed for #560 would require changing #560's implementation contract;
- Scheduler concurrency would need to increase above `0`.

## Escalation

1. Preserve the exact advisory and render IDs.
2. Record the exact mismatch or missing evidence without adding authority claims.
3. Stop publication, execution, merge, and Scheduler progression.
4. Notify the owner named in the active issue contract.
5. Use a focused follow-up issue when a canonical API or governance decision is required.
6. Do not patch around a failed identity or trust-boundary check in documentation or operator prose.

## Rollback

The renderer and shadow observation path are pure-local and stateless.

For documentation defects, revert the focused documentation merge. For a future renderer defect, revert the focused GEX4A merge and keep #560 blocked. No retry or concurrency increase is implied by rollback.

## Evidence checklist before rerunning the #560 gate

Do not rerun the #560 gate until all items below are directly evidenced:

- [ ] #574 / PR #576 is merged at `974866e8c6be7418b931aa33e0420d9ce0d1d98b` or a verified current-`main` descendant.
- [ ] The input is a canonical `AdvisoryEvidenceResult`.
- [ ] `serialize_advisory_evidence_result(...)` and `advisory_evidence_result_id(...)` agree before rendering.
- [ ] `serialize_advisory_render_result(...)` or `advisory_render_result_id(...)` verifies the render ID.
- [ ] The status is one of `passed`, `failed`, `incomplete`, `stale`, `invalid`, or `needs-decision` and has not been reclassified.
- [ ] Repository identity and pull-request number match the intended candidate.
- [ ] Base SHA, source-head SHA, and tested SHA are present and retain distinct meanings.
- [ ] Plan ID and validation evidence bundle ID are present when required by the canonical result.
- [ ] Runner ID and invocation ID match the supplied validation evidence.
- [ ] Command-result IDs and terminal statuses retain their canonical order.
- [ ] Reason codes and details remain bounded and match the verified render payload.
- [ ] All exact non-authority notices remain present and unchanged.
- [ ] No timestamp is used as freshness proof.
- [ ] No hash or ID is described as provenance, authentication, or attestation.
- [ ] No raw diagnostics, stdout, stderr, secrets, credentials, environment data, or arbitrary publication prose is present.
- [ ] No live repository read, persistent storage, command execution, Cloud Build execution, Scheduler execution, or external write was introduced by GEX4.
- [ ] #240 remains the owner of any future Cloud Build-to-PR publication.
- [ ] The current #560 issue contract has been freshly reviewed against current `main`.
- [ ] Scheduler concurrency remains `0`.

Completion of this checklist is evidence for a fresh #560 gate review. It is not authorization to implement #560 or execute a real Scheduler pilot.
