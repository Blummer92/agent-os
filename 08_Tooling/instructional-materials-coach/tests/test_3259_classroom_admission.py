"""Fail-closed matrix + purity tests for #3259 D8 classroom admission.

Feeds the REAL ``build_receipt.build_receipt_record`` output (never a mock
receipt shape) into ``classroom_admission.classify_classroom_admission``.
"""
import copy
import json

from instructional_materials_coach.build_receipt import (
    BUILD_RECEIPT_CONTRACT,
    build_receipt_record,
)
from instructional_materials_coach.classroom_admission import (
    ClassroomAdmission,
    ClassroomAdmissionReason,
    classify_classroom_admission,
    serialize_classroom_admission,
)
from instructional_materials_coach.live_build import (
    LiveBuildInput,
    LiveBuildReceipt,
    ArtifactReceipt,
)


def _admitting_record():
    """Real receipt via the canonical builder, with all evidence admitting."""
    build = LiveBuildInput(
        slides_template_id="slides-template", doc_template_id="docs-template",
        target_folder_id="folder", slides_name="Slides", doc_name="Worksheet",
        idempotency_key="d8-key", slides_requests=(), docs_requests=(),
    )
    receipt = LiveBuildReceipt(
        slides=ArtifactReceipt(role="slides", state="planned"),
        worksheet=ArtifactReceipt(role="worksheet", state="planned"),
    )
    record = build_receipt_record(build, receipt, requirement_identity={"requirement_id": "r1"})
    assert record["contract_version"] == BUILD_RECEIPT_CONTRACT
    # Force the two remaining evidence fields to their admitting values on the
    # real record shape (the builder hard-codes succeeded=False for planned
    # artifacts and terminal_qa_state=None without a QA report).
    record["succeeded"] = True
    record["terminal_qa_state"] = "verified"
    return record


def test_all_evidence_admits():
    result = classify_classroom_admission(_admitting_record())
    assert result.status is ClassroomAdmission.ADMITTED
    assert result.reason_codes == (ClassroomAdmissionReason.EVIDENCE_COMPLETE,)
    assert result.authoritative is False
    assert result.classroom_ready_granted is False


def test_wrong_contract_version_fails_closed():
    record = _admitting_record()
    record["contract_version"] = "imc-build-receipt-v0"
    result = classify_classroom_admission(record)
    assert result.status is ClassroomAdmission.NOT_ADMITTED
    assert ClassroomAdmissionReason.CONTRACT_VERSION_MISMATCH in result.reason_codes


def test_missing_contract_version_fails_closed():
    record = _admitting_record()
    del record["contract_version"]
    result = classify_classroom_admission(record)
    assert result.status is ClassroomAdmission.NOT_ADMITTED
    assert ClassroomAdmissionReason.CONTRACT_VERSION_MISMATCH in result.reason_codes


def test_build_not_succeeded_fails_closed():
    record = _admitting_record()
    record["succeeded"] = False
    result = classify_classroom_admission(record)
    assert result.status is ClassroomAdmission.NOT_ADMITTED
    assert ClassroomAdmissionReason.BUILD_NOT_SUCCEEDED in result.reason_codes


def test_truthy_non_bool_succeeded_fails_closed():
    record = _admitting_record()
    record["succeeded"] = 1  # truthy but not exactly True: refused
    result = classify_classroom_admission(record)
    assert result.status is ClassroomAdmission.NOT_ADMITTED
    assert ClassroomAdmissionReason.BUILD_NOT_SUCCEEDED in result.reason_codes


def test_terminal_qa_not_verified_fails_closed():
    record = _admitting_record()
    record["terminal_qa_state"] = "persisted"
    result = classify_classroom_admission(record)
    assert result.status is ClassroomAdmission.NOT_ADMITTED
    assert ClassroomAdmissionReason.TERMINAL_QA_NOT_VERIFIED in result.reason_codes


def test_missing_terminal_qa_state_fails_closed():
    record = _admitting_record()
    record["terminal_qa_state"] = None
    result = classify_classroom_admission(record)
    assert result.status is ClassroomAdmission.NOT_ADMITTED
    assert ClassroomAdmissionReason.TERMINAL_QA_NOT_VERIFIED in result.reason_codes


def test_multiple_failures_report_all_reasons():
    record = _admitting_record()
    record["contract_version"] = "bogus"
    record["succeeded"] = False
    record["terminal_qa_state"] = "failed"
    result = classify_classroom_admission(record)
    assert result.status is ClassroomAdmission.NOT_ADMITTED
    assert set(result.reason_codes) == {
        ClassroomAdmissionReason.CONTRACT_VERSION_MISMATCH,
        ClassroomAdmissionReason.BUILD_NOT_SUCCEEDED,
        ClassroomAdmissionReason.TERMINAL_QA_NOT_VERIFIED,
    }


def test_non_mapping_receipt_fails_closed():
    for bad in (None, "receipt", 42, ["contract_version"]):
        result = classify_classroom_admission(bad)
        assert result.status is ClassroomAdmission.NOT_ADMITTED
        assert result.reason_codes == (ClassroomAdmissionReason.RECEIPT_MALFORMED,)


def test_caller_authority_claims_are_ignored():
    # A caller asserting classroom_ready=True must not influence admission:
    # only evidence fields decide. Here the evidence fails, so the claim is
    # irrelevant.
    record = _admitting_record()
    record["succeeded"] = False
    record["authority"] = {
        "execution_authorized": True,
        "production_authorized": True,
        "classroom_ready": True,
    }
    result = classify_classroom_admission(record)
    assert result.status is ClassroomAdmission.NOT_ADMITTED
    # And a fully-admitting evidence set admits regardless of authority block.
    good = _admitting_record()
    good["authority"] = {
        "execution_authorized": False,
        "production_authorized": False,
        "classroom_ready": False,
    }
    assert classify_classroom_admission(good).status is ClassroomAdmission.ADMITTED


def test_input_mapping_is_never_mutated():
    record = _admitting_record()
    snapshot = copy.deepcopy(record)
    classify_classroom_admission(record)
    assert record == snapshot


def test_deterministic_result_ids():
    first = classify_classroom_admission(_admitting_record())
    second = classify_classroom_admission(_admitting_record())
    assert first.result_id == second.result_id
    assert first.result_id.startswith("classroom-admission:")


def test_serialization_integrity_binding():
    result = classify_classroom_admission(_admitting_record())
    serialized = serialize_classroom_admission(result)
    assert serialized["status"] == "admitted"
    assert serialized["result_id"] == result.result_id
    assert serialized["authoritative"] is False
    assert serialized["classroom_ready_granted"] is False
    # Tampering with the result is refused at serialization.
    tampered = classify_classroom_admission(_admitting_record())
    object.__setattr__(tampered, "status", ClassroomAdmission.NOT_ADMITTED)
    try:
        serialize_classroom_admission(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("tampered result must fail integrity verification")


def test_json_safe_evidence_roundtrip():
    record = _admitting_record()
    assert json.loads(json.dumps(record))["contract_version"] == BUILD_RECEIPT_CONTRACT
