import pytest

from instructional_workflow_contracts.current_curriculum_evidence import _request_mode as assembler_mode
from navigation_registry.connectors.curriculum_evidence_orchestrator import CurriculumReadRequest, _request_mode as planner_mode


@pytest.mark.parametrize(
    ("action", "artifact_type"),
    [
        ("images", "none"),
        ("improve-modeling", "none"),
        ("what-is-blocking", "none"),
        ("make", "slides"),
        ("make", "worksheet"),
        ("next-teaching", "none"),
        ("remodel", "worksheet"),
        ("unblock", "lesson"),
        ("images-are-not-needed", "worksheet"),
        ("model", "slides"),
        ("blocker review", "worksheet"),
    ],
)
def test_request_mode_is_consistent_across_planner_and_assembler(action: str, artifact_type: str) -> None:
    assert assembler_mode(action, artifact_type) == planner_mode(CurriculumReadRequest(action, artifact_type))


@pytest.mark.parametrize(
    ("action", "artifact_type", "expected"),
    [
        ("remodel", "none", "bounded"),
        ("unblock", "none", "bounded"),
        ("images-are-not-needed", "none", "bounded"),
        ("model", "none", "bounded"),
        ("blocker review", "none", "bounded"),
    ],
)
def test_unknown_substring_tokens_remain_bounded(action: str, artifact_type: str, expected: str) -> None:
    assert assembler_mode(action, artifact_type) == expected
