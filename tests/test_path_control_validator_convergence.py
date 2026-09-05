from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from scripts.agent_os_remote_validation.models import _validate_path as validate_remote_path


def _load_execution_models():
    path = (
        Path(__file__).resolve().parents[1]
        / "08_Tooling"
        / "agent-os-execution-service"
        / "src"
        / "agent_os_execution_service"
        / "models.py"
    )
    spec = importlib.util.spec_from_file_location("execution_service_models_for_path_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("control", ["\t", "\n", "\r"])
def test_repository_path_validators_reject_ascii_whitespace_controls(control: str) -> None:
    execution_models = _load_execution_models()
    candidate = f"a{control}b.py"

    with pytest.raises(ValueError, match="control character"):
        validate_remote_path(candidate)
    with pytest.raises(ValueError, match="control character"):
        execution_models._validate_path(candidate)


def test_bounded_text_still_allows_tab_lf_and_cr() -> None:
    from scripts.agent_os_remote_validation.models import _bounded_text

    assert _bounded_text("a\tb") is True
    assert _bounded_text("a\nb") is True
    assert _bounded_text("a\rb") is True
