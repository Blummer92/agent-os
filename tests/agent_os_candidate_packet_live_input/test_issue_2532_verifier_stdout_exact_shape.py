import pytest

from scripts.agent_os_candidate_packet_live_input.repository_observation import (
    VerifierStdoutError,
    parse_verifier_stdout,
)


VALID = "\n".join((
    "HEAD_REF=agent/2532-parser",
    f"HEAD_SHA={'a' * 40}",
    "BASE_REF=origin/main",
    f"BASE_SHA={'b' * 40}",
    "CHANGED_FILES_BEGIN",
    "path/to/file.py",
    "CHANGED_FILES_END",
))


def test_exact_contract_remains_accepted() -> None:
    assert parse_verifier_stdout(VALID).head_ref == "agent/2532-parser"


def test_trailing_undeclared_output_fails_closed() -> None:
    with pytest.raises(VerifierStdoutError, match="trailing undeclared output"):
        parse_verifier_stdout(VALID + "\nUNDECLARED=1\n")


def test_duplicate_end_marker_fails_closed() -> None:
    with pytest.raises(VerifierStdoutError, match="duplicate CHANGED_FILES_END"):
        parse_verifier_stdout(VALID + "\nCHANGED_FILES_END\n")
