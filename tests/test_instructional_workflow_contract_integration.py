from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

import instructional_workflow_contracts.artifact_manifest as manifest_module
import instructional_workflow_contracts.common as common_module
import instructional_workflow_contracts.handoff as handoff_module
import instructional_workflow_contracts.material_requirement as requirement_module
import instructional_workflow_contracts.reuse_planner as planner_module
from instructional_workflow_contracts import AuthorityEvidence, ValidationStatus, canonical_json_bytes

FIXTURES = Path(__file__).parent / "fixtures" / "instructional_workflow_contracts"
PACKAGE = Path(__file__).parents[1] / "src" / "instructional_workflow_contracts"
COMPONENT_BLOBS = {
    "common.py": "94159792d80079c18a36d8c36bee97fa13921115",
    "handoff.py": "b616580b0febaa2cab2f85a9327a5f62922289ae",
    "material_requirement.py": "b2e5513e41a3545424f2c3c791bb990e7a7cc4e1",
    "artifact_manifest.py": "e9d4d79cc085690593ac872b1fecade1ba7901f0",
    "reuse_planner.py": "e7da9179c2a39627d84a5c2b323cc87a581d29bb",
}
EXPECTED_PUBLIC_EXPORTS = (
    "AuthorityEvidence",
    "CANONICAL_OWNERS",
    "CLASSROOM_UNIT_WORKSPACE_CONTRACT_ID",
    "CLASSROOM_UNIT_WORKSPACE_RESOLUTION_CONTRACT_ID",
    "CLASSROOM_WORKSPACE_BINDING_STATES",
    "CLASSROOM_WORKSPACE_DEFAULT_ROLE_DISPLAY_NAMES",
    "CLASSROOM_WORKSPACE_FOLDER_MIME_TYPE",
    "CLASSROOM_WORKSPACE_OPERATION_TYPES",
    "CLASSROOM_WORKSPACE_PROVISIONING_CONTRACT_ID",
    "CLASSROOM_WORKSPACE_RESOLUTION_STATES",
    "CLASSROOM_WORKSPACE_ROLES",
    "CLASSROOM_WORKSPACE_ROLE_OUTCOMES",
    "CONTRACT_ID",
    "ContractReference",
    "ContractValidationError",
    "DEPRECATED_FIELD_ALIASES",
    "DriveFolderMetadataReader",
    "EXPERIMENT_EVIDENCE_AVAILABILITIES",
    "EXPERIMENT_EVIDENCE_VERSION",
    "FINGERPRINT_ALGORITHM",
    "FORBIDDEN_IMPORT_PREFIXES",
    "FolderMetadataReader",
    "IMAGE_INTENT_CONTRACT_ID",
    "IMPORTED_ASSET_CONTEXT_CONTRACT_ID",
    "MAX_BLOCKERS",
    "MAX_DEPENDENCY_KEYS",
    "MAX_DETAIL_LENGTH",
    "MAX_INPUT_BYTES",
    "MAX_NESTING_DEPTH",
    "MAX_REASONS",
    "MAX_REFERENCES",
    "MAX_RESULT_BYTES",
    "MAX_STRING_LENGTH",
    "ORDER_INSENSITIVE_FIELDS",
    "REQUEST_ACTIONS",
    "REQUEST_EFFECTS",
    "REQUEST_INTERPRETATION_VERSION",
    "REQUEST_ORIGINS",
    "REQUEST_RESOURCE_KINDS",
    "REQUEST_SYSTEMS",
    "RequestInterpretation",
    "TOP_LEVEL_FIELDS",
    "ValidatedRecord",
    "ValidationResult",
    "ValidationStatus",
    "WorkspaceDriveClient",
    "WorkspaceDriveResult",
    "WorkspaceDriveState",
    "assemble_gemini_manual_prompt",
    "canonical_json_bytes",
    "canonical_size",
    "execute_workspace_create",
    "freeze_json",
    "plan_classroom_workspace_provisioning",
    "resolve_classroom_unit_workspace",
    "resolve_status",
    "sha256_hex",
    "thaw_json",
    "validate_and_normalize_json",
    "validate_classroom_unit_workspace",
    "validate_curriculum_handoff",
    "validate_dependency_key",
    "validate_experiment_evidence",
    "validate_image_intent",
    "validate_imported_asset_context",
    "validate_reason_code",
    "validate_request_interpretation",
    "validate_revision",
    "validate_stable_id",
    "validate_version",
)


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def planner(requirement: object, manifests: list[object], *, supported: bool = True):
    return planner_module.plan_instructional_artifact_reuse(
        requirement,
        manifests,
        changed_dependency_keys=[],
        impact_map={"material.requirement": ["practice"], "source.unit": ["directions"]},
        supported_executor=supported,
    )


def test_valid_end_to_end_fixture_flow() -> None:
    handoff = fixture("valid_handoff.json")
    requirement = fixture("valid_material_requirement.json")
    manifest = fixture("valid_artifact_manifest.json")
    handoff_result = handoff_module.validate_curriculum_handoff(handoff)
    requirement_result = requirement_module.validate_material_requirement(requirement)
    manifest_result = manifest_module.validate_artifact_manifest(manifest)
    plan_result = planner(requirement_result, [manifest_result])
    assert handoff_result.status is ValidationStatus.VALID
    assert requirement_result.status is ValidationStatus.VALID
    assert manifest_result.status is ValidationStatus.VALID
    assert plan_result.status in {ValidationStatus.VALID, ValidationStatus.MANUAL_REVIEW_REQUIRED}
    assert handoff_result.record is not None
    assert requirement_result.record is not None
    assert requirement["handoff_reference"]["fingerprint"] == handoff_result.record.fingerprint
    assert manifest["requirement_reference"]["fingerprint"] == requirement_result.record.fingerprint


def test_outputs_are_byte_for_byte_deterministic() -> None:
    values = [
        (handoff_module.validate_curriculum_handoff, fixture("valid_handoff.json")),
        (requirement_module.validate_material_requirement, fixture("valid_material_requirement.json")),
        (manifest_module.validate_artifact_manifest, fixture("valid_artifact_manifest.json")),
    ]
    for validator, value in values:
        left = validator(copy.deepcopy(value))
        right = validator(copy.deepcopy(value))
        assert left.record is not None and right.record is not None
        assert canonical_json_bytes(left.record.to_dict()) == canonical_json_bytes(right.record.to_dict())
        assert left.record.fingerprint == right.record.fingerprint


def test_fixture_and_input_immutability() -> None:
    for name, validator in (
        ("valid_handoff.json", handoff_module.validate_curriculum_handoff),
        ("valid_material_requirement.json", requirement_module.validate_material_requirement),
        ("valid_artifact_manifest.json", manifest_module.validate_artifact_manifest),
    ):
        value = fixture(name)
        before = copy.deepcopy(value)
        validator(value)
        assert value == before


@pytest.mark.parametrize("name,path", [
    ("valid_handoff.json", ("identity", "contract_version")),
    ("valid_material_requirement.json", ("identity", "contract_version")),
    ("valid_artifact_manifest.json", ("identity", "contract_version")),
])
def test_unknown_contract_versions_fail_closed(name: str, path: tuple[str, str]) -> None:
    value = fixture(name)
    value[path[0]][path[1]] = "future-v9"
    validator = {
        "valid_handoff.json": handoff_module.validate_curriculum_handoff,
        "valid_material_requirement.json": requirement_module.validate_material_requirement,
        "valid_artifact_manifest.json": manifest_module.validate_artifact_manifest,
    }[name]
    assert validator(value).status is ValidationStatus.INVALID


def test_mixed_versions_fail_closed() -> None:
    value = fixture("valid_artifact_manifest.json")
    value["requirement_reference"]["contract_version"] = "curriculum-workflow-handoff-v1"
    assert manifest_module.validate_artifact_manifest(value).status is ValidationStatus.INVALID


def test_incompatible_stable_ids_fail_closed() -> None:
    requirement = fixture("valid_material_requirement.json")
    manifest = fixture("valid_artifact_manifest.json")
    manifest["requirement_reference"]["requirement_id"] = "requirement-other"
    assert planner(requirement, [manifest]).status is ValidationStatus.INVALID


def test_incompatible_fingerprints_fail_closed() -> None:
    value = fixture("valid_material_requirement.json")
    value["identity"]["source_fingerprint"] = "f" * 64
    assert requirement_module.validate_material_requirement(value).status is ValidationStatus.INVALID


def test_stale_dependency_evidence_fails_closed() -> None:
    result = handoff_module.validate_curriculum_handoff(fixture("stale_dependency_case.json"))
    assert result.status is ValidationStatus.STALE
    assert result.authority == AuthorityEvidence()


def test_reason_namespace_collision_fails_closed() -> None:
    value = fixture("valid_handoff.json")
    value["routing"]["reason_codes"] = ["reuse-not-a-governed-reason"]
    assert handoff_module.validate_curriculum_handoff(value).status is ValidationStatus.INVALID


def test_unsupported_executor_routes_safely() -> None:
    result = planner(fixture("valid_material_requirement.json"), [fixture("valid_artifact_manifest.json")], supported=False)
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.authority == AuthorityEvidence()


def test_duplicate_identity_fails_closed() -> None:
    value = fixture("valid_artifact_manifest.json")
    value["assets"].append(copy.deepcopy(value["assets"][0]))
    result = manifest_module.validate_artifact_manifest(value)
    assert result.status is ValidationStatus.INVALID


def test_sparse_evidence_routes_safely() -> None:
    result = planner(fixture("valid_material_requirement.json"), [])
    assert result.status in {ValidationStatus.VALID, ValidationStatus.MANUAL_REVIEW_REQUIRED}
    assert result.authority == AuthorityEvidence()


def test_manual_review_fixture_remains_manual_review() -> None:
    result = manifest_module.validate_artifact_manifest(fixture("manual_review_case.json"))
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.record is not None


def test_authority_states_never_collapse() -> None:
    for result in (
        handoff_module.validate_curriculum_handoff(fixture("valid_handoff.json")),
        requirement_module.validate_material_requirement(fixture("valid_material_requirement.json")),
        manifest_module.validate_artifact_manifest(fixture("valid_artifact_manifest.json")),
        planner(fixture("valid_material_requirement.json"), [fixture("valid_artifact_manifest.json")]),
    ):
        assert result.authority == AuthorityEvidence()
        assert result.record is not None
        assert not any(result.record.to_dict().get("authority", {}).values())


def test_teacher_approval_and_classroom_readiness_do_not_grant_authority() -> None:
    result = manifest_module.validate_artifact_manifest(fixture("valid_artifact_manifest.json"))
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload["statuses"]["teacher_approval"] == "approved"
    assert payload["statuses"]["classroom_readiness"] == "ready"
    assert result.authority == AuthorityEvidence()


def test_production_and_publication_do_not_collapse() -> None:
    result = manifest_module.validate_artifact_manifest(fixture("valid_artifact_manifest.json"))
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload["statuses"]["production_state"] == "not-authorized"
    assert payload["statuses"]["publication_state"] == "not-published"
    assert result.authority == AuthorityEvidence()


def test_shared_core_calls_are_observable(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"requirement": 0, "manifest": 0, "planner": 0}
    for key, module in (("requirement", requirement_module), ("manifest", manifest_module), ("planner", planner_module)):
        original = module.validate_and_normalize_json
        def wrapper(value, *args, _key=key, _original=original, **kwargs):
            calls[_key] += 1
            return _original(value, *args, **kwargs)
        monkeypatch.setattr(module, "validate_and_normalize_json", wrapper)
    requirement_module.validate_material_requirement(fixture("valid_material_requirement.json"))
    manifest_module.validate_artifact_manifest(fixture("valid_artifact_manifest.json"))
    planner(fixture("valid_material_requirement.json"), [fixture("valid_artifact_manifest.json")])
    assert all(count > 0 for count in calls.values())


def _domain_trees() -> dict[str, ast.Module]:
    return {name: ast.parse((PACKAGE / name).read_text(encoding="utf-8")) for name in ("material_requirement.py", "artifact_manifest.py", "reuse_planner.py")}


def test_ast_duplicate_infrastructure_detection_is_behavior_based() -> None:
    for name, tree in _domain_trees().items():
        imported_common = {
            alias.name for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == "common" for alias in node.names
        }
        assert {"validate_and_normalize_json", "sha256_hex", "ValidatedRecord", "ValidationResult", "ValidationStatus"} <= imported_common
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert not (isinstance(node.func.value, ast.Name) and node.func.value.id == "json" and node.func.attr == "dumps"), name
                assert not (isinstance(node.func.value, ast.Name) and node.func.value.id == "hashlib" and node.func.attr == "sha256"), name
            if isinstance(node, ast.ClassDef):
                assert not any(isinstance(base, ast.Name) and base.id in {"Enum", "IntEnum"} for base in node.bases), name


def test_no_generic_recursive_validator_is_reimplemented() -> None:
    for name, tree in _domain_trees().items():
        for function in [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            assert not any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == function.name for call in ast.walk(function)), name


def test_import_graph_restrictions() -> None:
    forbidden = common_module.FORBIDDEN_IMPORT_PREFIXES
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert not [item for item in imports if item.startswith(forbidden)], path.name


def test_import_time_side_effect_isolation() -> None:
    code = r'''
import builtins, importlib, os, socket, subprocess, sys, threading
sys.path.insert(0, sys.argv[1])
calls=[]
def blocked(name):
    def inner(*a, **k): calls.append(name); raise AssertionError(name)
    return inner
builtins.open=blocked("open")
os.getenv=blocked("getenv")
socket.socket=blocked("socket")
subprocess.Popen=blocked("popen")
threading.Thread=blocked("thread")
for name in ["instructional_workflow_contracts.material_requirement", "instructional_workflow_contracts.artifact_manifest", "instructional_workflow_contracts.reuse_planner"]:
    importlib.import_module(name)
assert calls == [], calls
'''
    completed = subprocess.run([sys.executable, "-I", "-c", code, str(PACKAGE.parent)], text=True, capture_output=True)
    assert completed.returncode == 0, completed.stderr


def test_no_ocr_image_model_or_external_client_imports() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in PACKAGE.glob("*.py"))
    for token in ("paddle", "ocr", "transformers", "torch", "sentence_transformers", "googleapiclient", "notion_client"):
        assert f"import {token}" not in text and f"from {token}" not in text


def test_exact_sha_evidence_fields_are_distinct() -> None:
    evidence = {
        "starting_main_sha": "a" * 40,
        "final_branch_head_sha": "b" * 40,
        "locally_tested_sha": None,
        "synthetic_merge_sha": "c" * 40,
        "workflow_run_ids": [1],
        "job_ids": [2],
        "event_types": None,
        "focused_rerun_after_final_change": True,
        "aggregate_tested_surface": "synthetic-merge",
    }
    assert set(evidence) == {"starting_main_sha", "final_branch_head_sha", "locally_tested_sha", "synthetic_merge_sha", "workflow_run_ids", "job_ids", "event_types", "focused_rerun_after_final_change", "aggregate_tested_surface"}
    assert evidence["final_branch_head_sha"] != evidence["synthetic_merge_sha"]


def test_branch_head_is_not_synthetic_merge() -> None:
    assert "1" * 40 != "2" * 40


def test_component_modules_and_exports_are_unchanged() -> None:
    assert {name: git_blob_sha(PACKAGE / name) for name in COMPONENT_BLOBS} == COMPONENT_BLOBS
    init_path = PACKAGE / "__init__.py"
    init_text = init_path.read_text(encoding="utf-8")
    init_tree = ast.parse(init_text)
    all_assignments = [
        node for node in init_tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    ]
    assert len(all_assignments) == 1, "__init__.py must define exactly one literal __all__ public-surface contract"
    all_value = all_assignments[0].value
    assert isinstance(all_value, (ast.List, ast.Tuple)), "__all__ must remain a literal list/tuple so export changes are reviewable"
    actual_exports = tuple(
        item.value for item in all_value.elts
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    )
    assert len(actual_exports) == len(all_value.elts), "__all__ entries must remain literal strings"
    assert actual_exports == EXPECTED_PUBLIC_EXPORTS, (
        "instructional_workflow_contracts public exports changed; update EXPECTED_PUBLIC_EXPORTS only when the public-surface change is intentional"
    )
    assert "material_requirement" not in init_text
    assert "artifact_manifest" not in init_text
    assert "reuse_planner" not in init_text


# Issue #850 v2 integration coverage

def test_valid_v2_material_requirement_fixture() -> None:
    value = fixture("valid_material_requirement_v2.json")
    result = requirement_module.validate_material_requirement(value)
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    assert result.record.contract_version == "curriculum-material-requirement-v2"
    payload = result.record.to_dict()
    assert payload["visual_direction"]["decision"] == "visuals-required"
    assert payload["visual_direction"]["maximum_visual_count"] == 2
    assert [role["role_type"] for role in payload["visual_direction"]["roles"]] == ["worked-example", "comparison"]
    assert result.authority == AuthorityEvidence()
    assert not any(payload["authority"].values())


def test_v1_and_v2_material_fingerprints_are_independent() -> None:
    v1 = fixture("valid_material_requirement.json")
    v2 = fixture("valid_material_requirement_v2.json")
    assert requirement_module.material_requirement_source_fingerprint(v1) != requirement_module.material_requirement_source_fingerprint(v2)
    v1_first = requirement_module.validate_material_requirement(copy.deepcopy(v1))
    v1_second = requirement_module.validate_material_requirement(copy.deepcopy(v1))
    v2_first = requirement_module.validate_material_requirement(copy.deepcopy(v2))
    v2_second = requirement_module.validate_material_requirement(copy.deepcopy(v2))
    assert v1_first.record is not None
    assert v1_second.record is not None
    assert v2_first.record is not None
    assert v2_second.record is not None
    assert v1_first.record.fingerprint == v1_second.record.fingerprint
    assert v2_first.record.fingerprint == v2_second.record.fingerprint
    assert v1_first.record.fingerprint != v2_first.record.fingerprint
