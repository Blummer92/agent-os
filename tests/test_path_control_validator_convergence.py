from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.agent_os_remote_validation.models import _bounded_text
from scripts.agent_os_remote_validation.models import _validate_path as validate_remote_path

EXECUTION_SERVICE_SRC = (
    Path(__file__).resolve().parents[1]
    / "08_Tooling"
    / "agent-os-execution-service"
    / "src"
)
if str(EXECUTION_SERVICE_SRC) not in sys.path:
    sys.path.insert(0, str(EXECUTION_SERVICE_SRC))

from agent_os_execution_service.models import _validate_path as validate_execution_path


@pytest.mark.parametrize("control", ["\t", "\n", "\r"])
def test_repository_path_validators_reject_ascii_whitespace_controls(control: str) -> None:
    candidate = f"a{control}b.py"

    with pytest.raises(ValueError, match="control character"):
        validate_remote_path(candidate)
    with pytest.raises(ValueError, match="control character"):
        validate_execution_path(candidate)


def test_bounded_text_still_allows_tab_lf_and_cr() -> None:
    assert _bounded_text("a\tb") is True
    assert _bounded_text("a\nb") is True
    assert _bounded_text("a\rb") is True
