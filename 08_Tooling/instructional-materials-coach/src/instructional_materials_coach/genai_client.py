"""Thin, injectable Gemini adapter for drafting lesson content.

Boundary rules come from
`00_Governance/architecture-decisions/adr-0004-model-invocation-boundary.md`:
output is always draft content, model invocation grants no write authority, and
the model can never execute anything.

Two controls enforce that last point, in order of strength:

1. **Declaration-only tools.** The SDK receives inert `FunctionDeclaration`
   objects, never a Python callable -- see `tools.py`. It cannot invoke what it
   does not possess.
2. **Automatic function calling disabled** on every request, as defense in
   depth.

This module has one responsibility -- talk to the model. It holds no business
logic, writes no files, and touches no Workspace API.
"""
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Any, Optional, Type

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from .tools import assert_no_callable_in_tools

# Single source for model selection. Do not scatter model names through the
# codebase. NOTE: gemini-2.5-flash has a documented shutdown date of
# 16 Oct 2026 -- migration is tracked with an owner and a 1 Sep 2026 decision
# deadline. Nothing here runs live, so the risk is latent, not active.
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_GEMINI_MODEL_SHUTDOWN = "2026-10-16"

# Upstream announced that a future major version removes automatic function
# calling from Models.generate_content. This design does not rely on that
# capability, so the bound guards an *untested* major version rather than a
# known incompatibility. Re-evaluate when a 3.x release exists to test.
MIN_SDK_MAJOR = 1
UNVALIDATED_SDK_MAJOR = 3

# Live execution is impossible unless this is explicitly set.
LIVE_MODE_ENV = "GENAI_LIVE"

STUDENT_LANGUAGE_STANDARD = "01_Shared_Standards/instructional-design/student-language-standard.md"
MATERIAL_QUALITY_RUBRIC = "01_Shared_Standards/instructional-design/material-quality-rubric.md"

# Candidate finish reasons meaning "no usable content", not "partial content".
_REFUSAL_FINISH_REASONS = frozenset(
    {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "RECITATION", "SPII", "MALFORMED_FUNCTION_CALL"}
)
_TRUNCATION_FINISH_REASONS = frozenset({"MAX_TOKENS"})

# Diagnostics must never carry prompts, credentials, or source content.
_MAX_DIAGNOSTIC_CHARS = 200


class GenerationResponseError(RuntimeError):
    """A model response could not be trusted. Never carries partial content."""


class LiveModeDisabledError(RuntimeError):
    """Raised when a real client is requested without the live-mode gate."""


class SdkCompatibilityError(RuntimeError):
    """Raised for an SDK major version Agent OS has not validated."""


def live_mode_enabled() -> bool:
    """True only when the operator explicitly opted in."""
    return os.getenv(LIVE_MODE_ENV, "").strip() == "1"


def check_sdk_compatibility(version: Optional[str] = None) -> str:
    """Reject SDK major versions Agent OS has not validated.

    Not a claim that 3.x is unsafe -- only that it is untested here. A
    pyproject pin does not protect an environment where the SDK was installed
    separately, so this check exists as well as the pin.
    """
    if version is None:
        from importlib.metadata import version as _version

        version = _version("google-genai")
    try:
        major = int(str(version).split(".", 1)[0])
    except (TypeError, ValueError) as exc:
        raise SdkCompatibilityError(f"Could not parse google-genai version {version!r}.") from exc
    if major < MIN_SDK_MAJOR or major >= UNVALIDATED_SDK_MAJOR:
        raise SdkCompatibilityError(
            f"google-genai {version} is outside the validated range "
            f"(>={MIN_SDK_MAJOR}.0,<{UNVALIDATED_SDK_MAJOR}.0). Agent OS has not yet "
            "validated this SDK major version; this is not a statement that it is unsafe."
        )
    return str(version)


def build_genai_client(api_key: Optional[str] = None) -> genai.Client:
    """Build a real, credential-backed client. Gated behind live mode.

    This is the only function in the package that constructs `genai.Client`.
    Offline tests inject fakes into `generate()` instead, which is deliberately
    ungated so that no test needs a credential.
    """
    if not live_mode_enabled():
        raise LiveModeDisabledError(
            f"Refusing to build a live Gemini client: set {LIVE_MODE_ENV}=1 to confirm a "
            "credential-backed, network-capable client is intended."
        )
    check_sdk_compatibility()
    resolved_key = api_key or os.getenv("GEMINI_API_KEY")
    if not resolved_key:
        raise ValueError("GEMINI_API_KEY must be provided or set in environment.")
    return genai.Client(api_key=resolved_key)


def render_pedagogical_instructions(repo_root: Optional[Path] = None) -> str:
    """Render pedagogical constraints directly from the source standards files.

    Enforces the render-don't-duplicate rule so the prompt cannot drift from
    the governed standards. Fails closed: a missing standards file raises
    rather than silently producing an unconstrained system instruction.
    """
    root = repo_root or Path(__file__).resolve().parents[4]

    student_lang_path = root / STUDENT_LANGUAGE_STANDARD
    quality_rubric_path = root / MATERIAL_QUALITY_RUBRIC

    missing = [str(p) for p in (student_lang_path, quality_rubric_path) if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Pedagogical standards could not be rendered, so generation would run "
            "without its governing constraints. Missing: " + ", ".join(missing)
        )

    student_lang = student_lang_path.read_text(encoding="utf-8")
    quality_rubric = quality_rubric_path.read_text(encoding="utf-8")

    return f"""--- PEDAGOGICAL STANDARDS ---
{student_lang}

--- QUALITY RUBRIC ---
{quality_rubric}
""".strip()


@dataclasses.dataclass(frozen=True)
class GenerationContext:
    """Bundles one generation request so future options do not churn signatures."""

    contents: Any
    system_instruction: str
    model: str = DEFAULT_GEMINI_MODEL
    response_schema: Optional[Type[BaseModel]] = None
    tools: Optional[list[types.Tool]] = None

    def run(self, client: genai.Client):
        return generate(
            client,
            model=self.model,
            contents=self.contents,
            system_instruction=self.system_instruction,
            response_schema=self.response_schema,
            tools=self.tools,
        )


def generate(
    client: genai.Client,
    *,
    model: str = DEFAULT_GEMINI_MODEL,
    contents: Any,
    system_instruction: str,
    response_schema: Optional[Type[BaseModel]] = None,
    tools: Optional[list[types.Tool]] = None,
    allow_write: bool = False,
):
    """Execute content generation via Gemini.

    `tools` accepts SDK `Tool` objects built by `ToolRegistry.sdk_tools()`
    only -- never raw callables. Automatic function calling is disabled on
    every request.
    """
    if allow_write:
        raise PermissionError(
            "Generation path cannot execute with write authority (ALLOW_WRITE must be False)."
        )

    assert_no_callable_in_tools(tools)

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_schema=response_schema,
        response_mime_type="application/json" if response_schema else None,
        tools=tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    return client.models.generate_content(model=model, contents=contents, config=config)


def _clip(text: Any) -> str:
    """Bounded diagnostic. Never echo a full prompt, credential, or payload."""
    rendered = str(text or "")
    if len(rendered) <= _MAX_DIAGNOSTIC_CHARS:
        return rendered
    return rendered[:_MAX_DIAGNOSTIC_CHARS] + "... [truncated]"


def _finish_reason(response: Any) -> str:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return ""
    reason = getattr(candidates[0], "finish_reason", None)
    return getattr(reason, "name", None) or str(reason or "")


def parse_response(response: Any, schema: Type[BaseModel]) -> BaseModel:
    """Turn a model response into a validated draft, or fail closed.

    Never returns partial content. Every failure path raises
    `GenerationResponseError` carrying bounded diagnostics only.
    """
    if response is None:
        raise GenerationResponseError("Model returned no response.")

    block_reason = getattr(getattr(response, "prompt_feedback", None), "block_reason", None)
    if block_reason:
        raise GenerationResponseError(
            f"Prompt was blocked: {_clip(getattr(block_reason, 'name', block_reason))}"
        )

    finish = _finish_reason(response)
    if finish in _REFUSAL_FINISH_REASONS:
        raise GenerationResponseError(f"Model refused or blocked the response: {finish}.")
    if finish in _TRUNCATION_FINISH_REASONS:
        raise GenerationResponseError(
            f"Model output was truncated ({finish}); partial content is not usable."
        )

    text = getattr(response, "text", None)
    parsed = getattr(response, "parsed", None)

    if parsed is None and not (text or "").strip():
        raise GenerationResponseError("Model returned empty output.")

    from_text: Optional[BaseModel] = None
    if (text or "").strip():
        try:
            from_text = schema.model_validate(json.loads(text))
        except json.JSONDecodeError as exc:
            if parsed is None:
                raise GenerationResponseError(
                    f"Model output was not valid JSON: {_clip(exc.msg)}"
                ) from exc
        except ValidationError as exc:
            if parsed is None:
                raise GenerationResponseError(
                    f"Model output did not match the required schema: {exc.error_count()} error(s)."
                ) from exc

    if parsed is None:
        if from_text is None:
            raise GenerationResponseError("Model output could not be validated against the schema.")
        return from_text

    if not isinstance(parsed, schema):
        raise GenerationResponseError(
            f"Model returned {type(parsed).__name__}, expected {schema.__name__}."
        )
    if from_text is not None and from_text != parsed:
        raise GenerationResponseError(
            "Model response text and parsed object disagree; refusing ambiguous content."
        )
    return parsed
