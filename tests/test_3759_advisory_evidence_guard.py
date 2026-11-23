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
        # Real producers always emit a candidates list matching the count.
        "candidates": [{"id": 1}, {"id": 2}],
    }
    data.update(overrides)
    path = tmp_path / "jscpd-advisory.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_ok_with_findings_passes(tmp_path):
    assert classify("jscpd", _write(tmp_path), SHA)[0] == "ok"


def test_ok_zero_findings_is_distinct_and_passes(tmp_path):
    state, _ = classify("jscpd", _write(tmp_path, candidate_count=0, candidates=[]), SHA)
    assert state == "ok-zero-findings" and state in PASSING


@pytest.mark.parametrize(
    "override",
    [
        {"candidates": None},
        {"candidates": "two"},
        {"candidates": [{"id": 1}]},
        {"candidates": [{"id": 1}, {"id": 2}, {"id": 3}]},
        {"candidates": [{"id": 1}, "not-an-object"]},
        {"candidates": [{"id": 1}, {"id": 2}], "candidate_count": 0},
    ],
)
def test_ok_with_missing_or_inconsistent_candidates_fails(tmp_path, override):
    # An `ok` report with candidate_count > 0 but no matching candidates list
    # must never pass, even though the status itself is `ok`.
    base = {"candidate_count": 2, "candidates": [{"id": 1}, {"id": 2}]}
    base.update(override)
    if "candidates" not in override and override.get("candidate_count") == 0:
        base["candidates"] = []
    path = _write(tmp_path, **base)
    if "candidates" in override and override["candidates"] is None:
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["candidates"]
        path.write_text(json.dumps(data), encoding="utf-8")
    assert classify("jscpd", path, SHA)[0] == "invalid-evidence"


def test_ok_truncated_report_may_list_fewer_than_count(tmp_path):
    state, _ = classify(
        "jscpd",
        _write(tmp_path, candidate_count=150, candidates=[{"id": 1}], truncated=True),
        SHA,
    )
    assert state == "ok"


def test_ok_untruncated_short_list_fails(tmp_path):
    assert (
        classify(
            "jscpd",
            _write(tmp_path, candidate_count=150, candidates=[{"id": 1}]),
            SHA,
        )[0]
        == "invalid-evidence"
    )


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


def test_escape_helper_is_safe_for_direct_callers():
    from scripts.advisory_evidence_guard import escape_workflow_command_value

    # Order: CR/LF mapped first, then % encoded, so no output token can be
    # decoded by the runner into a line break.
    assert escape_workflow_command_value("a\nb\r c%0A%d") == "a%250Ab%250D c%250A%25d"
    assert escape_workflow_command_value("plain") == "plain"


def test_scanner_error_detail_cannot_inject_workflow_commands(tmp_path, capsys):
    path = _write(tmp_path, status="scanner-error", detail="boom\n::warning::injected\r::set-output name=x::y")
    state, detail = classify("jscpd", path, SHA)
    assert state == "scanner-error" and not any(c in detail for c in "\r\n")
    assert main(["--kind", "jscpd", "--file", str(path), "--sha", SHA]) == 1
    stderr_lines = capsys.readouterr().err.splitlines()
    assert len(stderr_lines) == 1 and stderr_lines[0].startswith("::error::")


@pytest.mark.parametrize(
    "detail",
    [
        "x%0A::error::forged",
        "x%0D::error::forged",
        "100%25::error::forged",
        "%0A%0D%25::set-output name=x::y",
    ],
)
def test_scanner_error_encoded_escapes_cannot_inject_workflow_commands(tmp_path, capsys, detail):
    # Assert on the actual emitted stderr line: the runner decodes %0A/%0D/%25,
    # so the annotation must carry %25 in place of every producer % or the
    # decoded text would split into a second workflow command.
    path = _write(tmp_path, status="scanner-error", detail=detail)
    assert main(["--kind", "jscpd", "--file", str(path), "--sha", SHA]) == 1
    stderr_lines = capsys.readouterr().err.splitlines()
    assert len(stderr_lines) == 1 and stderr_lines[0].startswith("::error::")
    assert "%0A" not in stderr_lines[0] and "%0D" not in stderr_lines[0]
    assert "%25" in stderr_lines[0]
    # Single-pass runner decoding of the emitted line must not produce a
    # newline or a second command: "%250A" decodes to literal "%0A" text.
    decoded, i = "", 0
    line = stderr_lines[0]
    while i < len(line):
        token = line[i : i + 3]
        if token == "%25":
            decoded += "%"
            i += 3
        elif token == "%0A":
            decoded += "\n"
            i += 3
        elif token == "%0D":
            decoded += "\r"
            i += 3
        else:
            decoded += line[i]
            i += 1
    # A literal "::error::" mid-line is inert text: workflow commands are
    # recognized at line start, so the property that matters is one line,
    # starting with the intended annotation, with no decoded line break.
    assert "\n" not in decoded and "\r" not in decoded
    assert decoded.startswith("::error::") and decoded.splitlines() == [decoded]


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
