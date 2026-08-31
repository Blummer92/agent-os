"""Fixed, non-authorizing developer-validation contract for #1432/#1454/#1495/#1515.

This module deliberately exposes no caller-supplied command or argv surface.
Each validation identity maps to one repository-owned argv tuple. The GCE
transport may carry only the validated repository/issue/branch/SHA/identity
bindings produced here.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

REPOSITORY = "Blummer92/agent-os"
VALIDATION_ID = "remote-validation-suite"
VALIDATION_ARGV = ("python", "-m", "pytest", "tests/agent_os_remote_validation")
MATERIALS_VALIDATION_ID = "instructional-materials-current-curriculum-suite"
MATERIALS_VALIDATION_ARGV = (
    "python",
    "-m",
    "pytest",
    "08_Tooling/instructional-materials-coach/tests/test_generation_context.py",
    "08_Tooling/instructional-materials-coach/tests/test_content_spec.py",
    "08_Tooling/instructional-materials-coach/tests/test_cli.py",
    "tests/test_current_curriculum_state.py",
    "tests/test_current_curriculum_evidence.py",
)
SEMANTIC_OWNERSHIP_VALIDATION_ID = "semantic-ownership-advisory"
SEMANTIC_OWNERSHIP_VALIDATION_ARGV = (
    "python",
    "07_Agent_Tests/run-semantic-ownership-advisory-validation.py",
)
PPUX_VALIDATION_ID = "ppux-picture-perfect-ts-vitest"
# Vitest resolves its config and test paths from the package root, so the fixed
# package directory is part of the identity rather than something a caller picks.
PPUX_VALIDATION_PACKAGE_DIR = "08_Tooling/instructional-materials-coach/picture-perfect-coach"
PPUX_VALIDATION_ARGV = (
    "node",
    "vitest",
    "run",
    "src/overlayIntegrity.test.ts",
    "src/exactComposite.test.ts",
    "src/exactCompositeSuite.test.ts",
    "src/framePlan.test.ts",
    "src/executorContract.test.ts",
    "src/provenanceValidator.test.ts",
)
VALIDATION_REGISTRY = MappingProxyType(
    {
        VALIDATION_ID: VALIDATION_ARGV,
        MATERIALS_VALIDATION_ID: MATERIALS_VALIDATION_ARGV,
        SEMANTIC_OWNERSHIP_VALIDATION_ID: SEMANTIC_OWNERSHIP_VALIDATION_ARGV,
        PPUX_VALIDATION_ID: PPUX_VALIDATION_ARGV,
    }
)
_SHA40 = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_BRANCH = re.compile(r"^agent/[A-Za-z0-9._/-]{1,180}$", re.ASCII)


@dataclass(frozen=True, slots=True, kw_only=True)
class DevValidationRequest:
    repository: str
    issue_number: int
    branch: str
    source_sha: str
    validation_id: str
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
    if type(validation_id) is not str or validation_id not in VALIDATION_REGISTRY:
        raise ValueError("unknown validation identity")
    material = json.dumps(
        [repository, issue_number, branch, source_sha, validation_id],
        separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")
    request_id = "dev-validation:" + hashlib.sha256(
        b"agent-os-dev-validation:v1\0" + material
    ).hexdigest()
    return DevValidationRequest(
        repository=repository,
        issue_number=issue_number,
        branch=branch,
        source_sha=source_sha,
        validation_id=validation_id,
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
    if expected.request_id != request.request_id:
        raise ValueError("dev-validation request identity drift")
    return VALIDATION_REGISTRY[request.validation_id]
