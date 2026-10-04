"""#3252: build interruption → resume semantics.

Covers the issue acceptance criteria: a crash between the Slides and Docs
steps followed by a retry either completes or emits an explicit
reconciliation blocker; "required placeholder was not replaced" is never
reported for a copy the prior run already filled; a retry never duplicates
or loses state; reusing a key with different inputs is rejected.
"""
from __future__ import annotations

import json
import re
from typing import Any
from unittest.mock import patch

import pytest

from instructional_materials_coach.build_resume import (
    load_resume_record,
    write_resume_record,
)
from instructional_materials_coach.live_build import (
    IdempotencyKeyInputMismatchError,
    LiveBuildInput,
    build_live_materials,
)
from instructional_materials_coach.artifact_content_qa import TerminalQAExpectations
from instructional_materials_coach.workspace_clients import (
    _validate_replace_results,
)

PRESENTATION_MIME = "application/vnd.google-apps.presentation"
DOCUMENT_MIME = "application/vnd.google-apps.document"

TITLE_TEXT = "Fractions Intro"


def _build(key: str = "k" * 64, input_fingerprint: str = "fp-a") -> LiveBuildInput:
    slides_requests = (
        {
            "replaceAllText": {
                "containsText": {"text": "{{title}}"},
                "replaceText": {"text": TITLE_TEXT},
            }
        },
    )
    docs_requests = (
        {
            "replaceAllText": {
                "containsText": {"text": "{{title}}"},
                "replaceText": {"text": TITLE_TEXT},
            }
        },
    )
    return LiveBuildInput(
        slides_template_id="slides-template",
        doc_template_id="doc-template",
        target_folder_id="folder",
        slides_name="Lesson - Slides",
        doc_name="Lesson - Worksheet",
        idempotency_key=key,
        input_fingerprint=input_fingerprint,
        slides_requests=slides_requests,
        docs_requests=docs_requests,
        # #3258: terminal QA proves the persisted content; without governed
        # expectations the build can never be final.
        qa_expectations=TerminalQAExpectations.build_from_requests(
            idempotency_key=key,
            docs_requests=docs_requests,
            slides_requests=slides_requests,
        ),
    )


class _Executable:
    def __init__(self, payload: Any):
        self._payload = payload

    def execute(self) -> Any:
        return self._payload


class _FakeDriveFiles:
    """In-memory Drive fake supporting the idempotency-copy protocol."""

    def __init__(self, store: dict[str, dict[str, Any]]):
        self._store = store
        # Continue numbering past copies created through other service
        # instances sharing this store: ids must never collide.
        self._next = 0
        for existing_id in store:
            match = re.fullmatch(r"copy-(\d+)", str(existing_id))
            if match:
                self._next = max(self._next, int(match.group(1)))

    def list(self, q: str = "", **kwargs: Any) -> _Executable:
        key = re.search(r"key='agent_os_idempotency_key' and value='([^']*)'", q)
        role = re.search(r"key='agent_os_artifact_role' and value='([^']*)'", q)
        key_v = key.group(1) if key else ""
        role_v = role.group(1) if role else ""
        matches = [
            meta for meta in self._store.values()
            if isinstance(meta, dict)
            and meta.get("appProperties", {}).get("agent_os_idempotency_key") == key_v
            and meta.get("appProperties", {}).get("agent_os_artifact_role") == role_v
            and not meta.get("trashed")
        ]
        return _Executable({"files": matches})

    def copy(self, fileId: str | None = None, body: dict[str, Any] | None = None,
             fields: str | None = None, **kwargs: Any) -> _Executable:
        body = body or {}
        self._next += 1
        fid = f"copy-{self._next}"
        mime = PRESENTATION_MIME if "lides" in str(fileId) else DOCUMENT_MIME
        meta = {
            "id": fid,
            "name": body.get("name", ""),
            "mimeType": mime,
            "parents": body.get("parents", []),
            "trashed": False,
            "appProperties": body.get("appProperties", {}),
            "webViewLink": f"https://example/{fid}",
            "driveId": "drive-1",
        }
        self._store[fid] = meta
        return _Executable(meta)

    def get(self, fileId: str | None = None, fields: str | None = None,
            **kwargs: Any) -> _Executable:
        return _Executable(self._store[fileId or ""])


class _FakeDriveService:
    def __init__(self, store: dict[str, dict[str, Any]]):
        self._files = _FakeDriveFiles(store)

    def files(self) -> _FakeDriveFiles:
        return self._files


class _FakeWorkspaceService:
    """Fake Slides/Docs service with server-side document state.

    "Filled" state lives in the shared store (keyed by file ID), modeling
    the real API: once a document's placeholders are replaced, any later
    batchUpdate for the same file returns occurrencesChanged=0. The applied
    replacement text is tracked per file so the content-presence safety net
    can read it back. When fail_batch=True it raises instead, simulating a
    mid-build connector failure.
    """

    def __init__(self, kind: str, store: dict[str, Any]):
        self._kind = kind  # "presentations" or "documents"
        self._store = store
        self.fail_batch = False
        self.batch_calls = 0
        self.request_bodies: list[list[dict[str, Any]]] = []

    # service.presentations() / service.documents() both return self
    def presentations(self) -> "_FakeWorkspaceService":
        return self

    def documents(self) -> "_FakeWorkspaceService":
        return self

    def get(self, presentationId: str | None = None, documentId: str | None = None,
            fields: str | None = None) -> _Executable:
        fid = presentationId or documentId or ""
        # Content read for the safety net (the revision reads in these tests
        # go through the patched get_*_revision_id helpers).
        texts: dict[str, str] = self._store.get("_texts", {})
        text = texts.get(fid, "")
        # #3258: terminal QA binds evidence to the artifact revision, so the
        # fake readback carries a revisionId like the real API.
        revision = f"rev-{fid or self._kind}"
        if self._kind == "documents":
            return _Executable(
                {"revisionId": revision, "body": {"content": [{"paragraph": {"elements": [{"textRun": {"content": text}}]}}]}}
            )
        return _Executable(
            {"revisionId": revision, "slides": [{"pageElements": [{"shape": {"text": {"textElements": [{"textRun": {"content": text}}]}}}]}]}
        )

    def batchUpdate(self, presentationId: str | None = None, documentId: str | None = None,
                    body: dict[str, Any] | None = None) -> _Executable:
        self.batch_calls += 1
        if self.fail_batch:
            raise RuntimeError("docs connector failed mid-build")
        fid = presentationId or documentId or ""
        requests = (body or {}).get("requests", [])
        self.request_bodies.append(list(requests))
        filled: set[str] = self._store.setdefault("_filled", set())
        texts: dict[str, str] = self._store.setdefault("_texts", {})
        occurrences = []
        for request in requests:
            if fid in filled:
                occurrences.append(0)
            else:
                occurrences.append(1)
                replace = request.get("replaceAllText", {})
                new_text = replace.get("replaceText", {}).get("text", "")
                texts[fid] = texts.get(fid, "") + new_text
        filled.add(fid)
        replies = [{"replaceAllText": {"occurrencesChanged": n}} for n in occurrences]
        return _Executable({"replies": replies})


def _run(build_input: LiveBuildInput, store: dict[str, dict[str, Any]],
         slides_svc: _FakeWorkspaceService, docs_svc: _FakeWorkspaceService,
         resume_dir=None):
    drive = _FakeDriveService(store)
    with patch("instructional_materials_coach.live_build.verify_template"), \
         patch("instructional_materials_coach.live_build.verify_target_folder"), \
         patch("instructional_materials_coach.live_build.get_slides_revision_id", return_value="s-rev"), \
         patch("instructional_materials_coach.live_build.get_docs_revision_id", return_value="d-rev"), \
         patch("instructional_materials_coach.live_build.verify_final_copy",
               side_effect=lambda _d, fid, **kw: store[fid]):
        return build_live_materials(
            build_input, drive_service=drive,
            slides_service=slides_svc, docs_service=docs_svc,
            resume_dir=resume_dir,
        )


def test_retry_probe_run1_fails_mid_build_run2_completes(tmp_path):
    """The issue's fake-service retry probe — now fixed.

    run1: Slides requests apply (copy filled), then the docs connector fails
    mid-build → slides=updated, worksheet=failed, succeeded=False.
    run2 (same idempotency key): recovers both copies and completes — it
    must NOT report "required placeholder was not replaced" for the Slides
    copy run1 already filled.
    """
    store: dict[str, dict[str, Any]] = {}
    key = "probe-key-" + "k" * 54
    resume_dir = tmp_path / "resume"

    # run1: docs connector fails mid-build
    slides_svc = _FakeWorkspaceService("presentations", store)
    docs_svc = _FakeWorkspaceService("documents", store)
    docs_svc.fail_batch = True
    receipt1 = _run(_build(key), store, slides_svc, docs_svc, resume_dir=resume_dir)
    assert not receipt1.succeeded
    assert receipt1.slides.state == "updated", receipt1.slides
    assert receipt1.worksheet.state == "failed", receipt1.worksheet

    # run2: same key, healthy connectors — must complete
    slides_svc2 = _FakeWorkspaceService("presentations", store)
    docs_svc2 = _FakeWorkspaceService("documents", store)
    receipt2 = _run(_build(key), store, slides_svc2, docs_svc2, resume_dir=resume_dir)
    assert receipt2.succeeded, (
        f"run2 failed: slides={receipt2.slides.state} {receipt2.slides.error!r}; "
        f"worksheet={receipt2.worksheet.state} {receipt2.worksheet.error!r}"
    )
    assert "required placeholder was not replaced" not in (receipt2.slides.error or "")
    # No duplicate copies: exactly one slides copy and one worksheet copy.
    copies = [m for m in store.values() if isinstance(m, dict) and "appProperties" in m]
    assert len(copies) == 2


def test_resume_after_slides_updated_worksheet_failed_skips_slides_mutation(tmp_path):
    """Crash between Slides and Docs steps.

    The retry must NOT re-apply Slides requests; it verifies the recovered
    Slides copy and retries only the worksheet.
    """
    store: dict[str, dict[str, Any]] = {}
    key = "k" * 64
    resume_dir = tmp_path / "resume"

    slides_svc = _FakeWorkspaceService("presentations", store)
    docs_svc = _FakeWorkspaceService("documents", store)
    docs_svc.fail_batch = True
    _run(_build(key), store, slides_svc, docs_svc, resume_dir=resume_dir)

    slides_svc2 = _FakeWorkspaceService("presentations", store)
    docs_svc2 = _FakeWorkspaceService("documents", store)
    receipt = _run(_build(key), store, slides_svc2, docs_svc2, resume_dir=resume_dir)
    assert receipt.succeeded
    assert slides_svc2.batch_calls == 0, "recovered-verified Slides copy must not be mutated"
    assert docs_svc2.batch_calls == 1


def test_resume_after_copy_created_before_requests_applied(tmp_path):
    """Crash after duplicate_template but before any requests applied.

    The retry must recover the created copy (not create a second one) and
    apply the full request list to it.
    """
    store: dict[str, dict[str, Any]] = {}
    key = "k" * 64
    resume_dir = tmp_path / "resume"
    drive = _FakeDriveService(store)

    # Manually create copies as run1 would have, then a resume record with
    # state=created and no applied requests.
    slides_copy = drive.files().copy(
        fileId="slides-template",
        body={
            "name": "Lesson - Slides",
            "parents": ["folder"],
            "appProperties": {
                "agent_os_idempotency_key": key,
                "agent_os_artifact_role": "slides",
                "agent_os_input_fingerprint": "fp-a",
            },
        },
    ).execute()
    docs_copy = drive.files().copy(
        fileId="doc-template",
        body={
            "name": "Lesson - Worksheet",
            "parents": ["folder"],
            "appProperties": {
                "agent_os_idempotency_key": key,
                "agent_os_artifact_role": "worksheet",
                "agent_os_input_fingerprint": "fp-a",
            },
        },
    ).execute()
    from instructional_materials_coach.build_resume import (
        mark_role_state,
        new_resume_record,
    )

    record = new_resume_record(key, "fp-a")
    mark_role_state(record, "slides", state="created", file_id=slides_copy["id"])
    mark_role_state(record, "worksheet", state="created", file_id=docs_copy["id"])
    write_resume_record(resume_dir, record)

    slides_svc = _FakeWorkspaceService("presentations", store)
    docs_svc = _FakeWorkspaceService("documents", store)
    receipt = _run(_build(key), store, slides_svc, docs_svc, resume_dir=resume_dir)
    assert receipt.succeeded
    assert receipt.slides.file_id == slides_copy["id"]
    assert receipt.worksheet.file_id == docs_copy["id"]
    copies = [m for m in store.values() if isinstance(m, dict) and "appProperties" in m]
    assert len(copies) == 2, "no duplicate copies may be created"


def test_resume_applies_only_unapplied_requests(tmp_path):
    """Crash midway through a request list.

    With applied_request_indices=[0], the retry applies only requests[1:],
    in order.
    """
    store: dict[str, dict[str, Any]] = {}
    key = "k" * 64
    resume_dir = tmp_path / "resume"
    drive = _FakeDriveService(store)

    two_docs = (
        {
            "replaceAllText": {
                "containsText": {"text": "{{title}}"},
                "replaceText": {"text": "First"},
            }
        },
        {
            "replaceAllText": {
                "containsText": {"text": "{{question_1}}"},
                "replaceText": {"text": "Second"},
            }
        },
    )
    build_input = LiveBuildInput(
        slides_template_id="slides-template",
        doc_template_id="doc-template",
        target_folder_id="folder",
        slides_name="Lesson - Slides",
        doc_name="Lesson - Worksheet",
        idempotency_key=key,
        input_fingerprint="fp-a",
        slides_requests=(),
        docs_requests=two_docs,
        # #3258: terminal QA proves the persisted content.
        qa_expectations=TerminalQAExpectations.build_from_requests(
            idempotency_key=key,
            docs_requests=two_docs,
            slides_requests=(),
        ),
    )

    # Simulate the crash: worksheet copy exists, request 0 recorded applied.
    docs_copy = drive.files().copy(
        fileId="doc-template",
        body={
            "name": "Lesson - Worksheet",
            "parents": ["folder"],
            "appProperties": {
                "agent_os_idempotency_key": key,
                "agent_os_artifact_role": "worksheet",
                "agent_os_input_fingerprint": "fp-a",
            },
        },
    ).execute()
    from instructional_materials_coach.build_resume import (
        new_resume_record,
    )

    record = new_resume_record(key, "fp-a")
    record["worksheet"]["state"] = "created"
    record["worksheet"]["file_id"] = docs_copy["id"]
    record["worksheet"]["applied_request_indices"] = [0]
    write_resume_record(resume_dir, record)
    # Model the pre-crash reality the resume record claims: request 0's text
    # is already persisted in the copy, so terminal QA can observe it.
    store.setdefault("_texts", {})[docs_copy["id"]] = "First"

    # Retry: only requests[1:] must be applied, one at a time.
    docs_svc2 = _FakeWorkspaceService("documents", store)
    slides_svc2 = _FakeWorkspaceService("presentations", store)
    receipt = _run(build_input, store, slides_svc2, docs_svc2, resume_dir=resume_dir)
    assert receipt.succeeded
    assert docs_svc2.batch_calls == 1
    applied = docs_svc2.request_bodies[0]
    assert len(applied) == 1
    assert applied[0]["replaceAllText"]["replaceText"]["text"] == "Second"
    # Resume record now shows both applied.
    final_record = load_resume_record(resume_dir, key)
    assert final_record is not None
    assert sorted(final_record["worksheet"]["applied_request_indices"]) == [0, 1]


def test_resume_with_ambiguous_copies_still_fails_closed(tmp_path):
    """Two copies match the idempotency key on retry.

    The retry must return manual_reconciliation_required=True; it must not
    pick one arbitrarily or create a third.
    """
    store: dict[str, dict[str, Any]] = {}
    key = "k" * 64
    drive = _FakeDriveService(store)
    for _ in range(2):
        drive.files().copy(
            fileId="slides-template",
            body={
                "name": "Lesson - Slides",
                "parents": ["folder"],
                "appProperties": {
                    "agent_os_idempotency_key": key,
                    "agent_os_artifact_role": "slides",
                },
            },
        ).execute()
    slides_svc = _FakeWorkspaceService("presentations", store)
    docs_svc = _FakeWorkspaceService("documents", store)
    receipt = _run(_build(key), store, slides_svc, docs_svc, resume_dir=tmp_path / "r")
    assert receipt.manual_reconciliation_required is True
    assert receipt.slides.state == "ambiguous"
    copies = [m for m in store.values() if isinstance(m, dict) and "appProperties" in m]
    assert len(copies) == 2


def test_corrupt_resume_record_fails_closed_without_duplicate_copy(tmp_path):
    """A corrupt resume record must not be treated as absent recovery state.

    Silently ignoring malformed continuation state can re-run mutations whose
    completion cannot be proven. The build must stop for reconciliation rather
    than guessing or creating another copy.
    """
    store: dict[str, dict[str, Any]] = {}
    key = "k" * 64
    resume_dir = tmp_path / "resume"
    resume_dir.mkdir(parents=True)
    (resume_dir / f"{key}.json").write_text("{not-json", encoding="utf-8")

    slides_svc = _FakeWorkspaceService("presentations", store)
    docs_svc = _FakeWorkspaceService("documents", store)
    receipt = _run(_build(key), store, slides_svc, docs_svc, resume_dir=resume_dir)

    assert receipt.manual_reconciliation_required is True
    assert receipt.succeeded is False
    copies = [m for m in store.values() if isinstance(m, dict) and "appProperties" in m]
    assert copies == []


def test_resume_record_written_after_every_state_transition(tmp_path):
    """Crash-safety of the resume record itself.

    After the docs failure, the record on disk reflects the last completed
    step: slides=updated, worksheet=failed.
    """
    store: dict[str, dict[str, Any]] = {}
    key = "k" * 64
    resume_dir = tmp_path / "resume"
    slides_svc = _FakeWorkspaceService("presentations", store)
    docs_svc = _FakeWorkspaceService("documents", store)
    docs_svc.fail_batch = True
    receipt = _run(_build(key), store, slides_svc, docs_svc, resume_dir=resume_dir)
    assert not receipt.succeeded

    record = load_resume_record(resume_dir, key)
    assert record is not None
    assert record["slides"]["state"] == "updated"
    assert record["slides"]["file_id"] == receipt.slides.file_id
    assert record["worksheet"]["state"] == "failed"
    assert record["worksheet"]["error"]


def test_zero_occurrences_with_content_already_present_is_not_fatal():
    """Content-presence safety net in _validate_replace_results."""
    requests = [
        {
            "replaceAllText": {
                "containsText": {"text": "{{title}}"},
                "replaceText": {"text": TITLE_TEXT},
            }
        }
    ]
    response = {"replies": [{"replaceAllText": {"occurrencesChanged": 0}}]}

    # Replacement text already present → already-applied, no raise.
    _validate_replace_results(
        requests, response, surface="Docs", content_fetcher=lambda: f"prefix {TITLE_TEXT} suffix"
    )
    # Genuinely absent → still fails closed.
    with pytest.raises(RuntimeError, match="required placeholder was not replaced"):
        _validate_replace_results(
            requests, response, surface="Docs", content_fetcher=lambda: "unrelated text"
        )
    # No fetcher (hot path) → fails as before.
    with pytest.raises(RuntimeError, match="required placeholder was not replaced"):
        _validate_replace_results(requests, response, surface="Docs")
    # Unreadable fetch → fails closed, never silently passes.
    def _boom():
        raise RuntimeError("read failed")

    with pytest.raises(RuntimeError, match="required placeholder was not replaced"):
        _validate_replace_results(requests, response, surface="Docs", content_fetcher=_boom)


def test_lost_resume_record_with_filled_copy_completes_via_safety_net(tmp_path):
    """Resume record lost but the copy survives.

    run1 (no resume dir): Slides filled. run2 with a fresh resume dir:
    the recovered copy has no resume state, so the safety net reads back
    the document, proves the replacement is present, and completes.
    """
    store: dict[str, dict[str, Any]] = {}
    key = "k" * 64

    slides_svc = _FakeWorkspaceService("presentations", store)
    docs_svc = _FakeWorkspaceService("documents", store)
    docs_svc.fail_batch = True
    receipt1 = _run(_build(key), store, slides_svc, docs_svc, resume_dir=None)
    assert not receipt1.succeeded
    assert receipt1.slides.state == "updated"

    slides_svc2 = _FakeWorkspaceService("presentations", store)
    docs_svc2 = _FakeWorkspaceService("documents", store)
    receipt2 = _run(
        _build(key), store, slides_svc2, docs_svc2, resume_dir=tmp_path / "fresh"
    )
    assert receipt2.succeeded, (
        f"slides={receipt2.slides.state} {receipt2.slides.error!r}; "
        f"worksheet={receipt2.worksheet.state} {receipt2.worksheet.error!r}"
    )
    assert "required placeholder was not replaced" not in (receipt2.slides.error or "")


def test_resume_never_reuses_key_with_different_inputs(tmp_path):
    """Anti-collision on recovery: bound fingerprint mismatch raises."""
    store: dict[str, dict[str, Any]] = {}
    key = "k" * 64
    resume_dir = tmp_path / "resume"

    slides_svc = _FakeWorkspaceService("presentations", store)
    docs_svc = _FakeWorkspaceService("documents", store)
    receipt1 = _run(
        _build(key, input_fingerprint="fp-a"), store, slides_svc, docs_svc,
        resume_dir=resume_dir,
    )
    assert receipt1.succeeded

    slides_svc2 = _FakeWorkspaceService("presentations", store)
    docs_svc2 = _FakeWorkspaceService("documents", store)
    with pytest.raises(IdempotencyKeyInputMismatchError, match="idempotency-key-input-mismatch"):
        _run(
            _build(key, input_fingerprint="fp-b"), store, slides_svc2, docs_svc2,
            resume_dir=resume_dir,
        )
