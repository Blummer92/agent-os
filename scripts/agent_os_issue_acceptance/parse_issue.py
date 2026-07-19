from __future__ import annotations

import re
from typing import Any

import yaml

from .models import IssueMetadata

_METADATA_KEY = "agent_os_issue_acceptance"
_FENCED_YAML_RE = re.compile(r"```(?:yaml|yml)\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return [str(value).strip()]


def parse_issue_metadata(issue_body: str) -> IssueMetadata:
    """Parse the IA1 machine-checkable metadata block from an issue body."""
    for match in _FENCED_YAML_RE.finditer(issue_body or ""):
        try:
            parsed = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(parsed, dict) or _METADATA_KEY not in parsed:
            continue
        block = parsed.get(_METADATA_KEY) or {}
        if not isinstance(block, dict):
            return IssueMetadata(present=True, raw={})
        return IssueMetadata(
            present=True,
            owner_agent=block.get("owner_agent"),
            source_of_truth=block.get("source_of_truth"),
            external_writes=block.get("external_writes"),
            required_files=_as_list(block.get("required_files")),
            forbidden_paths=_as_list(block.get("forbidden_paths")),
            required_tests=_as_list(block.get("required_tests")),
            required_docs=_as_list(block.get("required_docs")),
            banned_patterns=_as_list(block.get("banned_patterns")),
            manual_review=_as_list(block.get("manual_review")),
            raw=block,
            documentation_impact=block.get("documentation_impact"),
            documentation_expected_change=block.get("documentation_expected_change"),
            documentation_exemption_reason=block.get("documentation_exemption_reason"),
        )
    return IssueMetadata.empty()
