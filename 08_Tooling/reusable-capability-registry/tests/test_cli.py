import json
import os
import subprocess
import sys
from pathlib import Path

from reusable_capability_registry import RegistryReader, discover_capabilities
from reusable_capability_registry.cli import main
from reusable_capability_registry.serialization import serialize_discovery_results

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parents[1]
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")}


def run_module(*args):
    return subprocess.run(
        [sys.executable, "-m", "reusable_capability_registry", *args],
        cwd=ROOT,
        env=ENV,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_json_success_no_match_and_manual_review(capsys):
    assert main(["--registry", str(FIXTURES / "valid_registry.yml"), "--id", "alpha-reader", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["results"][0]["capability"]["capability_id"] == "alpha-reader"
    assert main(["--registry", str(FIXTURES / "valid_registry.yml"), "--id", "missing"]) == 1
    capsys.readouterr()
    assert main(["--registry", str(FIXTURES / "valid_registry.yml"), "--keyword", "shared"]) == 2
    assert "multiple-equally-plausible-candidates" in capsys.readouterr().out


def test_cli_malformed_registry_returns_2_without_traceback(capsys):
    assert main(["--registry", str(FIXTURES / "malformed_registry.yml"), "--id", "alpha"]) == 2
    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert "Traceback" not in captured.err


def test_cli_output_is_deterministic(capsys):
    args = ["--registry", str(FIXTURES / "valid_registry.yml"), "--id", "alpha-reader", "--format", "json"]
    assert main(args) == 0
    first = capsys.readouterr().out
    assert main(args) == 0
    assert first == capsys.readouterr().out


def test_module_json_equals_canonical_serializer():
    args = ["--registry", str(FIXTURES / "valid_registry.yml"), "--id", "alpha-reader", "--format", "json"]
    completed = run_module(*args)
    expected = serialize_discovery_results(
        discover_capabilities(RegistryReader(FIXTURES / "valid_registry.yml"), capability_id="alpha-reader")
    )
    assert completed.returncode == 0
    assert completed.stdout == expected
    assert completed.stderr == ""


def test_module_exit_codes_and_no_traceback():
    success = run_module("--registry", str(FIXTURES / "valid_registry.yml"), "--id", "alpha-reader")
    missing = run_module("--registry", str(FIXTURES / "valid_registry.yml"), "--id", "missing")
    review = run_module("--registry", str(FIXTURES / "valid_registry.yml"), "--keyword", "shared")
    malformed = run_module("--registry", str(FIXTURES / "malformed_registry.yml"), "--id", "alpha")
    assert (success.returncode, missing.returncode, review.returncode, malformed.returncode) == (0, 1, 2, 2)
    assert "informational" in success.stdout.lower()
    assert "Traceback" not in success.stderr + missing.stderr + review.stderr + malformed.stderr


def test_installed_console_command():
    command = os.environ.get("AGENT_OS_CAPABILITIES_BIN", "agent-os-capabilities")
    completed = subprocess.run(
        [command, "--registry", str(FIXTURES / "valid_registry.yml"), "--id", "alpha-reader", "--format", "json"],
        cwd=ROOT,
        env=ENV,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stderr == ""
    assert completed.stdout == serialize_discovery_results(
        discover_capabilities(RegistryReader(FIXTURES / "valid_registry.yml"), capability_id="alpha-reader")
    )
