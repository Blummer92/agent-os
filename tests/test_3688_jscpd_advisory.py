"""Offline tests for the #3688 advisory runner."""
import json
from pathlib import Path
from unittest.mock import patch
from subprocess import CompletedProcess

from scripts.jscpd_advisory import scan, SCOPE, VERSION


def test_success_and_clone_evidence(tmp_path):
    def fake_run(args, **kwargs):
        raw = tmp_path / "raw"
        raw.mkdir()
        (raw / "jscpd-report.json").write_text(json.dumps({
            "duplicates": [{"firstFile": {"name": "a.py", "start": 1},
                            "secondFile": {"name": "b.py", "start": 1}, "lines": 9}]
        }))
        assert all(path in args for path in SCOPE)
        assert f"jscpd@{VERSION}" in args
        assert "--ignore" in args
        return CompletedProcess(args, 0, "", "")

    with patch("scripts.jscpd_advisory.subprocess.run", side_effect=fake_run):
        result = scan(tmp_path, tmp_path, sha="a" * 40)
    assert result["status"] == "ok"
    assert result["candidate_count"] == 1
    assert result["head_sha"] == "a" * 40
    assert json.loads((tmp_path / "jscpd-advisory.json").read_text())["candidates"]


def test_clean_report(tmp_path):
    def fake_run(args, **kwargs):
        raw = tmp_path / "raw"
        raw.mkdir()
        (raw / "jscpd-report.json").write_text('{"duplicates":[]}')
        return CompletedProcess(args, 0, "", "")

    with patch("scripts.jscpd_advisory.subprocess.run", side_effect=fake_run):
        result = scan(tmp_path, tmp_path, sha="b" * 40)
    assert result["status"] == "ok"
    assert result["candidate_count"] == 0


def test_missing_binary_is_reported_not_fatal(tmp_path):
    with patch("scripts.jscpd_advisory.subprocess.run", side_effect=FileNotFoundError):
        result = scan(tmp_path, tmp_path, sha="c" * 40)
    assert result["status"] == "scanner-error"
    assert (tmp_path / "jscpd-advisory.md").exists()


def test_nonzero_exit_is_scanner_error(tmp_path):
    with patch("scripts.jscpd_advisory.subprocess.run", return_value=CompletedProcess([], 1, "", "failure")):
        result = scan(tmp_path, tmp_path, sha="d" * 40)
    assert result["status"] == "scanner-error"


def test_truncates_large_candidate_set(tmp_path):
    def fake_run(args, **kwargs):
        raw = tmp_path / "raw"
        raw.mkdir()
        (raw / "jscpd-report.json").write_text(json.dumps({"duplicates": [{"n": n} for n in range(105)]}))
        return CompletedProcess(args, 0, "", "")

    with patch("scripts.jscpd_advisory.subprocess.run", side_effect=fake_run):
        result = scan(tmp_path, tmp_path, sha="e" * 40)
    assert result["truncated"]
    assert result["candidate_count"] == 105
    assert len(result["candidates"]) == 100
