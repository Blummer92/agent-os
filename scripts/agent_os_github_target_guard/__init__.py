from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class GitHubTargetKind(str, Enum):
    ISSUE = "issue"
    PULL_REQUEST = "pull-request"


@dataclass(frozen=True, slots=True)
class GitHubTargetEvidence:
    repository: str
    number: int
    kind: GitHubTargetKind
    canonical_url: str

    def __post_init__(self) -> None:
        if not isinstance(self.repository, str) or self.repository.count("/") != 1:
            raise ValueError("repository must use owner/name form")
        if type(self.number) is not int or self.number < 1:
            raise ValueError("number must be a positive integer")
        if not isinstance(self.kind, GitHubTargetKind):
            raise TypeError("kind must be GitHubTargetKind")
        expected = "pull" if self.kind is GitHubTargetKind.PULL_REQUEST else "issues"
        suffix = f"/{expected}/{self.number}"
        if not isinstance(self.canonical_url, str) or not self.canonical_url.endswith(suffix):
            raise ValueError("canonical_url does not match target kind and number")


@dataclass(frozen=True, slots=True)
class OperationCompatibility:
    compatible: bool
    reason: str
    authorization_granted: Literal[False] = field(default=False, init=False)
    mutation_performed: Literal[False] = field(default=False, init=False)


_OPERATION_KINDS = {
    "read-issue": frozenset({GitHubTargetKind.ISSUE}),
    "update-issue": frozenset({GitHubTargetKind.ISSUE}),
    "read-pull-request": frozenset({GitHubTargetKind.PULL_REQUEST}),
    "review-pull-request": frozenset({GitHubTargetKind.PULL_REQUEST}),
    "merge-pull-request": frozenset({GitHubTargetKind.PULL_REQUEST}),
}


def check_operation_compatibility(target: GitHubTargetEvidence, operation: str) -> OperationCompatibility:
    """Check resource-type compatibility only; never grant mutation authority."""
    if not isinstance(target, GitHubTargetEvidence):
        raise TypeError("target must be GitHubTargetEvidence")
    allowed = _OPERATION_KINDS.get(operation)
    if allowed is None:
        return OperationCompatibility(False, "operation-unknown")
    if target.kind not in allowed:
        return OperationCompatibility(False, "target-kind-incompatible")
    return OperationCompatibility(True, "target-kind-compatible")
