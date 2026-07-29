from __future__ import annotations

import ast
import copy
import dataclasses
from pathlib import Path

import pytest

from instructional_workflow_contracts import (
    CONTRACT_ID,
    FORBIDDEN_IMPORT_PREFIXES,
    MAX_BLOCKERS,
    MAX_DEPENDENCY_KEYS,
    MAX_DETAIL_LENGTH,
    MAX_NESTING_DEPTH,
    MAX_REASONS,
    MAX_REFERENCES,
    MAX_STRING_LENGTH,
    AuthorityEvidence,
    ValidationStatus,
    canonical_json_bytes,
    resolve_status,
    sha256_hex,
    validate_curriculum_handoff,
)


def _reference(suffix: str = "1") -> dict[str, str]:
    return {
        "system": "github",
        "stable_id": f"ref-{suffix}",
        "exact_location": f"issue:{suffix}",
        "verification_evidence": f"verified-{suffix}",
    }


def valid_handoff() -> dict[str, object]:
    dependency_keys = ["source.unit", "unit-alignment.objective"]
    dependency_values = {
        "source.unit": "unit-1",
        "unit-alignment.objective": "objective-1",
    }
    return {
        "identity": {
            "contract_version": CONTRACT_ID,
            "handoff_id": "handoff-1",
            "record_revision": 1,
            "request_id": "request-1",
            "course_ref": "course-1",
            "unit_ref": "unit-1",
            "lesson_ref": "lesson-1",
        },
        "source_evidence": {
            "source_record_identity": "source-1",
            "canonical_source": "github",
            "working_source": "notion",
            "exact_location": "workspace/course-1/unit-1",
            "source_confidence": "high",
            "evidence_status": "confirmed",
            "freshness_checked_at": "2026-07-29T00:00:00Z",
            "fingerprint_algorithm": "sha256",
            "source_fingerprint": "a" * 64,
            "produced_by": "unit-alignment-agent",
            "created_at": "2026-07-29T00:00:00Z",
        },
        "learning_alignment": {
            "owner": "unit-alignment-agent",
            "references": [_reference("2"), _reference("1")],
        },
        "readiness": {
            "unit_readiness": "ready-for-modeling",
            "modeling_readiness": "not-assessed",
            "materials_readiness": "not-assessed",
            "qa_status": "not-assessed",
            "teacher_approval": "not-requested",
            "classroom_ready_status": "not-assessed",
        },
        "authority": {
            "execution_authorized": False,
            "external_write_authorized": False,
            "production_authorized": False,
            "publication_authorized": False,
        },
        "reuse": {
            "candidate_references": [_reference("4"), _reference("3")],
            "selected_references": [],
            "rejected_candidates": [],
        },
        "routing": {
            "task_owner": "unit-alignment-agent",
            "mode": "Draft",
            "next_owner": "teacher-modeling-coach",
            "stop_or_continue": "continue",
            "blockers": [],
            "reason_codes": [],
            "manual_review_reasons": [],
            "required_handoff_artifacts": ["artifact-b", "artifact-a"],
            "compute_budget_class": "low",
            "permitted_destination_classes": ["notion-working", "github-evidence"],
            "unsupported_capability_findings": [],
        },
        "dependencies": {
            "dependency_keys": dependency_keys,
            "dependency_values": dependency_values,
            "dependency_fingerprint": sha256_hex(
                {
                    "dependency_keys": sorted(dependency_keys),
                    "dependency_values": dependency_values,
                }
            ),
            "upstream_contract_ref": "curriculum-contract-1",
            "upstream_record_revision": 1,
            "upstream_change_detected": False,
            "changed_dependency_keys": [],
            "impacted_output_refs": [],
            "unmapped_dependency_keys": [],
            "revalidation_scope": "none",
            "confidence": "high",
            "human_review_required": False,
        },
        "stage_payload": {
            "owner": "unit-alignment-agent",
            "payload": {
                "learning_objective": "Explain the evidence target.",
                "success_criteria": ["criterion-1", "criterion-2"],
                "essential_questions": ["question-1", "question-2"],
                "blockers": [],
                "ready_for_modeling": True,
            },
        },
        "audit": {
            "entries": [
                {
                    "owner": "unit-alignment-agent",
                    "action": "created",
                    "created_at": "2026-07-29T00:00:00Z",
                    "record_revision": 1,
                }
            ]
        },
    }


def test_valid_handoff_is_deterministic_and_immutable() -> None:
    supplied = valid_handoff()
    before = copy.deepcopy(supplied)
    first = validate_curriculum_handoff(supplied)
    second = validate_curriculum_handoff(copy.deepcopy(supplied))

    assert first.status is ValidationStatus.VALID
    assert first.record is not None
    assert second.record is not None
    assert first.record.fingerprint == second.record.fingerprint
    assert canonical_json_bytes(first.record.to_dict()) == canonical_json_bytes(second.record.to_dict())
    assert supplied == before
    assert first.record.to_dict() is not supplied
    assert dataclasses.is_dataclass(first.record)
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.record.record_revision = 2  # type: ignore[misc]


def test_semantic_sets_sort_while_instructional_lists_preserve_order() -> None:
    left = valid_handoff()
    right = valid_handoff()
    right["routing"]["required_handoff_artifacts"].reverse()  # type: ignore[index,union-attr]
    right["learning_alignment"]["references"].reverse()  # type: ignore[index,union-attr]
    right["stage_payload"]["payload"]["success_criteria"].reverse()  # type: ignore[index,union-attr]

    left_result = validate_curriculum_handoff(left)
    right_result = validate_curriculum_handoff(right)
    assert left_result.record is not None and right_result.record is not None
    left_dict = left_result.record.to_dict()
    right_dict = right_result.record.to_dict()
    assert left_dict["routing"]["required_handoff_artifacts"] == right_dict["routing"]["required_handoff_artifacts"]
    assert left_dict["learning_alignment"]["references"] == right_dict["learning_alignment"]["references"]
    assert left_dict["stage_payload"]["payload"]["success_criteria"] != right_dict["stage_payload"]["payload"]["success_criteria"]
    assert left_result.record.fingerprint != right_result.record.fingerprint


def test_authority_is_always_false() -> None:
    result = validate_curriculum_handoff(valid_handoff())
    assert result.record is not None
    assert result.authority == AuthorityEvidence()
    assert result.record.authority == AuthorityEvidence()
    assert result.record.to_dict()["authority"] == {
        "execution_authorized": False,
        "external_write_authorized": False,
        "production_authorized": False,
        "publication_authorized": False,
    }


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda value: value.pop("audit"), "handoff-invalid"),
        (lambda value: value.__setitem__("extra", {}), "handoff-unknown-field"),
        (lambda value: value["identity"].__setitem__("record_revision", True), "identity-invalid"),
        (lambda value: value["identity"].__setitem__("contract_version", "future-v2"), "handoff-version-unsupported"),
        (lambda value: value["identity"].__setitem__("schema_version", "1"), "handoff-unknown-field"),
        (lambda value: value["routing"].__setitem__("status", "ready"), "handoff-unknown-field"),
        (lambda value: value["authority"].__setitem__("execution_authorized", True), "authority-invalid"),
        (lambda value: value["stage_payload"].__setitem__("owner", "qa-test-agent"), "ownership-owner-conflict"),
        (lambda value: value["stage_payload"]["payload"].__setitem__("recommendation", "pass"), "ownership-owner-conflict"),
        (lambda value: value["dependencies"].__setitem__("dependency_fingerprint", "b" * 64), "dependency-invalid"),
        (lambda value: value["routing"].__setitem__("reason_codes", ["blocked"]), "handoff-invalid"),
        (lambda value: value["identity"].__setitem__("handoff_id", "bad id"), "identity-invalid"),
    ],
)
def test_field_and_contract_failures(mutation, reason: str) -> None:
    value = valid_handoff()
    mutation(value)
    result = validate_curriculum_handoff(value)
    assert result.status is ValidationStatus.INVALID
    assert result.record is None
    assert reason in result.reason_codes


class EvilInt(int):
    pass


class EvilString(str):
    pass


class EvilDict(dict):
    def items(self):  # pragma: no cover - must never execute
        raise AssertionError("custom items executed")


class EvilIterable:
    def __iter__(self):  # pragma: no cover - must never execute
        raise AssertionError("custom iterator executed")

    def __repr__(self):  # pragma: no cover - must never execute
        raise AssertionError("custom repr executed")


@pytest.mark.parametrize(
    "replacement",
    [EvilInt(1), EvilString("handoff-1"), EvilDict(), EvilIterable()],
)
def test_malicious_subclasses_and_objects_are_rejected_without_coercion(replacement: object) -> None:
    value = valid_handoff()
    value["identity"]["handoff_id"] = replacement  # type: ignore[index]
    result = validate_curriculum_handoff(value)
    assert result.status is ValidationStatus.INVALID
    assert result.record is None
    assert "handoff-wrong-type" in result.reason_codes


class EvilKey(str):
    def __lt__(self, other):  # pragma: no cover - must never execute
        raise AssertionError("custom key comparison executed")


def test_malicious_mapping_key_is_rejected_before_sorting() -> None:
    value = valid_handoff()
    value[EvilKey("audit2")] = {}
    result = validate_curriculum_handoff(value)
    assert result.status is ValidationStatus.INVALID
    assert "handoff-wrong-type" in result.reason_codes


def test_public_canonical_serializer_rejects_custom_objects_without_coercion() -> None:
    with pytest.raises(Exception) as caught:
        canonical_json_bytes(EvilIterable())
    assert "exact built-in JSON-compatible types" in str(caught.value)


def test_duplicate_ids_and_dependency_keys_fail_closed() -> None:
    duplicate_ref = valid_handoff()
    duplicate_ref["learning_alignment"]["references"] = [_reference("1"), _reference("1")]  # type: ignore[index]
    assert "identity-duplicate" in validate_curriculum_handoff(duplicate_ref).reason_codes

    duplicate_key = valid_handoff()
    duplicate_key["dependencies"]["dependency_keys"] = ["source.unit", "source.unit"]  # type: ignore[index]
    result = validate_curriculum_handoff(duplicate_key)
    assert result.status is ValidationStatus.INVALID
    assert "handoff-duplicate" in result.reason_codes


def test_unknown_dependency_namespace_fails_closed() -> None:
    value = valid_handoff()
    value["dependencies"]["dependency_keys"] = ["unknown.value"]  # type: ignore[index]
    value["dependencies"]["dependency_values"] = {"unknown.value": "x"}  # type: ignore[index]
    result = validate_curriculum_handoff(value)
    assert result.status is ValidationStatus.INVALID
    assert "dependency-invalid" in result.reason_codes


def test_string_control_injection_and_secret_keys_are_rejected_without_echo() -> None:
    for payload, expected in (
        ("x" * (MAX_STRING_LENGTH + 1), "handoff-invalid"),
        ("bad\nvalue", "handoff-invalid"),
        ("${{ secrets.TOKEN }}", "handoff-invalid"),
    ):
        value = valid_handoff()
        value["stage_payload"]["payload"]["learning_objective"] = payload  # type: ignore[index]
        result = validate_curriculum_handoff(value)
        assert result.status is ValidationStatus.INVALID
        assert expected in result.reason_codes
        assert payload not in " ".join(result.details)

    secret = valid_handoff()
    secret["stage_payload"]["payload"]["api_key"] = "not-a-real-secret"  # type: ignore[index]
    result = validate_curriculum_handoff(secret)
    assert result.status is ValidationStatus.INVALID
    assert "authority-secret-field" in result.reason_codes
    assert "not-a-real-secret" not in " ".join(result.details)


def test_collection_bounds() -> None:
    cases = []
    blockers = valid_handoff()
    blockers["routing"]["blockers"] = [f"routing-blocked-{index}" for index in range(MAX_BLOCKERS + 1)]  # type: ignore[index]
    cases.append(blockers)
    reasons = valid_handoff()
    reasons["routing"]["reason_codes"] = [f"routing-note-{index}" for index in range(MAX_REASONS + 1)]  # type: ignore[index]
    cases.append(reasons)
    dependencies = valid_handoff()
    keys = [f"source.key-{index}" for index in range(MAX_DEPENDENCY_KEYS + 1)]
    dependencies["dependencies"]["dependency_keys"] = keys  # type: ignore[index]
    dependencies["dependencies"]["dependency_values"] = {key: index for index, key in enumerate(keys)}  # type: ignore[index]
    cases.append(dependencies)
    references = valid_handoff()
    references["learning_alignment"]["references"] = [_reference(str(index)) for index in range(MAX_REFERENCES + 1)]  # type: ignore[index]
    cases.append(references)

    for value in cases:
        result = validate_curriculum_handoff(value)
        assert result.status is ValidationStatus.INVALID
        assert "handoff-oversized" in result.reason_codes


def test_total_input_result_and_depth_bounds() -> None:
    input_too_large = valid_handoff()
    input_too_large["stage_payload"]["payload"]["essential_questions"] = ["x" * 500 for _ in range(140)]  # type: ignore[index]
    result = validate_curriculum_handoff(input_too_large)
    assert result.status is ValidationStatus.INVALID
    assert "handoff-oversized" in result.reason_codes

    result_too_large = valid_handoff()
    result_too_large["stage_payload"]["payload"]["essential_questions"] = ["x" * 400 for _ in range(45)]  # type: ignore[index]
    result = validate_curriculum_handoff(result_too_large)
    assert result.status is ValidationStatus.INVALID
    assert "handoff-oversized" in result.reason_codes

    nested = valid_handoff()
    deep: object = "end"
    for _ in range(MAX_NESTING_DEPTH + 2):
        deep = [deep]
    nested["stage_payload"]["payload"]["essential_questions"] = deep  # type: ignore[index]
    result = validate_curriculum_handoff(nested)
    assert result.status is ValidationStatus.INVALID
    assert "handoff-oversized" in result.reason_codes


def test_diagnostics_are_bounded_and_do_not_echo_raw_values() -> None:
    value = valid_handoff()
    raw = "TOP-SECRET-" + "z" * 800
    value["identity"]["handoff_id"] = raw  # type: ignore[index]
    result = validate_curriculum_handoff(value)
    assert result.status is ValidationStatus.INVALID
    assert all(len(detail) <= MAX_DETAIL_LENGTH for detail in result.details)
    assert raw not in " ".join(result.details)


def test_status_precedence_and_distinct_states() -> None:
    assert resolve_status(()) is ValidationStatus.VALID
    assert resolve_status(("manual-review-inspection",), manual_review=True) is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert resolve_status(("source-stale",), stale=True) is ValidationStatus.STALE
    assert resolve_status((), ("routing-blocked-dependency",)) is ValidationStatus.BLOCKED
    assert resolve_status(
        ("handoff-invalid", "source-stale", "manual-review-inspection"),
        ("routing-blocked-dependency",),
        stale=True,
        manual_review=True,
    ) is ValidationStatus.INVALID


def test_validated_nonvalid_results_preserve_record() -> None:
    blocked = valid_handoff()
    blocked["routing"]["blockers"] = ["routing-blocked-dependency"]  # type: ignore[index]
    blocked_result = validate_curriculum_handoff(blocked)
    assert blocked_result.status is ValidationStatus.BLOCKED
    assert blocked_result.record is not None

    stale = valid_handoff()
    stale["source_evidence"]["evidence_status"] = "stale"  # type: ignore[index]
    stale["routing"]["reason_codes"] = ["source-stale"]  # type: ignore[index]
    stale_result = validate_curriculum_handoff(stale)
    assert stale_result.status is ValidationStatus.STALE
    assert stale_result.record is not None

    manual = valid_handoff()
    manual["routing"]["manual_review_reasons"] = ["manual-review-inspection"]  # type: ignore[index]
    manual_result = validate_curriculum_handoff(manual)
    assert manual_result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert manual_result.record is not None


def test_import_policy_and_no_side_effect_calls() -> None:
    package_root = Path(__file__).parents[1] / "src" / "instructional_workflow_contracts"
    allowed_common = {
        "__future__",
        "hashlib",
        "json",
        "math",
        "re",
        "dataclasses",
        "enum",
        "typing",
    }
    allowed_handoff = {"__future__", "typing", "common"}

    for path in package_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports: set[str] = set()
        calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.add(node.func.attr)
        for imported in imports:
            assert not any(
                imported == forbidden or imported.startswith(forbidden + ".")
                for forbidden in FORBIDDEN_IMPORT_PREFIXES
            )
        if path.name == "common.py":
            assert imports <= allowed_common
        elif path.name == "handoff.py":
            assert all(item in allowed_handoff or item.endswith(".common") for item in imports)
        assert calls.isdisjoint(
            {
                "open",
                "getenv",
                "environ",
                "Popen",
                "run",
                "system",
                "basicConfig",
                "register",
                "import_module",
                "eval",
                "exec",
            }
        )


def test_package_exports_are_explicit() -> None:
    import instructional_workflow_contracts as package

    assert package.__all__
    assert "validate_curriculum_handoff" in package.__all__
    assert not hasattr(package, "requests")
    assert not hasattr(package, "subprocess")
