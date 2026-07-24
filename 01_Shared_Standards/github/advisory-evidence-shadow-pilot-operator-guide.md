# Advisory Evidence Shadow-Pilot Operator Guide

Status: governed operator guidance for GEX4B  
Parent planning issue: #573  
Completed implementation: #574 / PR #576 / merge `974866e8c6be7418b931aa33e0420d9ce0d1d98b`  
Publication owner: #240  
Downstream gate: #560

## Purpose and authority boundary

This guide governs review of GEX4A advisory-render evidence during a bounded shadow pilot. The pilot is evidence review only. It does not execute commands, publish GitHub state, authorize implementation or merge, prove freshness or provenance, verify attestation, or change Scheduler concurrency.

The canonical implementation is `scripts/agent_os_remote_validation/advisory_render.py`.

## Canonical API and input verification

The merged API is:

- `AdvisoryRenderResult`
- `render_advisory_evidence(...)`
- `observe_advisory_evidence_shadow(...)`
- `serialize_advisory_render_result(...)`
- `advisory_render_result_id(...)`

`render_advisory_evidence(...)` accepts one canonical `AdvisoryEvidenceResult`, not mappings, logs, event payloads, free-form JSON, or live repository responses. Before rendering, it serializes through `serialize_advisory_evidence_result(...)`, recomputes identity through `advisory_evidence_result_id(...)`, and rejects disagreement. Operators must not bypass this boundary.

## Shadow-pilot workflow

1. Obtain a canonical GEX3 `AdvisoryEvidenceResult`.
2. Confirm repository, pull request, and revision identities.
3. Render with `render_advisory_evidence(...)`.
4. Verify with `serialize_advisory_render_result(...)` or `advisory_render_result_id(...)`.
5. Review structured fields and ordered lines without reclassification.
6. Confirm every non-authority notice.
7. Record only evidence authorized by the active GitHub handoff.
8. Stop on any identity, revision, ordering, authority, or scope uncertainty.

`observe_advisory_evidence_shadow(...)` accepts a tuple of canonical results, rejects duplicate advisory-result identities, and returns deterministic in-memory observations. It is not a live repository observation or execution result.

## Rendered fields and revision roles

The render preserves advisory result ID and status; repository and pull-request identity; base branch; base, source-head, and tested SHAs; plan and bundle IDs; runner and invocation IDs; ordered command-result IDs and terminal statuses; bounded reason codes; and bounded details.

Do not reorder command-result IDs or statuses. Their order is evidence.

- **Base SHA:** target-branch revision used as the evaluation base.
- **Source-head SHA:** exact source-branch revision proposed by the change.
- **Tested SHA:** exact revision validated by supplied evidence; it may be the source head or a governed synthetic merge revision.

A passing status never repairs a mismatch among these roles.

## Status interpretation

The renderer preserves the canonical GEX3 status. Operators must not promote, downgrade, combine, or reinterpret it.

| Status | Operator meaning and action |
|---|---|
| `passed` | Canonical checks passed for the bound identities and revisions. This authorizes nothing further. |
| `failed` | At least one supplied command result failed. Stop and inspect governed validation evidence. |
| `incomplete` | Required result evidence is absent or incomplete. Stop; missing is neither failed nor passed. |
| `stale` | Evidence no longer matches explicitly supplied current revisions or is canonically stale. Timestamps cannot clear it. |
| `invalid` | Evidence is malformed, inconsistent, or mixed across identities or runs. Treat it as unusable. |
| `needs-decision` | Human or governed policy review is required. Record bounded reasons and escalate to the issue owner. |

## Exact non-authority notices

Every valid render includes, in this order:

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

These notices may not be deleted, reordered, rewritten, or treated as optional.

A hash or semantic ID is a deterministic content binding only. It does not prove producer identity, execution environment, currentness, authentication, provenance, attestation, implementation authorization, or merge authorization. Timestamps also do not prove freshness; freshness requires explicit comparison with current revision identities.

## Permitted recording

Record only evidence explicitly required by the governed handoff, such as advisory and render IDs; status; repository and PR identity; three SHA roles; plan, bundle, runner, and invocation IDs; ordered result IDs and statuses; bounded reason codes; independently verified workflow run IDs; and confirmation that all notices remained intact.

Do not copy raw diagnostics, stdout, stderr, environment data, headers, tokens, credentials, unrelated logs, or arbitrary publication prose.

## #240 publication boundary

Issue #240 remains the sole owner of Cloud Build result routing and GitHub PR publication. GEX4 does not own build lookup, PR resolution, comments, checks, statuses, labels, artifacts, deduplication, GitHub credentials, or API writes.

A future #240 implementation may reuse the pure renderer. Reuse does not transfer routing or publication ownership to GEX4.

## Storage, stopping, and escalation

The shadow pilot introduces no database, cache, archive, log store, or second source of truth. Keep only minimal evidence in the canonical GitHub issue or PR location authorized by the active handoff.

Stop and route to `status:needs-decision` when:

- advisory or render identity cannot be verified;
- repository, PR, or SHA identity is missing, stale, mixed, or unclear;
- ordered result IDs and statuses disagree;
- status reclassification is requested;
- a non-authority notice is missing, reordered, or altered;
- diagnostics, credentials, secrets, environment data, or publication prose appear;
- live reads, external writes, persistence, execution, Cloud Build, or Scheduler are required;
- work overlaps #240 publication ownership;
- #560 evidence would require changing #560's contract;
- Scheduler concurrency would need to exceed `0`.

On stop: preserve exact IDs, record the bounded mismatch, halt publication/execution/merge/Scheduler progression, notify the issue owner, and create a focused follow-up only when a canonical API or governance decision is required.

## Rollback

For documentation defects, revert the focused guide merge. For a renderer defect, revert the focused GEX4A merge and keep #560 blocked. Rollback does not authorize retry or concurrency increase.

## Evidence checklist before rerunning the #560 gate

Do not rerun the #560 gate until all items are directly evidenced:

- [ ] #574 / PR #576 is merged at `974866e8c6be7418b931aa33e0420d9ce0d1d98b` or a verified current-`main` descendant.
- [ ] Input is a canonical `AdvisoryEvidenceResult`.
- [ ] `serialize_advisory_evidence_result(...)` and `advisory_evidence_result_id(...)` agree.
- [ ] `serialize_advisory_render_result(...)` or `advisory_render_result_id(...)` verifies the render ID.
- [ ] Status is one of the six canonical values and is not reclassified.
- [ ] Repository and pull-request identities match the intended candidate.
- [ ] Base, source-head, and tested SHAs retain distinct meanings.
- [ ] Plan, bundle, runner, and invocation identities match supplied evidence.
- [ ] Command-result IDs and terminal statuses retain canonical order.
- [ ] Reason codes and details are bounded and match the verified render payload.
- [ ] All exact non-authority notices remain unchanged.
- [ ] No timestamp is used as freshness proof.
- [ ] No hash or ID is described as authentication, provenance, or attestation.
- [ ] No diagnostics, stdout, stderr, secrets, credentials, environment data, or publication prose is present.
- [ ] GEX4 introduced no live read, persistence, command execution, Cloud Build execution, Scheduler execution, or external write.
- [ ] #240 remains the publication owner.
- [ ] The current #560 contract is freshly reviewed against current `main`.
- [ ] Scheduler concurrency remains `0`.

Completing this checklist supports a fresh #560 gate review. It does not authorize #560 implementation or a real Scheduler pilot.
