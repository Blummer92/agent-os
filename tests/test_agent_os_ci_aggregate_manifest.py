"""Successful aggregate claims require a complete manifest and receipt inventory."""
from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile

import pytest

from scripts.agent_os_ci_aggregate_manifest import (
    HEADER,
    validate_aggregate_manifest,
    validate_directory,
)
from scripts.agent_os_ci_evidence_collector import (
    build_verified_receipt,
    classify_junit_artifact,
)

XML = b'<testsuites><testsuite name="s" tests="1" failures="0" errors="0" skipped="0"><testcase classname="c" name="n"/></testsuite></testsuites>'


def valid_bundle() -> dict[str, bytes]:
    return {
        "root.xml": XML,
        "manifest.tsv": (HEADER + "\nroot\troot.xml\tyes\tPASS\t0\tEXECUTED_PASS\n"
                         "test selection completeness: root\ttest-completeness-root.json\tyes\tPASS\t0\tCOMPLETE\n").encode(),
        "test-completeness-root.json": json.dumps({'schema': 'agent-os-ci-test-completeness/1', 'suite_name': 'root', 'verdict': 'COMPLETE', 'error': None, 'expected_count': 1, 'executed_count': 1, 'missing_count': 0, 'missing': [], 'skipped_mandatory': [], 'skip_allowlist_stale': [], 'reference_only': [], 'reference_noconftest_only': [], 'reference_returncode': 0, 'reference_noconftest_returncode': 0, 'outcome': {'failures': 0, 'errors': 0, 'failed_nodes': []}}).encode(),
    }


def archive(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        for name, data in files.items():
            zipped.writestr(name, data)
    return output.getvalue()


def test_complete_bundle_preserves_xml_and_receipt_owners(tmp_path):
    files = valid_bundle()
    assert validate_aggregate_manifest(files) == {"suites": 1, "completeness_receipts": 1}
    assert classify_junit_artifact(archive(files), require_manifest=True)["classification"] == "EVIDENCE_VALID"
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    assert validate_directory(tmp_path)["suites"] == 1
    proc = subprocess.run([sys.executable, "scripts/agent_os_ci_aggregate_manifest.py", str(tmp_path)], capture_output=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("fault", [
    "missing-manifest", "garbage-manifest", "header-only", "truncated-manifest",
    "failed-row", "nonzero-pass", "extra-field", "duplicate-suite", "duplicate-artifact",
    "missing-xml", "missing-receipt", "failed-receipt", "wrong-receipt-suite",
    "wrong-receipt-schema", "duplicate-json-key", "unlisted-xml", "no-root",
    "focused-substitute", "unsafe-member", "minimal-receipt", "contradictory-count", "failed-outcome",
])
def test_claimed_success_rejects_incomplete_or_contradictory_evidence(fault):
    files = valid_bundle()
    text = files["manifest.tsv"].decode()
    if fault == "missing-manifest":
        del files["manifest.tsv"]
    elif fault == "garbage-manifest":
        files["manifest.tsv"] = b"garbage\n"
    elif fault == "header-only":
        files["manifest.tsv"] = (HEADER + "\n").encode()
    elif fault == "truncated-manifest":
        files["manifest.tsv"] = text.rstrip("\n").encode()
    elif fault == "failed-row":
        files["manifest.tsv"] = text.replace("PASS\t0\tEXECUTED_PASS", "FAIL\t1\tEXECUTED_FAIL").encode()
    elif fault == "nonzero-pass":
        files["manifest.tsv"] = text.replace("PASS\t0\tEXECUTED_PASS", "PASS\t1\tEXECUTED_PASS").encode()
    elif fault == "extra-field":
        files["manifest.tsv"] = text.replace("\tEXECUTED_PASS", "\tEXECUTED_PASS\textra").encode()
    elif fault == "duplicate-suite":
        files["manifest.tsv"] += b"root\tother.xml\tyes\tPASS\t0\tEXECUTED_PASS\n"
    elif fault == "duplicate-artifact":
        files["manifest.tsv"] += b"other\troot.xml\tyes\tPASS\t0\tEXECUTED_PASS\n"
    elif fault == "missing-xml":
        del files["root.xml"]
    elif fault == "missing-receipt":
        del files["test-completeness-root.json"]
    elif fault in {"failed-receipt", "wrong-receipt-suite", "wrong-receipt-schema"}:
        receipt = json.loads(files["test-completeness-root.json"])
        key, value = {"failed-receipt": ("verdict", "OUTCOME_FAILED"),
                      "wrong-receipt-suite": ("suite_name", "other"),
                      "wrong-receipt-schema": ("schema", "unknown")}[fault]
        receipt[key] = value
        files["test-completeness-root.json"] = json.dumps(receipt).encode()
    elif fault == "duplicate-json-key":
        files["test-completeness-root.json"] = b'{"schema":"agent-os-ci-test-completeness/1","suite_name":"root","verdict":"ERROR","verdict":"COMPLETE"}'
    elif fault == "unlisted-xml":
        files["stale.xml"] = XML.replace(b'name="n"', b'name="stale"')
    elif fault == "no-root":
        files["manifest.tsv"] = text.replace("root", "other").encode()
        files["other.xml"] = files.pop("root.xml")
        files["test-completeness-other.json"] = files.pop("test-completeness-root.json").replace(b'"root"', b'"other"')
    elif fault == "focused-substitute":
        files["manifest.tsv"] = text.replace("\nroot\t", "\nfocused: root\t").encode()
    elif fault == "unsafe-member":
        files["manifest.tsv"] = text.replace("root.xml", "../root.xml").encode()
    if fault in {"minimal-receipt", "contradictory-count", "failed-outcome"}:
        receipt = json.loads(files["test-completeness-root.json"])
        if fault == "minimal-receipt":
            receipt = {key: receipt[key] for key in ("schema", "suite_name", "verdict", "error")}
        elif fault == "contradictory-count":
            receipt["executed_count"] = 0
        else:
            receipt["outcome"]["errors"] = 1
        files["test-completeness-root.json"] = json.dumps(receipt).encode()
    with pytest.raises(ValueError):
        validate_aggregate_manifest(files)
    assert classify_junit_artifact(archive(files), require_manifest=True)["classification"] != "EVIDENCE_VALID"


@pytest.mark.parametrize("substitution", ["symlink", "directory"])
def test_producer_cli_rejects_member_substitution(tmp_path, substitution):
    for name, data in valid_bundle().items():
        (tmp_path / name).write_bytes(data)
    (tmp_path / "root.xml").unlink()
    if substitution == "symlink":
        outside = tmp_path.parent / "unrelated.xml"
        outside.write_bytes(XML)
        (tmp_path / "root.xml").symlink_to(outside)
    else:
        (tmp_path / "root.xml").mkdir()
    proc = subprocess.run([sys.executable, "scripts/agent_os_ci_aggregate_manifest.py", str(tmp_path)], capture_output=True)
    assert proc.returncode == 2


def test_focused_diagnostics_and_draft_deferral_remain_separate():
    assert classify_junit_artifact(archive({"focus.xml": XML}))["classification"] == "EVIDENCE_VALID"
    receipt = build_verified_receipt(
        source_run={"id": 100, "head_sha": "b" * 40, "path": ".github/workflows/agent-os-validation.yml", "status": "completed"},
        jobs=[{"name": "Run aggregate validation", "run_attempt": 1, "conclusion": "skipped"}],
        artifacts=[], downloads={}, source_attempt=1, collector_head="c" * 40, live_trigger=False,
    )
    assert receipt["streams"]["aggregate"]["classification"] == "INTENTIONALLY_DEFERRED"
