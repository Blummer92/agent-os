"""Controls for the pilot runner and its non-gating workflow contract."""
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import agent_os_ci_python_quality as quality

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/agent-os-validation.yml"
HEAD = "a" * 40


@pytest.mark.parametrize(
    "tool,code,diagnostics,status",
    [
        ("black", 0, "1 file would be left unchanged.", "clean"),
        ("black", 1, "would reformat one.py", "findings"),
        ("black", 1, "No module named black.__main__", "scanner-error"),
        ("black", 123, "would reformat one.py", "scanner-error"),
        ("mypy", 0, "Success: no issues found", "clean"),
        ("mypy", 1, "one.py:1: error: Type mismatch", "findings"),
        ("mypy", 1, "Traceback (most recent call last):", "scanner-error"),
        ("mypy", 2, "one.py:1: error: invalid syntax", "scanner-error"),
        ("vulture", 0, "", "clean"),
        ("vulture", 3, "one.py:1: unused import 'os' (90% confidence)", "findings"),
        ("vulture", 3, "", "scanner-error"),
        ("vulture", 1, "Invalid input", "scanner-error"),
    ],
)
def test_exit_classification(tool, code, diagnostics, status, monkeypatch):
    monkeypatch.setattr(quality.importlib.metadata, "version", lambda _: "1.0")
    monkeypatch.setenv("MYPYPATH", "/outside/analysis/scope")

    def scan(cmd, *, stdout, env, **kwargs):
        assert cmd[1:4] == ["-I", "-m", tool]
        assert cmd[-2:] == [quality.CONFIG, "one.py"]
        assert "MYPYPATH" not in env
        stdout.write(diagnostics.encode())
        return subprocess.CompletedProcess(cmd, code)

    monkeypatch.setattr(quality.subprocess, "run", scan)
    result = quality.run_check(tool, "1.0", ["one.py"])
    assert (result["status"], result["version"], result["exit_code"]) == (status, "1.0", code)
    assert result["diagnostics"] == diagnostics
    assert result["reason_code"] == ("scanner-exit-unexpected" if status == "scanner-error" else None)


@pytest.mark.parametrize("mode,reason", [
    ("missing", "dependency-missing"),
    ("wrong-version", "dependency-version-mismatch"),
    ("timeout", "scanner-timeout"),
    ("launch", "scanner-launch-failed"),
    ("oversize", "scanner-output-too-large"),
])
def test_scanner_faults_are_not_findings(mode, reason, monkeypatch):
    def version(name):
        if mode == "missing":
            raise quality.importlib.metadata.PackageNotFoundError(name)
        return "2.0" if mode == "wrong-version" else "1.0"

    def scan(cmd, *, stdout, **kwargs):
        assert mode not in {"missing", "wrong-version"}
        if mode == "timeout":
            raise subprocess.TimeoutExpired(cmd, 60)
        if mode == "launch":
            raise OSError("launch failed")
        stdout.write(b"x" * (quality.MAX_LOG_BYTES + 1))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(quality.importlib.metadata, "version", version)
    monkeypatch.setattr(quality.subprocess, "run", scan)
    result = quality.run_check("black", "1.0", ["one.py"])
    assert (result["status"], result["reason_code"], result["diagnostics"]) == ("scanner-error", reason, "")


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    package = tmp_path / quality.SCOPE
    package.mkdir(parents=True)
    (package / "tracked.py").write_text("x = 1\n", encoding="utf-8")
    (package / "untracked.py").write_text("y = 2\n", encoding="utf-8")
    config = tmp_path / quality.CONFIG
    config.parent.mkdir()
    config.write_text("[tool.black]\n", encoding="utf-8")
    (tmp_path / quality.REQUIREMENTS).write_text("black==1\nmypy==2\nvulture==3\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", str(package / "tracked.py"), quality.CONFIG, quality.REQUIREMENTS], check=True)
    subprocess.run(["git", "-c", "user.name=QA", "-c", "user.email=qa@example.invalid",
                    "-c", "core.hooksPath=/dev/null", "commit", "-qm", "fixture"], check=True)
    return tmp_path, subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


@pytest.mark.parametrize("status,exit_code", [("clean", 0), ("findings", 0), ("scanner-error", 1)])
def test_cli_binds_evidence_and_runs_all_scanners(checkout, monkeypatch, status, exit_code):
    root, head = checkout
    expected = f"{quality.SCOPE}/tracked.py"
    seen = []

    def scanner(tool, version, sources):
        assert sources == [expected]
        seen.append((tool, version))
        return {"status": status if tool == "black" else "clean"}

    monkeypatch.setattr(quality, "run_check", scanner)
    out = root / "out"
    monkeypatch.setattr("sys.argv", ["quality", "--head", head, "--run-id", "23", "--attempt", "2", "--output", str(out)])
    assert quality.main() == exit_code
    result = json.loads((out / "python-quality.json").read_bytes())
    assert seen == [("black", "1"), ("mypy", "2"), ("vulture", "3")]
    assert (result["head_sha"], result["run_id"], result["attempt"]) == (head, 23, 2)
    assert (result["sources"], result["status"]) == ([expected], status)


@pytest.mark.parametrize("mode,reason", [("wrong-head", "invalid-checkout"),
    ("removed-source", "scope-missing-or-invalid"), ("dirty-input", "checkout-inputs-changed"),
    ("bad-pins", "tool-config-invalid")])
def test_invalid_inputs_cannot_produce_a_clean_report(checkout, monkeypatch, mode, reason):
    root, head = checkout
    if mode == "removed-source":
        (root / quality.SCOPE / "tracked.py").unlink()
    if mode == "dirty-input":
        (root / quality.SCOPE / "tracked.py").write_text("changed = True", encoding="utf-8")
    if mode == "bad-pins":
        (root / quality.REQUIREMENTS).write_text("black>=1", encoding="utf-8")
        subprocess.run(["git", "-c", "user.name=QA", "-c", "user.email=qa@example.invalid",
                        "-c", "core.hooksPath=/dev/null", "commit", "-qam", "bad config"], check=True)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()

    def unexpected_scan(*args):
        pytest.fail("scanner ran before inputs were verified")

    monkeypatch.setattr(quality, "run_check", unexpected_scan)
    result = quality.build_report(HEAD if mode == "wrong-head" else head, 23, 2)
    assert (result["status"], result["reason_code"], result["tools"]) == ("scanner-error", reason, {})


def test_workflow_keeps_quality_advisory_and_publishes_receipt():
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    pilot = jobs["python-quality-advisory"]
    assert pilot["permissions"] == {"contents": "read"}
    assert pilot["steps"][0]["with"] == {"ref": "${{ env.QUALITY_HEAD }}", "persist-credentials": False}
    assert "github.event.pull_request.head.repo.full_name == github.repository" in pilot["if"]
    assert "github.event.pull_request.user.login == github.repository_owner" in pilot["if"]
    assert "github.actor == github.repository_owner" in pilot["if"]
    assert "python-quality-advisory" not in jobs["aggregate-gate"]["needs"]
    assert all("continue-on-error" not in step for step in pilot["steps"])
    upload = pilot["steps"][-1]
    assert upload["if"] == "${{ !cancelled() }}"
    assert upload["with"]["name"] == "python-quality-advisory-${{ github.run_attempt }}"
    assert upload["with"]["path"] == "${{ runner.temp }}/python-quality/python-quality.json"
    assert upload["with"]["if-no-files-found"] == "error"
