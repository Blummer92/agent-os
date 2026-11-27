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
        [
            "git",
            "-c",
            "user.name=QA",
            "-c",
            "user.email=qa@example.invalid",
            "commit",
            "-qam",
            "fixture",
        ],
        check=True,
    )


def head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def test_real_pinned_black_ignores_untracked_and_rejects_committed_formatting(checkout):
    (checkout.parent / "untracked.py").write_text("if not Python code\n")
    identity = head()
    code, receipt = black.check(identity, "42", "1")
    assert (code, receipt["status"], receipt["head_sha"], receipt["version"]) == (
        0,
        "clean",
        identity,
        black.VERSION,
    )
    assert receipt["sources"] == [checkout.as_posix()]
    checkout.write_text("VALUE=1\n")
    commit()
    code, receipt = black.check(head(), "42", "1")
    assert (code, receipt["status"], receipt["reason_code"]) == (
        1,
        "findings",
        "black-formatting-changes",
    )
    assert "would reformat" in receipt["diagnostics"]
    assert "@@ " in receipt["diagnostics"]
    assert "Fix: python -I -m black " in receipt["diagnostics"]
    assert receipt["files"] == [
        {
            "path": checkout.as_posix(),
            "would_reformat": True,
            "diff_lines": receipt["diff_lines"],
        }
    ]
    assert receipt["diff_lines"] > 0
    assert receipt["run_attempt"] == receipt["attempt"] == "1"
    assert checkout.read_text() == "VALUE=1\n"


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("head", "invalid-checkout"),
        ("dirty", "checkout-inputs-unverified"),
        ("missing", "dependency-missing"),
        ("version", "dependency-version-mismatch"),
        ("timeout", "scanner-timeout"),
        ("launch", "scanner-launch-failed"),
        ("output", "scanner-output-too-large"),
        ("crash", "scanner-exit-unexpected"),
        ("interrupt", "scanner-incomplete-scope"),
        ("signal", "scanner-incomplete-scope"),
        ("empty", "scanner-incomplete-scope"),
    ],
)
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
        assert (
            0 < kwargs["timeout"] <= black.TIMEOUT
            and "BLACK_CACHE_DIR" not in kwargs["env"]
        )
        if fault == "interrupt":
            raise KeyboardInterrupt
        if fault == "signal":
            return subprocess.CompletedProcess(command, -15)
        if fault == "timeout":
            raise subprocess.TimeoutExpired(command, 60)
        if fault == "launch":
            raise OSError("cannot spawn")
        kwargs["stdout"].write(
            b"x" * (black.MAX_OUTPUT + 1) if fault == "output" else b"private trace"
        )
        return subprocess.CompletedProcess(command, 0 if fault == "empty" else 1)

    monkeypatch.setattr(black.importlib.metadata, "version", version)
    monkeypatch.setenv("BLACK_CACHE_DIR", "/must-not-be-used")
    monkeypatch.setattr(black.subprocess, "run", scanner)
    code, receipt = black.check("b" * 40 if fault == "head" else actual, "42", "1")
    assert (code, receipt["reason_code"], receipt["diagnostics"]) == (2, reason, "")
    assert bool(observed_calls) == (
        fault
        in {"timeout", "launch", "output", "crash", "empty", "interrupt", "signal"}
    )


def test_multiple_files_exact_preview_and_truncation(checkout):
    peer = checkout.with_name("another file.py")
    peer.write_text("".join(f"VALUE_{i}={i}\n" for i in range(120)))
    subprocess.run(["git", "add", "--", str(peer)], check=True)
    commit()
    code, result = black.check(head(), "42", "1")
    assert code == 1, result
    assert result["sources"] == [peer.as_posix(), checkout.as_posix()]
    assert result["files"] == [
        {
            "path": peer.as_posix(),
            "would_reformat": True,
            "diff_lines": result["diff_lines"],
        }
    ]
    log = result["diagnostics"]
    assert log.count("would reformat ") == 1
    assert f"... [truncated {result['diff_lines'] - black.PREVIEW_LINES} lines]" in log
    assert f"Fix: python -I -m black '{peer.as_posix()}'" in log
    assert len(log.encode()) <= black.MAX_OUTPUT


def test_import_preserves_search_path():
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; saved=sys.path[:]; from scripts import agent_os_ci_black; assert saved==sys.path",
        ],
        cwd=Path(black.__file__).resolve().parents[1],
        check=True,
    )


def test_shift_left_uses_exact_black_and_does_not_write(checkout):
    import sys
    import yaml

    root = Path(black.__file__).resolve().parents[1]
    config = yaml.safe_load((root / ".pre-commit-config.yaml").read_text())
    hooks, formatter = config["repos"]
    assert hooks["repo"] == "https://github.com/pre-commit/pre-commit-hooks"
    assert (formatter["repo"], formatter["rev"]) == (
        "https://github.com/psf/black",
        black.VERSION,
    )
    (hook,) = formatter["hooks"]
    assert hook["id"] == "black"
    assert (
        hook["files"]
        == r"^08_Tooling/visual-asset-intake/src/visual_asset_intake/.*\.py$"
    )
    checkout.write_text("VALUE=1\n")
    p = subprocess.run(
        [sys.executable, "-I", "-m", "black", *hook["args"], str(checkout)],
        text=True,
        capture_output=True,
    )
    assert p.returncode == 1 and "would reformat" in p.stderr
    assert checkout.read_text() == "VALUE=1\n"
    assert "pre-commit" not in (root / "scripts/ci-local.sh").read_text()


@pytest.mark.parametrize(
    "output",
    [
        b"1 file would be left unchanged.\nwould reformat tracked.py\n",
        b"1 file would be left unchanged.\n1 file would be reformatted.\n",
    ],
)
def test_clean_never_accepts_conflicting_output(output):
    with pytest.raises(black.CheckError, match="scanner-incomplete-scope"):
        black.parse_output(0, output, "tracked.py")


@pytest.mark.parametrize(
    "field,value",
    [
        ("head", None),
        ("head", "A" * 40),
        ("run_id", 7),
        ("attempt", "0"),
        ("attempt", {}),
    ],
)
def test_invalid_identity_never_invokes_git(field, value, monkeypatch):
    def no_git(*args, **kwargs):
        pytest.fail("unverified identity reached Git")

    monkeypatch.setattr(black.subprocess, "check_output", no_git)
    args = {"head": "a" * 40, "run_id": "4", "attempt": "1"}
    args[field] = value
    code, result = black.check(**args)
    assert (code, result["reason_code"], result["files"], result["diagnostics"]) == (
        2,
        "invalid-checkout",
        [],
        "",
    )


@pytest.mark.parametrize("inventory", ["empty", "duplicate"])
def test_scope_inventory_fails_closed(checkout, monkeypatch, inventory):
    actual = head()
    run = subprocess.check_output

    def inventory_lookup(command, **kwargs):
        if command[1] != "ls-tree":
            return run(command, **kwargs)
        sources = [] if inventory == "empty" else [checkout.as_posix()] * 2
        return "\0".join([black.CONFIG, *sources, ""]).encode()

    monkeypatch.setattr(black.subprocess, "check_output", inventory_lookup)
    code, result = black.check(actual, "4", "1")
    assert (code, result["reason_code"], result["sources"]) == (
        2,
        "scope-missing-or-invalid",
        [],
    )


def assert_findings_shape(value):
    assert isinstance(value, dict) and value["status"] == "findings"
    assert (
        isinstance(value["diagnostics"], str)
        and "Fix: python -I -m black" in value["diagnostics"]
    )
    assert type(value["diff_lines"]) is int and value["diff_lines"] > 0
    assert isinstance(value["files"], list) and value["files"]
    assert all(
        type(item["diff_lines"]) is int and item["would_reformat"] is True
        for item in value["files"]
    )
    assert sum(item["diff_lines"] for item in value["files"]) == value["diff_lines"]


@pytest.mark.parametrize(
    "mutation", ["empty", "null", "wrong-type", "missing-field", "empty-files"]
)
def test_findings_assertions_reject_vacuous_receipts(mutation):
    expected = black.summarize_findings(
        {"tracked.py": ["@@ -1 +1 @@", "-X=1", "+X = 1"]}
    )
    assert_findings_shape(expected)
    candidates = {
        "empty": {},
        "null": None,
        "wrong-type": dict(expected, diff_lines="3"),
        "missing-field": {k: v for k, v in expected.items() if k != "files"},
        "empty-files": dict(expected, files=[]),
    }
    with pytest.raises((AssertionError, KeyError)):
        assert_findings_shape(candidates[mutation])


def test_preview_caps_unicode_bytes_without_mutating_caller_data(monkeypatch):
    monkeypatch.setattr(black, "MAX_OUTPUT", 420)
    sections = {
        "z.py": ["@@ -1 +1 @@", "+" + "é" * 170, "+tail"],
        "a.py": ["@@ -1 +1 @@", "+new"],
    }
    before = {name: lines[:] for name, lines in sections.items()}
    result = black.summarize_findings(sections)
    assert_findings_shape(result)
    assert sections == before
    assert len(result["diagnostics"].encode()) <= 420
    assert "... [truncated 2 lines]" in result["diagnostics"]
    assert [item["path"] for item in result["files"]] == ["a.py", "z.py"]
    assert result["diff_lines"] == 5


@pytest.mark.parametrize(
    "status,output",
    [
        (0, b"warning: scan incomplete\n1 file would be left unchanged.\n"),
        (0, b"Traceback (most recent call last):\n1 file would be left unchanged.\n"),
    ],
)
def test_clean_never_accepts_unrecognized_scanner_messages(status, output):
    with pytest.raises(black.CheckError, match="scanner-incomplete-scope"):
        black.parse_output(status, output, "tracked.py")
