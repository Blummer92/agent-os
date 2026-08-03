"""Pure execution-authorization evidence contract.

This module is intentionally independent from Workflow Scheduler and runtime
composition. It defines only immutable caller-supplied authorization evidence
and validates that evidence with the canonical Execution Service timestamp
parser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .models import parse_canonical_utc


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionAuthorizationEvidence:
    """Explicit, caller-supplied authorization binding one plan to one SHA."""

    authorization_id: str
    request_fingerprint: str
    command_plan_id: str
    repository: str
    expected_sha: str
    authorized_at: str
    expires_at: str
    execution_authorized: bool
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        for name in (
            "authorization_id",
            "request_fingerprint",
            "command_plan_id",
            "repository",
            "expected_sha",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise TypeError(f"{name} must be a non-empty exact string")
        if type(self.execution_authorized) is not bool:
            raise TypeError("execution_authorized must be an exact boolean")
        parse_canonical_utc(self.authorized_at)
        parse_canonical_utc(self.expires_at)
