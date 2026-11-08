"""Regression for #3024: a legacy Drive tutorial cannot be presented as the
current course artifact without verified current-course identity.

Fixture: the 2026-09-28 incident. The teacher asked for the hamburger tutorial
slides "as a part of Adobe foundation"; the live path returned the older
"Burger tutorial - All About Layers" Photopea-era deck and asserted it was the
actual requested tutorial. A Drive title match is candidate evidence, never
evidence that the file is the current requested course artifact.
"""
from __future__ import annotations

import instructional_workflow_contracts.current_curriculum_state as current_state
from instructional_workflow_contracts.classroom_artifact_candidate_verification import (
    CONTRACT_ID,
    verify_classroom_artifact_candidates,
)
from instructional_workflow_contracts.common import ValidationStatus

CURRENT_COURSE = "course-adobe-foundations"
LEGACY_COURSE = "course-photopea-legacy"

TEACHER_REQUEST_TEXT = (
    "Show me the tutorial slides for the hamburger assignment as a part of "
    "Adobe foundation"
)


def _owner(evidence_id: str) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "owner": "unit-alignment",
        "decision_key": "unit-generation-approval",
        "value": "locked-sequence-approved",
        "classification": "owner-governed",
        "source_revision": 1,
        "observed_at": "2026-09-28T12:00:00Z",
        "currentness": "current",
        "material": True,
        "relation_resolved": True,
        "reference": {
            "system": "notion",
            "stable_id": evidence_id,
            "exact_location": f"collection://example/{evidence_id}",
            "verification_evidence": "caller-supplied-read-back",
        },
    }


def _curriculum_state(unit_status: str = "active"):
    evidence = {
        "contract_version": current_state.INPUT_CONTRACT_ID,
        "canonical_unit": {"stable_id": CURRENT_COURSE, "status": unit_status},
        "request": {
            "action": "show-tutorial-slides",
            "artifact_type": "slides",
            "relative_time": "none",
            "requires_reusable_assets": False,
        },
        "required_decision_keys": ["unit-generation-approval"],
        "owner_evidence": [_owner("ua-3024")],
        "asset_evidence": [],
    }
    result = current_state.resolve_current_curriculum_state(evidence)
    assert result.record is not None
    return result.record


def _request(named_course: str | None = CURRENT_COURSE) -> dict[str, object]:
    return {
        "request_id": "issue-3024-request-2026-09-28",
        "named_course": named_course,
        "artifact_topic": "hamburger-tutorial-slides",
        "raw_text": TEACHER_REQUEST_TEXT,
    }


def _candidate(
    drive_file_id: str,
    title: str,
    *,
    course_binding: str | None = None,
    verified: bool = False,
    conflict: bool = False,
    provenance_note: str = "",
) -> dict[str, object]:
    return {
        "drive_file_id": drive_file_id,
        "title": title,
        "course_binding": course_binding,
        "course_binding_verified": verified,
        "identity_conflict": conflict,
        "provenance_note": provenance_note,
    }


def _legacy_deck(file_id: str, title: str) -> dict[str, object]:
    # Same-role (tutorial deck), same-topic (burger/hamburger) legacy file, so
    # artifact-role checks alone cannot pass this fixture.
    return _candidate(
        file_id,
        title,
        course_binding=LEGACY_COURSE,
        verified=False,
        conflict=True,
        provenance_note=(
            "2025-era Photopea deck; application identity and course era "
            "conflict with the current Adobe Foundations course"
        ),
    )


def _verdicts(result) -> list[dict[str, object]]:
    assert result.record is not None
    return result.record.to_dict()["candidate_verdicts"]


def _wording(result) -> dict[str, object]:
    assert result.record is not None
    return result.record.to_dict()["response_wording"]


def test_contract_id_is_versioned() -> None:
    assert CONTRACT_ID == "artifact-candidate-verification-v1"


def test_legacy_title_similar_deck_is_not_marked_current() -> None:
    result = verify_classroom_artifact_candidates(
        _request(),
        _curriculum_state(),
        [
            _legacy_deck("drive-legacy-burger-layers", "Burger tutorial - All About Layers"),
            _legacy_deck("drive-legacy-burger-2024", "Burger Tutorial - Layers Practice (2024)"),
            _candidate("drive-hamburger-draft", "Hamburger Tutorial Draft"),
        ],
    )
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    verdicts = {item["drive_file_id"]: item for item in _verdicts(result)}
    assert verdicts["drive-legacy-burger-layers"]["classification"] == "legacy"
    assert verdicts["drive-legacy-burger-2024"]["classification"] == "legacy"
    assert verdicts["drive-hamburger-draft"]["classification"] == "unverified"
    assert not any(item["classification"] == "verified-current" for item in verdicts.values())


def test_unresolved_identity_yields_visible_bounded_blocker() -> None:
    result = verify_classroom_artifact_candidates(
        _request(),
        _curriculum_state(),
        [_legacy_deck("drive-legacy-burger-layers", "Burger tutorial - All About Layers")],
    )
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert "artifact-identity-source-unresolved" in result.reason_codes
    assert "artifact-current-identity-unverified" in result.blockers


def test_certainty_language_not_authorized_without_provenance_evidence() -> None:
    result = verify_classroom_artifact_candidates(
        _request(),
        _curriculum_state(),
        [_legacy_deck("drive-legacy-burger-layers", "Burger tutorial - All About Layers")],
    )
    assert _wording(result)["certainty_language_authorized"] is False


def test_verified_current_binding_preserves_legacy_labels() -> None:
    result = verify_classroom_artifact_candidates(
        _request(),
        _curriculum_state(),
        [
            _legacy_deck("drive-legacy-burger-layers", "Burger tutorial - All About Layers"),
            _candidate(
                "drive-current-hamburger-slides",
                "Adobe Foundations - Hamburger Tutorial",
                course_binding=CURRENT_COURSE,
                verified=True,
                provenance_note=(
                    "bound to the current Adobe Foundations unit by the "
                    "canonical unit planning record"
                ),
            ),
        ],
    )
    assert result.status is ValidationStatus.VALID
    payload = result.record.to_dict()
    assert payload["overall_outcome"] == "verified-current-artifact"
    assert payload["verified_current_drive_file_id"] == "drive-current-hamburger-slides"
    assert _wording(result)["certainty_language_authorized"] is True
    verdicts = {item["drive_file_id"]: item for item in _verdicts(result)}
    assert verdicts["drive-current-hamburger-slides"]["classification"] == "verified-current"
    # The legacy deck may still be surfaced as a historical reference, but it
    # must be labeled legacy rather than current.
    assert verdicts["drive-legacy-burger-layers"]["classification"] == "legacy"


def test_missing_curriculum_identity_fails_closed() -> None:
    result = verify_classroom_artifact_candidates(
        _request(),
        None,
        [_legacy_deck("drive-legacy-burger-layers", "Burger tutorial - All About Layers")],
    )
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert "artifact-curriculum-identity-unresolved" in result.reason_codes
    assert "artifact-current-identity-unverified" in result.blockers
    assert _wording(result)["certainty_language_authorized"] is False


def test_request_without_named_course_fails_closed() -> None:
    result = verify_classroom_artifact_candidates(
        _request(named_course=None),
        _curriculum_state(),
        [_legacy_deck("drive-legacy-burger-layers", "Burger tutorial - All About Layers")],
    )
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert "artifact-named-course-unresolved" in result.reason_codes
    assert _wording(result)["certainty_language_authorized"] is False


def test_multiple_verified_current_claims_fail_closed() -> None:
    result = verify_classroom_artifact_candidates(
        _request(),
        _curriculum_state(),
        [
            _candidate(
                "drive-current-hamburger-a",
                "Adobe Foundations - Hamburger Tutorial",
                course_binding=CURRENT_COURSE,
                verified=True,
            ),
            _candidate(
                "drive-current-hamburger-b",
                "Adobe Foundations - Hamburger Tutorial (copy)",
                course_binding=CURRENT_COURSE,
                verified=True,
            ),
        ],
    )
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert "artifact-multiple-current-claims" in result.reason_codes
    assert _wording(result)["certainty_language_authorized"] is False
