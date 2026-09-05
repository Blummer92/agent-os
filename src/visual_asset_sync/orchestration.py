"""Disabled-by-default orchestration wrapper for Visual Asset Sync mutations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence

from .models import ReconciliationEntry
from .mutation_adapter import (
    MutationAction,
    MutationAuthorization,
    MutationExecutionError,
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
    stage_timeout_seconds: int = 30
    total_timeout_seconds: int = 120
    maximum_alerts: int = 1

    def __post_init__(self) -> None:
        if type(self.schedule_enabled) is not bool or type(self.mutation_enabled) is not bool:
            raise OrchestrationError("orchestration flags must be exact booleans")
        for name, value in (
            ("stage_timeout_seconds", self.stage_timeout_seconds),
            ("total_timeout_seconds", self.total_timeout_seconds),
            ("maximum_alerts", self.maximum_alerts),
        ):
            if type(value) is not int or value < 0:
                raise OrchestrationError(f"{name} must be a non-negative integer")
        if self.stage_timeout_seconds == 0 or self.total_timeout_seconds == 0:
            raise OrchestrationError("orchestration timeouts must be positive")
        if self.stage_timeout_seconds > self.total_timeout_seconds:
            raise OrchestrationError("stage timeout exceeds total timeout")


@dataclass(frozen=True)
class RunEvent:
    stage: str
    status: str


@dataclass(frozen=True)
class RunReceipt:
    status: str
    run_id: str
    outcomes: tuple[MutationOutcome, ...] = ()
    events: tuple[RunEvent, ...] = ()
    quarantined: bool = False
    alert_count: int = 0


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
    elapsed_seconds: Callable[[], float] = lambda: 0.0,
    emit_alert: Callable[[str], None] = lambda _: None,
) -> RunReceipt:
    """Run one bounded orchestration pass; disabled configuration is inert."""
    run_id = _run_id(authorization)
    if not config.schedule_enabled or not config.mutation_enabled:
        return RunReceipt(status="disabled", run_id=run_id, events=(RunEvent("gate", "disabled"),))
    if kill_switch_active():
        raise OrchestrationError("kill switch is active")
    validate_plan_authorization(entries, authorization)
    _check_timeout(config, elapsed_seconds(), "pre-lease")
    if not acquire_lease():
        raise OrchestrationError("run lease is unavailable")

    events = [RunEvent("lease", "acquired")]
    alert_keys: set[str] = set()
    try:
        _check_timeout(config, elapsed_seconds(), "pre-mutation")
        if kill_switch_active():
            raise OrchestrationError("kill switch activated before mutation")
        events.append(RunEvent("kill-switch", "clear"))
        try:
            outcomes = execute_mutation_actions(actions, authorization, client=client, now=now)
        except MutationExecutionError as error:
            key = "mutation-uncertain"
            _alert_once(key, "visual asset mutation requires reconciliation", alert_keys, config, emit_alert)
            events.append(RunEvent("mutation", "quarantined"))
            return RunReceipt(
                status="manual-reconciliation-required",
                run_id=run_id,
                events=tuple(events),
                quarantined=True,
                alert_count=len(alert_keys),
            )
        _check_timeout(config, elapsed_seconds(), "post-mutation")
        events.append(RunEvent("mutation", "completed"))
        return RunReceipt(
            status="completed",
            run_id=run_id,
            outcomes=outcomes,
            events=tuple(events),
            alert_count=len(alert_keys),
        )
    finally:
        release_lease()


def _check_timeout(config: OrchestrationConfig, elapsed: float, stage: str) -> None:
    if type(elapsed) not in {int, float} or elapsed < 0:
        raise OrchestrationError("elapsed time evidence is invalid")
    if elapsed > config.total_timeout_seconds:
        raise OrchestrationError("total orchestration timeout exceeded")
    if stage != "post-mutation" and elapsed > config.stage_timeout_seconds:
        raise OrchestrationError("orchestration stage timeout exceeded")


def _alert_once(
    key: str,
    message: str,
    seen: set[str],
    config: OrchestrationConfig,
    emit_alert: Callable[[str], None],
) -> None:
    if key in seen or len(seen) >= config.maximum_alerts:
        return
    try:
        emit_alert(message)
    except Exception:
        return
    seen.add(key)


def _run_id(authorization: MutationAuthorization) -> str:
    payload = json.dumps(
        {
            "data_source_id": authorization.data_source_id,
            "notion_version": authorization.notion_version,
            "plan_digest": authorization.plan_digest,
            "dry_run": authorization.dry_run,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
