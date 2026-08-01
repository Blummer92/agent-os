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
    LIVE_MODE_ENV,
    GenerationContext,
    GenerationResponseError,
    LiveModeDisabledError,
    SdkCompatibilityError,
    build_genai_client,
    check_sdk_compatibility,
    generate,
    live_mode_enabled,
    parse_response,
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


def test_live_gate_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv(LIVE_MODE_ENV, raising=False)
    assert live_mode_enabled() is False


def test_build_client_refuses_without_live_gate(monkeypatch):
    monkeypatch.delenv(LIVE_MODE_ENV, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "irrelevant-because-gate-is-off")
    with pytest.raises(LiveModeDisabledError, match=LIVE_MODE_ENV):
        build_genai_client()


def test_build_client_without_key_raises(monkeypatch):
    monkeypatch.setenv(LIVE_MODE_ENV, "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        build_genai_client()


def test_build_client_error_does_not_leak_a_key(monkeypatch):
    monkeypatch.setenv(LIVE_MODE_ENV, "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError) as excinfo:
        build_genai_client()
    assert "AIza" not in str(excinfo.value)


def test_no_other_module_constructs_a_real_client():
    """build_genai_client() is the only path to a credential-backed client."""
    src = Path(genai_client.__file__).resolve().parent
    offenders = []
    for path in sorted(src.rglob("*.py")):
        if path.name == "genai_client.py":
            continue
        if "genai.Client(" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert not offenders, f"these bypass the live gate: {offenders}"


# --- SDK compatibility -----------------------------------------------------


def test_sdk_compatibility_accepts_validated_majors():
    assert check_sdk_compatibility("1.9.0") == "1.9.0"
    assert check_sdk_compatibility("2.16.0") == "2.16.0"


def test_sdk_compatibility_rejects_unvalidated_major():
    with pytest.raises(SdkCompatibilityError, match="not yet"):
        check_sdk_compatibility("3.0.0")


def test_sdk_compatibility_error_does_not_call_3x_unsafe():
    """The message must describe untested, not unsafe."""
    with pytest.raises(SdkCompatibilityError) as excinfo:
        check_sdk_compatibility("3.1.0")
    message = str(excinfo.value)
    assert "not a statement that it is unsafe" in message
    assert "has not yet validated" in message


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


def test_afc_is_disabled_on_every_call():
    """Defense-in-depth behind declaration-only tools; must never regress."""
    client = FakeClient(result="ok")
    generate(client, contents="x", system_instruction="y")
    afc = client.models.calls[0]["config"].automatic_function_calling
    assert afc is not None and afc.disable is True


# --- parse_response: eight typed cases, all fail closed --------------------

from pydantic import BaseModel  # noqa: E402


class Tiny(BaseModel):
    value: str


def _response(*, text=None, parsed=None, finish=None, block_reason=None):
    from google.genai import types as t

    candidates = None
    if finish is not None:
        candidates = [t.Candidate(finish_reason=finish)]
    resp = FakeResponse(text=text, parsed=parsed, candidates=candidates)
    if block_reason is not None:
        resp.prompt_feedback = type("PF", (), {"block_reason": block_reason})()
    return resp


class FakeResponse:
    def __init__(self, text=None, parsed=None, candidates=None):
        self.text = text
        self.parsed = parsed
        self.candidates = candidates
        self.prompt_feedback = None


def test_parse_response_rejects_missing_response():
    with pytest.raises(GenerationResponseError, match="no response"):
        parse_response(None, Tiny)


def test_parse_response_rejects_empty_output():
    with pytest.raises(GenerationResponseError, match="empty output"):
        parse_response(_response(text="   "), Tiny)


def test_parse_response_rejects_invalid_json():
    with pytest.raises(GenerationResponseError, match="not valid JSON"):
        parse_response(_response(text="{not json"), Tiny)


def test_parse_response_rejects_truncated_output():
    with pytest.raises(GenerationResponseError, match="truncated"):
        parse_response(_response(text='{"value":"a"', finish="MAX_TOKENS"), Tiny)


def test_parse_response_rejects_schema_validation_failure():
    with pytest.raises(GenerationResponseError, match="did not match the required schema"):
        parse_response(_response(text='{"wrong":"field"}'), Tiny)


def test_parse_response_falls_back_to_text_when_parsed_missing():
    got = parse_response(_response(text='{"value":"a"}'), Tiny)
    assert got == Tiny(value="a")


def test_parse_response_rejects_parsed_text_disagreement():
    with pytest.raises(GenerationResponseError, match="disagree"):
        parse_response(_response(text='{"value":"a"}', parsed=Tiny(value="b")), Tiny)


def test_parse_response_rejects_refusal_and_blocked():
    for reason in ("SAFETY", "PROHIBITED_CONTENT", "RECITATION"):
        with pytest.raises(GenerationResponseError, match="refused or blocked"):
            parse_response(_response(text='{"value":"a"}', finish=reason), Tiny)
    with pytest.raises(GenerationResponseError, match="blocked"):
        parse_response(_response(text='{"value":"a"}', block_reason="OTHER"), Tiny)


def test_parse_response_returns_no_partial_content_on_any_failure():
    bad = [
        None,
        _response(text="   "),
        _response(text="{not json"),
        _response(text='{"value":"a"', finish="MAX_TOKENS"),
        _response(text='{"wrong":"f"}'),
        _response(text='{"value":"a"}', finish="SAFETY"),
    ]
    for response in bad:
        with pytest.raises(GenerationResponseError):
            parse_response(response, Tiny)


def test_error_diagnostics_are_bounded():
    """Errors must not echo prompts, credentials, or full payloads."""
    huge = '{"value": "' + ("SENSITIVE" * 500) + None.__class__.__name__
    with pytest.raises(GenerationResponseError) as excinfo:
        parse_response(_response(text=huge), Tiny)
    message = str(excinfo.value)
    assert len(message) < 400, "diagnostic must stay bounded"
    assert message.count("SENSITIVE") <= 1
