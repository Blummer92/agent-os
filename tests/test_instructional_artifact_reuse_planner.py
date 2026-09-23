from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

import instructional_workflow_contracts.reuse_planner as planner
from instructional_workflow_contracts.common import (
    AuthorityEvidence,
    FINGERPRINT_ALGORITHM,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    freeze_json,
    sha256_hex,
)
from instructional_workflow_contracts.reuse_planner import (
    MAX_CANDIDATES,
    MAX_CHANGED_KEYS,
    MAX_DEPENDENCY_KEYS,
    MAX_IMPACTED_SECTIONS,
    MAX_REJECTION_REASONS,
    MAX_VISUAL_RISK_REASONS,
    plan_instructional_artifact_reuse,
)


def _record(payload: dict[str, object], contract: str, record_id: str) -> ValidationResult:
    record = ValidatedRecord(
        contract_version=contract,
        record_id=record_id,
        record_revision=1,
        fingerprint_algorithm=FINGERPRINT_ALGORITHM,
        fingerprint=sha256_hex(payload),
        payload=freeze_json(payload),
    )
    return ValidationResult(status=ValidationStatus.VALID, record=record)


def requirement(*, templates: bool = False) -> ValidationResult:
    payload = {
        "identity": {
            "requirement_id": "requirement-1",
            "source_fingerprint": "a" * 64,
        },
        "artifact": {"artifact_type": "worksheet"},
        "templates": ([{"template_id": "template-1"}] if templates else []),
    }
    return _record(payload, "curriculum-material-requirement-v1", "requirement-1")


def asset(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "asset_id": "asset-1",
        "duplicate_relationship": "unique",
        "disposition": "canonical",
        "canonical_asset_ref": None,
        "rights_classification": "permission-documented",
        "privacy_observations": [],
        "privacy_resolved": True,
        "residual_privacy_risk": False,
        "content_findings": [],
        "repair_source_status": "not-needed",
        "correction_requirement": None,
        "replacement_required": False,
        "transformations": [],
        "required_context_flags": [],
        "preserved_context_flags": [],
        "context_preservation_complete": True,
    }
    value.update(overrides)
    return value


def manifest(
    *,
    manifest_id: str = "manifest-1",
    requirement_id: str = "requirement-1",
    artifact_type: str = "worksheet",
    access: str = "verified",
    quality: str = "pass",
    teacher: str = "approved",
    readiness: str = "ready",
    assets: list[dict[str, object]] | None = None,
) -> ValidationResult:
    payload = {
        "identity": {
            "manifest_id": manifest_id,
            "source_fingerprint": (manifest_id.encode().hex() + "0" * 64)[:64],
        },
        "requirement_reference": {"requirement_id": requirement_id},
        "artifact": {"artifact_type": artifact_type},
        "external_identity": {"access_state": access},
        "statuses": {
            "quality_state": quality,
            "teacher_approval": teacher,
            "classroom_readiness": readiness,
        },
        "assets": [asset()] if assets is None else assets,
    }
    return _record(payload, "curriculum-artifact-manifest-v1", manifest_id)


def payload(result: ValidationResult) -> dict[str, object]:
    assert result.record is not None
    return result.record.to_dict()


def plan(*, req=None, candidates=None, changed=(), impact=None, executor=True) -> ValidationResult:
    return plan_instructional_artifact_reuse(
        requirement() if req is None else req,
        [manifest()] if candidates is None else candidates,
        changed_dependency_keys=list(changed),
        impact_map={} if impact is None else impact,
        supported_executor=executor,
    )


def test_exact_approved_reuse_is_deterministic_immutable_and_advisory() -> None:
    req = requirement()
    candidate = manifest()
    req_before = copy.deepcopy(req.record.to_dict())
    candidate_before = copy.deepcopy(candidate.record.to_dict())
    first = plan(req=req, candidates=[candidate])
    second = plan(req=req, candidates=[candidate])
    assert first.status is ValidationStatus.VALID
    assert payload(first)["decision"] == "reuse-existing-approved"
    assert first.record is not None and second.record is not None
    assert first.record.fingerprint == second.record.fingerprint
    assert first.authority == first.record.authority == AuthorityEvidence()
    assert req.record.to_dict() == req_before
    assert candidate.record.to_dict() == candidate_before
    assert all(value is False for value in payload(first)["authority"].values())


def test_bounded_revision_maps_changed_dependencies() -> None:
    result = plan(
        changed=("alignment.objective",),
        impact={"alignment.objective": ["evidence-prompts", "rubric-rows"]},
    )
    assert result.status is ValidationStatus.VALID
    assert payload(result)["decision"] == "revise-existing-bounded"
    assert payload(result)["impacted_sections"] == ["evidence-prompts", "rubric-rows"]
    assert payload(result)["rejection_reasons"] == ["artifact-reuse-rejected-change-or-evidence"]


def test_unmapped_dependency_routes_to_manual_review() -> None:
    result = plan(changed=("alignment.objective",), impact={})
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert payload(result)["decision"] == "manual-review-required"
    assert payload(result)["unmapped_dependency_keys"] == ["alignment.objective"]


def test_unsafe_candidate_can_reuse_approved_components() -> None:
    candidate = manifest(quality="manual-review")
    result = plan(candidates=[candidate])
    assert result.status is ValidationStatus.VALID
    assert payload(result)["decision"] == "reuse-approved-components"
    assert "quality-evidence-missing" in payload(result)["missing_required_evidence"]


def test_template_copy_precedes_new_creation_when_no_candidate() -> None:
    result = plan(req=requirement(templates=True), candidates=[])
    assert payload(result)["decision"] == "copy-approved-template-and-create"
    assert payload(result)["rejection_reasons"] == [
        "artifact-reuse-rejected-change-or-evidence",
        "artifact-revision-rejected-unsafe-or-conflicting",
        "artifact-components-rejected-unavailable",
    ]


def test_no_candidate_or_template_requires_new_artifact() -> None:
    result = plan(candidates=[])
    assert payload(result)["decision"] == "create-new-required"
    assert result.status is ValidationStatus.VALID


def test_unsupported_executor_routes_to_manual_review_without_authority() -> None:
    result = plan(executor=False)
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert payload(result)["decision"] == "manual-review-required"
    assert payload(result)["confidence"] == "none"
    assert result.authority == AuthorityEvidence()


def test_candidate_order_is_canonical_and_best_evidence_wins() -> None:
    weak = manifest(manifest_id="manifest-z", quality="manual-review")
    strong = manifest(manifest_id="manifest-a")
    first = plan(candidates=[weak, strong])
    second = plan(candidates=[strong, weak])
    assert payload(first) == payload(second)
    assert payload(first)["selected_manifest_id"] == "manifest-a"


def test_conflicting_identity_does_not_silently_reuse() -> None:
    conflict = manifest(requirement_id="requirement-other")
    result = plan(candidates=[conflict])
    assert payload(result)["decision"] in {"reuse-approved-components", "manual-review-required"}
    assert "artifact-requirement-identity-conflict" in payload(result)["conflicting_evidence"]


def test_canonical_asset_is_preferred() -> None:
    result = plan(candidates=[manifest(assets=[asset()])])
    visual = payload(result)["visual_recommendations"]
    assert visual == [{"asset_id": "asset-1", "decision": "reuse-canonical-asset", "reasons": ["asset-canonical-reuse"]}]


def test_alternate_requires_canonical_reference_and_explicit_reason() -> None:
    safe = asset(disposition="alternate", duplicate_relationship="near-duplicate", canonical_asset_ref="asset-canonical")
    result = plan(candidates=[manifest(assets=[safe])])
    assert payload(result)["visual_recommendations"][0]["decision"] == "reuse-alternate-with-explicit-reason"
    unsafe = asset(disposition="alternate", duplicate_relationship="near-duplicate", canonical_asset_ref=None)
    result = plan(candidates=[manifest(assets=[unsafe])])
    assert payload(result)["visual_recommendations"][0]["decision"] == "manual-review-required"


def test_archive_candidate_is_not_reused() -> None:
    archived = asset(disposition="archive-candidate", duplicate_relationship="exact-duplicate", canonical_asset_ref="asset-canonical")
    result = plan(candidates=[manifest(assets=[archived])])
    assert payload(result)["visual_recommendations"][0]["decision"] == "manual-review-required"


def test_routine_cleanup_requires_preserved_context() -> None:
    safe = asset(
        transformations=["crop", "rotate", "cleanup"],
        required_context_flags=["labels", "arrows", "response-areas"],
        preserved_context_flags=["labels", "arrows", "response-areas"],
    )
    assert payload(plan(candidates=[manifest(assets=[safe])]))["visual_recommendations"][0]["decision"] == "bounded-context-preserving-crop-or-cleanup"
    unsafe = copy.deepcopy(safe)
    unsafe["preserved_context_flags"] = ["labels"]
    assert payload(plan(candidates=[manifest(assets=[unsafe])]))["visual_recommendations"][0]["decision"] == "manual-review-required"


def test_crop_never_clears_rights() -> None:
    risky = asset(rights_classification="unclear-provenance", transformations=["crop"])
    result = plan(candidates=[manifest(assets=[risky])])
    assert payload(result)["visual_recommendations"][0]["decision"] == "permission-or-rights-review-required"


def test_unresolved_privacy_requires_clearance_or_anonymization() -> None:
    risky = asset(
        privacy_observations=["names"],
        privacy_resolved=False,
        residual_privacy_risk=True,
        transformations=["crop"],
    )
    result = plan(candidates=[manifest(assets=[risky])])
    assert payload(result)["visual_recommendations"][0]["decision"] == "privacy-clearance-or-anonymization-required"


@pytest.mark.parametrize("finding", ["malformed-text", "answer-revealing-content"])
def test_content_repair_requires_complete_correction_scope(finding: str) -> None:
    repairable = asset(
        content_findings=[finding],
        repair_source_status="completed",
        correction_requirement="replace exact supplied label text",
    )
    result = plan(candidates=[manifest(assets=[repairable])])
    assert payload(result)["visual_recommendations"][0]["decision"] == "bounded-content-repair"
    rebuild = copy.deepcopy(repairable)
    rebuild["repair_source_status"] = "required"
    rebuild["correction_requirement"] = None
    result = plan(candidates=[manifest(assets=[rebuild])])
    assert payload(result)["visual_recommendations"][0]["decision"] == "rebuild-or-recreate-required"


def test_replacement_is_distinct_from_rebuild_and_cleanup() -> None:
    replacement = asset(content_findings=["inaccurate-content"], replacement_required=True)
    result = plan(candidates=[manifest(assets=[replacement])])
    assert payload(result)["visual_recommendations"][0]["decision"] == "replacement-asset-required"


def test_invalid_upstream_results_fail_closed() -> None:
    invalid = ValidationResult(status=ValidationStatus.INVALID, record=None, reason_codes=("material-invalid",))
    result = plan(req=invalid)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("artifact-planner-invalid-upstream",)


def test_raw_inputs_use_upstream_validators(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"material": 0, "manifest": 0}
    req = requirement()
    candidate = manifest()

    def validate_req(value: object) -> ValidationResult:
        calls["material"] += 1
        return req

    def validate_manifest(value: object) -> ValidationResult:
        calls["manifest"] += 1
        return candidate

    monkeypatch.setattr(planner, "validate_material_requirement", validate_req)
    monkeypatch.setattr(planner, "validate_artifact_manifest", validate_manifest)
    result = plan_instructional_artifact_reuse({}, [{}], changed_dependency_keys=[], impact_map={})
    assert result.status is ValidationStatus.VALID
    assert calls == {"material": 1, "manifest": 1}


def test_hostile_custom_objects_fail_before_arbitrary_behavior() -> None:
    class HostileList(list):
        def __iter__(self):
            raise AssertionError("hostile iterator executed")

    result = plan_instructional_artifact_reuse(requirement(), HostileList(), changed_dependency_keys=[], impact_map={})
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-wrong-type",)


def test_candidate_exact_and_one_over_bound() -> None:
    exact = [manifest(manifest_id=f"manifest-{index}") for index in range(MAX_CANDIDATES)]
    assert plan(candidates=exact).status in {ValidationStatus.VALID, ValidationStatus.MANUAL_REVIEW_REQUIRED}
    over = exact + [manifest(manifest_id="manifest-over")]
    result = plan(candidates=over)
    assert result.status is ValidationStatus.INVALID
    assert result.details == ("candidates exceed the 32-item bound",)


def test_changed_key_exact_and_one_over_bound() -> None:
    exact = [f"owner.key_{index}" for index in range(MAX_CHANGED_KEYS)]
    impact = {key: [f"section-{index}"] for index, key in enumerate(exact)}
    assert plan(changed=exact, impact=impact).status in {ValidationStatus.VALID, ValidationStatus.MANUAL_REVIEW_REQUIRED}
    result = plan(changed=exact + ["owner.key_over"], impact=impact)
    assert result.status is ValidationStatus.INVALID
    assert result.reason_codes == ("handoff-oversized",)


def test_impact_map_exact_and_one_over_bound() -> None:
    exact = {f"owner.key_{index}": [f"section-{index}"] for index in range(MAX_DEPENDENCY_KEYS)}
    assert plan(impact=exact).status is ValidationStatus.VALID
    exact["owner.key_over"] = ["section-over"]
    result = plan(impact=exact)
    assert result.status is ValidationStatus.INVALID
    assert result.details == ("impact_map exceeds 128 dependency keys",)


def test_impacted_section_one_over_bound() -> None:
    sections = [f"section-{index}" for index in range(MAX_IMPACTED_SECTIONS)]
    assert plan(changed=("owner.key",), impact={"owner.key": sections}).status is ValidationStatus.VALID
    result = plan(changed=("owner.key",), impact={"owner.key": sections + ["section-over"]})
    assert result.status is ValidationStatus.INVALID


def test_rejection_and_visual_reason_constants_are_finite() -> None:
    assert MAX_REJECTION_REASONS == 64
    assert MAX_VISUAL_RISK_REASONS == 64


def test_shared_result_bound_is_truthfully_stricter_than_domain_32_kib_bound() -> None:
    assert planner.SHARED_MAX_RESULT_BYTES == 16 * 1024
    assert planner.MAX_RESULT_BYTES == 32 * 1024


def test_no_duplicate_generic_framework_or_import_side_effects() -> None:
    path = Path(__file__).parents[1] / "src" / "instructional_workflow_contracts" / "reuse_planner.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    classes = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    calls = {
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert classes.isdisjoint({"ValidationResult", "ValidationStatus", "ValidatedRecord", "AuthorityEvidence"})
    assert functions.isdisjoint({"canonical_json_bytes", "canonical_size", "sha256_hex", "freeze_json", "validate_and_normalize_json"})
    assert imports <= {"__future__", "typing", "common", "material_requirement", "artifact_manifest"}
    assert calls.isdisjoint({"open", "getenv", "Popen", "run", "system", "basicConfig", "register", "import_module", "eval", "exec"})
