"""Authorization-gated Notion mutation planning and execution for Visual Asset Sync.

This module is fixture-first and client-neutral. Dry-run is the default and makes
zero external calls. Live execution requires an exact immutable authorization
object plus an injected client supplied by a separately authorized runtime.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, Sequence

from .models import ReconciliationEntry, ReconciliationResult, SourceAssetRecord
from .notion_adapter import SUPPORTED_NOTION_VERSION

_ALLOWED_ACTIONS = frozenset(
    {ReconciliationResult.UPDATE_EXISTING, ReconciliationResult.CREATE_MISSING}
)


class MutationAdapterError(Exception):
    """Base class for deterministic mutation adapter failures."""


class MutationAuthorizationError(MutationAdapterError):
    """Raised when live authorization is missing, stale, or mismatched."""


class MutationPlanError(MutationAdapterError):
    """Raised when planner output cannot be applied safely."""


class MutationExecutionError(MutationAdapterError):
    """Raised when an injected client returns an invalid or ambiguous result."""


@dataclass(frozen=True)
class MutationAuthorization:
    data_source_id: str
    notion_version: str
    plan_digest: str
    approved_actions: frozenset[ReconciliationResult]
    property_allowlist: frozenset[str]
    credential_route: str
    maximum_updates: int
    maximum_creates: int
    maximum_total_mutations: int
    valid_until: datetime
    dry_run: bool = True

    def __post_init__(self) -> None:
        if type(self.data_source_id) is not str or not self.data_source_id.strip():
            raise MutationAuthorizationError("data_source_id is required")
        if self.notion_version != SUPPORTED_NOTION_VERSION:
            raise MutationAuthorizationError("notion_version is not supported")
        if type(self.plan_digest) is not str or len(self.plan_digest) != 64:
            raise MutationAuthorizationError("plan_digest must be a sha256 hex digest")
        try:
            int(self.plan_digest, 16)
        except ValueError:
            raise MutationAuthorizationError("plan_digest must be a sha256 hex digest") from None
        if type(self.approved_actions) is not frozenset or not self.approved_actions:
            raise MutationAuthorizationError("approved_actions must be a non-empty frozenset")
        if not self.approved_actions <= _ALLOWED_ACTIONS:
            raise MutationAuthorizationError("approved_actions contains an unsupported action")
        if type(self.property_allowlist) is not frozenset or not self.property_allowlist:
            raise MutationAuthorizationError("property_allowlist must be a non-empty frozenset")
        if any(type(name) is not str or not name.strip() for name in self.property_allowlist):
            raise MutationAuthorizationError("property_allowlist contains an invalid property")
        if type(self.credential_route) is not str or not self.credential_route.strip():
            raise MutationAuthorizationError("credential_route is required")
        for name, value in (
            ("maximum_updates", self.maximum_updates),
            ("maximum_creates", self.maximum_creates),
            ("maximum_total_mutations", self.maximum_total_mutations),
        ):
            if type(value) is not int or value < 0:
                raise MutationAuthorizationError(f"{name} must be a non-negative integer")
        if self.maximum_total_mutations < self.maximum_updates:
            raise MutationAuthorizationError("maximum_total_mutations is below maximum_updates")
        if self.maximum_total_mutations < self.maximum_creates:
            raise MutationAuthorizationError("maximum_total_mutations is below maximum_creates")
        if not isinstance(self.valid_until, datetime) or self.valid_until.tzinfo is None:
            raise MutationAuthorizationError("valid_until must be timezone-aware")
        if type(self.dry_run) is not bool:
            raise MutationAuthorizationError("dry_run must be an exact boolean")


@dataclass(frozen=True)
class MutationAction:
    action: ReconciliationResult
    source_row: str
    identity_key: str
    page_id: str | None
    properties: tuple[tuple[str, str], ...]
    evidence_key: str


@dataclass(frozen=True)
class MutationOutcome:
    evidence_key: str
    action: ReconciliationResult
    status: str
    page_id: str | None = None
    page_url: str | None = None


class NotionMutationClient(Protocol):
    def update_page(self, *, page_id: str, properties: dict[str, str], notion_version: str) -> dict[str, Any]: ...

    def create_page(self, *, data_source_id: str, properties: dict[str, str], notion_version: str) -> dict[str, Any]: ...


def plan_digest(entries: Sequence[ReconciliationEntry]) -> str:
    payload = [
        {
            "source_row": entry.source_row,
            "result": entry.result.value,
            "identity_key": entry.identity_key,
            "matched_page_ids": list(entry.matched_page_ids),
        }
        for entry in entries
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_mutation_actions(
    entries: Sequence[ReconciliationEntry],
    source_records: Sequence[SourceAssetRecord],
    *,
    property_mapping: dict[str, str],
) -> tuple[MutationAction, ...]:
    if len(entries) != len(source_records):
        raise MutationPlanError("plan and source record counts differ")
    if type(property_mapping) is not dict or not property_mapping:
        raise MutationPlanError("property_mapping must be a non-empty dictionary")

    actions: list[MutationAction] = []
    for entry, source in zip(entries, source_records, strict=True):
        if entry.source_row != source.source_row:
            raise MutationPlanError("plan/source row identity mismatch")
        if entry.result not in _ALLOWED_ACTIONS:
            continue
        if entry.identity_key is None:
            raise MutationPlanError("mutable planner entry is missing identity")
        if entry.result is ReconciliationResult.UPDATE_EXISTING:
            if len(entry.matched_page_ids) != 1:
                raise MutationPlanError("update action requires exactly one page id")
            page_id = entry.matched_page_ids[0]
        else:
            if entry.matched_page_ids:
                raise MutationPlanError("create action must not carry matched page ids")
            page_id = None

        values = _mapped_properties(source, property_mapping)
        evidence_key = _action_evidence_key(entry, values)
        actions.append(
            MutationAction(
                action=entry.result,
                source_row=entry.source_row,
                identity_key=entry.identity_key,
                page_id=page_id,
                properties=tuple(sorted(values.items())),
                evidence_key=evidence_key,
            )
        )
    return tuple(actions)


def execute_mutation_actions(
    actions: Sequence[MutationAction],
    authorization: MutationAuthorization,
    *,
    client: NotionMutationClient | None = None,
    now: datetime | None = None,
) -> tuple[MutationOutcome, ...]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise MutationAuthorizationError("now must be timezone-aware")
    if current > authorization.valid_until:
        raise MutationAuthorizationError("authorization is expired")

    _validate_actions_against_authorization(actions, authorization)
    if authorization.dry_run:
        return tuple(
            MutationOutcome(action=a.action, evidence_key=a.evidence_key, status="dry-run")
            for a in actions
        )
    if client is None:
        raise MutationAuthorizationError("live execution requires an injected client")

    outcomes: list[MutationOutcome] = []
    seen: set[str] = set()
    for action in actions:
        if action.evidence_key in seen:
            raise MutationPlanError("duplicate action evidence key")
        seen.add(action.evidence_key)
        properties = dict(action.properties)
        try:
            if action.action is ReconciliationResult.UPDATE_EXISTING:
                assert action.page_id is not None
                response = client.update_page(
                    page_id=action.page_id,
                    properties=properties,
                    notion_version=authorization.notion_version,
                )
                outcome = _validate_response(response, action, expected_page_id=action.page_id)
            else:
                response = client.create_page(
                    data_source_id=authorization.data_source_id,
                    properties=properties,
                    notion_version=authorization.notion_version,
                )
                outcome = _validate_response(response, action, expected_page_id=None)
        except MutationAdapterError:
            raise
        except Exception:
            raise MutationExecutionError("Notion mutation failed") from None
        outcomes.append(outcome)
    return tuple(outcomes)


def validate_plan_authorization(
    entries: Sequence[ReconciliationEntry], authorization: MutationAuthorization
) -> None:
    if plan_digest(entries) != authorization.plan_digest:
        raise MutationAuthorizationError("authorization plan digest does not match")


def _validate_actions_against_authorization(
    actions: Sequence[MutationAction], authorization: MutationAuthorization
) -> None:
    updates = sum(a.action is ReconciliationResult.UPDATE_EXISTING for a in actions)
    creates = sum(a.action is ReconciliationResult.CREATE_MISSING for a in actions)
    if updates > authorization.maximum_updates:
        raise MutationAuthorizationError("update ceiling exceeded")
    if creates > authorization.maximum_creates:
        raise MutationAuthorizationError("create ceiling exceeded")
    if len(actions) > authorization.maximum_total_mutations:
        raise MutationAuthorizationError("total mutation ceiling exceeded")
    for action in actions:
        if action.action not in authorization.approved_actions:
            raise MutationAuthorizationError("action class is not authorized")
        for property_name, _ in action.properties:
            if property_name not in authorization.property_allowlist:
                raise MutationAuthorizationError("property is outside the authorization allowlist")


def _mapped_properties(source: SourceAssetRecord, mapping: dict[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for field_name, property_name in mapping.items():
        if type(field_name) is not str or not hasattr(source, field_name):
            raise MutationPlanError("property_mapping contains an unsupported source field")
        if type(property_name) is not str or not property_name.strip():
            raise MutationPlanError("property_mapping contains an invalid property name")
        raw = getattr(source, field_name)
        if raw is None:
            continue
        if type(raw) is not str:
            raise MutationPlanError("mapped source values must be strings")
        values[property_name.strip()] = raw
    if not values:
        raise MutationPlanError("mutable action has no mapped properties")
    return values


def _action_evidence_key(entry: ReconciliationEntry, properties: dict[str, str]) -> str:
    payload = {
        "source_row": entry.source_row,
        "result": entry.result.value,
        "identity_key": entry.identity_key,
        "matched_page_ids": list(entry.matched_page_ids),
        "properties": properties,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_response(
    response: Any, action: MutationAction, *, expected_page_id: str | None
) -> MutationOutcome:
    if type(response) is not dict:
        raise MutationExecutionError("Notion mutation response is malformed")
    page_id = response.get("id")
    page_url = response.get("url")
    if type(page_id) is not str or not page_id.strip():
        raise MutationExecutionError("Notion mutation response is missing page id")
    if expected_page_id is not None and page_id != expected_page_id:
        raise MutationExecutionError("Notion mutation returned an unexpected page id")
    if page_url is not None and type(page_url) is not str:
        raise MutationExecutionError("Notion mutation response has an invalid page url")
    return MutationOutcome(
        evidence_key=action.evidence_key,
        action=action.action,
        status="applied",
        page_id=page_id,
        page_url=page_url,
    )
