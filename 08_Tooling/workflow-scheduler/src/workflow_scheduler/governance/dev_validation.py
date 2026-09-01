"""Non-authorizing developer-validation request contract.

DEVVAL5 (#1566) keeps caller input finite: repository, issue, agent branch, exact
SHA, and one main-owned profile identity. Command construction remains trusted
repository code in ``dev_validation_profiles``. Stable legacy validation ids are
accepted as aliases during migration.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from .dev_validation_profiles import (
    PROFILE_ALIASES,
    PROFILE_CATALOG,
    canonical_profile_id,
    get_profile,
    profile_argv,
    project_selector_requirements,
)

REPOSITORY = "Blummer92/agent-os"
# Compatibility constants retained for existing consumers/tests while the
# canonical executable source of truth is the profile catalog.
VALIDATION_ID = "remote-validation-suite"
MATERIALS_VALIDATION_ID = "instructional-materials-current-curriculum-suite"
SEMANTIC_OWNERSHIP_VALIDATION_ID = "semantic-ownership-advisory"
PPUX_VALIDATION_ID = "ppux-picture-perfect-ts-vitest"
PPUX_VALIDATION_PACKAGE_DIR = "08_Tooling/instructional-materials-coach/picture-perfect-coach"
VALIDATION_ARGV = profile_argv(VALIDATION_ID)
MATERIALS_VALIDATION_ARGV = profile_argv(MATERIALS_VALIDATION_ID)
SEMANTIC_OWNERSHIP_VALIDATION_ARGV = profile_argv(SEMANTIC_OWNERSHIP_VALIDATION_ID)
PPUX_VALIDATION_ARGV = profile_argv(PPUX_VALIDATION_ID)

# Compatibility registry exposes both canonical reusable profile ids and stable
# legacy aliases, but every value is derived from the one canonical catalog.
_registry: dict[str, tuple[str, ...]] = {
    profile_id: profile_argv(profile_id) for profile_id in PROFILE_CATALOG
}
_registry.update({alias: profile_argv(alias) for alias in PROFILE_ALIASES})
VALIDATION_REGISTRY = MappingProxyType(_registry)

_SHA40 = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_BRANCH = re.compile(r"^agent/[A-Za-z0-9._/-]{1,180}$", re.ASCII)


@dataclass(frozen=True, slots=True, kw_only=True)
class DevValidationRequest:
    repository: str
    issue_number: int
    branch: str
    source_sha: str
    validation_id: str
    profile_id: str
    request_id: str
    execution_authorized: Literal[False] = field(default=False, init=False)
    scheduler_invoked: Literal[False] = field(default=False, init=False)
    publication_invoked: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "repository": self.repository,
            "issue_number": self.issue_number,
            "branch": self.branch,
            "source_sha": self.source_sha,
            "validation_id": self.validation_id,
            "profile_id": self.profile_id,
            "request_id": self.request_id,
            "execution_authorized": False,
            "scheduler_invoked": False,
            "publication_invoked": False,
            "merge_authorized": False,
        }


def _valid_branch(branch: object) -> bool:
    return (
        type(branch) is str
        and _BRANCH.fullmatch(branch) is not None
        and branch not in {"agent/", "agent/main"}
        and ".." not in branch
        and "//" not in branch
        and not branch.endswith(("/", "."))
    )


def build_dev_validation_request(
    *, repository: object, issue_number: object, branch: object,
    source_sha: object, validation_id: object,
) -> DevValidationRequest:
    if repository != REPOSITORY:
        raise ValueError("non-canonical repository rejected")
    if type(issue_number) is not int or isinstance(issue_number, bool) or issue_number < 1:
        raise ValueError("invalid issue number")
    if not _valid_branch(branch):
        raise ValueError("invalid or protected branch")
    if type(source_sha) is not str or _SHA40.fullmatch(source_sha) is None:
        raise ValueError("invalid source SHA")
    profile_id = canonical_profile_id(validation_id)
    # Force strict catalog validation before binding request identity.
    get_profile(profile_id)
    material = json.dumps(
        [repository, issue_number, branch, source_sha, profile_id],
        separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")
    request_id = "dev-validation:" + hashlib.sha256(
        b"agent-os-dev-validation:v2\0" + material
    ).hexdigest()
    return DevValidationRequest(
        repository=repository,
        issue_number=issue_number,
        branch=branch,
        source_sha=source_sha,
        validation_id=validation_id,
        profile_id=profile_id,
        request_id=request_id,
    )


def validation_argv(request: object) -> tuple[str, ...]:
    if type(request) is not DevValidationRequest:
        raise TypeError("request must be exact DevValidationRequest")
    expected = build_dev_validation_request(
        repository=request.repository,
        issue_number=request.issue_number,
        branch=request.branch,
        source_sha=request.source_sha,
        validation_id=request.validation_id,
    )
    if expected.request_id != request.request_id or expected.profile_id != request.profile_id:
        raise ValueError("dev-validation request identity drift")
    return profile_argv(request.profile_id)


__all__ = [
    "DevValidationRequest",
    "MATERIALS_VALIDATION_ARGV",
    "MATERIALS_VALIDATION_ID",
    "PPUX_VALIDATION_ARGV",
    "PPUX_VALIDATION_ID",
    "PPUX_VALIDATION_PACKAGE_DIR",
    "PROFILE_CATALOG",
    "REPOSITORY",
    "SEMANTIC_OWNERSHIP_VALIDATION_ARGV",
    "SEMANTIC_OWNERSHIP_VALIDATION_ID",
    "VALIDATION_ARGV",
    "VALIDATION_ID",
    "VALIDATION_REGISTRY",
    "build_dev_validation_request",
    "project_selector_requirements",
    "validation_argv",
]
