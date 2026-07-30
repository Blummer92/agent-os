from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

import instructional_workflow_contracts.material_requirement as material_module
from instructional_workflow_contracts import (
    AuthorityEvidence,
    ContractValidationError,
    ValidationStatus,
    canonical_json_bytes,
    canonical_size,
)
from instructional_workflow_contracts.material_requirement import (
    COMPLETENESS_STATES,
    MAX_ASSETS,
    MAX_BLOCKERS,
    MAX_INPUT_BYTES,
    MAX_REASONS,
    MAX_REFERENCES,
    MAX_REQUIRED_SECTIONS,
    MAX_RESULT_BYTES,
    MAX_TEMPLATES,
    SUPPORTED_ARTIFACT_TYPES,
    material_requirement_source_fingerprint,
    validate_material_requirement,
)


def _ref(stable_id: str, owner: str) -> dict[str, object]:
    return {
        "stable_id": stable_id,
        "owner": owner,
        "contract_version": "curriculum-workflow-handoff-v1",
        "record_revision": 1,
        "fingerprint": "a" * 64,
    }


def valid_requirement() -> dict[str, object]:
    value: dict[str, object] = {
        "identity": {
            "contract_version": "curriculum-material-requirement-v1",
            "requirement_id": "requirement-1",
            "record_revision": 1,
            "course_ref": "course-1",
            "unit_ref": "unit-1",
            "lesson_ref": "lesson-1",
            "created_at": "2026-07-30T00:00:00Z",
            "created_by": "instructional-materials-coach",
            "source_fingerprint": "0" * 64,
        },
        "artifact": {"artifact_type": "worksheet", "subject_metadata": "neutral"},
        "instructional": {
            "purpose": "Provide guided practice.",
            "audience": "students",
            "required_sections": ["directions", "practice"],
        },
        "handoff_reference": {
            "handoff_id": "handoff-1",
            "contract_version": "curriculum-workflow-handoff-v1",
            "record_revision": 1,
            "fingerprint": "b" * 64,
        },
        "learning_evidence": {
            "learning_objective_ref": _ref("objective-1", "unit-alignment-agent"),
            "success_criteria_ref": _ref("criteria-1", "unit-alignment-agent"),
            "evidence_target_ref": _ref("evidence-1", "unit-alignment-agent"),
            "alignment_owner": "unit-alignment-agent",
        },
        "modeling": {
            "modeling_readiness_ref": _ref("modeling-1", "teacher-modeling-coach"),
            "materials_extract_ref": _ref("extract-1", "teacher-modeling-coach"),
            "modeling_owner": "teacher-modeling-coach",
        },
        "requirements": {
            "vocabulary_references": [_ref("vocabulary-1", "unit-alignment-agent")],
            "accessibility_requirements": ["keyboard-readable", "plain-language"],
            "content_requirements": ["cite-supplied-sources"],
            "classroom_use_requirements": ["teacher-review-before-use"],
        },
        "assets": [{
            "asset_id": "asset-1",
            "stable_ref": "asset-ref-1",
            "access_state": "verified",
            "permission_state": "permission-documented",
            "provenance_state": "confirmed",
        }],
        "templates": [{
            "template_id": "template-1",
            "stable_ref": "template-ref-1",
            "access_state": "verified",
            "permission_state": "cleared-internal",
        }],
        "destination": {
            "destination_id": "destination-1",
            "destination_class": "approved-google-drive-folder",
            "verification_state": "verified",
            "exact_reference": "approved-folder-reference-evidence",
        },
        "ai_review": {
            "ai_assisted_generation_permitted": True,
            "human_review_owner": "instructional-materials-coach",
            "accessibility_review_required": True,
            "nondiscrimination_review_required": True,
        },
        "provenance": {
            "citation_expectations": "Cite supplied sources.",
            "provenance_state": "confirmed",
            "copyright_state": "permission-documented",
            "license_state": "licensed",
            "asset_permission_state": "permission-documented",
        },
        "prohibited_data": {
            "student_identifying_data": False,
            "protected_attributes": False,
            "raw_student_work": False,
            "permanent_learner_profile": False,
        },
        "completeness": {"state": "ready-for-planning", "blockers": [], "reason_codes": []},
        "authority": {
            "execution_authorized": False,
            "external_write_authorized": False,
            "production_authorized": False,
            "publication_authorized": False,
            "side_effects_performed": False,
        },
    }
    _refresh(value)
    return value


def _refresh(value: dict[str, object]) -> None:
    value["identity"]["source_fingerprint"] = (  # type: ignore[index]
        material_requirement_source_fingerprint(value)
    )


def _result(value: dict[str, object]):
    _refresh(value)
    return validate_material_requirement(value)


def _set(value: dict[str, object], path: tuple[str, ...], replacement: object) -> None:
    target: object = value
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = replacement  # type: ignore[index]


def test_valid_is_deterministic_immutable_bounded_and_authority_false() -> None:
    supplied = valid_requirement()
    before = copy.deepcopy(supplied)
    first = validate_material_requirement(supplied)
    second = validate_material_requirement(copy.deepcopy(supplied))
    assert first.status is ValidationStatus.VALID
    assert first.record is not None and second.record is not None
    assert first.record.fingerprint == second.record.fingerprint
    assert first.authority == first.record.authority == AuthorityEvidence()
    assert first.record.to_dict()["authority"] == {
        "execution_authorized": False,
        "external_write_authorized": False,
        "production_authorized": False,
        "publication_authorized": False,
        "side_effects_performed": False,
    }
    assert canonical_size(first.record.to_dict()) <= MAX_RESULT_BYTES
    assert supplied == before


@pytest.mark.parametrize("artifact_type", sorted(SUPPORTED_ARTIFACT_TYPES))
def test_supported_artifact_types(artifact_type: str) -> None:
    value = valid_requirement()
    _set(value, ("artifact", "artifact_type"), artifact_type)
    assert _result(value).status is ValidationStatus.VALID


def test_unsupported_artifact_is_finite() -> None:
    value = valid_requirement()
    _set(value, ("artifact", "artifact_type"), "interactive-hologram")
    assert _result(value).reason_codes == ("material-unsupported-artifact-type",)


@pytest.mark.parametrize(
    ("path", "replacement", "reason"),
    [
        (("learning_evidence", "alignment_owner"), "qa-test-agent", "material-missing-owner-evidence"),
        (("learning_evidence", "learning_objective_ref", "owner"), "qa-test-agent", "material-missing-owner-evidence"),
        (("learning_evidence", "success_criteria_ref", "owner"), "qa-test-agent", "material-missing-owner-evidence"),
        (("learning_evidence", "evidence_target_ref", "owner"), "qa-test-agent", "material-missing-owner-evidence"),
        (("modeling", "modeling_owner"), "unit-alignment-agent", "material-missing-owner-evidence"),
        (("modeling", "materials_extract_ref", "owner"), "unit-alignment-agent", "material-missing-owner-evidence"),
        (("handoff_reference", "contract_version"), "future-v2", "material-incompatible-handoff"),
        (("destination", "verification_state"), "ambiguous", "material-ambiguous-destination"),
        (("assets", "0", "access_state"), "unverified", "material-unverified-asset"),
        (("templates", "0", "access_state"), "denied", "material-unverified-template"),
        (("ai_review", "human_review_owner"), "unknown-owner", "material-ai-review-owner-missing"),
        (("provenance", "license_state"), "unclear", "material-provenance-incomplete"),
        (("assets", "0", "permission_state"), "restricted", "material-permission-incomplete"),
        (("prohibited_data", "student_identifying_data"), True, "material-prohibited-data"),
    ],
)
def test_domain_failures(path: tuple[str, ...], replacement: object, reason: str) -> None:
    value = valid_requirement()
    target: object = value
    for key in path[:-1]:
        target = target[int(key)] if key.isdigit() else target[key]  # type: ignore[index]
    target[path[-1]] = replacement  # type: ignore[index]
    assert reason in _result(value).reason_codes


def test_created_at_is_evidence_only_for_source_fingerprint() -> None:
    first = valid_requirement()
    second = copy.deepcopy(first)
    second["identity"]["created_at"] = "2026-07-30T01:00:00Z"  # type: ignore[index]
    assert material_requirement_source_fingerprint(first) == (
        material_requirement_source_fingerprint(second)
    )


def test_handoff_and_source_fingerprints_fail_closed() -> None:
    malformed = valid_requirement()
    _set(malformed, ("handoff_reference", "fingerprint"), "not-a-sha")
    assert _result(malformed).status is ValidationStatus.INVALID
    incompatible = valid_requirement()
    incompatible["identity"]["source_fingerprint"] = "f" * 64  # type: ignore[index]
    assert validate_material_requirement(incompatible).reason_codes == (
        "material-incompatible-fingerprint",
    )


def test_duplicate_asset_template_and_reference_fail() -> None:
    for key, reason in (
        ("assets", "material-duplicate-asset"),
        ("templates", "material-duplicate-template"),
    ):
        value = valid_requirement()
        value[key].append(copy.deepcopy(value[key][0]))  # type: ignore[index,union-attr]
        assert reason in _result(value).reason_codes
    value = valid_requirement()
    refs = value["requirements"]["vocabulary_references"]  # type: ignore[index]
    refs.append(copy.deepcopy(refs[0]))  # type: ignore[index,union-attr]
    assert "material-duplicate-reference" in _result(value).reason_codes


@pytest.mark.parametrize("state", sorted(COMPLETENESS_STATES))
def test_completeness_never_grants_authority(state: str) -> None:
    value = valid_requirement()
    value["completeness"] = {
        "state": state,
        "blockers": ["material-incomplete"] if state == "blocked" else [],
        "reason_codes": ["material-incomplete"]
        if state in {"incomplete", "manual-review-required"}
        else [],
    }
    result = _result(value)
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    assert result.authority == result.record.authority == AuthorityEvidence()


def test_authority_fields_cannot_be_true() -> None:
    for key in valid_requirement()["authority"]:  # type: ignore[union-attr]
        value = valid_requirement()
        value["authority"][key] = True  # type: ignore[index]
        assert "authority-invalid" in _result(value).reason_codes


def test_exact_asset_template_and_section_bounds() -> None:
    assets = valid_requirement()
    assets["assets"] = [{
        "asset_id": f"asset-{index}", "stable_ref": f"asset-ref-{index}",
        "access_state": "verified", "permission_state": "permission-documented",
        "provenance_state": "confirmed",
    } for index in range(MAX_ASSETS)]
    assert _result(assets).status is ValidationStatus.VALID
    assets["assets"].append({  # type: ignore[union-attr]
        "asset_id": "asset-over", "stable_ref": "asset-ref-over",
        "access_state": "verified", "permission_state": "permission-documented",
        "provenance_state": "confirmed",
    })
    assert "handoff-oversized" in _result(assets).reason_codes

    templates = valid_requirement()
    templates["templates"] = [{
        "template_id": f"template-{index}", "stable_ref": f"template-ref-{index}",
        "access_state": "verified", "permission_state": "cleared-internal",
    } for index in range(MAX_TEMPLATES)]
    assert _result(templates).status is ValidationStatus.VALID
    templates["templates"].append({  # type: ignore[union-attr]
        "template_id": "template-over", "stable_ref": "template-ref-over",
        "access_state": "verified", "permission_state": "cleared-internal",
    })
    assert "handoff-oversized" in _result(templates).reason_codes

    sections = valid_requirement()
    sections["instructional"]["required_sections"] = [  # type: ignore[index]
        f"section-{index}" for index in range(MAX_REQUIRED_SECTIONS)
    ]
    assert _result(sections).status is ValidationStatus.VALID
    sections["instructional"]["required_sections"].append("over")  # type: ignore[index,union-attr]
    assert "handoff-oversized" in _result(sections).reason_codes


def _fit_input(target: int) -> dict[str, object]:
    value: dict[str, object] = {"identity": {"source_fingerprint": "0" * 64}, "padding": []}
    padding = value["padding"]
    while len(canonical_json_bytes(value)) < target:
        current = len(canonical_json_bytes(value))
        prefix = f"item-{len(padding):03d}-"  # type: ignore[arg-type]
        padding.append(prefix + "x" * max(1, min(512 - len(prefix), target - current)))  # type: ignore[union-attr]
        overshoot = len(canonical_json_bytes(value)) - target
        if overshoot > 0:
            padding[-1] = padding[-1][:-overshoot]  # type: ignore[index]
    assert len(canonical_json_bytes(value)) == target
    return value


def _fit_result(value: dict[str, object], target: int) -> None:
    items = value["requirements"]["content_requirements"] = []  # type: ignore[index]
    while canonical_size(value) < target:
        _refresh(value)
        current = canonical_size(value)
        prefix = f"content-{len(items):02d}-"  # type: ignore[arg-type]
        items.append(prefix + "x" * max(1, min(512 - len(prefix), target - current)))  # type: ignore[union-attr]
        _refresh(value)
        overshoot = canonical_size(value) - target
        if overshoot > 0:
            items[-1] = items[-1][:-overshoot]  # type: ignore[index]
    _refresh(value)
    assert canonical_size(value) == target


def test_exact_input_and_result_byte_bounds_and_one_over() -> None:
    payload = _fit_input(MAX_INPUT_BYTES)
    assert material_requirement_source_fingerprint(payload)
    payload["padding"][-1] += "x"  # type: ignore[index]
    with pytest.raises(ContractValidationError) as caught:
        material_requirement_source_fingerprint(payload)
    assert caught.value.reason_code == "handoff-oversized"

    value = valid_requirement()
    _fit_result(value, MAX_RESULT_BYTES)
    assert validate_material_requirement(value).status is ValidationStatus.VALID
    value["requirements"]["content_requirements"][-1] += "x"  # type: ignore[index]
    assert "handoff-oversized" in _result(value).reason_codes


def test_reference_reason_and_blocker_bounds_and_one_over() -> None:
    references = valid_requirement()
    references["assets"] = []
    references["templates"] = []
    references["requirements"]["vocabulary_references"] = [  # type: ignore[index]
        _ref(f"r-{index}", "qa-test-agent") for index in range(MAX_REFERENCES - 7)
    ]
    exact = _result(references)
    assert exact.details == ("result exceeds 12 KiB",)
    references["requirements"]["vocabulary_references"].append(  # type: ignore[index,union-attr]
        _ref("r-over", "qa-test-agent")
    )
    assert _result(references).details == ("references exceed bound",)

    for state, field, maximum in (
        ("blocked", "blockers", MAX_BLOCKERS),
        ("incomplete", "reason_codes", MAX_REASONS),
    ):
        value = valid_requirement()
        value["completeness"] = {
            "state": state,
            "blockers": [f"material-blocker-{i}" for i in range(maximum)]
            if field == "blockers" else [],
            "reason_codes": [f"material-reason-{i}" for i in range(maximum)]
            if field == "reason_codes" else [],
        }
        assert _result(value).status is ValidationStatus.VALID
        value["completeness"][field].append(f"material-{field}-over")  # type: ignore[index,union-attr]
        assert "handoff-oversized" in _result(value).reason_codes


class HostileMapping(dict):
    def __iter__(self):
        raise AssertionError("custom iteration executed")


class HostileString(str):
    pass


def test_hostile_and_unknown_values_fail_closed() -> None:
    assert validate_material_requirement(HostileMapping()).status is ValidationStatus.INVALID
    value = valid_requirement()
    value["identity"]["requirement_id"] = HostileString("requirement-1")  # type: ignore[index]
    assert "handoff-wrong-type" in validate_material_requirement(value).reason_codes
    unknown = valid_requirement()
    unknown["extra"] = {}
    assert "material-unknown-field" in _result(unknown).reason_codes


def test_shared_cw5a_helpers_are_used(monkeypatch: pytest.MonkeyPatch) -> None:
    value = valid_requirement()
    calls = {"normalize": 0, "fingerprint": 0}
    original_normalize = material_module.validate_and_normalize_json
    original_fingerprint = material_module.sha256_hex

    def normalize_spy(raw: object, *, max_bytes: int):
        calls["normalize"] += 1
        return original_normalize(raw, max_bytes=max_bytes)

    def fingerprint_spy(raw: object) -> str:
        calls["fingerprint"] += 1
        return original_fingerprint(raw)

    monkeypatch.setattr(material_module, "validate_and_normalize_json", normalize_spy)
    monkeypatch.setattr(material_module, "sha256_hex", fingerprint_spy)
    assert validate_material_requirement(value).status is ValidationStatus.VALID
    assert calls["normalize"] >= 2 and calls["fingerprint"] >= 2


def test_no_duplicate_cw5a_mechanics_or_import_side_effects() -> None:
    path = Path(__file__).parents[1] / "src/instructional_workflow_contracts/material_requirement.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    classes: set[str] = set()
    functions: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
        elif isinstance(node, ast.ClassDef):
            classes.add(node.name)
        elif isinstance(node, ast.FunctionDef):
            functions.add(node.name)
        elif isinstance(node, ast.Call):
            calls.add(node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else "")
    assert imports <= {"__future__", "typing", "common"}
    assert classes.isdisjoint({"AuthorityEvidence", "ValidationResult", "ValidationStatus", "ValidatedRecord"})
    assert functions.isdisjoint({"canonical_json_bytes", "canonical_size", "sha256_hex", "freeze_json"})
    assert calls.isdisjoint({"open", "getenv", "Popen", "run", "system", "basicConfig", "register", "import_module", "eval", "exec"})
