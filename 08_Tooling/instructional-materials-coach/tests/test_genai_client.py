"""Adapter behaviour, failure paths, and tool safety for the Gemini client.

Requires the `genai` extra; skips cleanly without it so offline validation
still passes on a default install.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("google.genai", reason="requires the `genai` optional extra")
pytest.importorskip("pydantic", reason="requires the `genai` optional extra")

from instructional_materials_coach import genai_client  # noqa: E402
from instructional_materials_coach.genai_client import (  # noqa: E402
    DEFAULT_GEMINI_MODEL,
    GenerationContext,
    build_genai_client,
    generate,
    render_pedagogical_instructions,
)

# tests/ -> instructional-materials-coach/ -> 08_Tooling/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


class FakeModels:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.error:
            raise self.error
        return self.result


class FakeClient:
    def __init__(self, result=None, error=None):
        self.models = FakeModels(result=result, error=error)


# --- credentials -----------------------------------------------------------


def test_build_client_without_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        build_genai_client()


def test_build_client_error_does_not_leak_a_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError) as excinfo:
        build_genai_client()
    assert "AIza" not in str(excinfo.value)


# --- standards rendering fails closed --------------------------------------


def test_render_reads_the_real_standards_files():
    rendered = render_pedagogical_instructions(REPO_ROOT)
    assert "PEDAGOGICAL STANDARDS" in rendered
    assert "QUALITY RUBRIC" in rendered
    assert len(rendered) > 200


def test_render_fails_closed_when_standards_are_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="without its governing constraints"):
        render_pedagogical_instructions(tmp_path)


def test_render_names_the_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError) as excinfo:
        render_pedagogical_instructions(tmp_path)
    assert "student-language-standard.md" in str(excinfo.value)


# --- write gating ----------------------------------------------------------


def test_generate_refuses_write_authority():
    client = FakeClient(result="unused")
    with pytest.raises(PermissionError, match="ALLOW_WRITE"):
        generate(
            client,
            contents="x",
            system_instruction="y",
            allow_write=True,
        )
    assert client.models.calls == [], "must refuse before calling the model"


def test_generate_passes_system_instruction_into_config():
    client = FakeClient(result="ok")
    generate(client, contents="draft a lesson", system_instruction="RUBRIC")
    config = client.models.calls[0]["config"]
    assert config.system_instruction == "RUBRIC"


def test_generate_uses_the_centralized_model_constant():
    client = FakeClient(result="ok")
    generate(client, contents="x", system_instruction="y")
    assert client.models.calls[0]["model"] == DEFAULT_GEMINI_MODEL


def test_json_mime_type_only_set_when_a_schema_is_given():
    client = FakeClient(result="ok")
    generate(client, contents="x", system_instruction="y")
    assert client.models.calls[0]["config"].response_mime_type is None


# --- GenerationContext -----------------------------------------------------


def test_generation_context_runs_through_generate():
    client = FakeClient(result="ok")
    ctx = GenerationContext(contents="x", system_instruction="y", model="custom-model")
    assert ctx.run(client) == "ok"
    assert client.models.calls[0]["model"] == "custom-model"


def test_generation_context_is_frozen():
    ctx = GenerationContext(contents="x", system_instruction="y")
    with pytest.raises(Exception):
        ctx.model = "mutated"  # type: ignore[misc]


# --- failure paths ---------------------------------------------------------


def test_model_timeout_propagates_rather_than_returning_partial_content():
    client = FakeClient(error=TimeoutError("deadline exceeded"))
    with pytest.raises(TimeoutError):
        generate(client, contents="x", system_instruction="y")


def test_module_exposes_no_write_helper():
    """The adapter has one responsibility; it must not gain write verbs."""
    exported = dir(genai_client)
    for banned in ("upload", "write_file", "save", "batch_update", "create_file"):
        assert not any(banned in name.lower() for name in exported), banned
