"""#3413 post-approval re-verification regressions.

Proves the five-point owner architecture decision end to end through the
real pipeline:

1. Phase-specific diagnostic readiness reason codes are excluded from
   approval-bound identity composition; a first-packet-approved candidate
   re-verifies under post-approval consumers.
2. Previously approved (pre-#3413 composition) candidate fingerprints verify
   through an explicitly proven, fail-closed legacy compatibility path --
   never silently rewritten or re-authorized.
3. Post-approval rebuilds require caller-supplied canonical dependency
   identities; omitting them still fails closed.
4. The #1320 post-approval evidence owners stay mandatory.
5. Security-relevant semantic evidence and current-state identity stay
   identity-bound.

Fixture harness (Tier-2, issueplan-core/v1, offline) is reused from the
#3354 lifecycle module; every run below drives the real
``prepare_candidate_packet`` pipeline, never a hand-built identity.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXECUTION_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
if str(EXECUTION_SERVICE_SRC) not in sys.path:
    sys.path.insert(0, str(EXECUTION_SERVICE_SRC))

import pytest  # noqa: E402

from scripts.agent_os_candidate_packet.cli import prepare_candidate_packet  # noqa: E402
from scripts.agent_os_candidate_packet.legacy_identity_compatibility import (  # noqa: E402
    PostApprovalIdentityOutcome,
    verify_post_approval_stage_identities,
)
from scripts.agent_os_candidate_packet.models import CandidatePacketPhase  # noqa: E402
from scripts.agent_os_candidate_packet.planning_stage import (  # noqa: E402
    PHASE_SPECIFIC_DIAGNOSTIC_REASON_CODES,
)
from scripts.agent_os_candidate_packet.stage_models import (  # noqa: E402
    DependencyEvidence,
    EvidenceStatus,
    IssueReadinessStageStatus,
    ValidationEvidence,
)
from scripts.agent_os_issue_acceptance import ApprovalState  # noqa: E402
from tests.agent_os_candidate_packet.test_first_packet_approval_lifecycle import (  # noqa: E402
    _REPOSITORY,
    _approval_ready,
    _candidate_context,
    _decision,
    _items,
    _kwargs,
    _observation,
    _PostApprovalReader,
)

_OBSERVED_AT = "2026-10-08T00:05:00Z"


def _post_approval_rebuild(first, **overrides):
    """Consumer-style rebuild: post-approval mode, clear evidence, identities.

    Reuses the first-packet run's own canonical ``DependencyIdentityEvidence``
    -- the identical structured identities and provenance the approval was
    granted on, exactly as the #3413 reproduction describes.
    """
    values = dict(
        repository_reader=_PostApprovalReader(
            EvidenceStatus.RESOLVED_CLEAR, EvidenceStatus.RESOLVED_CLEAR
        ),
        repository_observation=_observation(first.implementation_contract_fingerprint),
        candidate_context=_candidate_context(),
        approval_record_exists=True,
        dependency_identity_evidence=first.readiness_stage_result.dependency_identity_evidence,
        requested_phase=CandidatePacketPhase.APPROVAL_READY,
    )
    values.update(overrides)
    return prepare_candidate_packet(**_kwargs(_items(), **values))


# --------------------------------------------------------------------------
# Point 1: phase-specific diagnostic codes are not approval-bound.
# --------------------------------------------------------------------------


def test_post_approval_rebuild_reproduces_first_packet_stage_identities() -> None:
    """A first-packet-approved candidate re-verifies under post-approval mode.

    Fails on the pre-#3413 composition: the first-packet run hashed
    ``validation.first-packet-not-required`` and
    ``dependency-graph.no-dependencies-declared`` into the planning node, so
    ``planning-handoff`` / ``proposal`` / ``approval-candidate`` drifted.
    """
    first = _approval_ready()
    assert first.disposition == "approval-ready"
    assert "validation.first-packet-not-required" in (
        first.readiness_stage_result.reason_codes
    )
    # ... but the diagnostic code is not identity-bound anymore.
    assert (
        "validation.first-packet-not-required"
        not in first.planning_stage_result.node.readiness_evidence
    )
    assert (
        "dependency-graph.no-dependencies-declared"
        not in first.planning_stage_result.node.readiness_evidence
    )

    rebuild = _post_approval_rebuild(first)
    assert rebuild.disposition == "approval-ready", rebuild.compilation_failure

    prior = dict(first.packet.stage_identities)
    current = dict(rebuild.packet.stage_identities)
    for name in (
        "source",
        "issueplan",
        "planning-handoff",
        "repository-evidence",
        "proposal",
        "approval-candidate",
    ):
        assert prior[name] == current[name], name


def test_excluded_codes_are_exactly_the_governed_diagnostic_set() -> None:
    assert PHASE_SPECIFIC_DIAGNOSTIC_REASON_CODES == frozenset(
        {
            "validation.first-packet-not-required",
            "dependency-graph.no-dependencies-declared",
            "dependency-graph.all-dependencies-closed",
        }
    )


def test_security_relevant_evidence_stays_identity_bound() -> None:
    """authorization.not-granted and the issueplan marker still bind identity."""
    first = _approval_ready()
    evidence = first.planning_stage_result.node.readiness_evidence
    assert "authorization.not-granted" in evidence
    assert any(
        item.startswith("issueplan-evidence:") for item in evidence
    )


def test_changed_issueplan_still_drifts() -> None:
    """Current-state identity is preserved: a changed IssuePlan is drift."""
    first = _approval_ready()
    rebuild = _post_approval_rebuild(first)
    tampered = dict(rebuild.packet.stage_identities)
    tampered["issueplan"] = "issueplan-current-state:tampered"
    verdict = verify_post_approval_stage_identities(
        expected_identities=tampered,
        current_identities=dict(first.packet.stage_identities),
        planning_stage_result=rebuild.planning_stage_result,
        approved_packet=first.packet,
        repository_observation=_observation(first.implementation_contract_fingerprint),
        candidate_context=_candidate_context(),
        observed_at=_OBSERVED_AT,
    )
    assert verdict.outcome is PostApprovalIdentityOutcome.DRIFT


# --------------------------------------------------------------------------
# Point 2: explicit fail-closed legacy compatibility path.
# --------------------------------------------------------------------------


def _legacy_approval_ready(**overrides):
    values = dict(identity_composition="legacy")
    values.update(overrides)
    return prepare_candidate_packet(**_kwargs(_items(), **values))


def test_legacy_first_packet_packet_verifies_via_explicit_legacy_path() -> None:
    """A pre-#3413-composed approval verifies through the named legacy path."""
    legacy = _legacy_approval_ready(
        repository_observation=_observation(
            _approval_ready().implementation_contract_fingerprint
        ),
        candidate_context=_candidate_context(),
    )
    assert legacy.disposition == "approval-ready"
    # The legacy packet really does carry the old composition.
    assert (
        "validation.first-packet-not-required"
        in legacy.planning_stage_result.node.readiness_evidence
    )

    current = _approval_ready()
    rebuild = _post_approval_rebuild(current)
    assert rebuild.disposition == "approval-ready"

    verdict = verify_post_approval_stage_identities(
        expected_identities=dict(legacy.packet.stage_identities),
        current_identities=dict(rebuild.packet.stage_identities),
        planning_stage_result=rebuild.planning_stage_result,
        approved_packet=legacy.packet,
        repository_observation=_observation(current.implementation_contract_fingerprint),
        candidate_context=_candidate_context(),
        observed_at=_OBSERVED_AT,
    )
    assert verdict.outcome is PostApprovalIdentityOutcome.VERIFIED_LEGACY_COMPOSITION
    assert set(verdict.legacy_diagnostic_codes) == {
        "validation.first-packet-not-required",
        "dependency-graph.no-dependencies-declared",
    }
    assert verdict.reason_codes == ("candidate-legacy-identity-composition-verified",)


def test_legacy_composition_all_closed_code_set() -> None:
    """Reinstating the all-closed code set reproduces the legacy handoff digest.

    A declared (closed) dependency keeps planning at needs-decision (#3354
    gap 1), so this is proven at the composition level: the legacy planning
    result built by the real stage and the recomputation with the all-closed
    code set reinstated must agree, while the no-deps set must not.
    """
    from scripts.agent_os_candidate_packet.legacy_identity_compatibility import (
        legacy_handoff_digest_for_codes,
    )
    from scripts.agent_os_candidate_packet.planning_stage import (
        prepare_planning_handoff,
    )

    items = _items(f"  depends_on:\n    - {_REPOSITORY}#41", ((41, "closed"),))
    first = prepare_candidate_packet(**_kwargs(items, approval_record_exists=False))
    assert first.readiness_stage_result.status is IssueReadinessStageStatus.READY
    assert (
        "dependency-graph.all-dependencies-closed"
        in first.readiness_stage_result.reason_codes
    )

    legacy_planning = prepare_planning_handoff(
        first.readiness_stage_result,
        evaluator_sha="a" * 40,
        created_at=_OBSERVED_AT,
        identity_composition="legacy",
    )
    recomputed = legacy_handoff_digest_for_codes(
        first.planning_stage_result,
        (
            "validation.first-packet-not-required",
            "dependency-graph.all-dependencies-closed",
        ),
    )
    assert recomputed is not None
    assert recomputed[0] == legacy_planning.handoff.handoff_digest

    wrong_set = legacy_handoff_digest_for_codes(
        first.planning_stage_result,
        (
            "validation.first-packet-not-required",
            "dependency-graph.no-dependencies-declared",
        ),
    )
    assert wrong_set is not None
    assert wrong_set[0] != legacy_planning.handoff.handoff_digest


class _CodedPostApprovalReader:
    """Clear post-approval evidence that still carries a semantic reason code."""

    def read_dependency_evidence(self, repository: str, issue_number: int):
        return DependencyEvidence(
            status=EvidenceStatus.RESOLVED_CLEAR,
            reason_codes=("dependency.test-semantic-code",),
        )

    def read_validation_evidence(self, repository: str, issue_number: int):
        return ValidationEvidence(status=EvidenceStatus.RESOLVED_CLEAR)


def test_legacy_verifier_fails_closed_when_rebuild_has_extra_codes() -> None:
    """Extra semantic codes in the rebuild make the legacy proof unprovable.

    The rebuild still reaches APPROVAL_READY, but its node carries a code the
    approval-time run never emitted, so no closed legacy code set can
    reproduce the stored identities. Fail closed, never guess.
    """
    legacy = _legacy_approval_ready(
        repository_observation=_observation(
            _approval_ready().implementation_contract_fingerprint
        ),
        candidate_context=_candidate_context(),
    )
    current = _approval_ready()
    rebuild = prepare_candidate_packet(
        **_kwargs(
            _items(),
            repository_reader=_CodedPostApprovalReader(),
            repository_observation=_observation(
                current.implementation_contract_fingerprint
            ),
            candidate_context=_candidate_context(),
            approval_record_exists=True,
            dependency_identity_evidence=(
                current.readiness_stage_result.dependency_identity_evidence
            ),
            requested_phase=CandidatePacketPhase.APPROVAL_READY,
        )
    )
    assert rebuild.disposition == "approval-ready"
    assert (
        "dependency.test-semantic-code"
        in rebuild.planning_stage_result.node.readiness_evidence
    )
    verdict = verify_post_approval_stage_identities(
        expected_identities=dict(legacy.packet.stage_identities),
        current_identities=dict(rebuild.packet.stage_identities),
        planning_stage_result=rebuild.planning_stage_result,
        approved_packet=legacy.packet,
        repository_observation=_observation(
            current.implementation_contract_fingerprint
        ),
        candidate_context=_candidate_context(),
        observed_at=_OBSERVED_AT,
    )
    assert verdict.outcome is PostApprovalIdentityOutcome.LEGACY_UNPROVABLE
    assert verdict.reason_codes == ("candidate-legacy-compatibility-unprovable",)


def test_legacy_verifier_requires_candidate_context() -> None:
    """Without the approval-time context the legacy proof cannot be built."""
    legacy = _legacy_approval_ready(
        repository_observation=_observation(
            _approval_ready().implementation_contract_fingerprint
        ),
        candidate_context=_candidate_context(),
    )
    current = _approval_ready()
    rebuild = _post_approval_rebuild(current)
    verdict = verify_post_approval_stage_identities(
        expected_identities=dict(legacy.packet.stage_identities),
        current_identities=dict(rebuild.packet.stage_identities),
        planning_stage_result=rebuild.planning_stage_result,
        approved_packet=legacy.packet,
        repository_observation=_observation(current.implementation_contract_fingerprint),
        candidate_context=None,
        observed_at=_OBSERVED_AT,
    )
    assert verdict.outcome is PostApprovalIdentityOutcome.LEGACY_UNPROVABLE


def test_current_composition_packets_verify_strictly() -> None:
    """Post-#3413 approvals take the strict path, never the legacy one."""
    first = _approval_ready()
    rebuild = _post_approval_rebuild(first)
    verdict = verify_post_approval_stage_identities(
        expected_identities=dict(first.packet.stage_identities),
        current_identities=dict(rebuild.packet.stage_identities),
        planning_stage_result=rebuild.planning_stage_result,
        approved_packet=first.packet,
        repository_observation=_observation(first.implementation_contract_fingerprint),
        candidate_context=_candidate_context(),
        observed_at=_OBSERVED_AT,
    )
    assert verdict.outcome is PostApprovalIdentityOutcome.VERIFIED
    assert verdict.legacy_diagnostic_codes == ()


# --------------------------------------------------------------------------
# Points 3-4: identity evidence required; #1320 owners stay mandatory.
# --------------------------------------------------------------------------


def test_missing_identity_evidence_still_fails_closed() -> None:
    """Omitting dependency identities still stops truthfully (point 3)."""
    first = _approval_ready()
    rebuild = prepare_candidate_packet(
        **_kwargs(
            _items(),
            repository_reader=_PostApprovalReader(
                EvidenceStatus.RESOLVED_CLEAR, EvidenceStatus.RESOLVED_CLEAR
            ),
            repository_observation=_observation(first.implementation_contract_fingerprint),
            candidate_context=_candidate_context(),
            approval_record_exists=True,
            requested_phase=CandidatePacketPhase.APPROVAL_READY,
        )
    )
    assert rebuild.disposition == "needs-decision"
    assert (
        "dependency-identity.not-supplied"
        in rebuild.readiness_stage_result.dependency_identity_evidence.reason_codes
    )
    assert (
        "dependency-identity-incomplete"
        in rebuild.planning_stage_result.reason_codes
    )


def test_post_approval_evidence_owners_stay_mandatory() -> None:
    """#1320 DependencyReadinessEvidence/AdvisoryEvidenceResult still gate."""
    first = _approval_ready()
    rebuild = prepare_candidate_packet(
        **_kwargs(
            _items(),
            repository_reader=_PostApprovalReader(
                EvidenceStatus.UNAVAILABLE, EvidenceStatus.UNAVAILABLE
            ),
            repository_observation=_observation(first.implementation_contract_fingerprint),
            candidate_context=_candidate_context(),
            approval_record_exists=True,
            dependency_identity_evidence=(
                first.readiness_stage_result.dependency_identity_evidence
            ),
            requested_phase=CandidatePacketPhase.APPROVAL_READY,
        )
    )
    assert rebuild.disposition in ("blocked", "needs-decision")
    assert rebuild.packet is None
