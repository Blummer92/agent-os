# Advisory Evidence Shadow-Pilot Operator Guide

Status: governed operator guidance for GEX4B  
Parent: #573 · Implementation: #574 / PR #576 / `974866e8c6be7418b931aa33e0420d9ce0d1d98b` · Publication: #240 · Gate: #560

## Purpose and authority
This guide governs review of GEX4A advisory-render evidence during a bounded shadow pilot. The pilot reviews evidence only; it does not execute commands, publish GitHub state, authorize implementation or merge, prove freshness or provenance, verify attestation, or change Scheduler concurrency. Canonical code: `scripts/agent_os_remote_validation/advisory_render.py`.

## Canonical API and workflow
Public API: `AdvisoryRenderResult`, `render_advisory_evidence(...)`, `observe_advisory_evidence_shadow(...)`, `serialize_advisory_render_result(...)`, and `advisory_render_result_id(...)`.

`render_advisory_evidence(...)` accepts one canonical `AdvisoryEvidenceResult`, not mappings, logs, event payloads, free-form JSON, or live responses. It serializes through `serialize_advisory_evidence_result(...)`, recomputes identity with `advisory_evidence_result_id(...)`, and rejects disagreement.

1. Obtain canonical GEX3 evidence.
2. Confirm repository, PR, and revision identities.
3. Render and verify the render ID.
4. Review fields and ordered lines without reclassification.
5. Confirm every non-authority notice.
6. Record only evidence authorized by the active handoff.
7. Stop on identity, revision, ordering, authority, or scope uncertainty.

`observe_advisory_evidence_shadow(...)` accepts a tuple, rejects duplicate advisory-result identities, and returns deterministic in-memory observations. It is not a live repository observation or execution result.

## Fields, ordering, and SHA roles
The render preserves advisory ID/status; repository/PR identity; base branch; base, source-head, and tested SHAs; plan/bundle IDs; runner/invocation IDs; ordered command-result IDs/statuses; bounded reasons; and bounded details. Do not reorder result IDs or statuses.

- **Base SHA:** target-branch evaluation base.
- **Source-head SHA:** exact proposed source revision.
- **Tested SHA:** exact validated revision, including a governed synthetic merge when applicable.

A passing status never repairs a SHA-role mismatch.

## Status interpretation
| Status | Required interpretation |
|---|---|
| `passed` | Bound canonical checks passed; nothing further is authorized. |
| `failed` | A supplied command result failed; stop and review governed validation evidence. |
| `incomplete` | Required evidence is missing; missing is neither failure nor pass. |
| `stale` | Evidence does not match explicit current revisions; timestamps cannot clear it. |
| `invalid` | Evidence is malformed, inconsistent, or mixed; treat it as unusable. |
| `needs-decision` | Human or governed policy review is required; record bounded reasons and escalate. |

Operators must not promote, downgrade, combine, or reinterpret these statuses.

## Exact non-authority notices
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
The notices may not be deleted, reordered, rewritten, or treated as optional. Hashes and semantic IDs bind content only; they do not prove producer identity, trusted environment, currentness, authentication, provenance, attestation, implementation authorization, or merge authorization. Timestamps do not prove freshness.

## Recording, publication, and storage
Record only evidence required by the governed handoff: advisory/render IDs; status; repository/PR identity; three SHA roles; plan, bundle, runner, and invocation IDs; ordered result IDs/statuses; bounded reasons; independently verified workflow run IDs; and notice integrity.

Do not record raw diagnostics, stdout/stderr, environment data, headers, tokens, credentials, unrelated logs, or publication prose.

Issue #240 solely owns Cloud Build routing and GitHub publication, including build lookup, PR resolution, comments, checks, statuses, labels, artifacts, deduplication, credentials, and API writes. Renderer reuse does not transfer ownership.

The pilot introduces no database, cache, archive, log store, or second source of truth. Keep only minimal evidence in the authorized GitHub issue or PR.

## Stop, escalation, and rollback
Route to `status:needs-decision` when identity cannot be verified; repository/PR/SHA identity is stale, mixed, or unclear; ordered results disagree; reclassification is requested; a notice changes; diagnostics, secrets, environment data, or publication prose appear; live reads, writes, persistence, execution, Cloud Build, or Scheduler are required; work overlaps #240; #560's contract must change; or concurrency must exceed `0`.

On stop, preserve exact IDs, record the bounded mismatch, halt publication/execution/merge/Scheduler progression, notify the issue owner, and create a focused follow-up only for a canonical API or governance decision.

For documentation defects, revert the guide merge. For renderer defects, revert GEX4A and keep #560 blocked. Rollback authorizes neither retry nor concurrency increase.

## Evidence checklist before rerunning #560
- [ ] #574 / PR #576 is merged at `974866e8c6be7418b931aa33e0420d9ce0d1d98b` or a verified descendant.
- [ ] Input is canonical and its serializer and result-ID API agree.
- [ ] The render serializer or render-ID API verifies the render ID.
- [ ] Status is one of the six canonical values and is not reclassified.
- [ ] Repository and PR identities match the intended candidate.
- [ ] Base, source-head, and tested SHAs retain distinct meanings.
- [ ] Plan, bundle, runner, and invocation identities match supplied evidence.
- [ ] Command-result IDs and statuses retain canonical order.
- [ ] Reasons/details are bounded and match the verified payload.
- [ ] All exact non-authority notices remain unchanged.
- [ ] No timestamp proves freshness and no hash/ID is called authentication, provenance, or attestation.
- [ ] No diagnostics, secrets, credentials, environment data, or publication prose is present.
- [ ] GEX4 introduced no live read, persistence, execution, Cloud Build, Scheduler, or external write.
- [ ] #240 remains publication owner.
- [ ] The current #560 contract is freshly reviewed against current `main`.
- [ ] Scheduler concurrency remains `0`.

This checklist supports a fresh #560 gate review. It does not authorize #560 implementation or a real Scheduler pilot.
