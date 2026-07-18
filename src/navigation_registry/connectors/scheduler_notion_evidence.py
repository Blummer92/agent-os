"""Translate Workflow Scheduler Notion results into registry evidence.

This module is a pure contract boundary. It imports no Scheduler internals, performs
no network calls, creates no credentials, and exposes no write operations. The
Workflow Scheduler remains the canonical live-read executor; this adapter only
normalizes its five-state result dictionaries through the existing B2 contract.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from .base import ConnectorError, ConnectorErrorCode, RegistryResource
from .notion_contract_adapter import NotionContractAdapter

_SUPPORTED_RESOURCE_ACTIONS = {"get_page", "get_database"}
_SAFE_RESULT_KEYS = ("status", "message", "retry_after")


class SchedulerNotionEvidenceAdapter:
    """Convert Scheduler read results without changing Scheduler behavior."""

    write_capabilities = "none"
    live_system_access = False

    def __init__(self, contract_adapter: NotionContractAdapter | None = None) -> None:
        self._contract_adapter = contract_adapter or NotionContractAdapter()

    def from_scheduler_result(
        self,
        action: str,
        result: Mapping[str, Any],
    ) -> RegistryResource | ConnectorError:
        """Normalize one Scheduler result for a supported live-read action."""

        normalized_action = str(action or "").strip()
        if normalized_action not in _SUPPORTED_RESOURCE_ACTIONS:
            return _error(
                ConnectorErrorCode.METADATA_INCOMPLETE,
                "Scheduler action cannot produce one canonical registry resource.",
                evidence={"scheduler_action": normalized_action or "missing"},
            )
        if not isinstance(result, Mapping):
            return _error(
                ConnectorErrorCode.METADATA_INCOMPLETE,
                "Scheduler result must be a mapping.",
                evidence={"scheduler_action": normalized_action},
            )

        status = str(result.get("status") or "").strip().lower()
        if status == "retryable":
            return _scheduler_error(
                result,
                action=normalized_action,
                code=ConnectorErrorCode.SYSTEM_UNAVAILABLE,
                retryable=True,
            )
        if status == "failure":
            return _scheduler_error(
                result,
                action=normalized_action,
                code=ConnectorErrorCode.VERIFICATION_FAILED,
                retryable=False,
            )
        if status != "success":
            return _error(
                ConnectorErrorCode.METADATA_INCOMPLETE,
                "Scheduler result has an unsupported or missing status.",
                evidence={
                    "scheduler_action": normalized_action,
                    "scheduler_result": _safe_result_evidence(result),
                },
            )

        output = result.get("output")
        if not isinstance(output, dict):
            return _error(
                ConnectorErrorCode.METADATA_INCOMPLETE,
                "Successful Scheduler result is missing an output mapping.",
                evidence={
                    "scheduler_action": normalized_action,
                    "scheduler_result": _safe_result_evidence(result),
                },
            )

        if normalized_action == "get_page":
            normalized = self._contract_adapter.from_live_page_payload(output)
        else:
            normalized = self._contract_adapter.from_live_database_payload(output)

        if isinstance(normalized, ConnectorError):
            return replace(
                normalized,
                evidence={
                    **normalized.evidence,
                    "scheduler_action": normalized_action,
                    "scheduler_result": _safe_result_evidence(result),
                },
            )

        return replace(
            normalized,
            metadata={
                **normalized.metadata,
                "scheduler_action": normalized_action,
                "scheduler_result": dict(result),
                "raw_scheduler_output": dict(output),
                "evidence_path_mode": "live_notion_verification",
            },
        )


def _scheduler_error(
    result: Mapping[str, Any],
    *,
    action: str,
    code: ConnectorErrorCode,
    retryable: bool,
) -> ConnectorError:
    message = str(result.get("message") or "Scheduler Notion read failed.")
    return ConnectorError(
        code=code,
        severity="medium",
        retryable=retryable,
        message=message,
        evidence={
            "scheduler_action": action,
            "scheduler_result": _safe_result_evidence(result),
            "write_boundary": "read-only-live-evidence",
        },
    )


def _safe_result_evidence(result: Mapping[str, Any]) -> dict[str, Any]:
    return {key: result.get(key) for key in _SAFE_RESULT_KEYS if key in result}


def _error(
    code: ConnectorErrorCode,
    message: str,
    *,
    evidence: dict[str, Any],
) -> ConnectorError:
    return ConnectorError(
        code=code,
        severity="medium",
        retryable=False,
        message=message,
        evidence=evidence,
    )
