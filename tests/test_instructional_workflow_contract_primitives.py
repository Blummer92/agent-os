"""Behavioral locks for the shared contract primitives consolidated under #1738.

The four primitives replace twenty-four byte-equivalent private helpers that
previously lived in individual contract modules. Existing suites already cover
most of their behavior; these cases pin the failure semantics a mutation probe
showed were otherwise unobservable, plus a structural guard that keeps the
reduction from silently regrowing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import instructional_workflow_contracts.common as common_module
from instructional_workflow_contracts import ContractValidationError, ValidationStatus

PACKAGE = Path(__file__).parents[1] / "src" / "instructional_workflow_contracts"

# Modules whose duplicate helper was migrated onto the canonical primitive.
MIGRATED = {
    "artifact_manifest.py": {"validate_mapping"},
    "cohesive_visual_plan.py": {"invalid_result"},
    "conversational_unit_knowledge.py": {"validate_mapping", "validate_bounded_list", "validate_exact_fields"},
    "current_curriculum_state.py": {"validate_mapping", "invalid_result"},
    "experiment_evidence.py": {"validate_mapping", "validate_bounded_list", "validate_exact_fields"},
    "handoff.py": {"invalid_result"},
    "image_intent.py": {"validate_mapping", "invalid_result"},
    "material_requirement.py": {"invalid_result"},
    "mixed_class_pathway.py": {"validate_mapping", "validate_exact_fields"},
    "request_interpretation.py": {"validate_mapping", "validate_bounded_list", "validate_exact_fields"},
    "visual_asset_candidates.py": {"invalid_result"},
    "visual_asset_compatibility.py": {"validate_mapping", "invalid_result"},
    "visual_needs.py": {"validate_mapping", "invalid_result"},
}

# Same-named helpers deliberately left local because their semantics differ.
# Flattening these onto the shared primitives would change contract behavior.
LOCAL_VARIANTS = {
    "artifact_manifest.py": {"_invalid", "_list"},
    "current_curriculum_evidence.py": {"_mapping"},
    "material_requirement.py": {"_mapping", "_list"},
    "mixed_class_pathway.py": {"_invalid"},
    "reuse_planner.py": {"_invalid"},
}


def _module_functions(name: str) -> set[str]:
    tree = ast.parse((PACKAGE / name).read_text(encoding="utf-8"))
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


def _common_imports(name: str) -> set[str]:
    tree = ast.parse((PACKAGE / name).read_text(encoding="utf-8"))
    return {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "common"
        for alias in node.names
    }


def test_validate_mapping_rejects_non_dict_with_exact_failure_semantics() -> None:
    assert common_module.validate_mapping({"a": 1}, "payload") == {"a": 1}
    for value in ([], "text", None, 1):
        with pytest.raises(ContractValidationError) as excinfo:
            common_module.validate_mapping(value, "payload")
        assert excinfo.value.reason_code == "handoff-wrong-type"
        assert excinfo.value.detail == "payload must be a built-in mapping"


def test_validate_mapping_rejects_dict_subclasses() -> None:
    class Mapping(dict):
        pass

    with pytest.raises(ContractValidationError) as excinfo:
        common_module.validate_mapping(Mapping(a=1), "payload")
    assert excinfo.value.reason_code == "handoff-wrong-type"


def test_validate_bounded_list_failure_semantics() -> None:
    assert common_module.validate_bounded_list([1, 2], "items", 2) == [1, 2]

    with pytest.raises(ContractValidationError) as wrong_type:
        common_module.validate_bounded_list(("a",), "items", 2)
    assert wrong_type.value.reason_code == "handoff-wrong-type"
    assert wrong_type.value.detail == "items must be a built-in list"

    with pytest.raises(ContractValidationError) as oversized:
        common_module.validate_bounded_list([1, 2, 3], "items", 2)
    assert oversized.value.reason_code == "handoff-oversized"
    assert oversized.value.detail == "items exceeds its collection bound"


def test_validate_exact_fields_distinguishes_unknown_from_missing() -> None:
    expected = frozenset({"a", "b"})
    assert common_module.validate_exact_fields({"a": 1, "b": 2}, expected, "record") is None

    with pytest.raises(ContractValidationError) as unknown:
        common_module.validate_exact_fields({"a": 1, "b": 2, "c": 3}, expected, "record")
    assert unknown.value.reason_code == "handoff-unknown-field"
    assert unknown.value.detail == "record contains unknown fields"

    with pytest.raises(ContractValidationError) as missing:
        common_module.validate_exact_fields({"a": 1}, expected, "record")
    assert missing.value.reason_code == "handoff-invalid"
    assert missing.value.detail == "record is missing required fields"


def test_validate_exact_fields_reports_unknown_when_both_differ() -> None:
    with pytest.raises(ContractValidationError) as excinfo:
        common_module.validate_exact_fields({"a": 1, "c": 3}, frozenset({"a", "b"}), "record")
    assert excinfo.value.reason_code == "handoff-unknown-field"


def test_invalid_result_shape_and_detail_sanitization() -> None:
    result = common_module.invalid_result("handoff-invalid", "payload <script>alert(1)</script>")
    assert result.status is ValidationStatus.INVALID
    assert result.record is None
    assert result.reason_codes == ("handoff-invalid",)
    assert "<script>" not in result.details[0]
    assert result.details[0].startswith("payload [redacted]")
    assert result.authority.execution_authorized is False
    assert result.authority.external_write_authorized is False


def test_invalid_result_rejects_ungoverned_reason_codes() -> None:
    # ValidationResult canonicalizes reason codes, so the shared constructor stays
    # fail-closed without the call-site prevalidation the local variants perform.
    with pytest.raises(ValueError, match="canonical namespaces"):
        common_module.invalid_result("not-a-governed-reason", "detail")


@pytest.mark.parametrize("module_name", sorted(MIGRATED))
def test_migrated_modules_use_the_canonical_primitives(module_name: str) -> None:
    imported = _common_imports(module_name)
    assert MIGRATED[module_name] <= imported, module_name

    defined = _module_functions(module_name)
    migrated_spellings = {
        "validate_mapping": "_mapping",
        "validate_bounded_list": "_list",
        "validate_exact_fields": "_exact",
        "invalid_result": "_invalid",
    }
    for canonical in MIGRATED[module_name]:
        local = migrated_spellings[canonical]
        if local in LOCAL_VARIANTS.get(module_name, set()):
            continue
        assert local not in defined, f"{module_name} redefines {local}"
        assert f"{local}_fields" not in defined, f"{module_name} redefines {local}_fields"


@pytest.mark.parametrize("module_name", sorted(LOCAL_VARIANTS))
def test_semantic_variants_remain_local(module_name: str) -> None:
    """These helpers differ from the shared primitives and must not be flattened."""
    defined = _module_functions(module_name)
    assert LOCAL_VARIANTS[module_name] <= defined, module_name
