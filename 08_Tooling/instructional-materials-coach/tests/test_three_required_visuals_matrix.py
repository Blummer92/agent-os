"""A lesson that requires three different visuals: planner -> terminal QA -> classroom admission.

Existing suites protect one visual at a time. This matrix uses a three-visual lesson so
that "two of three present" and "the right image on the wrong slide" are first-class
cases, at the three production layers that can each refuse an incomplete artifact:

* planner (``plan_governed_visual_reuse``): required roles with no candidates block production;
* terminal QA (``run_terminal_qa``): the persisted Docs/Slides content is observed, never the
  build receipt, so a successful write alone cannot make an artifact final;
* classroom admission (``classify_classroom_admission``): re-derives every required visual
  from placement receipts, asset identity, role and observed terminal-QA state.

Every case changes exactly one input and asserts the exact state or reason code. This is
offline QA over fake services; live Google Docs/Slides rendering is a separate acceptance.

Known boundary (deliberately not pinned as expected behavior): admission re-derives each *listed*
required visual, but the list is assembled from the build input. Omitting every requirement from the
build input is stopped upstream by the planner block (test_b) and the CLI refusals in test_cli.py
(visual-gap and missing-placement-binding cases), which must remain.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from instructional_materials_coach import visual_reuse
from instructional_workflow_contracts.material_requirement import material_requirement_source_fingerprint
from instructional_materials_coach.artifact_content_qa import (
    QA_STATE_ARTIFACT_INACCESSIBLE,
    QA_STATE_VERIFIED,
    QA_STATE_VISUAL_MISMATCH,
    QA_STATE_VISUAL_MISSING,
)
from instructional_materials_coach.build_receipt import build_receipt_record
from instructional_materials_coach.classroom_admission import (
    ClassroomAdmission,
    ClassroomAdmissionReason as Reason,
    classify_classroom_admission,
)


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


QA = _load("_three_visual_qa_fixtures", "test_3258_terminal_content_qa.py")  # _Executable only
AD = _load("_three_visual_admission_fixtures", "test_3259_classroom_admission.py")

ROLES = ("worked-example", "teacher-model", "process-sequence")
ASSETS = ("asset-1", "asset-2", "asset-3")
IDENTITIES = tuple({"sha256": f"sha-{index}"} for index in range(3))
INLINE = ("img-1", "img-2", "img-3")


# ---------------------------------------------------------------------------
# Planner: three required roles, nothing to fill them with.
# ---------------------------------------------------------------------------
def _three_role_requirement():
    root = Path(__file__).resolve().parents[3]
    path = root / "tests" / "fixtures" / "instructional_workflow_contracts" / "valid_material_requirement_v2.json"
    requirement = json.loads(path.read_text(encoding="utf-8"))
    direction = requirement["visual_direction"]
    base = direction["roles"][0]
    direction["maximum_visual_count"] = 3
    direction["roles"] = [
        {**base, "role_type": role, "requirement_state": "required"} for role in ROLES
    ]
    # Editing the fixture invalidates its source fingerprint; recompute it with the canonical
    # function, otherwise the planner stops at invalid-material-requirement and never reaches
    # the candidate/gap logic this case is about.
    requirement["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(requirement)
    return requirement


def test_b_three_required_roles_with_zero_candidates_block_production():
    plan = visual_reuse.plan_governed_visual_reuse(
        _three_role_requirement(),
        artifact_manifests=[],
        visual_candidates=[],
        source_revision="visual-library-snapshot-v2",
        changed_dependency_keys=[],
        impact_map={},
    )
    # Reached the real gap logic (not an invalid-requirement short circuit).
    assert plan.outcome == "visual-gap-blocked"
    assert plan.final_production_blocked is True
    assert plan.selected_asset_ids == ()
    assert len(plan.image_gap_briefs) == 3  # one gap brief per required role
    # A blocked plan is what keeps an empty placement list from reaching admission as
    # "no visuals required" (cli.py refuses on this flag).


# ---------------------------------------------------------------------------
# Writer -> persisted artifact -> terminal QA, using the real placement producer.
# ---------------------------------------------------------------------------
P = _load("_three_visual_placement_fixtures", "test_3258_batch_proof_integrity.py")
FAKES = P._fakes
FIGURES = ("figure-0", "figure-1", "figure-2")
DERIVED = "qa-worksheet-revision-render-missing-required-visuals"


def _placed_docs(tmp_path):
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    bindings, docs, drive, transport = P._docs_env(3)
    outcomes = P._place_docs(bindings, docs, drive, transport, receipts)
    assert [o.status for o in outcomes] == ["placed"] * 3  # writer invoked for all three
    return bindings, docs, receipts


def _terminal(bindings, docs, receipts):
    return P._terminal_qa(tuple(bindings), docs, receipts).worksheet


def _roles(report, code):
    return {
        role for finding in report.findings if finding.code == code
        for role in FIGURES if role in finding.message
    }


def _codes(report):
    return {finding.code for finding in report.findings}


def test_a_three_required_three_embedded_is_verified(tmp_path):
    bindings, docs, receipts = _placed_docs(tmp_path)
    report = _terminal(bindings, docs, receipts)
    assert report.state == QA_STATE_VERIFIED
    assert report.findings == ()
    assert len(docs.documents_store["doc-1"]["inline_objects"]) == 3  # persisted, not just reported


def test_c_three_written_zero_persisted_is_a_visual_mismatch(tmp_path):
    """The writer reported success, but the persisted artifact holds no images."""
    bindings, docs, receipts = _placed_docs(tmp_path)
    docs.documents_store["doc-1"]["inline_objects"] = []
    report = _terminal(bindings, docs, receipts)
    assert report.state == QA_STATE_VISUAL_MISMATCH
    assert "qa-visual-element-mismatch" in _codes(report)
    # The derived render check names every required role that is not physically present.
    assert _roles(report, DERIVED) == set(FIGURES)


def test_d_only_two_of_three_persisted_names_exactly_the_missing_role(tmp_path):
    bindings, docs, receipts = _placed_docs(tmp_path)
    store = docs.documents_store["doc-1"]
    store["inline_objects"] = store["inline_objects"][:2]
    report = _terminal(bindings, docs, receipts)
    assert report.state == QA_STATE_VISUAL_MISMATCH
    assert _roles(report, "qa-visual-element-mismatch") == {"figure-2"}


def test_e_wrong_image_asset_for_one_role_is_a_visual_mismatch(tmp_path):
    bindings, docs, receipts = _placed_docs(tmp_path)
    expected = list(bindings)
    expected[1] = dataclasses.replace(bindings[1], asset_id="asset-other")
    report = _terminal(expected, docs, receipts)
    assert report.state == QA_STATE_VISUAL_MISMATCH
    assert _roles(report, "qa-receipt-asset-mismatch") == {"figure-1"}


def test_h_correct_asset_id_but_wrong_content_identity_is_a_visual_mismatch(tmp_path):
    bindings, docs, receipts = _placed_docs(tmp_path)
    expected = list(bindings)
    expected[2] = dataclasses.replace(
        bindings[2], content_identity={**bindings[2].content_identity, "value": "0" * 64}
    )
    report = _terminal(expected, docs, receipts)
    assert report.state == QA_STATE_VISUAL_MISMATCH
    assert _roles(report, "qa-receipt-asset-mismatch") == {"figure-2"}


def test_g_unresolved_placeholder_for_one_role_is_visual_missing(tmp_path):
    bindings, docs, receipts = _placed_docs(tmp_path)
    docs.documents_store["doc-1"]["paragraphs"].append("{{visual:figure-1}}")
    report = _terminal(bindings, docs, receipts)
    assert report.state == QA_STATE_VISUAL_MISSING
    assert _roles(report, "qa-visual-missing") == {"figure-1"}


def test_k_three_images_persisted_but_the_reconciled_batch_proof_is_gone_is_not_verified(tmp_path):
    """Three images need the producer's batch proof; correct-looking output alone is unproven."""
    bindings, docs, receipts = _placed_docs(tmp_path)
    assert _terminal(bindings, docs, receipts).state == QA_STATE_VERIFIED  # positive control
    P._rewrite_store(receipts, lambda payload: payload.pop("batch_proofs", None))
    report = _terminal(bindings, docs, receipts)
    assert report.state != QA_STATE_VERIFIED
    assert "qa-batch-proof-missing" in _codes(report)


def test_j_a_build_whose_persisted_output_cannot_be_inspected_is_not_verified(tmp_path):
    bindings, _, receipts = _placed_docs(tmp_path)

    class _Unreachable:
        def documents(self):
            return self

        def get(self, **kwargs):
            return QA._Executable(RuntimeError("connection reset"))

    report = _terminal(bindings, _Unreachable(), receipts)
    assert report.state == QA_STATE_ARTIFACT_INACCESSIBLE
    assert "qa-artifact-inaccessible" in _codes(report)


def test_f_correct_images_on_the_wrong_slide_are_a_visual_mismatch(tmp_path):
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    bindings = tuple(
        FAKES._binding(role, asset_id=f"asset-{index}", drive_file_id=f"file-{index}")
        for index, role in enumerate(FIGURES)
    )
    docs = FAKES.FakeDocsService()
    docs.add_document("doc-1", ["Worksheet"])
    slides = FAKES.FakeSlidesService()
    slides.add_presentation("slides-1", [
        {"objectId": f"slide-{index}", "elements": [
            {"objectId": f"shape-{index}", "text": "{{visual:" + role + "}}"}]}
        for index, role in enumerate(FIGURES)
    ])
    drive = FAKES.FakeDriveService({f"file-{index}": FAKES._drive_metadata(f"file-{index}") for index in range(3)})
    transport = FAKES.FakePlacementTransport(docs=docs, slides=slides)
    outcomes = P.execute_artifact_visual_placements(
        bindings=bindings, artifact_type="slides", artifact_id="slides-1", drive_service=drive,
        artifact_service=slides, transport=transport, receipts_dir=str(receipts), idempotency_key=P.KEY,
    )
    assert [o.status for o in outcomes] == ["placed"] * 3

    def _qa():
        expectations = P.TerminalQAExpectations.build_from_requests(
            idempotency_key=P.KEY, visual_placements=bindings)
        return P.run_terminal_qa(
            expectations=expectations, slides_service=slides, docs_service=docs,
            slides_file_id="slides-1", worksheet_file_id="doc-1",
            receipts_dir=str(receipts), qa_evidence_dir=None).slides

    assert _qa().state == QA_STATE_VERIFIED  # positive control: every image on its own slide
    store = slides.presentations_store["slides-1"]["slides"]
    moved = store[1]["elements"].pop()  # slide-1's image ends up on slide-2
    store[2]["elements"].append(moved)
    report = _qa()
    assert report.state == QA_STATE_VISUAL_MISMATCH
    assert _roles(report, "qa-visual-container-mismatch") == {"figure-1"}


# ---------------------------------------------------------------------------
# Classroom admission: every required visual re-derived from receipts.
# ---------------------------------------------------------------------------
def _bindings():
    return tuple(
        AD._binding(role_id=role, slot_id=str(index), asset_id=ASSETS[index],
                    content_identity=IDENTITIES[index])
        for index, role in enumerate(ROLES)
    )


def _records(overrides=None, skip=()):
    out = []
    for index, role in enumerate(ROLES):
        if index in skip:
            continue
        values = dict(role_id=role, slot_id=str(index), asset_id=ASSETS[index],
                      content_identity=IDENTITIES[index])
        values.update((overrides or {}).get(index, {}))
        out.append(AD._placement_record(**values))
    return tuple(out)


def _admit(records, *, qa_state="verified", bindings=None, canonical_qa_state=None):
    build = AD._build_input(_bindings() if bindings is None else bindings)
    receipt = AD._live_receipt(qa_state)
    record = build_receipt_record(
        build, receipt, requirement_identity=dict(AD.REQUIREMENT_IDENTITY),
        template_revisions=dict(AD.TEMPLATE_REVISIONS),
    )
    evidence = AD._evidence(
        build, receipt, records, qa_state=canonical_qa_state or qa_state)
    return classify_classroom_admission(record, evidence)


def test_admission_a_three_required_three_verified_is_admitted():
    result = _admit(_records())
    assert result.status is ClassroomAdmission.ADMITTED
    assert result.reason_codes == (Reason.EVIDENCE_COMPLETE,)


def test_admission_c_three_required_zero_receipts_is_refused():
    result = _admit(())
    AD._assert_not_admitted(result, Reason.PLACEMENT_RECEIPT_MISSING)


def test_admission_d_two_of_three_receipts_is_refused():
    result = _admit(_records(skip=(2,)))
    AD._assert_not_admitted(result, Reason.PLACEMENT_RECEIPT_MISSING)


def test_admission_e_wrong_asset_for_one_role_is_refused():
    result = _admit(_records(overrides={1: {"asset_id": "asset-other"}}))
    AD._assert_not_admitted(result, Reason.PLACEMENT_EVIDENCE_MISMATCH)


def test_admission_h_wrong_content_identity_for_one_role_is_refused():
    result = _admit(_records(overrides={2: {"content_identity": {"sha256": "tampered"}}}))
    AD._assert_not_admitted(result, Reason.PLACEMENT_EVIDENCE_MISMATCH)


def test_admission_i_right_image_for_the_wrong_instructional_role_is_refused():
    result = _admit(_records(overrides={0: {"role_id": ROLES[1]}}))
    AD._assert_not_admitted(result, Reason.SEMANTIC_ROLE_MISMATCH)


def test_admission_j_unverified_terminal_qa_is_refused_even_with_all_receipts():
    result = _admit(_records(), qa_state="visual-missing")
    AD._assert_not_admitted(result, Reason.TERMINAL_QA_NOT_VERIFIED)


def test_admission_j2_receipt_claiming_verified_cannot_override_unverified_canonical_qa():
    """The receipt is untrusted: canonical terminal-QA evidence decides."""
    result = _admit(_records(), qa_state="verified", canonical_qa_state="visual-missing")
    AD._assert_not_admitted(result, Reason.TERMINAL_QA_NOT_VERIFIED)
