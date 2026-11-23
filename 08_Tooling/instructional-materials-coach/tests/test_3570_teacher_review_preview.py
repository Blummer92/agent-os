"""Fail-closed tests for #3570 Q2 Teacher Review Preview.

The preview is a pure, non-authorizing projection over a canonical
``imc-build-receipt-v1`` record plus caller-supplied canonical evidence.
It never grants classroom-ready status, never derives required visuals
from the receipt's placement references, and never touches Drive/Notion.
"""
import copy
import json

import pytest

from instructional_materials_coach.teacher_review_preview import (
    TEACHER_REVIEW_PREVIEW_LABEL,
    build_teacher_review_preview,
)

IDEMPOTENCY_KEY = "q2-preview-key"
REQUIREMENT_IDENTITY = {
    "requirement_id": "req-1",
    "contract_version": "material-requirement-v1",
    "record_revision": "rev-req-7",
    "source_fingerprint": "fp-abc",
}
CONTENT_IDENTITY = {"asset_id": "asset-9", "revision": "v3", "sha256": "abc123"}
ROLE_ID = "inline-analysis-diagram"
SLOT_ID = "0"
ASSET_ID = "asset-9"
SLIDES_FILE = "slides-file-1"
DOC_FILE = "doc-file-1"


def _receipt(*, placement_references=(), succeeded=True, terminal_qa_state="verified"):
    return {
        "contract_version": "imc-build-receipt-v1",
        "idempotency_key": IDEMPOTENCY_KEY,
        "requirement_identity": dict(REQUIREMENT_IDENTITY),
        "templates": {
            "slides": {"file_id": "slides-tmpl", "revision_id": "tmpl-rev-s3"},
            "worksheet": {"file_id": "doc-tmpl", "revision_id": "tmpl-rev-w5"},
        },
        "artifacts": {
            "slides": {"file_id": SLIDES_FILE, "revision_id": "srev-11", "state": "updated",
                       "terminal_qa_state": terminal_qa_state,
                       "requested_format": {"status": "ok", "complete": True, "reason_code": "ok"}},
            "worksheet": {"file_id": DOC_FILE, "revision_id": "drev-22", "state": "updated",
                          "terminal_qa_state": terminal_qa_state,
                          "requested_format": {"status": "ok", "complete": True, "reason_code": "ok"}},
        },
        "terminal_qa_state": terminal_qa_state,
        "placement_receipt_references": list(placement_references),
        "succeeded": succeeded,
        "authority": {"execution_authorized": False, "production_authorized": False,
                      "classroom_ready": False},
    }


def _required(role_id=ROLE_ID, slot_id=SLOT_ID, asset_id=ASSET_ID,
              content_identity=CONTENT_IDENTITY, required=True):
    return {"role_id": role_id, "slot_id": slot_id, "asset_id": asset_id,
            "content_identity": dict(content_identity), "required": required}


def _placement(role_id=ROLE_ID, slot_id=SLOT_ID, asset_id=ASSET_ID,
               content_identity=CONTENT_IDENTITY, artifact_id=SLIDES_FILE,
               state="verified"):
    return {"role_id": role_id, "slot_id": slot_id, "asset_id": asset_id,
            "content_identity": dict(content_identity), "artifact_id": artifact_id,
            "state": state, "contract_version": "visual-placement-receipt-v1",
            "idempotency_key": IDEMPOTENCY_KEY}


def _preview(receipt=None, required=(), placements=()):
    return build_teacher_review_preview(
        _receipt() if receipt is None else receipt,
        idempotency_key=IDEMPOTENCY_KEY,
        requirement_identity=dict(REQUIREMENT_IDENTITY),
        required_visuals=list(required),
        placement_records=list(placements),
    )


def _visual(preview, role_id=ROLE_ID, slot_id=SLOT_ID):
    matches = [v for v in preview["visuals"] if v["role_id"] == role_id and v["slot_id"] == slot_id]
    assert len(matches) == 1, preview["visuals"]
    return matches[0]


def test_label_exact_and_never_classroom_ready_empty_required():
    # Q2-01: valid receipt, empty required set.
    preview = _preview()
    assert preview["label"] == TEACHER_REVIEW_PREVIEW_LABEL
    assert preview["label"] == "Teacher Review Preview — Not Classroom Ready"
    assert preview["classroom_ready"] is False
    assert preview["authority"] == {"execution_authorized": False,
                                    "production_authorized": False,
                                    "classroom_ready": False}
    assert preview["visuals"] == []
    assert preview["visual_completeness"] == "all-verified-within-preview"
    assert preview["provenance_status"] == "available"


def test_required_visual_without_placement_is_explicitly_incomplete():
    # Q2-02
    preview = _preview(required=[_required()])
    visual = _visual(preview)
    assert visual["status"] == "incomplete"
    assert visual["reason_code"] == "preview.placement-receipt-missing"
    assert visual["role_id"] == ROLE_ID and visual["slot_id"] == SLOT_ID
    assert preview["visual_completeness"] == "incomplete"
    assert preview["incomplete_visuals"] == [{"role_id": ROLE_ID, "slot_id": SLOT_ID}]


def test_only_unsatisfied_slot_is_incomplete():
    # Q2-03: two required slots, one verified placement.
    reference = {"role_id": ROLE_ID, "slot_id": "0", "asset_id": ASSET_ID,
                 "idempotency_key": IDEMPOTENCY_KEY}
    receipt = _receipt(placement_references=[reference])
    preview = _preview(receipt, required=[_required(slot_id="0"), _required(slot_id="1")],
                       placements=[_placement(slot_id="0")])
    assert _visual(preview, slot_id="0")["status"] == "verified-within-preview"
    second = _visual(preview, slot_id="1")
    assert second["status"] == "incomplete"
    assert second["reason_code"] == "preview.placement-receipt-missing"
    assert preview["incomplete_visuals"] == [{"role_id": ROLE_ID, "slot_id": "1"}]


def test_empty_placement_references_never_clear_a_requirement():
    # Q2-04: the negative proof at the heart of #3570. The receipt lists
    # no placement references at all, yet the required visual stays
    # incomplete instead of being silently cleared.
    receipt = _receipt(placement_references=[])
    preview = _preview(receipt, required=[_required()], placements=[])
    assert _visual(preview)["status"] == "incomplete"
    assert preview["visual_completeness"] == "incomplete"


def test_verified_placement_is_verified_within_preview_not_ready():
    # Q2-05
    reference = {"role_id": ROLE_ID, "slot_id": SLOT_ID, "asset_id": ASSET_ID,
                 "idempotency_key": IDEMPOTENCY_KEY}
    preview = _preview(_receipt(placement_references=[reference]),
                       required=[_required()], placements=[_placement()])
    visual = _visual(preview)
    assert visual["status"] == "verified-within-preview"
    assert visual["reason_code"] == "preview.verified-within-preview"
    assert preview["classroom_ready"] is False
    assert preview["visual_completeness"] == "all-verified-within-preview"


def test_wrong_role_or_slot_or_stale_revision_is_not_verified():
    # Q2-06
    reference = {"role_id": ROLE_ID, "slot_id": SLOT_ID, "asset_id": ASSET_ID,
                 "idempotency_key": IDEMPOTENCY_KEY}
    receipt = _receipt(placement_references=[reference])
    # Wrong role, same slot.
    preview = _preview(receipt, required=[_required()],
                       placements=[_placement(role_id="other-role")])
    assert _visual(preview)["reason_code"] == "preview.semantic-role-mismatch"
    # Wrong slot, same role.
    preview = _preview(receipt, required=[_required()],
                       placements=[_placement(slot_id="9")])
    assert _visual(preview)["reason_code"] == "preview.placement-receipt-missing"
    # Stale content identity.
    preview = _preview(receipt, required=[_required()],
                       placements=[_placement(content_identity={"asset_id": ASSET_ID,
                                                                  "revision": "v2"})])
    assert _visual(preview)["reason_code"] == "preview.placement-evidence-mismatch"
    # Artifact not bound to the receipt's artifacts.
    preview = _preview(receipt, required=[_required()],
                       placements=[_placement(artifact_id="unknown-file")])
    assert _visual(preview)["reason_code"] == "preview.placement-evidence-mismatch"
    # Placement record exists but the receipt carries no matching reference.
    preview = _preview(_receipt(placement_references=[]),
                       required=[_required()], placements=[_placement()])
    assert _visual(preview)["reason_code"] == "preview.placement-evidence-mismatch"
    for result in (preview,):
        assert result["classroom_ready"] is False


def test_conflicting_placements_fail_closed():
    # Q2-07
    reference = {"role_id": ROLE_ID, "slot_id": SLOT_ID, "asset_id": ASSET_ID,
                 "idempotency_key": IDEMPOTENCY_KEY}
    preview = _preview(_receipt(placement_references=[reference]),
                       required=[_required()],
                       placements=[_placement(),
                                   _placement(content_identity={"asset_id": ASSET_ID,
                                                                 "revision": "v9"})])
    visual = _visual(preview)
    assert visual["status"] == "incomplete"
    assert visual["reason_code"] == "preview.placement-evidence-conflict"


@pytest.mark.parametrize("mutation", [
    lambda r: r.pop("contract_version"),
    lambda r: r.update(contract_version="imc-build-receipt-v2"),
    lambda r: r.update(idempotency_key=""),
    lambda r: r.update(idempotency_key="other-key"),
    lambda r: r["requirement_identity"].pop("source_fingerprint"),
    lambda r: r["requirement_identity"].update(requirement_id="other-req"),
])
def test_missing_malformed_or_wrong_receipt_is_unavailable(mutation):
    # Q2-08
    receipt = _receipt()
    mutation(receipt)
    preview = _preview(receipt, required=[_required()], placements=[_placement()])
    assert preview["provenance_status"] == "unavailable"
    assert preview["visuals"] == []
    assert preview["classroom_ready"] is False
    assert preview["reason_codes"] == ["preview.provenance-unavailable"]


def test_non_mapping_receipt_is_unavailable():
    preview = build_teacher_review_preview(
        "not-a-mapping", idempotency_key=IDEMPOTENCY_KEY,
        requirement_identity=dict(REQUIREMENT_IDENTITY),
        required_visuals=[_required()], placement_records=[_placement()])
    assert preview["provenance_status"] == "unavailable"
    assert preview["visuals"] == []


def test_missing_idempotency_or_mismatched_identity_fails_closed():
    # Q2-09: caller-side identity is missing/mismatched against the receipt.
    preview = build_teacher_review_preview(
        _receipt(), idempotency_key="",
        requirement_identity=dict(REQUIREMENT_IDENTITY),
        required_visuals=[_required()], placement_records=[_placement()])
    assert preview["provenance_status"] == "unavailable"
    preview = build_teacher_review_preview(
        _receipt(), idempotency_key=IDEMPOTENCY_KEY,
        requirement_identity={**REQUIREMENT_IDENTITY, "record_revision": "other-rev"},
        required_visuals=[_required()], placement_records=[_placement()])
    assert preview["provenance_status"] == "unavailable"


def test_successful_build_preview_stays_not_classroom_ready():
    # Q2-10: even a succeeded, terminal-QA-verified build previewed here
    # stays a preview; build/QA facts are reported, never used as admission.
    reference = {"role_id": ROLE_ID, "slot_id": SLOT_ID, "asset_id": ASSET_ID,
                 "idempotency_key": IDEMPOTENCY_KEY}
    preview = _preview(_receipt(placement_references=[reference], succeeded=True,
                                terminal_qa_state="verified"),
                       required=[_required()], placements=[_placement()])
    assert preview["build_succeeded"] is True
    assert preview["terminal_qa_state"] == "verified"
    assert preview["classroom_ready"] is False
    assert preview["label"] == TEACHER_REVIEW_PREVIEW_LABEL


def test_not_required_visual_is_listed_not_counted_incomplete():
    preview = _preview(required=[_required(required=False)])
    visual = _visual(preview)
    assert visual["status"] == "not-required"
    assert visual["reason_code"] == "preview.not-required"
    assert preview["incomplete_visuals"] == []
    assert preview["visual_completeness"] == "all-verified-within-preview"


def test_inputs_are_never_mutated_and_output_is_deterministic():
    receipt = _receipt()
    required = [_required()]
    placements = [_placement()]
    before = (copy.deepcopy(receipt), copy.deepcopy(required), copy.deepcopy(placements))
    first = build_teacher_review_preview(
        receipt, idempotency_key=IDEMPOTENCY_KEY,
        requirement_identity=dict(REQUIREMENT_IDENTITY),
        required_visuals=required, placement_records=placements)
    second = build_teacher_review_preview(
        receipt, idempotency_key=IDEMPOTENCY_KEY,
        requirement_identity=dict(REQUIREMENT_IDENTITY),
        required_visuals=required, placement_records=placements)
    assert (receipt, required, placements) == before
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["preview_id"].startswith("teacher-review-preview:")


def test_duplicate_required_slot_is_evidence_malformed():
    preview = _preview(required=[_required(), _required()])
    assert preview["provenance_status"] == "unavailable"
    assert preview["reason_codes"] == ["preview.evidence-malformed"]


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return str(path)


def _cli_args(tmp_path, receipt=None, required=None, placements=None):
    return [
        "preview-teacher-review",
        "--build-receipt", _write_json(tmp_path / "receipt.json",
                                       _receipt() if receipt is None else receipt),
        "--required-visuals", _write_json(tmp_path / "required.json",
                                          [_required()] if required is None else required),
        "--placement-records", _write_json(tmp_path / "placements.json",
                                           [] if placements is None else placements),
        "--requirement-identity", _write_json(tmp_path / "identity.json", REQUIREMENT_IDENTITY),
        "--idempotency-key", IDEMPOTENCY_KEY,
    ]


def test_cli_consumer_shows_label_provenance_and_incomplete_visual(tmp_path, capsys):
    # Q2-12: the preview is produced through an actual supported consumer
    # (the offline CLI), not only through a unit-tested helper.
    from instructional_materials_coach import cli

    assert cli.main(_cli_args(tmp_path)) == 0
    out = capsys.readouterr().out
    preview = json.loads(out[out.index("{"):out.rindex("}") + 1])
    assert preview["label"] == "Teacher Review Preview — Not Classroom Ready"
    assert preview["provenance_status"] == "available"
    assert preview["contract_version"] == "imc-build-receipt-v1"
    assert preview["idempotency_key"] == IDEMPOTENCY_KEY
    assert preview["classroom_ready"] is False
    assert _visual(preview)["status"] == "incomplete"
    assert "Teacher Review Preview — Not Classroom Ready" in out


def test_cli_no_write_produces_stdout_only_and_unavailable_exits_nonzero(tmp_path, capsys):
    # Q2-13: with no --preview-out, the run writes no file at all.
    from instructional_materials_coach import cli

    args = _cli_args(tmp_path)
    before = set(tmp_path.iterdir())
    assert cli.main(args) == 0
    assert set(tmp_path.iterdir()) == before
    # A receipt with the wrong contract version is refused, exit 1.
    bad = _receipt()
    bad["contract_version"] = "imc-build-receipt-v2"
    assert cli.main(_cli_args(tmp_path, receipt=bad)) == 1
