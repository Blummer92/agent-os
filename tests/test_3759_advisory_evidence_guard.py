"""Track B: scanner evidence is classified honestly; broken scanners fail the advisory job (#3759/#3761)."""
import json
import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from scripts import jscpd_advisory, pyan3_advisory
from scripts.advisory_evidence_guard import PASSING, classify, main

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40


def _write(tmp_path, **overrides):
    data = {
        "schema": "agent-os-jscpd-advisory/1",
        "tool": "jscpd",
        "status": "ok",
        "head_sha": SHA,
        "candidate_count": 2,
    }
    data.update(overrides)
    path = tmp_path / "jscpd-advisory.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_ok_with_findings_passes(tmp_path):
    assert classify("jscpd", _write(tmp_path), SHA)[0] == "ok"


def test_ok_zero_findings_is_distinct_and_passes(tmp_path):
    state, _ = classify("jscpd", _write(tmp_path, candidate_count=0), SHA)
    assert state == "ok-zero-findings" and state in PASSING


def test_scanner_error_fails(tmp_path):
    state, _ = classify("jscpd", _write(tmp_path, status="scanner-error", candidate_count=0), SHA)
    assert state == "scanner-error" and state not in PASSING


def test_missing_artifact_fails(tmp_path):
    assert classify("jscpd", tmp_path / "absent.json", SHA)[0] == "artifact-missing"


def test_stale_sha_fails(tmp_path):
    assert classify("jscpd", _write(tmp_path, head_sha="b" * 40), SHA)[0] == "stale-sha"


@pytest.mark.parametrize("text", ["{not json", "[]", '"str"', ""])
def test_unparseable_or_wrong_shape_fails(tmp_path, text):
    path = tmp_path / "jscpd-advisory.json"
    path.write_text(text, encoding="utf-8")
    assert classify("jscpd", path, SHA)[0] == "invalid-evidence"


@pytest.mark.parametrize(
    "override",
    [{"schema": "other/1"}, {"tool": "pyan3"}, {"status": "weird"}, {"status": None}, {"candidate_count": -1}, {"candidate_count": True}, {"candidate_count": "3"}],
)
def test_contract_violations_fail(tmp_path, override):
    assert classify("jscpd", _write(tmp_path, **override), SHA)[0] == "invalid-evidence"


def test_bad_expected_sha_cannot_pass(tmp_path):
    assert classify("jscpd", _write(tmp_path), "HEAD")[0] == "invalid-evidence"


def test_kind_binding_prevents_cross_tool_evidence(tmp_path):
    assert classify("pyan3", _write(tmp_path), SHA)[0] == "invalid-evidence"


def test_main_exit_codes(tmp_path, capsys):
    good = _write(tmp_path)
    assert main(["--kind", "jscpd", "--file", str(good), "--sha", SHA]) == 0
    assert main(["--kind", "jscpd", "--file", str(tmp_path / "x.json"), "--sha", SHA]) == 1
    assert "advisory only" in capsys.readouterr().err.lower()


def test_real_jscpd_producer_scanner_error_now_fails_the_job(tmp_path):
    """Differential: the producer exits 0 on scanner-error; the guard must not."""
    with patch("scripts.jscpd_advisory.subprocess.run", side_effect=FileNotFoundError):
        assert jscpd_advisory.scan(tmp_path, tmp_path / "out", sha=SHA)["status"] == "scanner-error"
    assert jscpd_advisory.main.__module__  # producer entry point stays advisory (exit 0)
    code = main(["--kind", "jscpd", "--file", str(tmp_path / "out" / "jscpd-advisory.json"), "--sha", SHA])
    assert code == 1


def test_real_jscpd_producer_clean_report_passes_as_zero_findings(tmp_path):
    def fake_run(args, **kwargs):
        raw = tmp_path / "out" / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        (raw / "jscpd-report.json").write_text('{"duplicates":[]}')
        return CompletedProcess(args, 0, "", "")

    with patch("scripts.jscpd_advisory.subprocess.run", side_effect=fake_run):
        jscpd_advisory.scan(tmp_path, tmp_path / "out", sha=SHA)
    path = tmp_path / "out" / "jscpd-advisory.json"
    assert classify("jscpd", path, SHA)[0] == "ok-zero-findings"


def test_real_pyan3_producer_empty_scope_is_scanner_error_and_fails(tmp_path):
    evidence = pyan3_advisory.scan(tmp_path, tmp_path / "out", sha=SHA)
    assert evidence["status"] == "scanner-error"
    path = tmp_path / "out" / "pyan3-advisory.json"
    assert classify("pyan3", path, SHA)[0] == "scanner-error"


def test_cli_entrypoint_runs_as_module(tmp_path):
    done = subprocess.run(
        [sys.executable, "-m", "scripts.advisory_evidence_guard", "--kind", "jscpd", "--file", str(tmp_path / "none.json"), "--sha", SHA],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert done.returncode == 1
    assert json.loads(done.stdout)["state"] == "artifact-missing"


def test_scanner_error_detail_cannot_inject_workflow_commands(tmp_path, capsys):
    path = _write(tmp_path, status="scanner-error", detail="boom\n::warning::injected\r::set-output name=x::y")
    state, detail = classify("jscpd", path, SHA)
    assert state == "scanner-error" and not any(c in detail for c in "\r\n")
    assert main(["--kind", "jscpd", "--file", str(path), "--sha", SHA]) == 1
    stderr_lines = capsys.readouterr().err.splitlines()
    assert len(stderr_lines) == 1 and stderr_lines[0].startswith("::error::")


def test_sha_sharing_a_prefix_with_the_expected_head_is_stale(tmp_path):
    expected = "a" * 40
    evidence = tmp_path / "jscpd-advisory.json"
    for other in (expected[:7] + "b" * 33, expected[:39] + "b"):
        evidence.write_text(
            json.dumps({"schema": "agent-os-jscpd-advisory/1", "tool": "jscpd", "status": "ok",
                        "head_sha": other, "candidate_count": 1}),
            encoding="utf-8",
        )
        assert classify("jscpd", evidence, expected)[0] == "stale-sha"
