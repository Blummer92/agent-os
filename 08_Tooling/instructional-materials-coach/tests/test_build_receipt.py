"""Synthetic, offline regression tests for #3454."""
import json
from pathlib import Path
from types import SimpleNamespace

from instructional_materials_coach.build_receipt import (
    BUILD_RECEIPT_CONTRACT, build_receipt_record, write_build_receipt_atomic,
)
from instructional_materials_coach.live_build import LiveBuildInput, LiveBuildReceipt


def test_receipt_is_deterministic_json_safe_and_non_authorizing(tmp_path: Path):
    build = LiveBuildInput(
        slides_template_id="slides-template", doc_template_id="docs-template",
        target_folder_id="folder", slides_name="Slides", doc_name="Worksheet",
        idempotency_key="exact-key", slides_requests=(), docs_requests=(),
    )
    receipt = LiveBuildReceipt(
        slides=SimpleNamespace(role="slides", state="failed", file_id="", delivery_kind="pending", terminal_qa_state="not-run", mime_type="", persistence_verified=False, parents=()),
        worksheet=SimpleNamespace(role="worksheet", state="planned", file_id="", delivery_kind="pending", terminal_qa_state="not-run", mime_type="", persistence_verified=False, parents=()),
    )
    record = build_receipt_record(build, receipt, requirement_identity={"requirement_id": "r1"})
    assert record["contract_version"] == BUILD_RECEIPT_CONTRACT
    assert record["idempotency_key"] == "exact-key"
    assert record["requirement_identity"]["requirement_id"] == "r1"
    assert record["succeeded"] is False
    assert not any(record["authority"].values())
    assert json.dumps(record, sort_keys=True) == json.dumps(
        build_receipt_record(build, receipt, requirement_identity={"requirement_id": "r1"}),
        sort_keys=True,
    )
    output = tmp_path / "receipt.json"
    write_build_receipt_atomic(output, record)
    assert json.loads(output.read_text()) == record
    assert list(tmp_path.iterdir()) == [output]


def test_missing_build_stays_explicitly_unresolved():
    record = build_receipt_record(None, None, error_code="RuntimeError")
    assert record["succeeded"] is False
    assert record["artifacts"]["slides"]["state"] == "not-run"
    assert record["failure_code"] == "RuntimeError"
    assert record["requirement_identity"]["source_fingerprint"] is None
