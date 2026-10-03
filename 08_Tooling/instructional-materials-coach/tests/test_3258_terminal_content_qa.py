"""#3258: terminal artifact-content QA — regression matrix.

Wave 4 proves the core invariant: Agent OS calls an instructional artifact
complete only when it can prove that the PERSISTED final artifact contains
the governed required content and governed required visuals, attributable
to the current build and artifact state.

Matrix (scenario -> expected QA state -> completion admitted?):

 1  Valid Doc                              verified                            Yes
 2  Valid Slides                           verified                            Yes
 3  Missing required text                  content-missing                     No
 4  Incorrect required text                content-missing                     No
 5  Invalid duplicated content             content-mismatch                    No
 6  Missing required visual                visual-missing                      No
 7  Wrong visual                           visual-mismatch                     No
 8  Visual at wrong target                 visual-mismatch                     No
 9  Missing receipt                        placement-unverified                No
10  Receipt does not match selected asset  visual-mismatch                     No
11  Receipt points to different artifact   artifact-conflict                   No
12  Receipt is stale relative to artifact  artifact-stale                      No
13  Artifact changed after placement       artifact-stale                      No
14  Artifact changed after text QA         reverification required             No until verified
15  Artifact inaccessible                  artifact-inaccessible               No
16  Verification runtime unavailable       verification-runtime-unavailable    No
17  Partial multi-visual success           placement-unverified                No
18  Retry with unchanged artifact          verified (recovered)                Yes
19  Retry after artifact mutation          reverification required             No until verified
20  Evidence belongs to another build      artifact-conflict                   No

"Completion admitted?" is decided by the terminal QA state: only
``verified`` admits terminal success (proven at the admission layer by the
updated build-path tests). The red/green test at the end demonstrates the
false positive this wave eliminates: on the pre-repair base, a build whose
persisted artifact still carries an unresolved token reported final from
metadata alone.
"""
from __future__ import annotations

from typing import Any, Mapping

import pytest

from instructional_materials_coach.artifact_content_qa import (
    QA_STATE_ARTIFACT_CONFLICT,
    QA_STATE_ARTIFACT_INACCESSIBLE,
    QA_STATE_ARTIFACT_STALE,
    QA_STATE_CONTENT_MISMATCH,
    QA_STATE_CONTENT_MISSING,
    QA_STATE_EVIDENCE_INCOMPLETE,
    QA_STATE_PLACEMENT_UNVERIFIED,
    QA_STATE_TOKEN_UNRESOLVED,
    QA_STATE_VERIFICATION_RUNTIME_UNAVAILABLE,
    QA_STATE_VERIFIED,
    QA_STATE_VISUAL_MISMATCH,
    QA_STATE_VISUAL_MISSING,
    ContentExpectation,
    TerminalQAExpectations,
    VisualExpectation,
    normalize_text,
    run_terminal_qa,
    scan_unresolved_tokens,
)
from instructional_materials_coach.placement_receipts import (
    RECEIPT_RECORD_CONTRACT,
    append_placement_record,
)


KEY = "k" * 64
IDENTITY = {"sha256": "abc123"}


# ---------------------------------------------------------------------------
# Injected readback fakes (persisted-artifact observation surface)
# ---------------------------------------------------------------------------

class _Executable:
    def __init__(self, payload: Any):
        self._payload = payload

    def execute(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeDocsService:
    """Fake Docs v1 service: documents().get(documentId=).execute()."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    def add(self, doc_id: str, paragraphs: list[str],
            inline_objects: list[str] | None = None, revision: str = "r1") -> None:
        self.docs[doc_id] = {
            "revisionId": revision,
            "paragraphs": list(paragraphs),
            "inline_objects": list(inline_objects or []),
        }

    def documents(self) -> "_FakeDocsResource":
        return _FakeDocsResource(self)


class _FakeDocsResource:
    def __init__(self, service: FakeDocsService):
        self._service = service

    def get(self, *, documentId: str, fields: str | None = None) -> _Executable:
        doc = self._service.docs[documentId]
        content = [
            {"paragraph": {"elements": [{"textRun": {"content": text + "\n"}}]}}
            for text in doc["paragraphs"]
        ]
        for object_id in doc["inline_objects"]:
            content.append(
                {"paragraph": {"elements": [{"inlineObjectElement": {"embeddedObjectId": object_id}}]}}
            )
        return _Executable({
            "documentId": documentId,
            "revisionId": doc["revisionId"],
            "body": {"content": content},
            "inlineObjects": {oid: {"objectId": oid} for oid in doc["inline_objects"]},
        })


class FakeSlidesService:
    """Fake Slides v1 service: presentations().get(presentationId=).execute()."""

    def __init__(self) -> None:
        self.presentations_store: dict[str, dict[str, Any]] = {}

    def add(self, pres_id: str, slides: list[dict[str, Any]], revision: str = "r1") -> None:
        """slides: [{"objectId": str, "elements": [{"objectId": str, "text": str, "image": bool}]}]"""
        self.presentations_store[pres_id] = {"revisionId": revision, "slides": slides}

    def presentations(self) -> "_FakeSlidesResource":
        return _FakeSlidesResource(self)


class _FakeSlidesResource:
    def __init__(self, service: FakeSlidesService):
        self._service = service

    def get(self, *, presentationId: str, fields: str | None = None) -> _Executable:
        pres = self._service.presentations_store[presentationId]
        slides = []
        for slide in pres["slides"]:
            elements = []
            for element in slide["elements"]:
                rendered: dict[str, Any] = {"objectId": element["objectId"]}
                if element.get("image"):
                    rendered["image"] = {"contentUrl": "https://example/img"}
                else:
                    rendered["shape"] = {"text": {"textElements": [{"textRun": {"content": element.get("text", "") + "\n"}}]}}
                elements.append(rendered)
            slides.append({"objectId": slide["objectId"], "pageElements": elements})
        return _Executable({
            "presentationId": presentationId,
            "revisionId": pres["revisionId"],
            "slides": slides,
        })


# ---------------------------------------------------------------------------
# Expectation / receipt builders
# ---------------------------------------------------------------------------

def _content(token: str, text: str, artifact_type: str = "docs", **kwargs: Any) -> ContentExpectation:
    return ContentExpectation(artifact_type=artifact_type, token=token, expected_text=text, **kwargs)


def _visual(role_id: str = "worked-example", asset_id: str = "asset-1",
            identity: Mapping[str, Any] | None = None, required: bool = True) -> VisualExpectation:
    return VisualExpectation(
        role_id=role_id, slot_id="0", asset_id=asset_id,
        content_identity=dict(identity or IDENTITY), required=required,
    )


def _expectations(*, docs_content: tuple = (), slides_content: tuple = (),
                  visuals: tuple = (), key: str = KEY) -> TerminalQAExpectations:
    return TerminalQAExpectations(
        idempotency_key=key, docs_content=tuple(docs_content),
        slides_content=tuple(slides_content), visuals=tuple(visuals),
    )


def _store_receipt(receipts_dir: Any, *, role_id: str = "worked-example",
                   artifact_type: str = "docs", artifact_id: str = "doc-1",
                   asset_id: str = "asset-1",
                   identity: Mapping[str, Any] | None = None,
                   revision: str = "r1", inserted: str = "img-1",
                   key: str = KEY) -> dict[str, Any]:
    record = {
        "asset_id": asset_id,
        "drive_file_id": "file-1",
        "role_id": role_id,
        "slot_id": "0",
        "artifact_type": artifact_type,
        "artifact_id": artifact_id,
        "artifact_revision_id": "r0",
        "marker": "{{visual:" + role_id + "}}",
        "container_id": "c1",
        "inserted_element_id": inserted,
        "state": "verified",
        "content_identity": dict(identity or IDENTITY),
        "source_plan_id": "plan-1",
        "required": True,
        "eligibility_evidence": None,
        "transport": "fake-test-transport",
        "post_insertion_revision_id": revision,
        "placed_at": "2026-10-03T00:00:00+00:00",
    }
    return append_placement_record(receipts_dir, key, record)


def _run(*, docs=None, slides=None, expectations, receipts_dir=None,
         qa_evidence_dir=None):
    # Default to valid-but-empty artifacts on the side the scenario does
    # not exercise, so the overall report reflects the scenario's side.
    if docs is None:
        docs = FakeDocsService()
        docs.add("doc-1", [])
    if slides is None:
        slides = FakeSlidesService()
        slides.add("slides-1", [])
    return run_terminal_qa(
        expectations=expectations,
        slides_service=slides,
        docs_service=docs,
        slides_file_id="slides-1",
        worksheet_file_id="doc-1",
        receipts_dir=receipts_dir,
        qa_evidence_dir=qa_evidence_dir,
    )


def _codes(report) -> list[str]:
    return [f.code for f in report.findings]


# ---------------------------------------------------------------------------
# Normalization + token scan unit behavior
# ---------------------------------------------------------------------------

def test_normalization_folds_whitespace_only():
    assert normalize_text("  Title\t\n more ") == "Title more"
    # Case is preserved: matchCase semantics from the write requests.
    assert normalize_text("Title") != normalize_text("title")


def test_token_scan_finds_unresolved_markers():
    assert scan_unresolved_tokens("no tokens here") == ()
    assert scan_unresolved_tokens("a {{title}} b {{visual:worked-example}}") == (
        "{{title}}", "{{visual:worked-example}}",
    )


# ---------------------------------------------------------------------------
# Matrix scenarios 1-5: content proof (Docs)
# ---------------------------------------------------------------------------

def test_matrix_01_valid_doc_is_verified(tmp_path):
    docs = FakeDocsService()
    docs.add("doc-1", ["Fractions Intro", "Count the shaded parts."])
    report = _run(docs=docs, expectations=_expectations(
        docs_content=(_content("{{title}}", "Fractions Intro"),
                      _content("{{directions}}", "Count the shaded parts.")),))
    assert report.worksheet.state == QA_STATE_VERIFIED
    assert report.state == QA_STATE_VERIFIED  # slides had no expectations: verified


def test_matrix_02_valid_slides_is_verified():
    slides = FakeSlidesService()
    slides.add("slides-1", [{"objectId": "s1", "elements": [
        {"objectId": "e1", "text": "Fractions Intro"},
        {"objectId": "e2", "text": "Count the shaded parts."},
    ]}])
    report = _run(slides=slides, expectations=_expectations(
        slides_content=(_content("{{title}}", "Fractions Intro", "slides"),
                        _content("{{directions}}", "Count the shaded parts.", "slides")),))
    assert report.slides.state == QA_STATE_VERIFIED
    assert report.state == QA_STATE_VERIFIED


def test_matrix_03_missing_required_text_is_content_missing():
    docs = FakeDocsService()
    docs.add("doc-1", ["Fractions Intro"])  # directions never rendered
    report = _run(docs=docs, expectations=_expectations(
        docs_content=(_content("{{title}}", "Fractions Intro"),
                      _content("{{directions}}", "Count the shaded parts.")),))
    assert report.worksheet.state == QA_STATE_CONTENT_MISSING
    assert "qa-content-missing" in _codes(report.worksheet)
    assert report.state == QA_STATE_CONTENT_MISSING


def test_matrix_04_incorrect_required_text_is_content_missing():
    # The write "succeeded" but the persisted text is materially wrong: the
    # governed expected string is absent. (Whitespace folding is the only
    # normalization; it cannot rescue wrong content.)
    docs = FakeDocsService()
    docs.add("doc-1", ["Fraction Introduction"])  # not "Fractions Intro"
    report = _run(docs=docs, expectations=_expectations(
        docs_content=(_content("{{title}}", "Fractions Intro"),),))
    assert report.worksheet.state == QA_STATE_CONTENT_MISSING
    assert report.state != QA_STATE_VERIFIED


def test_matrix_05_invalid_duplicated_content_is_content_mismatch():
    docs = FakeDocsService()
    docs.add("doc-1", ["Fractions Intro", "Fractions Intro"])  # title twice
    report = _run(docs=docs, expectations=_expectations(
        docs_content=(_content("{{title}}", "Fractions Intro", max_occurrences=1),),))
    assert report.worksheet.state == QA_STATE_CONTENT_MISMATCH
    assert "qa-content-duplicated" in _codes(report.worksheet)


def test_issue_regression_leftover_token_fails_qa():
    """#3258 acceptance: any unresolved template token fails terminal QA."""
    docs = FakeDocsService()
    docs.add("doc-1", ["Fractions Intro", "{{directions}}"])
    report = _run(docs=docs, expectations=_expectations(
        docs_content=(_content("{{title}}", "Fractions Intro"),
                      _content("{{directions}}", "Count the shaded parts.")),))
    assert report.worksheet.state == QA_STATE_TOKEN_UNRESOLVED
    assert "qa-token-unresolved" in _codes(report.worksheet)
    assert report.state == QA_STATE_TOKEN_UNRESOLVED


# ---------------------------------------------------------------------------
# Matrix scenarios 6-13, 17, 20: visual proof (Docs + Slides)
# ---------------------------------------------------------------------------

def _placed_docs(tmp_path, *, paragraphs=("Worksheet",), inline_objects=("img-1",),
                 revision="r1", receipt_revision=None, identity=None, artifact_id="doc-1",
                 role_id="worked-example", asset_id="asset-1", key=KEY):
    docs = FakeDocsService()
    docs.add(artifact_id, list(paragraphs), list(inline_objects), revision=revision)
    receipts_dir = tmp_path / "receipts"
    _store_receipt(receipts_dir, role_id=role_id, artifact_type="docs",
                   artifact_id=artifact_id, asset_id=asset_id,
                   identity=identity,
                   revision=receipt_revision if receipt_revision is not None else revision,
                   key=key)
    return docs, receipts_dir


def test_matrix_06_valid_doc_visual_is_verified(tmp_path):
    docs, receipts_dir = _placed_docs(tmp_path)
    report = _run(docs=docs, receipts_dir=receipts_dir,
                  expectations=_expectations(visuals=(_visual(),)))
    assert report.worksheet.state == QA_STATE_VERIFIED
    assert report.state == QA_STATE_VERIFIED


def test_matrix_06b_valid_slides_visual_is_verified(tmp_path):
    slides = FakeSlidesService()
    slides.add("slides-1", [{"objectId": "s1", "elements": [
        {"objectId": "img-1", "image": True},
    ]}], revision="r1")
    receipts_dir = tmp_path / "receipts"
    _store_receipt(receipts_dir, artifact_type="slides", artifact_id="slides-1", revision="r1")
    report = _run(slides=slides, receipts_dir=receipts_dir,
                  expectations=_expectations(visuals=(_visual(),)))
    assert report.slides.state == QA_STATE_VERIFIED
    assert report.state == QA_STATE_VERIFIED


def test_matrix_06c_marker_still_present_is_visual_missing(tmp_path):
    # Placement claimed success but the marker was never replaced: the
    # visual-specific diagnosis wins over the generic token scan (the
    # token-level finding is still recorded per the #3258 acceptance).
    docs, receipts_dir = _placed_docs(
        tmp_path, paragraphs=("Worksheet", "{{visual:worked-example}}"))
    report = _run(docs=docs, receipts_dir=receipts_dir,
                  expectations=_expectations(visuals=(_visual(),)))
    assert report.worksheet.state == QA_STATE_VISUAL_MISSING
    assert "qa-visual-missing" in _codes(report.worksheet)
    assert "qa-token-unresolved" in _codes(report.worksheet)


def test_matrix_07_wrong_visual_asset_revision_is_visual_mismatch(tmp_path):
    # Receipt references a different content identity than the governed
    # selection: the persisted visual is not the approved revision.
    docs, receipts_dir = _placed_docs(tmp_path, identity={"sha256": "different"})
    report = _run(docs=docs, receipts_dir=receipts_dir,
                  expectations=_expectations(visuals=(_visual(),)))
    assert report.worksheet.state == QA_STATE_VISUAL_MISMATCH
    assert "qa-receipt-asset-mismatch" in _codes(report.worksheet)


def test_matrix_08_visual_at_wrong_target_is_visual_mismatch(tmp_path):
    # Receipt names an inserted element that the persisted artifact does
    # not contain.
    docs = FakeDocsService()
    docs.add("doc-1", ["Worksheet"], [], revision="r1")  # no inline objects
    receipts_dir = tmp_path / "receipts"
    _store_receipt(receipts_dir, revision="r1", inserted="img-1")
    report = _run(docs=docs, receipts_dir=receipts_dir,
                  expectations=_expectations(visuals=(_visual(),)))
    assert report.worksheet.state == QA_STATE_VISUAL_MISMATCH
    assert "qa-visual-element-mismatch" in _codes(report.worksheet)


def test_matrix_09_missing_receipt_is_placement_unverified(tmp_path):
    # A required visual with no verified receipt anywhere: never final.
    # The unresolved role is named for manual review.
    docs = FakeDocsService()
    docs.add("doc-1", ["Worksheet"])
    report = _run(docs=docs, receipts_dir=tmp_path / "receipts",
                  expectations=_expectations(visuals=(_visual(),)))
    assert report.worksheet.state == QA_STATE_PLACEMENT_UNVERIFIED
    codes = _codes(report.worksheet)
    assert "qa-placement-unverified" in codes
    assert any("worked-example" in f.message for f in report.worksheet.findings)


def test_matrix_10_receipt_asset_mismatch_is_visual_mismatch(tmp_path):
    docs, receipts_dir = _placed_docs(tmp_path, asset_id="asset-2")
    report = _run(docs=docs, receipts_dir=receipts_dir,
                  expectations=_expectations(visuals=(_visual(asset_id="asset-1"),)))
    assert report.worksheet.state == QA_STATE_VISUAL_MISMATCH
    assert report.state != QA_STATE_VERIFIED


def test_matrix_11_receipt_for_different_artifact_is_conflict(tmp_path):
    # The receipt store carries a verified receipt for another artifact id:
    # evidence is not attributable to the inspected artifact.
    docs = FakeDocsService()
    docs.add("doc-1", ["Worksheet"], ["img-1"], revision="r1")
    receipts_dir = tmp_path / "receipts"
    _store_receipt(receipts_dir, artifact_id="doc-2", revision="r1")
    report = _run(docs=docs, receipts_dir=receipts_dir,
                  expectations=_expectations(visuals=(_visual(),)))
    assert report.worksheet.state == QA_STATE_ARTIFACT_CONFLICT
    assert "qa-receipt-artifact-conflict" in _codes(report.worksheet)


def test_matrix_12_stale_receipt_is_artifact_stale(tmp_path):
    # Receipt's post-insertion revision no longer matches the artifact:
    # the artifact mutated after placement; stale evidence is not reused.
    docs, receipts_dir = _placed_docs(tmp_path, revision="r2", receipt_revision="r1")
    report = _run(docs=docs, receipts_dir=receipts_dir,
                  expectations=_expectations(visuals=(_visual(),)))
    assert report.worksheet.state == QA_STATE_ARTIFACT_STALE
    assert "qa-artifact-stale" in _codes(report.worksheet)


def test_matrix_13_artifact_changed_after_placement_is_stale(tmp_path):
    docs, receipts_dir = _placed_docs(tmp_path, revision="r1")
    # External mutation after placement: revision bumped, content intact.
    docs.docs["doc-1"]["revisionId"] = "r1-mutated"
    report = _run(docs=docs, receipts_dir=receipts_dir,
                  expectations=_expectations(visuals=(_visual(),)))
    assert report.worksheet.state == QA_STATE_ARTIFACT_STALE
    assert report.state != QA_STATE_VERIFIED


def test_matrix_17_partial_multi_visual_success_is_not_verified(tmp_path):
    docs = FakeDocsService()
    docs.add("doc-1", ["Worksheet"], ["img-1"], revision="r1")
    receipts_dir = tmp_path / "receipts"
    _store_receipt(receipts_dir, role_id="worked-example", revision="r1")
    report = _run(docs=docs, receipts_dir=receipts_dir,
                  expectations=_expectations(visuals=(
                      _visual("worked-example"), _visual("teacher-model"),)),)
    assert report.worksheet.state == QA_STATE_PLACEMENT_UNVERIFIED
    assert report.state != QA_STATE_VERIFIED


def test_matrix_20_evidence_for_another_build_is_conflict():
    # QA expectations bound to build A evaluated under build B's identity:
    # evidence is not attributable to this build.
    from instructional_materials_coach.artifact_content_qa import (
        evaluate_artifact_qa,
        observe_artifact,
    )
    docs = FakeDocsService()
    docs.add("doc-1", ["Fractions Intro"])
    observation = observe_artifact(docs, "docs", "doc-1")
    report = evaluate_artifact_qa(
        artifact_type="docs",
        artifact_id="doc-1",
        expectations=_expectations(
            docs_content=(_content("{{title}}", "Fractions Intro"),),
            key="build-a-" + "k" * 57),
        observation=observation,
        placement_records=(),
        idempotency_key="build-b-" + "k" * 57,
    )
    assert report.state == QA_STATE_ARTIFACT_CONFLICT
    assert "qa-build-attribution-mismatch" in _codes(report)


# ---------------------------------------------------------------------------
# Matrix scenarios 14-16, 18-19: retry, continuation, runtime failures
# ---------------------------------------------------------------------------

def test_matrix_14_artifact_changed_after_text_qa_requires_reverification(tmp_path):
    qa_dir = tmp_path / "qa"
    docs = FakeDocsService()
    docs.add("doc-1", ["Fractions Intro"], revision="r1")
    expectations = _expectations(docs_content=(_content("{{title}}", "Fractions Intro"),))
    run1 = _run(docs=docs, expectations=expectations, qa_evidence_dir=qa_dir)
    assert run1.worksheet.state == QA_STATE_VERIFIED
    assert not run1.worksheet.recovered
    # Benign mutation after QA: revision changes, content intact.
    docs.docs["doc-1"]["revisionId"] = "r2"
    run2 = _run(docs=docs, expectations=expectations, qa_evidence_dir=qa_dir)
    # Prior proof is NOT reused: identity assumptions changed.
    assert not run2.worksheet.recovered
    # Re-verification against the current state still passes.
    assert run2.worksheet.state == QA_STATE_VERIFIED
    assert run2.state == QA_STATE_VERIFIED


def test_matrix_15_artifact_inaccessible_is_not_verified():
    class _FailingDocsService:
        def documents(self):
            return self

        def get(self, **kwargs):
            return _Executable(RuntimeError("connection reset"))

    report = _run(docs=_FailingDocsService(),
                  expectations=_expectations(
                      docs_content=(_content("{{title}}", "Fractions Intro"),),))
    assert report.worksheet.state == QA_STATE_ARTIFACT_INACCESSIBLE
    assert "qa-artifact-inaccessible" in _codes(report.worksheet)
    assert report.state != QA_STATE_VERIFIED


def test_matrix_16_verification_runtime_unavailable_is_not_verified():
    # The injected service has no read surface at all: QA cannot even
    # attempt verification. Blocked/nonterminal, never success.
    report = _run(docs=object(),
                  expectations=_expectations(
                      docs_content=(_content("{{title}}", "Fractions Intro"),),))
    assert report.worksheet.state == QA_STATE_VERIFICATION_RUNTIME_UNAVAILABLE
    assert report.state != QA_STATE_VERIFIED


def test_matrix_18_retry_with_unchanged_artifact_recovers_verified(tmp_path):
    qa_dir = tmp_path / "qa"
    docs = FakeDocsService()
    docs.add("doc-1", ["Fractions Intro"], revision="r1")
    expectations = _expectations(docs_content=(_content("{{title}}", "Fractions Intro"),))
    run1 = _run(docs=docs, expectations=expectations, qa_evidence_dir=qa_dir)
    assert run1.worksheet.state == QA_STATE_VERIFIED
    run2 = _run(docs=docs, expectations=expectations, qa_evidence_dir=qa_dir)
    assert run2.worksheet.recovered
    assert run2.worksheet.state == QA_STATE_VERIFIED
    assert run2.state == QA_STATE_VERIFIED


def test_matrix_19_retry_after_mutation_does_not_reuse_stale_proof(tmp_path):
    qa_dir = tmp_path / "qa"
    docs = FakeDocsService()
    docs.add("doc-1", ["Fractions Intro"], revision="r1")
    expectations = _expectations(docs_content=(_content("{{title}}", "Fractions Intro"),))
    run1 = _run(docs=docs, expectations=expectations, qa_evidence_dir=qa_dir)
    assert run1.worksheet.state == QA_STATE_VERIFIED
    # Mutation breaks the required content AND bumps the revision.
    docs.docs["doc-1"]["paragraphs"] = ["Something else entirely"]
    docs.docs["doc-1"]["revisionId"] = "r2"
    run2 = _run(docs=docs, expectations=expectations, qa_evidence_dir=qa_dir)
    assert not run2.worksheet.recovered
    assert run2.worksheet.state == QA_STATE_CONTENT_MISSING
    assert run2.state != QA_STATE_VERIFIED


def test_qa_evidence_is_durable_and_bound_to_build_and_revision(tmp_path):
    from instructional_materials_coach.artifact_content_qa import load_qa_evidence
    qa_dir = tmp_path / "qa"
    docs = FakeDocsService()
    docs.add("doc-1", ["Fractions Intro"], revision="r1")
    expectations = _expectations(docs_content=(_content("{{title}}", "Fractions Intro"),))
    report = _run(docs=docs, expectations=expectations, qa_evidence_dir=qa_dir)
    stored = load_qa_evidence(qa_dir, KEY)
    assert stored is not None
    assert stored["idempotency_key"] == KEY
    assert stored["state"] == QA_STATE_VERIFIED
    assert stored["worksheet"]["revision_id"] == "r1"
    assert stored["worksheet"]["artifact_id"] == "doc-1"
    assert stored["expectations_hash"] == expectations.expectations_hash()
    assert report.worksheet.expectations_hash == expectations.expectations_hash()


def test_changed_expectations_invalidate_stored_proof(tmp_path):
    qa_dir = tmp_path / "qa"
    docs = FakeDocsService()
    docs.add("doc-1", ["Fractions Intro"], revision="r1")
    run1 = _run(docs=docs, qa_evidence_dir=qa_dir,
                expectations=_expectations(
                    docs_content=(_content("{{title}}", "Fractions Intro"),),))
    assert run1.worksheet.state == QA_STATE_VERIFIED
    # Same artifact, different governed expectations: prior proof unusable.
    run2 = _run(docs=docs, qa_evidence_dir=qa_dir,
                expectations=_expectations(
                    docs_content=(_content("{{title}}", "Fractions Intro"),
                                  _content("{{directions}}", "Count the parts.")),))
    assert not run2.worksheet.recovered
    assert run2.worksheet.state == QA_STATE_CONTENT_MISSING


# ---------------------------------------------------------------------------
# Admission: persisted vs final, and the false-positive red/green proof
# ---------------------------------------------------------------------------

def test_metadata_only_receipt_is_persisted_never_final():
    """#3258 acceptance: metadata-only verification yields ``persisted``."""
    from instructional_materials_coach.live_build import ArtifactReceipt, LiveBuildReceipt
    meta = dict(role="worksheet", state="updated", file_id="doc-1",
                mime_type="application/vnd.google-apps.document", parents=("folder",),
                delivery_kind="final", canonical_editable=True, persistence_verified=True)
    receipt = LiveBuildReceipt(ArtifactReceipt(**meta), ArtifactReceipt(**meta))
    assert receipt.slides.is_persisted and receipt.worksheet.is_persisted
    assert not receipt.slides.is_final and not receipt.worksheet.is_final
    assert not receipt.succeeded


def test_qa_verified_receipt_is_final_and_succeeds():
    from instructional_materials_coach.live_build import ArtifactReceipt, LiveBuildReceipt
    meta = dict(role="worksheet", state="updated", file_id="doc-1",
                mime_type="application/vnd.google-apps.document", parents=("folder",),
                delivery_kind="final", canonical_editable=True, persistence_verified=True,
                terminal_qa_state=QA_STATE_VERIFIED)
    receipt = LiveBuildReceipt(ArtifactReceipt(**meta), ArtifactReceipt(**meta))
    assert receipt.slides.is_final and receipt.worksheet.is_final
    assert receipt.succeeded



def test_cli_reports_final_only_on_qa_pass(capsys):
    """The CLI failure report names terminal QA states (never bare 'final')."""
    from types import SimpleNamespace
    from instructional_materials_coach import cli as cli_module

    receipt = SimpleNamespace(
        slides=SimpleNamespace(state="updated", terminal_qa_state=QA_STATE_VERIFIED,
                                is_persisted=False, web_view_link="https://example/s"),
        worksheet=SimpleNamespace(state="updated", terminal_qa_state=QA_STATE_TOKEN_UNRESOLVED,
                                   is_persisted=True, web_view_link="https://example/d"),
        manual_reconciliation_required=False,
        succeeded=False,
        terminal_qa=SimpleNamespace(
            slides=SimpleNamespace(findings=()),
            worksheet=SimpleNamespace(findings=(
                SimpleNamespace(code="qa-token-unresolved", severity="fail",
                                message="Unresolved template token {{title}} persists."),
            )),
        ),
    )
    summary = cli_module._terminal_qa_summary(receipt)
    assert "slides=verified" in summary
    assert "worksheet=persisted-not-final" in summary
    assert "qa-token-unresolved" in summary
