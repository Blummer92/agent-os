"""Fail-closed matrix + purity tests for #3556 D8 classroom admission.

Feeds the REAL ``build_receipt.build_receipt_record`` output (never a mock
receipt shape) plus a canonical evidence bundle assembled from the same
real governed objects into
``classroom_admission.classify_classroom_admission``.
"""
import copy
import json

import pytest

from instructional_materials_coach.artifact_content_qa import (
    QA_STATE_CONTENT_MISSING,
    ArtifactQAReport,
    TerminalQAReport,
)
from instructional_materials_coach.build_receipt import (
    BUILD_RECEIPT_CONTRACT,
    build_receipt_record,
)
from instructional_materials_coach.classroom_admission import (
    ClassroomAdmission,
    ClassroomAdmissionReason,
    assemble_admission_evidence,
    classify_classroom_admission,
    serialize_classroom_admission,
)
from instructional_materials_coach.connected_visual_placement import (
    VisualPlacementBinding,
)
from instructional_materials_coach.drive_client import (
    GOOGLE_DOCS_MIME,
    GOOGLE_SLIDES_MIME,
)
from instructional_materials_coach.live_build import (
    ArtifactReceipt,
    LiveBuildInput,
    LiveBuildReceipt,
)
from instructional_materials_coach.placement_receipts import build_placement_record

IDEMPOTENCY_KEY = "d8-admission-key"
FOLDER_ID = "folder-1"
SLIDES_FILE = "slides-file-1"
DOC_FILE = "doc-file-1"
SLIDES_REV = "srev-11"
DOC_REV = "drev-22"
SLIDES_TEMPLATE = "slides-tmpl"
DOC_TEMPLATE = "doc-tmpl"
REQUIREMENT_IDENTITY = {
    "requirement_id": "req-1",
    "contract_version": "material-requirement-v1",
    "record_revision": "rev-req-7",
    "source_fingerprint": "fp-abc",
}
TEMPLATE_REVISIONS = {"slides": "tmpl-rev-s3", "worksheet": "tmpl-rev-w5"}
ROLE_ID = "inline-analysis-diagram"
ASSET_ID = "asset-9"
CONTENT_IDENTITY = {"asset_id": ASSET_ID, "revision": "v3", "sha256": "abc123"}


def _artifact_receipt(role, file_id, mime, qa_state="verified"):
    return ArtifactReceipt(
        role=role,
        state="updated",
        file_id=file_id,
        mime_type=mime,
        parents=(FOLDER_ID,),
        persistence_verified=True,
        canonical_editable=True,
        delivery_kind="final",
        terminal_qa_state=qa_state,
    )


def _qa_report(state="verified", slides_rev=SLIDES_REV, doc_rev=DOC_REV):
    return TerminalQAReport(
        idempotency_key=IDEMPOTENCY_KEY,
        slides=ArtifactQAReport(
            artifact_type="slides", artifact_id=SLIDES_FILE, revision_id=slides_rev,
            idempotency_key=IDEMPOTENCY_KEY, state=state,
        ),
        worksheet=ArtifactQAReport(
            artifact_type="worksheet", artifact_id=DOC_FILE, revision_id=doc_rev,
            idempotency_key=IDEMPOTENCY_KEY, state=state,
        ),
        state=state,
    )


def _binding(role_id=ROLE_ID, slot_id="0", asset_id=ASSET_ID,
             content_identity=CONTENT_IDENTITY, required=True):
    return VisualPlacementBinding(
        role_id=role_id, asset_id=asset_id, drive_file_id="drive-1",
        content_identity=dict(content_identity), source_plan_id="plan-1",
        required=required, slot_id=slot_id,
    )


def _placement_record(role_id=ROLE_ID, slot_id="0", asset_id=ASSET_ID,
                      content_identity=CONTENT_IDENTITY, artifact_id=SLIDES_FILE,
                      state="verified"):
    record = build_placement_record(
        receipt={
            "asset_id": asset_id, "drive_file_id": "drive-1", "role_id": role_id,
            "artifact_type": "slides", "artifact_id": artifact_id,
            "artifact_revision_id": SLIDES_REV, "marker": None,
            "container_id": None, "inserted_element_id": None, "state": state,
        },
        content_identity=dict(content_identity),
        slot_id=slot_id, source_plan_id="plan-1", required=True,
        eligibility_evidence=None, transport_name="test",
        post_insertion_revision=SLIDES_REV,
    )
    record["idempotency_key"] = IDEMPOTENCY_KEY
    # append_placement_record stamps these on persist; the predicate checks
    # both, so the test fixture mirrors the stored form.
    record["contract_version"] = "visual-placement-receipt-v1"
    return record


def _build_input(visual_placements=()):
    return LiveBuildInput(
        slides_template_id=SLIDES_TEMPLATE, doc_template_id=DOC_TEMPLATE,
        target_folder_id=FOLDER_ID, slides_name="S", doc_name="W",
        idempotency_key=IDEMPOTENCY_KEY, slides_requests=(), docs_requests=(),
        visual_placements=tuple(visual_placements),
    )


def _live_receipt(qa_state="verified", slides_rev=SLIDES_REV, doc_rev=DOC_REV):
    return LiveBuildReceipt(
        slides=_artifact_receipt("slides", SLIDES_FILE, GOOGLE_SLIDES_MIME, qa_state),
        worksheet=_artifact_receipt("worksheet", DOC_FILE, GOOGLE_DOCS_MIME, qa_state),
        terminal_qa=_qa_report(qa_state, slides_rev, doc_rev),
    )


def _evidence(build, receipt, placement_records, requirement_identity=None,
              qa_state="verified"):
    return assemble_admission_evidence(
        idempotency_key=IDEMPOTENCY_KEY,
        requirement_identity=dict(REQUIREMENT_IDENTITY if requirement_identity is None else requirement_identity),
        template_identities=(
            ("slides", SLIDES_TEMPLATE, TEMPLATE_REVISIONS["slides"]),
            ("worksheet", DOC_TEMPLATE, TEMPLATE_REVISIONS["worksheet"]),
        ),
        artifact_identities=(
            ("slides", SLIDES_FILE, SLIDES_REV),
            ("worksheet", DOC_FILE, DOC_REV),
        ),
        requested_artifact_roles=("slides", "worksheet"),
        terminal_qa_states=(("slides", qa_state), ("worksheet", qa_state)),
        build_succeeded=bool(receipt.succeeded),
        placement_records=tuple(placement_records),
        required_visuals=[
            {
                "role_id": binding.role_id, "slot_id": binding.slot_id,
                "asset_id": binding.asset_id,
                "content_identity": dict(binding.content_identity),
                "required": binding.required,
            }
            for binding in (build.visual_placements or ())
        ],
    )


def _admitting_fixture(with_visual=True, qa_state="verified"):
    bindings = (_binding(),) if with_visual else ()
    build = _build_input(bindings)
    receipt = _live_receipt(qa_state)
    record = build_receipt_record(
        build, receipt,
        requirement_identity=dict(REQUIREMENT_IDENTITY),
        template_revisions=dict(TEMPLATE_REVISIONS),
    )
    assert record["contract_version"] == BUILD_RECEIPT_CONTRACT
    assert record["succeeded"] is True or qa_state != "verified"
    records = (_placement_record(),) if with_visual else ()
    evidence = _evidence(build, receipt, records, qa_state=qa_state)
    return record, evidence


def _assert_not_admitted(result, *codes):
    assert result.status is ClassroomAdmission.NOT_ADMITTED
    for code in codes:
        assert code in result.reason_codes, result.reason_codes
    assert result.authoritative is False
    assert result.execution_authorized is False
    assert result.production_authorized is False
    assert result.classroom_ready_granted is False


def test_all_evidence_admits_visual_required():
    record, evidence = _admitting_fixture(with_visual=True)
    result = classify_classroom_admission(record, evidence)
    assert result.status is ClassroomAdmission.ADMITTED
    assert result.reason_codes == (ClassroomAdmissionReason.EVIDENCE_COMPLETE,)
    assert result.authoritative is False
    assert result.classroom_ready_granted is False


def test_all_evidence_admits_no_visual_needed_control():
    record, evidence = _admitting_fixture(with_visual=False)
    result = classify_classroom_admission(record, evidence)
    assert result.status is ClassroomAdmission.ADMITTED
    assert result.reason_codes == (ClassroomAdmissionReason.EVIDENCE_COMPLETE,)


def test_missing_receipt_fails_closed():
    _, evidence = _admitting_fixture()
    for bad in (None, "receipt", 42, ["contract_version"]):
        result = classify_classroom_admission(bad, evidence)
        assert result.status is ClassroomAdmission.NOT_ADMITTED
        assert result.reason_codes == (ClassroomAdmissionReason.RECEIPT_MALFORMED,)


def test_missing_evidence_fails_closed():
    record, _ = _admitting_fixture()
    result = classify_classroom_admission(record, None)
    assert result.status is ClassroomAdmission.NOT_ADMITTED
    assert result.reason_codes == (ClassroomAdmissionReason.EVIDENCE_MISSING,)


def test_wrong_contract_version_fails_closed():
    record, evidence = _admitting_fixture()
    record["contract_version"] = "imc-build-receipt-v0"
    _assert_not_admitted(
        classify_classroom_admission(record, evidence),
        ClassroomAdmissionReason.CONTRACT_VERSION_MISMATCH,
    )


def test_missing_contract_version_fails_closed():
    record, evidence = _admitting_fixture()
    del record["contract_version"]
    _assert_not_admitted(
        classify_classroom_admission(record, evidence),
        ClassroomAdmissionReason.CONTRACT_VERSION_MISMATCH,
    )


def test_idempotency_key_mismatch_fails_closed():
    record, evidence = _admitting_fixture()
    record["idempotency_key"] = "some-other-build"
    _assert_not_admitted(
        classify_classroom_admission(record, evidence),
        ClassroomAdmissionReason.IDEMPOTENCY_KEY_MISMATCH,
    )


def test_missing_requirement_identity_field_fails_closed():
    record, evidence = _admitting_fixture()
    del record["requirement_identity"]["record_revision"]
    _assert_not_admitted(
        classify_classroom_admission(record, evidence),
        ClassroomAdmissionReason.REQUIREMENT_IDENTITY_INCOMPLETE,
    )


def test_wrong_requirement_identity_fails_closed():
    record, evidence = _admitting_fixture()
    record["requirement_identity"]["requirement_id"] = "req-other-task"
    _assert_not_admitted(
        classify_classroom_admission(record, evidence),
        ClassroomAdmissionReason.REQUIREMENT_IDENTITY_MISMATCH,
    )


def test_stale_template_revision_fails_closed():
    record, evidence = _admitting_fixture()
    record["templates"]["slides"]["revision_id"] = "tmpl-rev-s1-stale"
    _assert_not_admitted(
        classify_classroom_admission(record, evidence),
        ClassroomAdmissionReason.TEMPLATE_IDENTITY_MISMATCH,
    )


def test_stale_artifact_revision_fails_closed():
    record, evidence = _admitting_fixture()
    record["artifacts"]["worksheet"]["revision_id"] = "drev-01-stale"
    _assert_not_admitted(
        classify_classroom_admission(record, evidence),
        ClassroomAdmissionReason.ARTIFACT_IDENTITY_MISMATCH,
    )


def test_tampered_succeeded_flag_fails_closed():
    record, evidence = _admitting_fixture()
    record["succeeded"] = False  # canonical build succeeded; receipt disagrees
    _assert_not_admitted(
        classify_classroom_admission(record, evidence),
        ClassroomAdmissionReason.BUILD_NOT_SUCCEEDED,
    )


def test_missing_requested_format_fails_closed():
    record, evidence = _admitting_fixture()
    record["artifacts"]["slides"]["requested_format"]["complete"] = False
    _assert_not_admitted(
        classify_classroom_admission(record, evidence),
        ClassroomAdmissionReason.REQUESTED_FORMAT_INCOMPLETE,
    )


def test_requested_format_mismatch_fails_closed():
    record, evidence = _admitting_fixture()
    record["artifacts"]["worksheet"]["requested_format"] = {
        "status": "blocked-production", "complete": False,
        "reason_code": "requested-format-mismatch",
    }
    _assert_not_admitted(
        classify_classroom_admission(record, evidence),
        ClassroomAdmissionReason.REQUESTED_FORMAT_INCOMPLETE,
    )


def test_terminal_qa_failed_fails_closed():
    record, evidence = _admitting_fixture(qa_state="failed")
    _assert_not_admitted(
        classify_classroom_admission(record, evidence),
        ClassroomAdmissionReason.TERMINAL_QA_NOT_VERIFIED,
    )


def test_terminal_qa_receipt_disagreement_fails_closed():
    record, evidence = _admitting_fixture()  # canonical QA verified...
    record["artifacts"]["slides"]["terminal_qa_state"] = "persisted"  # ...receipt says otherwise
    _assert_not_admitted(
        classify_classroom_admission(record, evidence),
        ClassroomAdmissionReason.TERMINAL_QA_NOT_VERIFIED,
    )


def test_missing_required_section_content_fails_closed():
    record, evidence = _admitting_fixture(qa_state=QA_STATE_CONTENT_MISSING)
    _assert_not_admitted(
        classify_classroom_admission(record, evidence),
        ClassroomAdmissionReason.TERMINAL_QA_NOT_VERIFIED,
    )


def test_q2_preview_state_is_never_admitted():
    record, evidence = _admitting_fixture(qa_state="preview")
    result = classify_classroom_admission(record, evidence)
    _assert_not_admitted(result, ClassroomAdmissionReason.TERMINAL_QA_NOT_VERIFIED)
    assert "preview" not in result.status.value


def test_missing_placement_receipt_fails_closed():
    record, evidence = _admitting_fixture(with_visual=True)
    build = _build_input((_binding(),))
    receipt = _live_receipt()
    no_records = _evidence(build, receipt, (), qa_state="verified")
    _assert_not_admitted(
        classify_classroom_admission(record, no_records),
        ClassroomAdmissionReason.PLACEMENT_RECEIPT_MISSING,
    )


def test_unplaced_required_visual_fails_closed():
    # A second required visual declared by the canonical evidence with no
    # placement record is a required visual missing its placement.
    record, evidence = _admitting_fixture(with_visual=True)
    build = _build_input((_binding(), _binding(role_id="second-required-visual", slot_id="1", asset_id="asset-2")))
    receipt = _live_receipt()
    partial = _evidence(build, receipt, (_placement_record(),), qa_state="verified")
    _assert_not_admitted(
        classify_classroom_admission(record, partial),
        ClassroomAdmissionReason.PLACEMENT_RECEIPT_MISSING,
    )


def test_placement_asset_mismatch_fails_closed():
    record, evidence = _admitting_fixture(with_visual=True)
    build = _build_input((_binding(),))
    receipt = _live_receipt()
    wrong_asset = _evidence(
        build, receipt, (_placement_record(asset_id="asset-other"),), qa_state="verified"
    )
    _assert_not_admitted(
        classify_classroom_admission(record, wrong_asset),
        ClassroomAdmissionReason.PLACEMENT_EVIDENCE_MISMATCH,
    )


def test_placement_stale_content_identity_fails_closed():
    record, evidence = _admitting_fixture(with_visual=True)
    build = _build_input((_binding(),))
    receipt = _live_receipt()
    stale = dict(CONTENT_IDENTITY, revision="v2")
    stale_evidence = _evidence(
        build, receipt, (_placement_record(content_identity=stale),), qa_state="verified"
    )
    _assert_not_admitted(
        classify_classroom_admission(record, stale_evidence),
        ClassroomAdmissionReason.PLACEMENT_EVIDENCE_MISMATCH,
    )


def test_semantic_role_mismatch_fails_closed():
    # A verified record for the same slot but a DIFFERENT role never
    # satisfies the required visual: roles are semantic identities.
    record, evidence = _admitting_fixture(with_visual=True)
    build = _build_input((_binding(),))
    receipt = _live_receipt()
    wrong_role = _evidence(
        build, receipt, (_placement_record(role_id="decorative-banner"),),
        qa_state="verified",
    )
    _assert_not_admitted(
        classify_classroom_admission(record, wrong_role),
        ClassroomAdmissionReason.SEMANTIC_ROLE_MISMATCH,
    )


def test_placement_evidence_conflict_fails_closed():
    record, evidence = _admitting_fixture(with_visual=True)
    build = _build_input((_binding(),))
    receipt = _live_receipt()
    conflicting = _evidence(
        build, receipt,
        (_placement_record(), _placement_record(content_identity=dict(CONTENT_IDENTITY, revision="v9"))),
        qa_state="verified",
    )
    _assert_not_admitted(
        classify_classroom_admission(record, conflicting),
        ClassroomAdmissionReason.PLACEMENT_EVIDENCE_CONFLICT,
    )


def test_placement_receipt_reference_mismatch_fails_closed():
    # Verified store record exists, but the receipt's placement references
    # do not correspond (tampered receipt references).
    record, evidence = _admitting_fixture(with_visual=True)
    record["placement_receipt_references"] = []
    _assert_not_admitted(
        classify_classroom_admission(record, evidence),
        ClassroomAdmissionReason.PLACEMENT_EVIDENCE_MISMATCH,
    )


def test_multiple_failures_report_all_reasons():
    record, evidence = _admitting_fixture()
    record["contract_version"] = "bogus"
    record["succeeded"] = False
    result = classify_classroom_admission(record, evidence)
    assert result.status is ClassroomAdmission.NOT_ADMITTED
    assert ClassroomAdmissionReason.CONTRACT_VERSION_MISMATCH in result.reason_codes
    assert ClassroomAdmissionReason.BUILD_NOT_SUCCEEDED in result.reason_codes
    assert result.reason_codes == tuple(sorted(result.reason_codes, key=lambda r: r.value))


def test_forged_caller_authority_is_ignored():
    # A caller asserting classroom_ready=True must not influence admission:
    # only re-derived canonical evidence decides.
    record, evidence = _admitting_fixture()
    record["authority"] = {
        "execution_authorized": True,
        "production_authorized": True,
        "classroom_ready": True,
    }
    result = classify_classroom_admission(record, evidence)
    assert result.status is ClassroomAdmission.ADMITTED
    assert result.classroom_ready_granted is False
    # And forged authority cannot rescue failing evidence.
    bad_record, bad_evidence = _admitting_fixture()
    bad_record["succeeded"] = False
    bad_record["authority"] = {"classroom_ready": True}
    _assert_not_admitted(
        classify_classroom_admission(bad_record, bad_evidence),
        ClassroomAdmissionReason.BUILD_NOT_SUCCEEDED,
    )


def test_inputs_are_never_mutated():
    record, evidence = _admitting_fixture()
    record_snapshot = copy.deepcopy(record)
    classify_classroom_admission(record, evidence)
    assert record == record_snapshot


def test_deterministic_result_ids():
    first = classify_classroom_admission(*_admitting_fixture())
    second = classify_classroom_admission(*_admitting_fixture())
    assert first.result_id == second.result_id
    assert first.result_id.startswith("classroom-admission:")


def test_serialization_integrity_binding():
    record, evidence = _admitting_fixture()
    result = classify_classroom_admission(record, evidence)
    serialized = serialize_classroom_admission(result)
    assert serialized["status"] == "admitted"
    assert serialized["result_id"] == result.result_id
    assert serialized["schema_version"] == "2.0"
    assert serialized["authoritative"] is False
    assert serialized["classroom_ready_granted"] is False
    # Tampering with the result is refused at serialization.
    tampered = classify_classroom_admission(record, evidence)
    object.__setattr__(tampered, "status", ClassroomAdmission.NOT_ADMITTED)
    with pytest.raises(ValueError):
        serialize_classroom_admission(tampered)


def test_assemble_evidence_rejects_malformed_input():
    build = _build_input((_binding(),))
    receipt = _live_receipt()
    with pytest.raises(TypeError):
        _evidence(build, receipt, (), requirement_identity={"requirement_id": 42})


def test_json_safe_evidence_roundtrip():
    record, evidence = _admitting_fixture()
    assert json.loads(json.dumps(record))["contract_version"] == BUILD_RECEIPT_CONTRACT
    serialized = serialize_classroom_admission(classify_classroom_admission(record, evidence))
    assert json.loads(json.dumps(serialized))["status"] == "admitted"
