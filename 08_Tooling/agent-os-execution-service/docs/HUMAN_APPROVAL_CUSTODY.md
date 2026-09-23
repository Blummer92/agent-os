# Production human-approval custody (#1982 / #1985)

Issue #1982 composes two separately authorized inputs without creating a second approval or persistence system. Issue #1985 additively extends the same Option-C evidence family so the pre-validation plan can be reconstructed in a fresh process without requiring validation evidence first.

## Option C — candidate-preparer provenance

Before human approval, the candidate-preparation boundary may persist one exact `CandidateApprovalProvenanceEvidence` in the existing `pre-publication-producer-evidence` namespace under the trusted checkpoint-store root. The evidence creates no approval, execution, publication, GitHub-write, merge, or external-write authority.

Legacy schema v1.0 contains the complete verified `APPROVAL_READY` `CandidatePacket` and exact `ApprovalCandidateContext`. Existing v1.0 records remain readable and retain their original content-addressed identity.

Schema v2.0 is additive. When the exact canonical `RepositoryProposalStageResult` is supplied at the pre-approval boundary, v2.0 retains that canonical stage payload alongside the same packet/context. This is the minimum current canonical object #753 needs to rebuild approval applicability/projection without reconstructing proposal, IssuePlan, repository, or planning evidence from hashes. The existing canonical serializer/reconstructor verifies the nested stage material, and the outer evidence identity binds it content-addressedly.

The candidate-preparer provenance remains deliberately distinct from the later repository-owner decision. The later approver cannot be used to reconstruct or replace `ApprovalCandidateContext`, proposal/currentness evidence, or the retained canonical proposal stage.

## Option A — repository-owner human decision

The later human decision is reacquired from the existing complete GitHub issue-comment snapshot. Only this exact fixed command is eligible:

```text
/agent-os approve-candidate pre-publication-evidence:<64 lowercase hex>
```

The comment must be authored by the repository owner. Ordinary prose, labels, reviews, Scheduler state, execution authorization, partial comment snapshots, extra tokens, approval JSON, arbitrary JSON, shell, argv, credentials, store paths, and caller-supplied authority booleans do not approve anything.

The trusted comment provenance becomes one typed `ApprovalDecision`: the repository owner is the authorizer, the immutable comment ID is the decision identity, and GitHub `created_at` is the decision time. #753 remains the approval/applicability owner and still rejects self-approval when candidate preparer and human approver are the same.

## Fresh-process pre-validation reconstruction (#1985)

`prepare_fresh_pre_validation(...)` accepts only v2.0 Option-C evidence, the separately reacquired `ApprovalDecision`, explicit `PreValidationCandidateInputs`, and evaluation/projection timestamps. It verifies the retained proposal/IssuePlan/repository/planning identities against the persisted `APPROVAL_READY` packet before doing anything else.

It then delegates to existing owners in this order:

```text
v2 Option-C evidence
-> verify packet/stage/currentness bindings
-> #753 prepare_approval_projection(...)
-> require COMPLETE projection
-> #1985 prepare_pre_validation_stage(...)
-> canonical PR-less PrePrValidationPlan
```

No hashes are treated as reconstructable payloads. No approval/proposal/projection identity is fabricated. A v1.0 record fails closed for this fresh-process route because it intentionally lacks the canonical stage material. Nested-stage tamper, packet/stage identity drift, repository-evidence mismatch, incomplete projection, or pre-validation-plan rejection all fail closed.

This seam does not bypass readiness generally. It reuses exact canonical material that was already proven at the pre-approval boundary so the first-run validation evidence can be produced without recursively requiring itself.

## Production custody composition

`produce_human_approval_custody(...)` continues to load Option-C provenance, reacquire the Option-A owner decision, rerun the canonical candidate pipeline against current supplied readers/observations, require a complete verified `EXECUTION_CANDIDATE`, and prove source/IssuePlan/planning/repository/proposal/approval-candidate identities still match the pre-approval packet. It then delegates to existing #1978 `build_approval_custody_evidence(...)` and `append_pre_publication_evidence(...)`.

The resulting custody ID remains `pre-publication-evidence:<64hex>` and remains non-authorizing. Invocation-specific execution authorization is a separate later decision.

## Boundaries

This implementation adds no workflow, IAM/WIF, credential, VM/network, Scheduler dispatch, new validation runner, new store root, namespace, mutable latest pointer, index, database, approval model, currentness model, or execution-authorization model. The existing fixed-command dev-validation and PR-less `ValidationEvidenceBundle` owners remain unchanged. Live execution, deployment, merge, and issue closure remain separately governed.
