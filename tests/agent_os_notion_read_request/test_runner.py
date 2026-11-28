"""Focused tests for the #3501 catch-and-publish failure receipt in runner.main()."""

from __future__ import annotations

import io
import json
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.agent_os_notion_read_request.models import (
    SCHEMA_VERSION,
    NotionReadRequestError,
)
from scripts.agent_os_notion_read_request.projection import reject_credential_keys
from scripts.agent_os_notion_read_request.runner import MAX_TRANSPORT_BYTES, main

from .notion_read_support import transport

REPO = "Blummer92/agent-os"
ACTOR = "32861845"
GENERATED_AT = "2026-10-12T00:00:00Z"


def _run_main(tmp_path: Path, transport_bytes: bytes, capsys) -> tuple[int, dict]:
    transport = tmp_path / "transport.json"
    transport.write_bytes(transport_bytes)
    output = tmp_path / "out" / "result.json"
    argv = [
        "--transport", str(transport),
        "--repository", REPO,
        "--allowed-actor", ACTOR,
        "--generated-at", GENERATED_AT,
        "--output", str(output),
    ]
    code = main(argv)
    captured = capsys.readouterr()
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert json.loads(captured.out.strip().splitlines()[-1]) == receipt
    return code, receipt


def _assert_failure_shape(receipt: dict, reason: str) -> None:
    assert receipt["schema_version"] == SCHEMA_VERSION
    assert receipt["dispatch_status"] == "failed"
    assert receipt["dispatch_reason"] == reason
    assert receipt["result"] is None
    assert receipt["generated_at"] == GENERATED_AT
    for flag in (
        "notion_writes_performed",
        "drive_writes_performed",
        "classroom_artifact_writes_performed",
        "gce_invoked",
    ):
        assert receipt[flag] is False
    failure = receipt["failure"]
    assert failure["reason_code"] == reason
    assert isinstance(failure["error_class"], str) and failure["error_class"]
    assert failure["phase"] in ("transport", "run", "write")
    # The receipt itself must be publishable: no credential-class leakage.
    reject_credential_keys(receipt, "evidence")


def test_transport_unreadable_yields_failure_receipt(tmp_path, capsys) -> None:
    output = tmp_path / "result.json"
    argv = [
        "--transport", str(tmp_path / "missing.json"),
        "--repository", REPO,
        "--allowed-actor", ACTOR,
        "--generated-at", GENERATED_AT,
        "--output", str(output),
    ]
    code = main(argv)
    assert code == 1
    receipt = json.loads(output.read_text(encoding="utf-8"))
    _assert_failure_shape(receipt, "transport-unreadable")
    assert receipt["failure"]["error_class"] == "FileNotFoundError"
    assert receipt["failure"]["detail"] is None


def test_transport_invalid_json_yields_failure_receipt(tmp_path, capsys) -> None:
    code, receipt = _run_main(tmp_path, b"{not json", capsys)
    assert code == 1
    _assert_failure_shape(receipt, "transport-invalid-json")
    assert receipt["failure"]["error_class"] == "JSONDecodeError"


def test_transport_byte_bound_yields_failure_receipt(tmp_path, capsys) -> None:
    code, receipt = _run_main(tmp_path, b"x" * (MAX_TRANSPORT_BYTES + 1), capsys)
    assert code == 1
    _assert_failure_shape(receipt, "transport-exceeds-byte-bound")
    assert receipt["failure"]["error_class"] == "NotionReadRequestError"


def test_injected_provider_exception_yields_failure_receipt(tmp_path, capsys) -> None:
    transport = tmp_path / "transport.json"
    transport.write_text("{}", encoding="utf-8")
    output = tmp_path / "result.json"
    argv = [
        "--transport", str(transport),
        "--repository", REPO,
        "--allowed-actor", ACTOR,
        "--generated-at", GENERATED_AT,
        "--output", str(output),
    ]
    with patch(
        "scripts.agent_os_notion_read_request.runner.run_notion_read_request",
        side_effect=NotionReadRequestError("provider exploded"),
    ):
        code = main(argv)
    assert code == 1
    receipt = json.loads(output.read_text(encoding="utf-8"))
    _assert_failure_shape(receipt, "notion-read-request-error")
    # Domain exceptions may embed provider messages. Never publish raw detail.
    assert receipt["failure"]["detail"] is None


def test_unexpected_exception_yields_unhandled_receipt_without_leakage(
    tmp_path, capsys
) -> None:
    transport = tmp_path / "transport.json"
    transport.write_text("{}", encoding="utf-8")
    output = tmp_path / "result.json"
    argv = [
        "--transport", str(transport),
        "--repository", REPO,
        "--allowed-actor", ACTOR,
        "--generated-at", GENERATED_AT,
        "--output", str(output),
    ]
    with patch(
        "scripts.agent_os_notion_read_request.runner.run_notion_read_request",
        side_effect=RuntimeError("token sk-abc123 leaked here"),
    ):
        code = main(argv)
    assert code == 1
    receipt = json.loads(output.read_text(encoding="utf-8"))
    _assert_failure_shape(receipt, "unhandled-runner-exception")
    # Non-domain messages are never published.
    assert receipt["failure"]["detail"] is None
    assert "sk-abc123" not in json.dumps(receipt)


def test_refused_request_keeps_success_receipt_shape(tmp_path, capsys) -> None:
    # Admission refusal is the existing non-exceptional path: exit 0 and the
    # established evidence schema must be unchanged.
    code, receipt = _run_main(tmp_path, b'{"status": "nope"}', capsys)
    assert code == 0
    assert receipt["schema_version"] == SCHEMA_VERSION
    assert receipt["dispatch_status"] == "blocked"
    assert "failure" not in receipt
    reject_credential_keys(receipt, "evidence")


def test_transport_invalid_utf8_has_bounded_decode_reason(tmp_path, capsys) -> None:
    code, receipt = _run_main(tmp_path, b"\xff", capsys)
    assert code == 1
    _assert_failure_shape(receipt, "transport-invalid-encoding")
    assert receipt["failure"]["error_class"] == "UnicodeDecodeError"
    assert receipt["failure"]["detail"] is None


def test_run_phase_oserror_is_not_misclassified_as_transport(tmp_path, capsys) -> None:
    with patch(
        "scripts.agent_os_notion_read_request.runner.run_notion_read_request",
        side_effect=OSError("provider-private-string"),
    ):
        code, receipt = _run_main(tmp_path, b"{}", capsys)
    assert code == 1
    _assert_failure_shape(receipt, "execution-unavailable")
    assert receipt["failure"]["phase"] == "run"
    assert "provider-private-string" not in json.dumps(receipt)


def test_provider_wrapped_domain_error_does_not_leak_detail(tmp_path, capsys) -> None:
    sensitive_marker = "provider-private-synthetic-value"
    with patch(
        "scripts.agent_os_notion_read_request.runner.run_notion_read_request",
        side_effect=NotionReadRequestError("read failed: " + sensitive_marker),
    ):
        code, receipt = _run_main(tmp_path, b"{}", capsys)
    assert code == 1
    _assert_failure_shape(receipt, "notion-read-request-error")
    assert receipt["failure"]["detail"] is None
    assert sensitive_marker not in json.dumps(receipt)


def test_transport_actual_byte_bound_does_not_trust_stat(tmp_path, capsys) -> None:
    with patch("scripts.agent_os_notion_read_request.runner.Path.stat", side_effect=AssertionError("stat must not be used")):
        code, receipt = _run_main(tmp_path, b"x" * (MAX_TRANSPORT_BYTES + 1), capsys)
    assert code == 1
    _assert_failure_shape(receipt, "transport-exceeds-byte-bound")


_RUNNER_ROUTES = (
    ("visual-asset-library-schema", 2816, "execute_source_schema", "project_source_schema_result"),
    ("candy-branding-lesson-content", 3580, "execute_lesson_content", "project_lesson_content_result"),
    ("rc6-operator-planning-destination", 249, "execute_destination_verification", None),
    ("photography-foundations-visual-assets", 2283, "execute_admitted_notion_read", "project_public_result"),
)
_RUNNER_ROUTE_IDS = ("source-schema", "lesson-content", "destination-verification", "visual-assets")


@pytest.mark.parametrize(
    ("request_id", "issue_number", "executor_name", "projector_name"),
    _RUNNER_ROUTES,
    ids=_RUNNER_ROUTE_IDS,
)
@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        ({"status": "failed"}, "execution-returned-non-success"),
        ({"status": "success", "error": "synthetic-error"}, "execution-returned-non-success"),
        (None, "execution-return-contract-invalid"),
        ({"status": "success", "test_marker": "validated"}, None),
    ],
    ids=("failed-status", "error-despite-success", "not-a-mapping", "success-control"),
)
def test_runner_enforces_completion_contract_before_projection(
    verified_catalog, request_id, issue_number, executor_name, projector_name, outcome, reason,
) -> None:
    from scripts.agent_os_notion_read_request import runner

    # Use a real admitted transport/catalog, but isolate the completion guard
    # from the independent projector's defensive validation on three routes.
    event = transport(request_id=request_id, issue_number=issue_number)
    projected_result = {"test_marker": "validated"}
    projector = (
        patch.object(runner, projector_name, return_value=projected_result)
        if projector_name is not None else nullcontext(None)
    )
    evidence = None
    caught = None
    with patch.object(runner, executor_name, return_value=outcome) as executor, projector as project:
        try:
            evidence = runner.run_notion_read_request(
                event, expected_repository=REPO, expected_actor=event["actor"],
                generated_at=GENERATED_AT, catalog=verified_catalog,
                scheduler_task_executor_factory=lambda: None,
            )
        except (NotionReadRequestError, TypeError) as error:
            caught = error
        executor.assert_called_once()

        if reason is not None:
            # Destination's bare ** expansion would raise TypeError for None
            # without the producer guard: the typed, finite runner refusal is
            # the contract, not just any exception from downstream.
            assert type(caught) is NotionReadRequestError, (
                f"runner completion guard must issue its typed refusal, got {caught!r} "
                f"and dispatch={evidence and evidence['dispatch_status']!r}"
            )
            assert str(caught) == reason
            if project is not None:
                project.assert_not_called()
        else:
            assert caught is None
            assert evidence is not None
            assert evidence["dispatch_status"] == "completed"
            assert evidence["result"]["test_marker"] == "validated"
            if project is not None:
                project.assert_called_once()


def test_malformed_runner_catalog_is_not_a_transport_failure(tmp_path, capsys) -> None:
    from scripts.agent_os_notion_read_request import catalog

    catalog_path = tmp_path / "catalog.json"
    synthetic_private = "synthetic-local-catalog-detail"
    catalog_path.write_text("{" + synthetic_private, encoding="utf-8")
    with patch.object(catalog, "CATALOG_PATH", catalog_path):
        code, receipt = _run_main(tmp_path, b"{}", capsys)
    assert code == 1
    _assert_failure_shape(receipt, "unhandled-runner-exception")
    assert receipt["failure"]["phase"] == "run"
    assert receipt["failure"]["error_class"] == "JSONDecodeError"
    assert receipt["failure"]["detail"] is None
    assert synthetic_private not in json.dumps(receipt)


def test_transport_accepts_exactly_its_byte_limit(tmp_path, capsys) -> None:
    code, receipt = _run_main(tmp_path, b"{}" + b" " * (MAX_TRANSPORT_BYTES - 2), capsys)
    assert code == 0
    assert receipt["dispatch_status"] == "blocked"
    assert "failure" not in receipt



def test_transport_bounds_bytes_requested_before_parsing(tmp_path) -> None:
    from scripts.agent_os_notion_read_request.runner import _read_transport

    class RecordingBinaryInput(io.BytesIO):
        def __init__(self) -> None:
            super().__init__(b"{}")
            self.read_sizes = []

        def read(self, size=-1):
            self.read_sizes.append(size)
            return super().read(size)

    stream = RecordingBinaryInput()
    with patch.object(Path, "open", return_value=stream) as boundary:
        assert _read_transport(tmp_path / "transport.json") == {}
    boundary.assert_called_once_with("rb")
    assert stream.read_sizes == [MAX_TRANSPORT_BYTES + 1]


def test_result_write_failure_emits_only_sanitized_stdout_receipt(tmp_path, capsys) -> None:
    transport = tmp_path / "transport.json"
    transport.write_text("{}", encoding="utf-8")
    output = tmp_path / "output-is-directory"
    output.mkdir()
    code = main([
        "--transport", str(transport),
        "--repository", REPO,
        "--allowed-actor", ACTOR,
        "--generated-at", GENERATED_AT,
        "--output", str(output),
    ])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err == ""
    receipt = json.loads(captured.out)
    _assert_failure_shape(receipt, "receipt-write-failed")
    assert receipt["failure"]["phase"] == "write"
    assert receipt["failure"]["error_class"] == "IsADirectoryError"
    assert receipt["failure"]["detail"] is None
    assert str(output) not in captured.out
    assert output.is_dir()
    assert not list(output.iterdir())
