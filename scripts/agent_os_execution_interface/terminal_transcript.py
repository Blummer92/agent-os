"""Bounded terminal transcript normalization for execution-interface handoffs.

This module interprets pasted terminal text only. It performs no shell execution,
repository mutation, routing, authorization, or external writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

_PROMPT_RE = re.compile(
    r"^(?P<prompt>(?:[^\s@]+@[^:]+:[^$#]*|[A-Za-z0-9_.-]+:[^$#]*)[$#])\s*(?P<command>.*)$"
)
_BRANCH_RE = re.compile(r"\((?P<branch>[A-Za-z0-9._/-]+)\)\s*[$#]")
_PYTHON_RE = re.compile(r"\bPython\s+(?P<version>\d+\.\d+(?:\.\d+)?)\b")
_ERROR_PREFIXES = (
    "fatal:",
    "error:",
    "traceback (most recent call last):",
    "modulenotfounderror:",
    "importerror:",
    "syntaxerror:",
    "-bash:",
    "bash:",
)
_BANNER_PREFIXES = (
    "Welcome to Cloud Shell!",
    "To set your Cloud Platform project",
    "You can view your projects by running",
)


@dataclass(frozen=True)
class TerminalTranscript:
    commands: tuple[str, ...]
    output_lines: tuple[str, ...]
    newest_actionable_failure: str | None
    prompt: str | None
    current_directory: str | None
    branch: str | None
    cloud_project: str | None
    python_version: str | None


def _iter_nonempty_lines(text: str) -> Iterable[str]:
    for raw in text.splitlines():
        line = raw.strip()
        if line:
            yield line


def _parse_prompt(prompt: str) -> tuple[str | None, str | None]:
    directory = None
    branch = None
    if ":" in prompt:
        tail = prompt.split(":", 1)[1]
        tail = tail.rsplit("$", 1)[0].rsplit("#", 1)[0].strip()
        branch_match = re.search(r"\s+\(([^)]+)\)\s*$", tail)
        if branch_match:
            branch = branch_match.group(1)
            tail = tail[: branch_match.start()].strip()
        if tail:
            directory = tail
    return directory, branch


def _latest_failure(lines: list[str]) -> str | None:
    for index in range(len(lines) - 1, -1, -1):
        lower = lines[index].lower()
        if lower.startswith(_ERROR_PREFIXES) or "no module named" in lower:
            if lower.startswith("traceback"):
                return "\n".join(lines[index:])
            return lines[index]
    return None


def parse_terminal_transcript(text: str) -> TerminalTranscript:
    """Parse a pasted terminal transcript without executing or mutating anything."""
    if not isinstance(text, str):
        raise TypeError("terminal transcript must be a string")

    commands: list[str] = []
    output: list[str] = []
    latest_prompt: str | None = None
    current_directory: str | None = None
    branch: str | None = None
    cloud_project: str | None = None
    python_version: str | None = None

    for line in _iter_nonempty_lines(text):
        if line.startswith(_BANNER_PREFIXES):
            continue

        prompt_match = _PROMPT_RE.match(line)
        if prompt_match:
            latest_prompt = prompt_match.group("prompt")
            parsed_directory, parsed_branch = _parse_prompt(latest_prompt)
            current_directory = parsed_directory or current_directory
            branch = parsed_branch or branch
            command = prompt_match.group("command").strip()
            if command:
                commands.append(command)
            continue

        if line.startswith("Updated property [core/project]."):
            output.append(line)
            continue

        project_match = re.search(r"gcloud config set project\s+([A-Za-z0-9._:-]+)", line)
        if project_match:
            cloud_project = project_match.group(1)

        python_match = _PYTHON_RE.search(line)
        if python_match:
            python_version = python_match.group("version")

        output.append(line)

    if latest_prompt:
        prompt_project = re.search(r"\(([^()]+)\)\s*[$#]", latest_prompt)
        if prompt_project and not branch:
            cloud_project = cloud_project or prompt_project.group(1)

    return TerminalTranscript(
        commands=tuple(commands),
        output_lines=tuple(output),
        newest_actionable_failure=_latest_failure(output),
        prompt=latest_prompt,
        current_directory=current_directory,
        branch=branch,
        cloud_project=cloud_project,
        python_version=python_version,
    )
