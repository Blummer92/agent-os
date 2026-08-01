"""Thin, injectable Gemini adapter for drafting lesson content.

Boundary rules come from
`00_Governance/architecture-decisions/adr-0004-model-invocation-boundary.md`:
output is always draft content, model invocation grants no write authority,
and every tool handed to the model must be read-only.

This module has one responsibility -- talk to the model. It holds no business
logic, writes no files, and touches no Workspace API.
"""
from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Any, Callable, Optional, Type

from google import genai
from google.genai import types
from pydantic import BaseModel

# Single source for model selection. Do not scatter model names through the
# codebase; change it here and verify against current Google documentation.
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

# Rendered from these standards files, never retyped into a prompt string.
STUDENT_LANGUAGE_STANDARD = "01_Shared_Standards/instructional-design/student-language-standard.md"
MATERIAL_QUALITY_RUBRIC = "01_Shared_Standards/instructional-design/material-quality-rubric.md"


def build_genai_client(api_key: Optional[str] = None) -> genai.Client:
    """Builds and returns an injectable, mockable Google GenAI client."""
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
    """Bundles one generation request so future options do not churn signatures.

    Additive convenience over `generate()`; it carries no authority of its own.
    """

    contents: Any
    system_instruction: str
    model: str = DEFAULT_GEMINI_MODEL
    response_schema: Optional[Type[BaseModel]] = None
    tools: Optional[list[Callable]] = None

    def run(self, client: genai.Client):
        """Execute this context against an injected client."""
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
    tools: Optional[list[Callable]] = None,
    allow_write: bool = False,
):
    """Execute content generation via Gemini.

    Refuses to run if write authority is asserted: per ADR-0004 the generation
    path carries no write permissions, and every registered tool must be
    read-only because automatic function calling executes tools.
    """
    if allow_write:
        raise PermissionError(
            "Generation path cannot execute with write authority (ALLOW_WRITE must be False)."
        )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_schema=response_schema,
        response_mime_type="application/json" if response_schema else None,
        tools=tools,
    )
    return client.models.generate_content(model=model, contents=contents, config=config)
