"""Disabled-by-default orchestration wrapper for Visual Asset Sync mutations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence

from .models import ReconciliationEntry
from .mutation_adapter import (
    MutationAction,
    MutationAuthorization,
    MutationOutcome,
    NotionMutationClient,
    execute_mutation_actions,
    validate_plan_authorization,
)


class OrchestrationError(Exception):
    """Raised when the orchestration gate cannot proceed safely."""


@dataclass(frozen=True)
class OrchestrationConfig:
    schedule_enabled: bool = False
    mutation_enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.schedule_enabled) is not bool or type(self.mutation_enabled) is not bool:
            raise OrchestrationError("orchestration flags must be exact booleans")


@dataclass(frozen=True)
class RunReceipt:
    status: str
    outcomes: tuple[MutationOutcome, ...] = ()


def run_once(
    *,
    config: OrchestrationConfig,
    entries: Sequence[ReconciliationEntry],
    actions: Sequence[MutationAction],
    authorization: MutationAuthorization,
    kill_switch_active: Callable[[], bool],
    acquire_lease: Callable[[], bool],
    release_lease: Callable[[], None],
    client: NotionMutationClient | None = None,
    now: datetime | None = None,
) -> RunReceipt:
    """Run one bounded orchestration pass; disabled configuration is inert."""
    if not config.schedule_enabled or not config.mutation_enabled:
        return RunReceipt(status="disabled")
    if kill_switch_active():
        raise OrchestrationError("kill switch is active")
    validate_plan_authorization(entries, authorization)
    if not acquire_lease():
        raise OrchestrationError("run lease is unavailable")

    try:
        if kill_switch_active():
            raise OrchestrationError("kill switch activated before mutation")
        outcomes = execute_mutation_actions(actions, authorization, client=client, now=now)
        return RunReceipt(status="completed", outcomes=outcomes)
    finally:
        release_lease()
