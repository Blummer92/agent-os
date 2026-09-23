from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

from instructional_evidence_intake import CONTRACT_ID, interpret_teacher_summary
from instructional_workflow_contracts import ValidationStatus, canonical_json_bytes


def _authority() -> dict[str, bool]:
    return {
        "grading_authorized": False,
        "mastery_authorized": False,
        "readiness_authorized": False,
        "learner_classification_authorized": False,
        "placement_authorized": False,
        "route_assignment_authorized": False,
        "pacing_execution_authorized": False,
        "production_authorized": False,
        "publication_authorized": False,
        "external_write_authorized": False,
    }


def _payload() -> dict[str, object]:
    return {
        "identity": {
            "contract_version": CONTRACT_ID,
            "record_id": "teacher-summary-1",
            "record_revision": 1,
        },
        "source_evidence": {
            "source_ref": "source-summary-1",
            "source_type": "teacher-summary",
            "observed_on": "2026-07-29",
            "privacy_eligible": True,
            "freshness": "current",
            "measurement_quality": "sufficient",
        },
        "observed_evidence": {
            "objective_refs": ["objective-1"],
            "prerequisite_refs": [],
            "success_criteria_refs": ["criterion-1"],
            "depth_demands": ["explain"],
            "performance_formats": ["written-explanation"],
            "tools_and_routines": ["claim-evidence-reasoning"],
            "representation_demands": ["written-text"],
            "work_modes": ["independent"],
            "evidence_quality": "sufficient",
            "evaluation_basis": "teacher-confirmed",
            "response_type": "closed",
            "support_conditions": [],
            "prompting": "none",
            "revision": "none",
            "independence": "independent",
        },
        "current_assignment": {
            "objective_refs": ["objective-1"],
            "prerequisite_refs": [],
            "success_criteria_refs": ["criterion-1"],
            "depth_demands": ["explain"],
            "performance_formats": ["written-explanation"],
            "tools_and_routines": ["claim-evidence-reasoning"],
            "representation_demands": ["written-text"],
            "work_modes": ["independent"],
        },
        "interpretation_context": {
            "contradictions": [],
            "uncertainties": [],
            "manual_review_requested": False,
        },
        "authority": _authority(),
    }


def _output(payload: dict[str, object]) -> dict[str, object]:
    result = interpret_teacher_summary(payload)
    assert result.record is not None
    return result.record.to_dict()


def test_teacher_summary_mode_succeeds_without_ocr() -> None:
    result = interpret_teacher_summary(_payload())
    assert result.status is ValidationStatus.VALID
    assert _output(_payload())["alignment"]["overall_disposition"] == "direct-evidence"


def test_output_is_byte_deterministic_and_input_is_immutable() -> None:
    payload = _payload()
    original = copy.deepcopy(payload)
    first = interpret_teacher_summary(payload)
    second = interpret_teacher_summary(copy.deepcopy(payload))
    assert payload == original
    assert first.record is not None and second.record is not None
    assert first.record.fingerprint == second.record.fingerprint
    assert canonical_json_bytes(first.record.payload) == canonical_json_bytes(second.record.payload)


def test_returned_record_does_not_share_mutable_input() -> None:
    payload = _payload()
    result = interpret_teacher_summary(payload)
    assert result.record is not None
    payload["current_assignment"]["objective_refs"].append("objective-2")
    assert result.record.to_dict()["alignment"]["what_supported"] == [
        "claim-evidence-reasoning",
        "criterion-1",
        "explain",
        "independent",
        "objective-1",
        "written-explanation",
        "written-text",
    ]


def test_identification_for_explanation_is_partial() -> None:
    payload = _payload()
    payload["observed_evidence"]["performance_formats"] = ["identification"]
    result = _output(payload)
    assert result["alignment"]["overall_disposition"] == "partial-evidence"
    assert "performance-format" in result["alignment"]["what_remains_unmeasured"]


def test_tool_familiarity_is_context_only() -> None:
    payload = _payload()
    payload["observed_evidence"]["objective_refs"] = ["objective-other"]
    payload["observed_evidence"]["success_criteria_refs"] = []
    payload["observed_evidence"]["depth_demands"] = []
    payload["observed_evidence"]["performance_formats"] = []
    payload["observed_evidence"]["representation_demands"] = []
    payload["observed_evidence"]["work_modes"] = []
    result = _output(payload)
    assert result["alignment"]["overall_disposition"] == "context-evidence"


def test_same_vocabulary_with_different_objective_is_not_comparable() -> None:
    payload = _payload()
    for field in (
        "objective_refs",
        "prerequisite_refs",
        "success_criteria_refs",
        "depth_demands",
        "performance_formats",
        "tools_and_routines",
        "representation_demands",
        "work_modes",
    ):
        payload["observed_evidence"][field] = []
    payload["observed_evidence"]["objective_refs"] = ["topic-overlap-only"]
    result = _output(payload)
    assert result["alignment"]["overall_disposition"] == "not-comparable"


@pytest.mark.parametrize(
    ("group", "field", "value"),
    [
        ("source_evidence", "privacy_eligible", False),
        ("source_evidence", "freshness", "stale"),
        ("source_evidence", "measurement_quality", "unknown"),
        ("observed_evidence", "evidence_quality", "insufficient"),
    ],
)
def test_fail_closed_conditions_route_to_manual_review(
    group: str, field: str, value: object
) -> None:
    payload = _payload()
    payload[group][field] = value
    result = interpret_teacher_summary(payload)
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.record is not None
    assert result.record.to_dict()["alignment"]["overall_disposition"] == "uncertain"


def test_contradiction_and_uncertainty_remain_visible() -> None:
    payload = _payload()
    payload["interpretation_context"]["contradictions"] = ["recent-evidence-conflicts"]
    payload["interpretation_context"]["uncertainties"] = ["measurement-basis-unclear"]
    output = _output(payload)
    assert output["alignment"]["contradictions"] == ["recent-evidence-conflicts"]
    assert output["alignment"]["uncertainties"] == ["measurement-basis-unclear"]
    assert output["alignment"]["manual_review_required"] is True


def test_missing_evaluation_prevents_direct_correctness_inference() -> None:
    payload = _payload()
    payload["observed_evidence"]["evaluation_basis"] = "none"
    output = _output(payload)
    assert output["alignment"]["overall_disposition"] == "partial-evidence"
    assert "correctness-without-supplied-evaluation" in output["alignment"]["what_remains_unmeasured"]


def test_open_ended_without_teacher_judgment_requires_review() -> None:
    payload = _payload()
    payload["observed_evidence"]["response_type"] = "open-ended"
    payload["observed_evidence"]["evaluation_basis"] = "structured-rule"
    assert interpret_teacher_summary(payload).status is ValidationStatus.MANUAL_REVIEW_REQUIRED


def test_support_context_does_not_create_learner_labels() -> None:
    payload = _payload()
    payload["observed_evidence"].update(
        {
            "support_conditions": ["sentence-stems"],
            "prompting": "some",
            "revision": "used",
            "independence": "supported",
        }
    )
    serialized = canonical_json_bytes(_output(payload)).decode("utf-8")
    for prohibited in ("struggling", "gifted", "advanced", "behind", "learner_profile"):
        assert prohibited not in serialized


def test_all_authority_fields_are_immutable_false() -> None:
    assert _output(_payload())["authority"] == _authority()
    payload = _payload()
    payload["authority"]["grading_authorized"] = True
    result = interpret_teacher_summary(payload)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("authority-invalid",)


@pytest.mark.parametrize("bad_value", [True, 1.0, {"x": "y"}, ("objective-1",)])
def test_exact_builtin_list_enforcement(bad_value: object) -> None:
    payload = _payload()
    payload["observed_evidence"]["objective_refs"] = bad_value
    assert interpret_teacher_summary(payload).status is ValidationStatus.INVALID


def test_boolean_is_not_accepted_as_revision() -> None:
    payload = _payload()
    payload["identity"]["record_revision"] = True
    assert interpret_teacher_summary(payload).status is ValidationStatus.INVALID


def test_unknown_field_and_version_fail_closed() -> None:
    payload = _payload()
    payload["unexpected"] = "value"
    assert interpret_teacher_summary(payload).reason_codes == ("handoff-unknown-field",)
    payload = _payload()
    payload["identity"]["contract_version"] = "future-version"
    assert interpret_teacher_summary(payload).reason_codes == ("handoff-version-unsupported",)


def test_collection_bounds_and_duplicate_values_fail_closed() -> None:
    payload = _payload()
    payload["observed_evidence"]["objective_refs"] = [f"objective-{i}" for i in range(65)]
    assert interpret_teacher_summary(payload).reason_codes == ("handoff-oversized",)
    payload = _payload()
    payload["observed_evidence"]["objective_refs"] = ["objective-1", "objective-1"]
    assert interpret_teacher_summary(payload).reason_codes == ("handoff-duplicate",)


def test_hostile_object_is_rejected_without_echo_or_repr() -> None:
    class Hostile:
        def __repr__(self) -> str:
            raise AssertionError("repr must not run")

    payload = _payload()
    payload["observed_evidence"]["objective_refs"] = [Hostile()]
    result = interpret_teacher_summary(payload)
    assert result.status is ValidationStatus.INVALID
    assert "Hostile" not in " ".join(result.details)


def test_input_byte_and_depth_bounds_fail_closed() -> None:
    payload = _payload()
    payload["source_evidence"]["observed_on"] = "x" * 513
    assert interpret_teacher_summary(payload).status is ValidationStatus.INVALID
    payload = _payload()
    payload["unexpected"] = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": "x"}}}}}}}}}
    assert interpret_teacher_summary(payload).status is ValidationStatus.INVALID


def test_no_grades_mastery_profiles_placement_routes_or_readiness_outputs() -> None:
    serialized = canonical_json_bytes(_output(_payload())).decode("utf-8")
    for prohibited in (
        '"grade"',
        '"score"',
        '"mastery"',
        '"learner_profile"',
        '"placement"',
        '"route"',
        '"readiness"',
    ):
        assert prohibited not in serialized


def test_import_graph_is_offline_and_side_effect_free() -> None:
    root = Path(__file__).parents[1] / "src" / "instructional_evidence_intake"
    forbidden = {
        "os",
        "pathlib",
        "subprocess",
        "socket",
        "requests",
        "httpx",
        "urllib",
        "importlib",
        "logging",
        "notion",
        "google",
        "paddle",
        "torch",
        "transformers",
    }
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        assert not (imports & forbidden)


def test_shared_core_is_used_instead_of_duplicate_generic_mechanics() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "instructional_evidence_intake"
        / "interpreter.py"
    ).read_text(encoding="utf-8")
    for required in (
        "validate_and_normalize_json",
        "validate_stable_id",
        "validate_version",
        "validate_revision",
        "canonical_size",
        "sha256_hex",
        "freeze_json",
        "ValidatedRecord",
        "ValidationResult",
        "ValidationStatus",
    ):
        assert required in source
    assert "json.dumps" not in source
    assert "hashlib" not in source
