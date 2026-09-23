"""Mock-only boundary guard for a future live Notion adapter.

This module intentionally has no Notion SDK dependency, no HTTP client, no
credentials, and no live system behavior. It exists so tests can lock the
safety boundary before a live adapter is implemented.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .base import ConnectorError, ConnectorErrorCode, RegistryResource
from .notion_normalizer import normalize_notion_resource


@dataclass(frozen=True)
class NotionLiveReadOnlyConfig:
    token: str | None
    allowed_target_ids: frozenset[str]
    live_mode: str | None

    @classmethod
    def from_environment(
        cls, env: Mapping[str, str]
    ) -> "NotionLiveReadOnlyConfig":
        allowed_ids = frozenset(
            target_id.strip()
            for target_id in env.get("NOTION_ALLOWED_TARGET_IDS", "").split(",")
            if target_id.strip()
        )
        return cls(
            token=env.get("NOTION_READONLY_TOKEN"),
            allowed_target_ids=allowed_ids,
            live_mode=env.get("NOTION_LIVE_MODE"),
        )


class NotionLiveReadOnlyBoundary:
    """Pre-live safety guard for future Notion metadata reads."""

    connector_id = "notion-live-readonly-boundary"
    write_capabilities = "none"
    page_body_reads_enabled = False

    def __init__(self, config: NotionLiveReadOnlyConfig) -> None:
        self._config = config

    def live_mode_error(self) -> ConnectorError | None:
        if not self._config.token:
            return ConnectorError(
                code=ConnectorErrorCode.AUTHENTICATION_FAILED,
                severity="critical",
                retryable=False,
                message="Live Notion mode disabled: NOTION_READONLY_TOKEN is missing.",
            )
        if self._config.live_mode != "readonly":
            return ConnectorError(
                code=ConnectorErrorCode.PERMISSION_DENIED,
                severity="critical",
                retryable=False,
                message="Live Notion mode requires NOTION_LIVE_MODE=readonly.",
            )
        return None

    def lookup_mock_resource(
        self, target_id: str, mock_payloads: Mapping[str, dict[str, Any]]
    ) -> RegistryResource | ConnectorError:
        error = self.live_mode_error()
        if error is not None:
            return error
        if target_id not in self._config.allowed_target_ids:
            return ConnectorError(
                code=ConnectorErrorCode.PERMISSION_DENIED,
                severity="critical",
                retryable=False,
                message="Target id is not approved for live read-only Notion access.",
                resource_id=target_id,
            )
        payload = mock_payloads.get(target_id)
        if payload is None:
            return ConnectorError(
                code=ConnectorErrorCode.RESOURCE_MISSING,
                severity="high",
                retryable=True,
                message="Approved target id was not present in mock payloads.",
                resource_id=target_id,
            )
        return normalize_notion_resource(payload)

    def read_page_body(self, target_id: str) -> ConnectorError:
        return ConnectorError(
            code=ConnectorErrorCode.PERMISSION_DENIED,
            severity="critical",
            retryable=False,
            message="Page-body reads are blocked by default.",
            resource_id=target_id,
        )
