"""The strict formatter trusts only committed source and a working pinned scanner."""

import importlib.metadata
import subprocess
from pathlib import Path

import pytest

from scripts import agent_os_ci_black as black


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    folder = Path(black.SCOPE)
    folder.mkdir(parents=True)
    file = folder / "tracked.py"
    file.write_text("VALUE = 1\n")
    Path(black.CONFIG).write_text('[tool.black]\ntarget-version = ["py311"]\n')
    subprocess.run(["git", "add", "."], check=True)
    commit()
    return file


def commit():
    subprocess.run(
        ["git", "-c", "user.name=QA", "-c", "user.email=qa@example.invalid", "commit", "-qam", "fixture"],
        check=True,
    )


def head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def test_real_pinned_black_ignores_untracked_and_rejects_committed_formatting(checkout):
    (checkout.parent / "untracked.py").write_text("if not Python code\n")
    identity = head()
    code, receipt = black.check(identity, "42", "1")
    assert (code, receipt["status"], receipt["head_sha"], receipt["version"]) == (0, "clean", identity, black.VERSION)
    assert receipt["sources"] == [checkout.as_posix()]
    checkout.write_text("VALUE=1\n")
    commit()
    code, receipt = black.check(head(), "42", "1")
    assert (code, receipt["status"], receipt["reason_code"]) == (1, "findings", "black-formatting-changes")
    assert "would reformat" in receipt["diagnostics"]
    assert checkout.read_text() == "VALUE=1\n"


@pytest.mark.parametrize("fault,reason", [
    ("head", "invalid-checkout"),
    ("dirty", "checkout-inputs-unverified"),
    ("missing", "dependency-missing"),
    ("version", "dependency-version-mismatch"),
    ("timeout", "scanner-timeout"),
    ("launch", "scanner-launch-failed"),
    ("output", "scanner-output-too-large"),
    ("crash", "scanner-exit-unexpected"),
    ("empty", "scanner-incomplete-scope"),
])
def test_fails_closed_without_leaking_diagnostics(checkout, monkeypatch, fault, reason):
    actual = head()
    if fault == "dirty":
        checkout.write_text("VALUE=2\n")
    observed_calls = []

    def version(_):
        if fault == "missing":
            raise importlib.metadata.PackageNotFoundError("black")
        return "99" if fault == "version" else black.VERSION

    run = subprocess.run

    def scanner(command, **kwargs):
        if command[0] == "git":
            return run(command, **kwargs)
        observed_calls.append(command)
        assert command[1:4] == ["-I", "-m", "black"]
        assert kwargs["timeout"] == 60 and "BLACK_CACHE_DIR" not in kwargs["env"]
        if fault == "timeout":
            raise subprocess.TimeoutExpired(command, 60)
        if fault == "launch":
            raise OSError("cannot spawn")
        kwargs["stdout"].write(b"x" * (black.MAX_OUTPUT + 1) if fault == "output" else b"private trace")
        return subprocess.CompletedProcess(command, 0 if fault == "empty" else 1)

    monkeypatch.setattr(black.importlib.metadata, "version", version)
    monkeypatch.setenv("BLACK_CACHE_DIR", "/must-not-be-used")
    monkeypatch.setattr(black.subprocess, "run", scanner)
    code, receipt = black.check("b" * 40 if fault == "head" else actual, "42", "1")
    assert (code, receipt["reason_code"], receipt["diagnostics"]) == (2, reason, "")
    assert bool(observed_calls) == (fault in {"timeout", "launch", "output", "crash", "empty"})
