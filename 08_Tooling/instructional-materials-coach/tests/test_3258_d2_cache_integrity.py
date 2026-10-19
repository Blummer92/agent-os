"""#3258 D2: cached QA-evidence integrity -- fail-closed recovery gates.

Drives the real ``run_terminal_qa()`` against tampered QA-evidence caches
(no mocks of the function under test). Every tampered case must fail closed:
no exception, and the tampered cache is never trusted (``recovered`` is
False; verification falls through to a fresh evaluation).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from instructional_materials_coach.artifact_content_qa import (
    QA_STATE_VERIFIED,
    ContentExpectation,
    TerminalQAExpectations,
    qa_evidence_path,
    run_terminal_qa,
)

KEY = "k" * 64
WRONG_KEY = "wrong-build-" + "k" * 52


# ---------------------------------------------------------------------------
# Injected readback fakes (mirrors the repo's own test fakes)
# ---------------------------------------------------------------------------


class _Executable:
    def __init__(self, payload: Any):
        self._payload = payload

    def execute(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeDocsService:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    def add(self, doc_id: str, paragraphs: list[str], revision: str = "r1") -> None:
        self.docs[doc_id] = {"revisionId": revision, "paragraphs": list(paragraphs)}

    def documents(self):  # noqa: ANN202
        service = self

        class _Res:
            def get(self, *, documentId: str, fields: str | None = None):  # noqa: ANN202
                doc = service.docs[documentId]
                content = [
                    {"paragraph": {"elements": [{"textRun": {"content": t + "\n"}}]}}
                    for t in doc["paragraphs"]
                ]
                return _Executable(
                    {
                        "documentId": documentId,
                        "revisionId": doc["revisionId"],
                        "body": {"content": content},
                        "inlineObjects": {},
                    }
                )

        return _Res()


class FakeSlidesService:
    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}

    def add(self, pres_id: str, slides: tuple = (), revision: str = "r1") -> None:
        self.store[pres_id] = {"revisionId": revision, "slides": list(slides)}

    def presentations(self):  # noqa: ANN202
        service = self

        class _Res:
            def get(self, *, presentationId: str, fields: str | None = None):  # noqa: ANN202
                pres = service.store[presentationId]
                return _Executable(
                    {
                        "presentationId": presentationId,
                        "revisionId": pres["revisionId"],
                        "slides": [
                            {"objectId": f"slide-{i}", "pageElements": []}
                            for i, _ in enumerate(pres["slides"])
                        ],
                    }
                )

        return _Res()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _expectations(key: str = KEY) -> TerminalQAExpectations:
    return TerminalQAExpectations(
        idempotency_key=key,
        docs_content=(
            ContentExpectation(
                artifact_type="docs", token="<redacted>",
                expected_text="Fractions Intro",
            ),
        ),
    )


def _run(*, docs, slides, expectations, qa_evidence_dir):  # noqa: ANN001, ANN202
    return run_terminal_qa(
        expectations=expectations,
        slides_service=slides,
        docs_service=docs,
        slides_file_id="slides-1",
        worksheet_file_id="doc-1",
        receipts_dir=None,
        qa_evidence_dir=qa_evidence_dir,
    )


def _fresh_services():
    docs = FakeDocsService()
    docs.add("doc-1", ["Fractions Intro"], revision="r1")
    slides = FakeSlidesService()
    slides.add("slides-1", (), revision="r1")
    return docs, slides


def _seed(qa_dir: Path) -> Path:
    """Run QA once against a valid artifact; persists a VERIFIED report."""
    docs, slides = _fresh_services()
    report = _run(
        docs=docs, slides=slides, expectations=_expectations(), qa_evidence_dir=qa_dir
    )
    assert report.worksheet.state == QA_STATE_VERIFIED, report.worksheet.state
    assert not report.worksheet.recovered
    return qa_evidence_path(qa_dir, KEY)


def _tamper(path: Path, mutate) -> None:  # noqa: ANN001
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _rerun_after_tamper(tmp_path: Path, mutate) -> Any:  # noqa: ANN001
    qa_dir = tmp_path / "qa"
    qa_dir.mkdir()
    path = _seed(qa_dir)
    _tamper(path, mutate)
    docs, slides = _fresh_services()
    # Must never raise, even on structurally malformed caches.
    return _run(
        docs=docs, slides=slides, expectations=_expectations(), qa_evidence_dir=qa_dir
    )


def _fail_closed(report) -> None:  # noqa: ANN001
    """The tampered cache was not trusted; fresh verification took over."""
    assert not report.worksheet.recovered
    assert report.worksheet.idempotency_key == KEY
    # The artifact itself is valid, so fresh verification still verifies --
    # the verdict comes from live readback, never from the tampered cache.
    assert report.worksheet.state == QA_STATE_VERIFIED


# ---------------------------------------------------------------------------
# Positive: valid persist_qa_report output still recovers
# ---------------------------------------------------------------------------


def test_valid_verified_cache_recovers(tmp_path):
    qa_dir = tmp_path / "qa"
    qa_dir.mkdir()
    _seed(qa_dir)
    docs, slides = _fresh_services()
    run2 = _run(
        docs=docs, slides=slides, expectations=_expectations(), qa_evidence_dir=qa_dir
    )
    assert run2.worksheet.recovered
    assert run2.worksheet.state == QA_STATE_VERIFIED


def test_verified_report_with_advisory_verified_finding_still_recovers(tmp_path):
    def add_advisory(payload):
        payload["worksheet"]["findings"].append(
            {
                "code": "qa-note",
                "severity": "advisory",
                "state": "verified",
                "message": "coherent advisory note",
                "detail": {"source": "test"},
            }
        )

    report = _rerun_after_tamper(tmp_path, add_advisory)
    assert report.worksheet.recovered
    assert report.worksheet.state == QA_STATE_VERIFIED


# ---------------------------------------------------------------------------
# Negative: contradictory / malformed caches fail closed
# ---------------------------------------------------------------------------


def test_wrong_nested_idempotency_key_fails_closed(tmp_path):
    report = _rerun_after_tamper(
        tmp_path, lambda p: p["worksheet"].update({"idempotency_key": WRONG_KEY})
    )
    _fail_closed(report)


def test_wrong_top_level_idempotency_key_fails_closed(tmp_path):
    report = _rerun_after_tamper(
        tmp_path, lambda p: p.update({"idempotency_key": WRONG_KEY})
    )
    _fail_closed(report)


def test_bogus_contract_version_top_and_nested_fails_closed(tmp_path):
    def bad_contract(payload):
        payload["contract_version"] = "bogus-contract"
        payload["worksheet"]["contract_version"] = "bogus-contract"

    report = _rerun_after_tamper(tmp_path, bad_contract)
    _fail_closed(report)


def test_bogus_nested_contract_version_only_fails_closed(tmp_path):
    report = _rerun_after_tamper(
        tmp_path,
        lambda p: p["worksheet"].update({"contract_version": "bogus-contract"}),
    )
    _fail_closed(report)


def test_missing_nested_idempotency_key_fails_closed(tmp_path):
    def drop_key(payload):
        del payload["worksheet"]["idempotency_key"]

    report = _rerun_after_tamper(tmp_path, drop_key)
    _fail_closed(report)


def test_missing_nested_contract_version_fails_closed(tmp_path):
    def drop_contract(payload):
        del payload["worksheet"]["contract_version"]

    report = _rerun_after_tamper(tmp_path, drop_contract)
    _fail_closed(report)


def test_verified_report_with_fail_findings_fails_closed(tmp_path):
    def fail_findings(payload):
        payload["worksheet"]["findings"] = [
            {
                "code": "qa-token-unresolved",
                "severity": "fail",
                "state": "token-unresolved",
                "message": "Unresolved template token {{title}} persists.",
                "detail": {"token": "{{title}}"},
            },
        ]

    report = _rerun_after_tamper(tmp_path, fail_findings)
    _fail_closed(report)


def test_contradictory_finding_state_fails_closed(tmp_path):
    def contradictory(payload):
        payload["worksheet"]["findings"] = [
            {
                "code": "qa-note",
                "severity": "advisory",
                "state": "token-unresolved",
                "message": "advisory severity but non-verified state",
                "detail": {},
            },
        ]

    report = _rerun_after_tamper(tmp_path, contradictory)
    _fail_closed(report)


def test_null_findings_fails_closed_without_crash(tmp_path):
    report = _rerun_after_tamper(
        tmp_path, lambda p: p["worksheet"].update({"findings": None})
    )
    _fail_closed(report)


def test_non_list_findings_fails_closed_without_crash(tmp_path):
    report = _rerun_after_tamper(
        tmp_path, lambda p: p["worksheet"].update({"findings": "oops"})
    )
    _fail_closed(report)


def test_non_dict_finding_item_fails_closed_without_crash(tmp_path):
    report = _rerun_after_tamper(
        tmp_path, lambda p: p["worksheet"].update({"findings": ["not-a-dict"]})
    )
    _fail_closed(report)


def test_non_mapping_detail_fails_closed_without_crash(tmp_path):
    def bad_detail(payload):
        payload["worksheet"]["findings"] = [
            {
                "code": "qa-note",
                "severity": "advisory",
                "state": "verified",
                "message": "note",
                "detail": 5,
            },
        ]

    report = _rerun_after_tamper(tmp_path, bad_detail)
    _fail_closed(report)


def test_finding_missing_required_fields_fails_closed(tmp_path):
    def sparse_finding(payload):
        payload["worksheet"]["findings"] = [{"code": "qa-note"}]

    report = _rerun_after_tamper(tmp_path, sparse_finding)
    _fail_closed(report)


# ---------------------------------------------------------------------------
# Preserved: staleness still refuses recovery
# ---------------------------------------------------------------------------


def test_stale_revision_still_refuses_recovery(tmp_path):
    qa_dir = tmp_path / "qa"
    qa_dir.mkdir()
    _seed(qa_dir)
    docs, slides = _fresh_services()
    docs.docs["doc-1"]["revisionId"] = "r2"
    run2 = _run(
        docs=docs, slides=slides, expectations=_expectations(), qa_evidence_dir=qa_dir
    )
    assert not run2.worksheet.recovered
