"""Focused tests for the #3501 catch-and-publish failure receipt in runner.main()."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.agent_os_notion_read_request.models import (
    SCHEMA_VERSION,
    NotionReadRequestError,
)
from scripts.agent_os_notion_read_request.projection import reject_credential_keys
from scripts.agent_os_notion_read_request.runner import MAX_TRANSPORT_BYTES, main

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
    # Developer-authored domain messages are publishable detail.
    assert receipt["failure"]["detail"] == "provider exploded"


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
