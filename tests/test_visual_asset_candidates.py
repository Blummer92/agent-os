from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from instructional_workflow_contracts import ValidationStatus
from instructional_workflow_contracts.visual_asset_candidates import (
    MAX_CANDIDATES,
    filter_approved_visual_candidates,
)
from instructional_workflow_contracts.visual_needs import plan_visual_needs

FIXTURES = Path(__file__).parent / "fixtures" / "instructional_workflow_contracts"


def _load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _plan():
    result = plan_visual_needs(_load("valid_material_requirement_v2.json"))
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    return result.record


def _compatibility() -> dict[str, object]:
    return _load("valid_visual_asset_compatibility.json")


def _mutate(value: dict[str, object], path: list[str], replacement: object) -> None:
    cursor: object = value
    for key in path[:-1]:
        assert isinstance(cursor, dict)
        cursor = cursor[key]
    assert isinstance(cursor, dict)
    cursor[path[-1]] = replacement


def test_valid_candidate_is_eligible_and_deterministic() -> None:
    candidate = _compatibility()
    before = copy.deepcopy(candidate)

    first = filter_approved_visual_candidates(
        _plan(),
        [candidate],
        source_revision="visual-library-snapshot-v1",
    )
    second = filter_approved_visual_candidates(
        _plan(),
        [copy.deepcopy(candidate)],
        source_revision="visual-library-snapshot-v1",
    )

    assert first.status is ValidationStatus.VALID
    assert first.record is not None
    assert second.record is not None
    payload = first.record.to_dict()
    assert payload["candidate_count"] == 1
    assert len(payload["eligible"]) == 1
    assert payload["rejected"] == []
    assert payload["manual_review"] == []
    assert first.record.fingerprint == second.record.fingerprint
    assert first.record.record_id == second.record.record_id
    assert candidate == before
    assert payload["authority"] == {
        "execution_authorized": False,
        "external_write_authorized": False,
        "production_authorized": False,
        "publication_authorized": False,
        "side_effects_performed": False,
    }


def test_fixture_cases_route_to_expected_groups() -> None:
    matrix = _load("visual_asset_candidate_cases.json")
    source_revision = matrix["source_revision"]
    assert isinstance(source_revision, str)

    for case in matrix["cases"]:
        candidate = _compatibility()
        mutation = case["mutation"]
        if mutation is not None:
            _mutate(candidate, mutation["path"], mutation["value"])

        result = filter_approved_visual_candidates(
            _plan(),
            [candidate],
            source_revision=source_revision,
        )
        assert result.record is not None, case["name"]
        payload = result.record.to_dict()
        group = case["expected_group"]
        assert len(payload[group]) == 1, case["name"]
        if "expected_reason" in case:
            assert case["expected_reason"] in payload[group][0]["reason_codes"]


def test_manual_review_candidate_controls_result_status() -> None:
    candidate = _compatibility()
    candidate["compatibility_evidence"]["freshness"]["stale"] = True  # type: ignore[index]

    result = filter_approved_visual_candidates(
        _plan(),
        [candidate],
        source_revision="visual-library-snapshot-v1",
    )

    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.reason_codes == ("manual-review-visual-candidates",)


def test_invalid_candidate_is_rejected_without_aborting_batch() -> None:
    invalid = _compatibility()
    invalid["compatibility_evidence"]["unexpected"] = True  # type: ignore[index]

    result = filter_approved_visual_candidates(
        _plan(),
        [_compatibility(), invalid],
        source_revision="visual-library-snapshot-v1",
    )

    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    payload = result.record.to_dict()
    assert len(payload["eligible"]) == 1
    assert len(payload["rejected"]) == 1
    assert payload["rejected"][0]["classification"] == "invalid"


def test_candidate_order_does_not_change_result_identity() -> None:
    eligible = _compatibility()
    rejected = _compatibility()
    rejected["compatibility_evidence"]["accessibility"]["review_state"] = "fail"  # type: ignore[index]

    forward = filter_approved_visual_candidates(
        _plan(),
        [eligible, rejected],
        source_revision="visual-library-snapshot-v1",
    )
    reverse = filter_approved_visual_candidates(
        _plan(),
        [rejected, eligible],
        source_revision="visual-library-snapshot-v1",
    )

    assert forward.record is not None
    assert reverse.record is not None
    assert forward.record.fingerprint == reverse.record.fingerprint
    assert forward.record.record_id == reverse.record.record_id


def test_source_revision_is_required_and_identity_bound() -> None:
    first = filter_approved_visual_candidates(
        _plan(),
        [_compatibility()],
        source_revision="revision-1",
    )
    second = filter_approved_visual_candidates(
        _plan(),
        [_compatibility()],
        source_revision="revision-2",
    )

    assert first.record is not None
    assert second.record is not None
    assert first.record.record_id != second.record.record_id

    invalid = filter_approved_visual_candidates(
        _plan(),
        [_compatibility()],
        source_revision="",
    )
    assert invalid.status is ValidationStatus.INVALID


def test_candidate_count_is_bounded() -> None:
    result = filter_approved_visual_candidates(
        _plan(),
        [_compatibility() for _ in range(MAX_CANDIDATES + 1)],
        source_revision="visual-library-snapshot-v1",
    )

    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-oversized",)


@pytest.mark.parametrize("value", [None, (), {}, "candidate"])
def test_candidates_require_a_builtin_list(value: object) -> None:
    result = filter_approved_visual_candidates(
        _plan(),
        value,
        source_revision="visual-library-snapshot-v1",
    )
    assert result.status is ValidationStatus.INVALID


def test_non_actionable_plan_is_rejected() -> None:
    requirement = _load("valid_material_requirement_v2.json")
    requirement["visual_direction"] = {  # type: ignore[index]
        "decision": "no-visuals",
        "maximum_visual_count": 0,
        "roles": [],
    }
    plan = plan_visual_needs(requirement)
    assert plan.record is not None

    result = filter_approved_visual_candidates(
        plan.record,
        [],
        source_revision="visual-library-snapshot-v1",
    )

    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("visual-candidates-plan-not-actionable",)


def test_plain_plan_mapping_is_not_trusted() -> None:
    result = filter_approved_visual_candidates(
        _plan().to_dict(),
        [_compatibility()],
        source_revision="visual-library-snapshot-v1",
    )
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("visual-candidates-invalid-plan",)
