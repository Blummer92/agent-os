# Production human-approval custody (#1982)

Issue #1982 composes two separately authorized inputs without creating a second approval or persistence system.

## Option C — candidate-preparer provenance

Before human approval, the candidate-preparation boundary may persist one exact `CandidateApprovalProvenanceEvidence`. The evidence contains only a complete verified `APPROVAL_READY` `CandidatePacket` and the exact `ApprovalCandidateContext` that produced its pending candidate. It is content-addressed in the existing `pre-publication-producer-evidence` namespace under the trusted checkpoint-store root. It creates no approval, execution, publication, GitHub-write, merge, or external-write authority.

The candidate-preparer provenance is deliberately distinct from the later repository-owner decision. The later approver cannot be used to reconstruct or replace `ApprovalCandidateContext`.

## Option A — repository-owner human decision

The later human decision is reacquired from the existing complete GitHub issue-comment snapshot. Only this exact fixed command is eligible:

```text
/agent-os approve-candidate pre-publication-evidence:<64 lowercase hex>
```

The comment must be authored by the repository owner. Ordinary prose, labels, reviews, Scheduler state, execution authorization, partial comment snapshots, extra tokens, approval JSON, arbitrary JSON, shell, argv, credentials, store paths, and caller-supplied authority booleans do not approve anything.

The trusted comment provenance becomes one typed `ApprovalDecision`: the repository owner is the authorizer, the immutable comment ID is the decision identity, and GitHub `created_at` is the decision time. #753 remains the approval/applicability owner and still rejects self-approval when candidate preparer and human approver are the same.

## Production composition

`produce_human_approval_custody(...)` loads the exact Option-C provenance from the trusted root, reacquires the Option-A owner decision, reruns the canonical candidate pipeline against current supplied readers/observations, requires a complete verified `EXECUTION_CANDIDATE`, and proves the source/IssuePlan/planning/repository/proposal/approval-candidate identities still match the pre-approval packet. It then delegates to existing #1978 `build_approval_custody_evidence(...)` and `append_pre_publication_evidence(...)`.

The resulting custody ID remains `pre-publication-evidence:<64hex>` and remains non-authorizing. Invocation-specific execution authorization is a separate later decision.

## Boundaries

This implementation adds no workflow, IAM/WIF, credential, VM/network, Scheduler dispatch, validation runner, new store root, namespace, mutable latest pointer, index, database, approval model, currentness model, or execution-authorization model. Live execution and deployment remain separately governed.
