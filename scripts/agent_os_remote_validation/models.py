from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VALIDATION_PLAN_SCHEMA_NAME = "agent-os-validation-plan"
VALIDATION_PLAN_SCHEMA_VERSION = "1.0"
MAX_PLAN_STRING_LENGTH = 4096
MAX_PLAN_COMMANDS = 64
MAX_PLAN_REASON_CODES = 32
MAX_PLAN_SERIALIZED_BYTES = 262_144

ValidationProfile = Literal["static", "focused", "aggregate", "manual-review"]


@dataclass(frozen=True)
class SelectionInput:
    repository: str
    pull_request: int
    base_sha: str
    head_sha: str
    changed_files: tuple[str, ...]
    selector_version: str = "1.0.0"


@dataclass(frozen=True)
class ValidationPlan:
    selector_version: str
    repository: str
    pull_request: int
    base_sha: str
    head_sha: str
    profile: ValidationProfile
    commands: tuple[str, ...]
    command_set_digest: str
    reason_codes: tuple[str, ...]
    remote_build_required: bool
    execution_authorized: bool = False
    side_effects_performed: bool = False
