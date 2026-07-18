import json
from pathlib import Path

from reusable_capability_registry.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_cli_json_success_no_match_and_manual_review(capsys):
    assert main(["--registry", str(FIXTURES / "valid_registry.yml"), "--id", "alpha-reader", "--format", "json"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["results"][0]["capability"]["capability_id"] == "alpha-reader"

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
    second = capsys.readouterr().out
    assert first == second
