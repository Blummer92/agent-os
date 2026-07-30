"""Resolve one exact issue snapshot, source revision, and body digest.

Read-only: takes an injected ``IssueSourceReader`` and performs no network
calls or writes itself. Reuses
``scripts.agent_os_github_issue_provider.revision.issue_source_revision`` and
``canonical_issue_payload`` for the revision binding rather than
reimplementing digest logic.
"""

from __future__ import annotations

import hashlib

from scripts.agent_os_github_issue_provider.revision import issue_source_revision

from .stage_models import (
    IssueReadResult,
    IssueReadStatus,
    IssueSnapshot,
    IssueSourceReader,
    IssueSourceStageResult,
    IssueSourceStageStatus,
)

_SOURCE_FAILURE_REASONS = {
    IssueReadStatus.NOT_FOUND: "source.not-found",
    IssueReadStatus.PERMISSION_DENIED: "source.permission-denied",
    IssueReadStatus.SOURCE_INACCESSIBLE: "source.inaccessible",
    IssueReadStatus.API_ERROR: "source.api-error",
}


def resolve_issue_snapshot(
    repository: str,
    issue_number: int,
    issue_reader: IssueSourceReader,
    *,
    retrieved_at: str,
) -> IssueSourceStageResult:
    """Fetch exactly one issue and bind it to a canonical source revision.

    Fails closed: any adapter error, malformed response, or missing revision
    field produces an explicit ``source-failure`` or ``incomplete-evidence``
    result rather than a guessed snapshot.
    """
    if issue_reader is None:
        raise TypeError("issue_reader is required")

    try:
        result = issue_reader.read_issue(repository, issue_number)
    except (TypeError, ValueError, PermissionError, LookupError, RuntimeError) as error:
        return IssueSourceStageResult(
            status=IssueSourceStageStatus.SOURCE_FAILURE,
            snapshot=None,
            reason_codes=("source.reader-error",),
            details=(str(error),),
        )

    if not isinstance(result, IssueReadResult):
        return IssueSourceStageResult(
            status=IssueSourceStageStatus.SOURCE_FAILURE,
            snapshot=None,
            reason_codes=("source.reader-contract-violation",),
            details=("issue_reader did not return an IssueReadResult",),
        )

    if result.status in _SOURCE_FAILURE_REASONS:
        return IssueSourceStageResult(
            status=IssueSourceStageStatus.SOURCE_FAILURE,
            snapshot=None,
            reason_codes=(_SOURCE_FAILURE_REASONS[result.status],),
        )
    if result.status == IssueReadStatus.MALFORMED_RESPONSE:
        return IssueSourceStageResult(
            status=IssueSourceStageStatus.INCOMPLETE_EVIDENCE,
            snapshot=None,
            reason_codes=("source.malformed-response",),
        )

    item = result.item
    assert item is not None  # enforced by IssueReadResult.__post_init__

    required = ("number", "html_url", "created_at", "updated_at", "body")
    missing = [name for name in required if name not in item]
    if missing:
        return IssueSourceStageResult(
            status=IssueSourceStageStatus.INCOMPLETE_EVIDENCE,
            snapshot=None,
            reason_codes=("source.missing-fields",),
            details=tuple(f"missing={name}" for name in missing),
        )

    try:
        source_revision = issue_source_revision(item)
    except (TypeError, ValueError) as error:
        return IssueSourceStageResult(
            status=IssueSourceStageStatus.INCOMPLETE_EVIDENCE,
            snapshot=None,
            reason_codes=("source.missing-revision-fields",),
            details=(str(error),),
        )

    body = item.get("body") or ""
    if not isinstance(body, str):
        return IssueSourceStageResult(
            status=IssueSourceStageStatus.INCOMPLETE_EVIDENCE,
            snapshot=None,
            reason_codes=("source.malformed-body",),
        )

    try:
        snapshot = IssueSnapshot(
            repository=repository,
            issue_number=issue_number,
            url=str(item["html_url"]),
            created_at=str(item["created_at"]),
            updated_at=str(item["updated_at"]),
            body=body,
            body_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            source_revision=source_revision,
            retrieved_at=retrieved_at,
        )
    except (TypeError, ValueError) as error:
        return IssueSourceStageResult(
            status=IssueSourceStageStatus.INCOMPLETE_EVIDENCE,
            snapshot=None,
            reason_codes=("source.malformed-fields",),
            details=(str(error),),
        )

    return IssueSourceStageResult(
        status=IssueSourceStageStatus.RESOLVED,
        snapshot=snapshot,
    )
