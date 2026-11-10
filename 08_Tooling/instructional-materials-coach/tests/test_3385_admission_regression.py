"""Admission-predicate regression fixtures for #3385's two bypass reproductions.

#3385 owns the direct-authoring bypass acceptance/regression boundary:
generation-side repair of the direct ChatGPT/DOCX route is not
repository-reachable (host-capability boundary), so enforcement is
admission-side via the D8 predicate. These fixtures pin the two
reproductions against the REAL
``classroom_admission.classify_classroom_admission`` predicate, fed with
REAL ``build_receipt.build_receipt_record`` output (never a mock receipt
shape) plus canonical evidence assembled from the same real governed
objects:

- Photography 2026-10-07 ("Same Subject, Different Ways"): a
  required-visual worksheet delivered text-only — zero embedded/placed
  images — must NOT be admitted (visual-role reason code), even though the
  receipt itself claims render success. Mechanical render success does not
  satisfy instructional visual completeness.
- Day 1 Marketing Detectives: a receipt carrying a caller-asserted
  ``classroom_ready: true`` with incomplete canonical evidence must NOT be
  admitted; the verdict is identical with and without the authority block
  (caller claims are never trusted, every check is re-derived).

Fixture helpers are intentionally self-contained here rather than imported
from ``test_3259_classroom_admission``: the regression fixtures must not
break if the D8 fail-closed matrix helpers are refactored.
"""
import copy

from instructional_materials_coach.artifact_content_qa import (
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

IDEMPOTENCY_KEY = "3385-admission-key"
FOLDER_ID = "folder-1"
SLIDES_FILE = "slides-file-1"
DOC_FILE = "doc-file-1"
SLIDES_REV = "srev-11"
DOC_REV = "drev-22"
SLIDES_TEMPLATE = "slides-tmpl"
DOC_TEMPLATE = "doc-tmpl"
REQUIREMENT_IDENTITY = {
    "requirement_id": "req-photography-foundations",
    "contract_version": "material-requirement-v1",
    "record_revision": "rev-req-7",
    "source_fingerprint": "fp-abc",
}
TEMPLATE_REVISIONS = {"slides": "tmpl-rev-s3", "worksheet": "tmpl-rev-w5"}

# Photography Foundations "Same Subject, Different Ways" (2026-10-07):
# the required visual roles the direct-DOCX worksheet omitted.
PHOTOGRAPHY_ROLES = (
    ("photography-example-angle", "slot-photo-angle", "photo-asset-angle"),
    ("photography-example-distance", "slot-photo-distance", "photo-asset-distance"),
    ("photography-example-framing", "slot-photo-framing", "photo-asset-framing"),
    ("photography-example-composition", "slot-photo-composition", "photo-asset-composition"),
)

# Day 1 Marketing Detectives: caller-asserted classroom-ready on a worksheet
# the direct route delivered without canonical QA consumption.
DAY1_ROLE_ID = "marketing-detective-clue-board"
DAY1_ASSET_ID = "day1-asset-1"


def _content_identity(asset_id):
    return {"asset_id": asset_id, "revision": "v1", "sha256": f"sha-{asset_id}"}


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


def _qa_report(state="verified"):
    return TerminalQAReport(
        idempotency_key=IDEMPOTENCY_KEY,
        slides=ArtifactQAReport(
            artifact_type="slides", artifact_id=SLIDES_FILE, revision_id=SLIDES_REV,
            idempotency_key=IDEMPOTENCY_KEY, state=state,
        ),
        worksheet=ArtifactQAReport(
            artifact_type="worksheet", artifact_id=DOC_FILE, revision_id=DOC_REV,
            idempotency_key=IDEMPOTENCY_KEY, state=state,
        ),
        state=state,
    )


def _binding(role_id, slot_id, asset_id):
    return VisualPlacementBinding(
        role_id=role_id, asset_id=asset_id, drive_file_id="drive-1",
        content_identity=_content_identity(asset_id), source_plan_id="plan-1",
        required=True, slot_id=slot_id,
    )


def _placement_record(role_id, slot_id, asset_id, artifact_id=SLIDES_FILE):
    record = build_placement_record(
        receipt={
            "asset_id": asset_id, "drive_file_id": "drive-1", "role_id": role_id,
            "artifact_type": "slides", "artifact_id": artifact_id,
            "artifact_revision_id": SLIDES_REV, "marker": None,
            "container_id": None, "inserted_element_id": None, "state": "verified",
        },
        content_identity=_content_identity(asset_id),
        slot_id=slot_id, source_plan_id="plan-1", required=True,
        eligibility_evidence=None, transport_name="test",
        post_insertion_revision=SLIDES_REV,
    )
    record["idempotency_key"] = IDEMPOTENCY_KEY
    # append_placement_record stamps these on persist; the predicate checks
    # both, so the test fixture mirrors the stored form.
    record["contract_version"] = "visual-placement-receipt-v1"
    return record


def _build_input(bindings):
    return LiveBuildInput(
        slides_template_id=SLIDES_TEMPLATE, doc_template_id=DOC_TEMPLATE,
        target_folder_id=FOLDER_ID, slides_name="S", doc_name="W",
        idempotency_key=IDEMPOTENCY_KEY, slides_requests=(), docs_requests=(),
        visual_placements=tuple(bindings),
    )


def _live_receipt():
    return LiveBuildReceipt(
        slides=_artifact_receipt("slides", SLIDES_FILE, GOOGLE_SLIDES_MIME),
        worksheet=_artifact_receipt("worksheet", DOC_FILE, GOOGLE_DOCS_MIME),
        terminal_qa=_qa_report(),
    )


def _evidence(build, placement_records):
    return assemble_admission_evidence(
        idempotency_key=IDEMPOTENCY_KEY,
        requirement_identity=dict(REQUIREMENT_IDENTITY),
        template_identities=(
            ("slides", SLIDES_TEMPLATE, TEMPLATE_REVISIONS["slides"]),
            ("worksheet", DOC_TEMPLATE, TEMPLATE_REVISIONS["worksheet"]),
        ),
        artifact_identities=(
            ("slides", SLIDES_FILE, SLIDES_REV),
            ("worksheet", DOC_FILE, DOC_REV),
        ),
        requested_artifact_roles=("slides", "worksheet"),
        terminal_qa_states=(("slides", "verified"), ("worksheet", "verified")),
        build_succeeded=True,
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


def _receipt(bindings):
    record = build_receipt_record(
        _build_input(bindings), _live_receipt(),
        requirement_identity=dict(REQUIREMENT_IDENTITY),
        template_revisions=dict(TEMPLATE_REVISIONS),
    )
    assert record["contract_version"] == BUILD_RECEIPT_CONTRACT
    return record


def _assert_not_admitted(result, *codes):
    assert result.status is ClassroomAdmission.NOT_ADMITTED
    for code in codes:
        assert code in result.reason_codes, result.reason_codes
    assert result.authoritative is False
    assert result.execution_authorized is False
    assert result.production_authorized is False
    assert result.classroom_ready_granted is False


def test_photography_text_only_worksheet_not_admitted():
    """#3385 reproduction 1: the 2026-10-07 Photography case.

    The direct DOCX worksheet omitted every required visual role
    (angle/distance/framing/composition): zero embedded/placed images, so
    the canonical evidence declares required visuals with no verified
    placement receipts. The receipt itself claims the build succeeded and
    every requested format is complete — mechanical render success must
    still not admit the worksheet.
    """
    bindings = [_binding(role_id, slot_id, asset_id)
                for role_id, slot_id, asset_id in PHOTOGRAPHY_ROLES]
    build = _build_input(bindings)
    record = _receipt(bindings)
    # The receipt asserts its own mechanical completeness...
    assert record["succeeded"] is True
    for role in ("slides", "worksheet"):
        assert record["artifacts"][role]["requested_format"]["complete"] is True
    # ...but no visuals were ever placed: zero placement receipts.
    evidence = _evidence(build, ())
    result = classify_classroom_admission(record, evidence)
    # All four unfulfilled required visuals name the same visual-role
    # failure; the contract dedupes to one deterministic reason code.
    assert result.status is ClassroomAdmission.NOT_ADMITTED
    assert result.reason_codes == (ClassroomAdmissionReason.PLACEMENT_RECEIPT_MISSING,)
    _assert_not_admitted(result, ClassroomAdmissionReason.PLACEMENT_RECEIPT_MISSING)


def test_photography_verified_visuals_are_admission_eligible_control():
    """Control for reproduction 1: the same Photography worksheet WITH the
    required visuals placed and verified IS eligible for admission. The
    failure above is specific to the omitted visuals, not to the
    Photography worksheet shape."""
    bindings = [_binding(role_id, slot_id, asset_id)
                for role_id, slot_id, asset_id in PHOTOGRAPHY_ROLES]
    build = _build_input(bindings)
    record = _receipt(bindings)
    records = [_placement_record(role_id, slot_id, asset_id)
               for role_id, slot_id, asset_id in PHOTOGRAPHY_ROLES]
    evidence = _evidence(build, records)
    result = classify_classroom_admission(record, evidence)
    assert result.status is ClassroomAdmission.ADMITTED
    assert result.reason_codes == (ClassroomAdmissionReason.EVIDENCE_COMPLETE,)


def test_day1_caller_asserted_classroom_ready_not_admitted():
    """#3385 reproduction 2: the Day 1 Marketing Detectives case.

    The direct-authoring route delivered the worksheet as a review draft
    with a caller-asserted ``classroom_ready: true`` but no demonstrated
    canonical QA consumption — here the governed requirement identity is
    absent from the receipt. The caller claim must not influence admission:
    the verdict is identical with and without the authority block, because
    every check is re-derived from canonical evidence.
    """
    bindings = (_binding(DAY1_ROLE_ID, "slot-day1", DAY1_ASSET_ID),)
    build = _build_input(bindings)
    record = _receipt(bindings)
    records = (_placement_record(DAY1_ROLE_ID, "slot-day1", DAY1_ASSET_ID),)
    evidence = _evidence(build, records)
    # The direct route produced no governed requirement identity, but the
    # caller asserts the worksheet is classroom-ready.
    del record["requirement_identity"]
    record["authority"] = {
        "classroom_ready": True,
        "execution_authorized": True,
        "production_authorized": True,
    }
    with_claim = classify_classroom_admission(record, evidence)
    _assert_not_admitted(
        with_claim, ClassroomAdmissionReason.REQUIREMENT_IDENTITY_INCOMPLETE
    )

    # The identical receipt/evidence without any caller authority claim
    # yields the identical verdict: caller claims are never trusted.
    unclaimed = copy.deepcopy(record)
    del unclaimed["authority"]
    without_claim = classify_classroom_admission(unclaimed, evidence)
    assert without_claim.status is with_claim.status
    assert without_claim.reason_codes == with_claim.reason_codes
    assert without_claim.result_id == with_claim.result_id
