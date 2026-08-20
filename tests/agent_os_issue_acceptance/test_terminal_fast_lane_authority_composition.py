from instructional_workflow_contracts import (
    ValidationStatus,
    validate_request_interpretation,
)
from instructional_workflow_contracts.common import sha256_hex

from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorityProjection,
    AuthorizationState,
    DependencyState,
    FreshnessState,
    IssueOperationalEvidence,
    IssueState,
    LifecycleStage,
    PrimaryIssueClaim,
    ReadinessState,
    SourceState,
    TerminalDisposition,
    ValidationState,
    build_issue_operational_state,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    AdmissionStatus,
    LifecycleMutationAuthorization,
    LifecycleStateSnapshot,
    evaluate_lifecycle_mutation,
)
from scripts.agent_os_issue_acceptance.merge_authorization import (
    MergeAuthorizationApplicabilityResult,
)
from scripts.agent_os_issue_acceptance.operating_mode import (
    EnvironmentCapabilityEvidence,
    EnvironmentCapabilityState,
    RequestedMode,
    evaluate_operating_mode_decision,
)

HEAD = "a" * 40
BASE = "b" * 40
APPROVAL_ID = "approval:" + "1" * 64
MERGE_AUTH_ID = "merge-authorization:" + "2" * 64
MERGE_REVISION = "merge-authorization-revision:" + "3" * 64
PR_EVIDENCE_ID = "pull-request-merge-evidence:" + "4" * 64
ENV_EVIDENCE_ID = "environment-capability:" + "5" * 64


def request_payload():
    return {
        "schema_name": "request-interpretation",
        "contract_version": "request-interpretation-v1",
        "record_revision": 1,
        "observed_at": "2026-08-20T19:00:00Z",
        "interpreter_id": "chatgpt-orchestrator",
        "raw_input_digest": sha256_hex("work on #844 in fast lane"),
        "instruction_origin": "direct-user",
        "action": "implement",
        "requested_effect": "mutate",
        "continuation_mode": "new",
        "target": {
            "system": "github",
            "resource_kind": "issue",
            "repository": "Blummer92/agent-os",
            "resource_id": "844",
        },
        "requested_outputs": ["implementation"],
        "constraints": [{"name": "operating-mode", "value": "release"}],
        "reason_codes": [],
        "evidence_references": [],
    }


def authority(state, evidence_id=None):
    return AuthorityProjection(state=state, evidence_id=evidence_id)


def environment():
    return EnvironmentCapabilityEvidence(
        local_execution_state=EnvironmentCapabilityState.VERIFIED,
        push_state=EnvironmentCapabilityState.VERIFIED,
        evidence_id=ENV_EVIDENCE_ID,
    )


def operational_state(merge_authorization, closure_authorization):
    evidence = IssueOperationalEvidence(
        repository="Blummer92/agent-os",
        issue_number=844,
        source_revision=HEAD,
        observed_at="2026-08-20T19:05:00Z",
        evidence_ids=(APPROVAL_ID,),
        source_state=SourceState.COMPLETE,
        issue_state=IssueState.OPEN,
        lifecycle_stage=LifecycleStage.REVIEW,
        terminal_disposition=TerminalDisposition.NONE,
        readiness=ReadinessState.READY,
        implementation_authorization=authority(
            AuthorizationState.AUTHORIZED, APPROVAL_ID
        ),
        ready_for_review_authorization=authority(
            AuthorizationState.AUTHORIZED, APPROVAL_ID
        ),
        execution_authorization=authority(
            AuthorizationState.AUTHORIZED, APPROVAL_ID
        ),
        merge_authorization=merge_authorization,
        closure_authorization=closure_authorization,
        external_write_authorization=authority(AuthorizationState.NOT_APPLICABLE),
        dependency_state=DependencyState.CLEAR,
        primary_claims=(
            PrimaryIssueClaim(
                pull_request_number=1311,
                branch="agent/1309-governance-go-fast",
                head_sha=HEAD,
                state="ready",
            ),
        ),
        validation_state=ValidationState.PASSED,
        freshness_state=FreshnessState.CURRENT,
        observed_labels=("status:ready",),
    )
    return build_issue_operational_state(evidence)


def test_fast_lane_request_stays_non_authorizing_until_canonical_records_admit():
    interpreted = validate_request_interpretation(request_payload())
    assert interpreted.status is ValidationStatus.VALID
    assert interpreted.record is not None
    assert interpreted.record.to_dict()["authorization_created"] is False

    no_authority = authority(AuthorizationState.NOT_AUTHORIZED)
    decision = evaluate_operating_mode_decision(
        operational_state(no_authority, no_authority),
        RequestedMode.RELEASE,
        environment(),
    )
    assert decision.maximum_permitted_stage is LifecycleStage.REVIEW
    assert "authorization.merge-not-authorized" in decision.blocker_codes


def test_request_identity_backs_existing_merge_and_closure_authority_paths():
    interpreted = validate_request_interpretation(request_payload())
    assert interpreted.status is ValidationStatus.VALID
    assert interpreted.record is not None
    request_id = interpreted.record.record_id

    merge_applicability = MergeAuthorizationApplicabilityResult(
        status="applicable",
        authorization_id=MERGE_AUTH_ID,
        authorization_revision=MERGE_REVISION,
        current_pull_request_evidence_id=PR_EVIDENCE_ID,
        changed_bindings=(),
        reason_codes=(),
        merge_authorized=True,
    )
    merge_projection = AuthorityProjection.from_merge_authorization_applicability(
        merge_applicability
    )

    close_snapshot = LifecycleStateSnapshot(
        repository="Blummer92/agent-os",
        issue_number=844,
        pull_request_number=1311,
        source_head=HEAD,
        base_head=BASE,
        pr_state="ready",
        merged=True,
        issue_state="open",
        review_state="clear",
        unresolved_threads=0,
        lifecycle_labels=("status:ready",),
        observed_revision="terminal-readback-1",
    )
    close_authorization = LifecycleMutationAuthorization(
        schema_version="1.0",
        repository="Blummer92/agent-os",
        issue_number=844,
        pull_request_number=1311,
        authorized_mutations=("close-issue",),
        expected_source_head=HEAD,
        expected_base_head=BASE,
        expected_pr_state="ready",
        expected_merged=True,
        expected_issue_state="open",
        expected_review_state="clear",
        expected_unresolved_threads=0,
        expected_lifecycle_labels=("status:ready",),
        observed_at_revision="terminal-readback-1",
        state="authorized",
        authorizer_id="repository-owner",
        decision_id=request_id,
    )
    close_admission = evaluate_lifecycle_mutation(
        close_authorization, close_snapshot, "close-issue"
    )
    assert close_admission.status is AdmissionStatus.ADMITTED
    closure_projection = AuthorityProjection.from_lifecycle_admission(close_admission)

    decision = evaluate_operating_mode_decision(
        operational_state(merge_projection, closure_projection),
        RequestedMode.RELEASE,
        environment(),
    )
    assert decision.maximum_permitted_stage is LifecycleStage.CLOSED
    assert decision.next_permitted_action == "merge"
