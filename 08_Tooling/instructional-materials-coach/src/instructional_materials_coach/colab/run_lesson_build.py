"""Colab entry point: draft lesson content with Gemini, write it locally.

Produces a draft YAML spec only. Per ADR-0004 the generation path carries no
write authority, so this never touches Drive, Slides, Docs, Notion, or GitHub.
Rendering the draft into Workspace stays with the existing `imc-build` CLI and
its `ALLOW_WRITE` gate, run by a human after review.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from ..content_schema import LessonDraft
from ..genai_client import (
    DEFAULT_GEMINI_MODEL,
    GenerationContext,
    build_genai_client,
    render_pedagogical_instructions,
)
from .bootstrap import GEMINI_API_KEY, get_secret, resolve_repo_root

DRAFT_BANNER = "# DRAFT -- model-generated, requires human review before use.\n"


def draft_lesson(
    prompt: str,
    *,
    api_key: Optional[str] = None,
    repo_root: Optional[str] = None,
    model: str = DEFAULT_GEMINI_MODEL,
    tools: Optional[list[Callable]] = None,
    client: Any = None,
) -> LessonDraft:
    """Generate one draft lesson. `client` is injectable for testing."""
    root = resolve_repo_root(repo_root)
    system_instruction = render_pedagogical_instructions(root)

    active_client = client or build_genai_client(api_key or get_secret(GEMINI_API_KEY))

    response = GenerationContext(
        contents=prompt,
        system_instruction=system_instruction,
        model=model,
        response_schema=LessonDraft,
        tools=tools,
    ).run(active_client)

    parsed = getattr(response, "parsed", None)
    if not isinstance(parsed, LessonDraft):
        raise ValueError(
            "Model response did not parse into LessonDraft. Treat as a failed draft, "
            "not as partial content."
        )
    return parsed


def write_draft(draft: LessonDraft, out_path: str | Path) -> Path:
    """Write the draft to a local YAML spec the existing CLI can consume."""
    path = Path(out_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(draft.to_dict(), sort_keys=False, allow_unicode=True)
    path.write_text(DRAFT_BANNER + body, encoding="utf-8")
    return path


def main(
    prompt: str,
    *,
    out_path: str | Path = "reports/drafts/lesson-draft.yaml",
    api_key: Optional[str] = None,
    repo_root: Optional[str] = None,
    model: str = DEFAULT_GEMINI_MODEL,
    client: Any = None,
) -> Path:
    """Draft a lesson and write it locally. Returns the written path."""
    draft = draft_lesson(
        prompt, api_key=api_key, repo_root=repo_root, model=model, client=client
    )
    path = write_draft(draft, out_path)
    print(f"Draft written: {path}")
    print("Review it, then render with: imc-build build --content " f"{path} ...")
    return path
