from __future__ import annotations

import ast
import copy
import dataclasses
from pathlib import Path

import pytest

from instructional_workflow_contracts import (
    CONTRACT_ID,
    FORBIDDEN_IMPORT_PREFIXES,
    MAX_DETAIL_LENGTH,
    MAX_INPUT_BYTES,
    MAX_NESTING_DEPTH,
    MAX_RESULT_BYTES,
    AuthorityEvidence,
    ContractValidationError,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    canonical_json_bytes,
    resolve_status,
    sha256_hex,
    validate_and_normalize_json,
    validate_curriculum_handoff,
    validate_reason_code,
)


def _reference(suffix: str) -> dict[str, str]:
    return {
        "system": "github",
        "stable_id": f"ref-{suffix}",
        "exact_location": f"issue:{suffix}",
        "verification_evidence": f"verified-{suffix}",
    }


def valid_handoff() -> dict[str, object]:
    keys = ["source.unit", "unit-alignment.objective"]
    values = {"source.unit": "unit-1", "unit-alignment.objective": "objective-1"}
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
            "dependency_keys": keys,
            "dependency_values": values,
            "dependency_fingerprint": sha256_hex(
                {"dependency_keys": sorted(keys), "dependency_values": values}
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


def test_valid_handoff_is_deterministic_immutable_and_authority_false() -> None:
    supplied = valid_handoff()
    before = copy.deepcopy(supplied)
    first = validate_curriculum_handoff(supplied)
    second = validate_curriculum_handoff(copy.deepcopy(supplied))
    assert first.status is ValidationStatus.VALID
    assert first.record is not None and second.record is not None
    assert first.record.fingerprint == second.record.fingerprint
    assert first.authority == AuthorityEvidence()
    assert first.record.authority == AuthorityEvidence()
    assert supplied == before
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.record.record_revision = 2  # type: ignore[misc]


def test_order_insensitive_fields_normalize_but_instructional_order_remains() -> None:
    left = valid_handoff()
    right = valid_handoff()
    right["routing"]["required_handoff_artifacts"].reverse()  # type: ignore[index,union-attr]
    right["learning_alignment"]["references"].reverse()  # type: ignore[index,union-attr]
    right["stage_payload"]["payload"]["success_criteria"].reverse()  # type: ignore[index,union-attr]
    left_result = validate_curriculum_handoff(left)
    right_result = validate_curriculum_handoff(right)
    assert left_result.record is not None and right_result.record is not None
    left_payload = left_result.record.to_dict()
    right_payload = right_result.record.to_dict()
    assert left_payload["routing"] == right_payload["routing"]
    assert left_payload["learning_alignment"] == right_payload["learning_alignment"]
    assert left_payload["stage_payload"] != right_payload["stage_payload"]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda value: value.pop("audit"), "handoff-invalid"),
        (lambda value: value.__setitem__("extra", {}), "handoff-unknown-field"),
        (lambda value: value["identity"].__setitem__("record_revision", True), "identity-invalid"),
        (lambda value: value["identity"].__setitem__("contract_version", "future-v2"), "handoff-version-unsupported"),
        (lambda value: value["authority"].__setitem__("execution_authorized", True), "authority-invalid"),
        (lambda value: value["stage_payload"].__setitem__("owner", "qa-test-agent"), "ownership-owner-conflict"),
        (lambda value: value["dependencies"].__setitem__("dependency_fingerprint", "b" * 64), "dependency-invalid"),
        (lambda value: value["identity"].__setitem__("handoff_id", "bad id"), "identity-invalid"),
    ],
)
def test_contract_failures_are_finite(mutation, reason: str) -> None:
    value = valid_handoff()
    mutation(value)
    result = validate_curriculum_handoff(value)
    assert result.status is ValidationStatus.INVALID
    assert result.record is None
    assert reason in result.reason_codes


class EvilString(str):
    pass


class EvilIterable:
    def __iter__(self):
        raise AssertionError("custom iterator executed")

    def __repr__(self):
        raise AssertionError("custom repr executed")


class EvilKey(str):
    def __lt__(self, other):
        raise AssertionError("custom key comparison executed")


class EvilTuple(tuple):
    def __getitem__(self, item):
        raise AssertionError("custom tuple indexing executed")

    def __iter__(self):
        raise AssertionError("custom tuple iteration executed")


@pytest.mark.parametrize("replacement", [EvilString("handoff-1"), EvilIterable()])
def test_malicious_values_are_rejected_without_coercion(replacement: object) -> None:
    value = valid_handoff()
    value["identity"]["handoff_id"] = replacement  # type: ignore[index]
    result = validate_curriculum_handoff(value)
    assert result.status is ValidationStatus.INVALID
    assert "handoff-wrong-type" in result.reason_codes


def test_malicious_key_is_rejected_before_sorting() -> None:
    value = valid_handoff()
    value[EvilKey("audit2")] = {}
    assert "handoff-wrong-type" in validate_curriculum_handoff(value).reason_codes


def test_duplicate_reference_and_dependency_fail_closed() -> None:
    duplicate_ref = valid_handoff()
    duplicate_ref["learning_alignment"]["references"] = [_reference("1"), _reference("1")]  # type: ignore[index]
    assert "identity-duplicate" in validate_curriculum_handoff(duplicate_ref).reason_codes
    duplicate_key = valid_handoff()
    duplicate_key["dependencies"]["dependency_keys"] = ["source.unit", "source.unit"]  # type: ignore[index]
    assert "handoff-duplicate" in validate_curriculum_handoff(duplicate_key).reason_codes


def test_diagnostics_are_bounded_and_do_not_echo_raw_values() -> None:
    value = valid_handoff()
    raw = "TOP-SECRET-" + "z" * 800
    value["identity"]["handoff_id"] = raw  # type: ignore[index]
    result = validate_curriculum_handoff(value)
    assert all(len(detail) <= MAX_DETAIL_LENGTH for detail in result.details)
    assert raw not in " ".join(result.details)


def test_status_precedence_is_explicit() -> None:
    assert resolve_status(()) is ValidationStatus.VALID
    assert resolve_status(("manual-review-inspection",)) is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert resolve_status(("source-stale",)) is ValidationStatus.STALE
    assert resolve_status((), ("routing-blocked-dependency",)) is ValidationStatus.BLOCKED
    assert resolve_status(
        ("handoff-invalid", "source-stale"),
        ("routing-blocked-dependency",),
    ) is ValidationStatus.INVALID


def test_status_mapping_is_not_substring_driven() -> None:
    for code in ("routing-unblocked", "source-not-stale", "routing-conflict-free"):
        with pytest.raises(ContractValidationError) as caught:
            resolve_status((code,))
        assert caught.value.reason_code == "handoff-invalid"


DOMAIN_REASON_CODES = (
    "material-unsupported-artifact-type",
    "artifact-invalid-lifecycle",
    "asset-unresolved-privacy-risk",
    "template-unverified-permission",
    "destination-ambiguous-identity",
    "quality-answer-revealing-content",
)


@pytest.mark.parametrize("reason_code", DOMAIN_REASON_CODES)
def test_domain_reason_namespaces_are_syntax_only(reason_code: str) -> None:
    assert validate_reason_code(reason_code) == reason_code

    result = ValidationResult(
        status=ValidationStatus.INVALID,
        record=None,
        reason_codes=(reason_code,),
    )
    assert result.reason_codes == (reason_code,)
    assert result.authority == AuthorityEvidence()

    with pytest.raises(ContractValidationError) as caught:
        resolve_status((reason_code,))
    assert caught.value.reason_code == "handoff-invalid"


@pytest.mark.parametrize(
    "reason_code",
    [
        "artifact",
        "asset-",
        "Template-invalid",
        "destination invalid",
        "quality-invalid\n",
        "artifact-" + "x" * 120,
        "reuse-invalid",
    ],
)
def test_domain_reason_namespaces_reject_malformed_and_unsupported_values(
    reason_code: str,
) -> None:
    with pytest.raises((ContractValidationError, ValueError)):
        validate_reason_code(reason_code)


@pytest.mark.parametrize(
    "reason_code",
    [
        "source-invalid",
        "identity-invalid",
        "ownership-owner-conflict",
        "readiness-incomplete",
        "authority-invalid",
        "handoff-invalid",
        "dependency-invalid",
        "routing-invalid",
        "manual-review-inspection",
        "material-invalid",
        "artifact-invalid",
        "asset-invalid",
        "template-invalid",
        "destination-invalid",
        "quality-invalid",
    ],
)
def test_existing_and_new_reason_namespaces_remain_accepted(reason_code: str) -> None:
    assert validate_reason_code(reason_code) == reason_code


def test_domain_reason_ordering_and_duplicate_rejection_remain_canonical() -> None:
    result = ValidationResult(
        status=ValidationStatus.INVALID,
        record=None,
        reason_codes=("quality-zeta", "artifact-alpha", "asset-beta"),
    )
    assert result.reason_codes == ("artifact-alpha", "asset-beta", "quality-zeta")

    with pytest.raises(ContractValidationError) as caught:
        ValidationResult(
            status=ValidationStatus.INVALID,
            record=None,
            reason_codes=("asset-alpha", "asset-alpha"),
        )
    assert caught.value.reason_code == "handoff-duplicate"


@pytest.mark.parametrize(
    ("evidence_status", "expected", "reason", "blocker"),
    [
        ("confirmed", ValidationStatus.VALID, None, None),
        ("provisional", ValidationStatus.MANUAL_REVIEW_REQUIRED, "source-provisional", None),
        ("conflicting", ValidationStatus.BLOCKED, None, "source-conflicting"),
        ("unavailable", ValidationStatus.MANUAL_REVIEW_REQUIRED, "source-unavailable", None),
        ("stale", ValidationStatus.STALE, "source-stale", None),
    ],
)
def test_source_evidence_states_have_governed_outcomes(
    evidence_status: str,
    expected: ValidationStatus,
    reason: str | None,
    blocker: str | None,
) -> None:
    value = valid_handoff()
    value["source_evidence"]["evidence_status"] = evidence_status  # type: ignore[index]
    result = validate_curriculum_handoff(value)
    assert result.status is expected
    assert result.record is not None
    if reason:
        assert reason in result.reason_codes
    if blocker:
        assert blocker in result.blockers


def test_unknown_source_evidence_state_fails_closed() -> None:
    value = valid_handoff()
    value["source_evidence"]["evidence_status"] = "unknown"  # type: ignore[index]
    assert "source-invalid" in validate_curriculum_handoff(value).reason_codes


def test_authority_cannot_be_injected_into_public_models() -> None:
    record = validate_curriculum_handoff(valid_handoff()).record
    assert record is not None
    with pytest.raises(TypeError):
        ValidatedRecord(
            contract_version=record.contract_version,
            record_id=record.record_id,
            record_revision=record.record_revision,
            fingerprint_algorithm=record.fingerprint_algorithm,
            fingerprint=record.fingerprint,
            payload=record.payload,
            authority=object(),  # type: ignore[call-arg]
        )
    with pytest.raises(TypeError):
        ValidationResult(
            status=ValidationStatus.VALID,
            record=record,
            authority=object(),  # type: ignore[call-arg]
        )


def test_valid_result_requires_record() -> None:
    with pytest.raises(ValueError, match="require a validated record"):
        ValidationResult(status=ValidationStatus.VALID, record=None)


def test_hostile_tuple_is_rejected_before_indexing() -> None:
    record = validate_curriculum_handoff(valid_handoff()).record
    assert record is not None
    with pytest.raises(TypeError, match="details must be an exact tuple"):
        ValidationResult(
            status=ValidationStatus.VALID,
            record=record,
            details=EvilTuple(("x",)),
        )


def test_exact_64k_input_boundary_and_one_over() -> None:
    exact = ["x" * 252 for _ in range(255)] + ["x" * 507]
    assert len(canonical_json_bytes(exact)) == MAX_INPUT_BYTES
    assert validate_and_normalize_json(exact, max_bytes=MAX_INPUT_BYTES) == exact
    with pytest.raises(ContractValidationError):
        validate_and_normalize_json(exact[:-1] + ["x" * 508], max_bytes=MAX_INPUT_BYTES)


def test_exact_16k_result_boundary_and_one_over() -> None:
    exact = ["x" * 253 for _ in range(63)] + ["x" * 252]
    assert len(canonical_json_bytes(exact)) == MAX_RESULT_BYTES
    assert validate_and_normalize_json(exact, max_bytes=MAX_RESULT_BYTES) == exact
    with pytest.raises(ContractValidationError):
        validate_and_normalize_json(exact[:-1] + ["x" * 253], max_bytes=MAX_RESULT_BYTES)


def test_exact_maximum_depth_and_one_over() -> None:
    at_limit: object = "end"
    for _ in range(MAX_NESTING_DEPTH):
        at_limit = [at_limit]
    assert validate_and_normalize_json(at_limit) == at_limit
    with pytest.raises(ContractValidationError):
        validate_and_normalize_json([at_limit])


@pytest.mark.parametrize(
    "timestamp",
    ["2024-02-29T23:59:59Z", "2026-01-01T00:00:00Z", "9999-12-31T23:59:59Z"],
)
def test_semantically_valid_timestamps(timestamp: str) -> None:
    value = valid_handoff()
    value["source_evidence"]["created_at"] = timestamp  # type: ignore[index]
    value["source_evidence"]["freshness_checked_at"] = timestamp  # type: ignore[index]
    value["audit"]["entries"][0]["created_at"] = timestamp  # type: ignore[index]
    assert validate_curriculum_handoff(value).status is ValidationStatus.VALID


@pytest.mark.parametrize(
    "timestamp",
    [
        "2025-02-29T00:00:00Z",
        "2026-13-01T00:00:00Z",
        "2026-04-31T00:00:00Z",
        "2026-01-01T24:00:00Z",
    ],
)
def test_semantically_invalid_timestamps(timestamp: str) -> None:
    value = valid_handoff()
    value["source_evidence"]["created_at"] = timestamp  # type: ignore[index]
    assert "handoff-invalid" in validate_curriculum_handoff(value).reason_codes


def test_freshness_and_audit_revision_consistency() -> None:
    stale_order = valid_handoff()
    stale_order["source_evidence"]["created_at"] = "2026-07-29T00:00:01Z"  # type: ignore[index]
    assert "source-invalid" in validate_curriculum_handoff(stale_order).reason_codes
    wrong_revision = valid_handoff()
    wrong_revision["audit"]["entries"][0]["record_revision"] = 2  # type: ignore[index]
    assert "identity-invalid" in validate_curriculum_handoff(wrong_revision).reason_codes


def test_public_core_reuse_needs_no_private_validator_copy() -> None:
    import instructional_workflow_contracts as package

    normalized = package.validate_and_normalize_json({"b": 2, "a": 1})
    assert package.canonical_json_bytes(normalized) == b'{"a":1,"b":2}'
    assert package.ValidatedRecord is ValidatedRecord
    assert package.ValidationResult is ValidationResult


def test_import_policy_and_no_side_effect_calls() -> None:
    root = Path(__file__).parents[1] / "src" / "instructional_workflow_contracts"
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
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports: set[str] = set()
        calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")
            elif isinstance(node, ast.Call):
                calls.add(
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else ""
                )
        assert not any(
            imported == forbidden or imported.startswith(forbidden + ".")
            for imported in imports
            for forbidden in FORBIDDEN_IMPORT_PREFIXES
        )
        if path.name == "common.py":
            assert imports <= allowed_common
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
