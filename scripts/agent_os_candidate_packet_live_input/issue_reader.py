"""Production ``IssueSourceReader`` backed by an injected single-issue transport.

``LiveIssueReader`` never hard-wires a credential, a GitHub client, or a
network call itself. It is parameterized over a ``SingleIssueTransport`` the
caller supplies -- the transport performs the already-authorized live read
(reusing whatever GitHub access the caller already holds) and returns a
typed ``SingleIssueTransportResult``; this module only normalizes that result
into the canonical ``IssueReadResult`` /
``scripts.agent_os_candidate_packet.stage_models.IssueReadStatus`` vocabulary.

This module does not depend on ``scripts.agent_os_github_issue_provider``'s
paginated-listing transport (a different contract for a different consumer,
per #1155) and does not depend on #531 reaching a terminal state.

An error the transport reports is never converted to ``OK``, and no missing
issue field is ever invented -- a malformed or incomplete transport payload
maps to ``MALFORMED_RESPONSE``, the existing fail-closed vocabulary member.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Protocol

from scripts.agent_os_candidate_packet.stage_models import (
    IssueReadResult,
    IssueReadStatus,
)


class SingleIssueTransportOutcome(str, Enum):
    """Truthful outcome of one transport-level single-issue fetch attempt."""

    OK = "ok"
    NOT_FOUND = "not-found"
    PERMISSION_DENIED = "permission-denied"
    SOURCE_INACCESSIBLE = "source-inaccessible"
    MALFORMED_RESPONSE = "malformed-response"
    API_ERROR = "api-error"


@dataclass(frozen=True, slots=True)
class SingleIssueTransportResult:
    """One transport response, before adapter normalization.

    Mirrors ``IssueReadResult``'s own OK/item pairing rule so a transport
    cannot report success without a payload, or a payload without success.
    """

    outcome: SingleIssueTransportOutcome
    item: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, SingleIssueTransportOutcome):
            raise TypeError("outcome must be a SingleIssueTransportOutcome")
        if self.outcome == SingleIssueTransportOutcome.OK and self.item is None:
            raise ValueError("ok outcome requires an item")
        if self.outcome != SingleIssueTransportOutcome.OK and self.item is not None:
            raise ValueError("non-ok outcome must not carry an item")


class SingleIssueTransport(Protocol):
    """Read-only single-issue transport. No write method exists on this protocol."""

    def get_issue(self, repository: str, issue_number: int) -> SingleIssueTransportResult:
        """Perform exactly one authorized live read of one issue."""


_OUTCOME_TO_STATUS: Mapping[SingleIssueTransportOutcome, IssueReadStatus] = {
    SingleIssueTransportOutcome.OK: IssueReadStatus.OK,
    SingleIssueTransportOutcome.NOT_FOUND: IssueReadStatus.NOT_FOUND,
    SingleIssueTransportOutcome.PERMISSION_DENIED: IssueReadStatus.PERMISSION_DENIED,
    SingleIssueTransportOutcome.SOURCE_INACCESSIBLE: IssueReadStatus.SOURCE_INACCESSIBLE,
    SingleIssueTransportOutcome.MALFORMED_RESPONSE: IssueReadStatus.MALFORMED_RESPONSE,
    SingleIssueTransportOutcome.API_ERROR: IssueReadStatus.API_ERROR,
}


@dataclass(frozen=True, slots=True)
class LiveIssueReader:
    """Production ``IssueSourceReader`` over an injected ``SingleIssueTransport``."""

    transport: SingleIssueTransport
    execution_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.transport is None:
            raise TypeError("transport is required")

    def read_issue(self, repository: str, issue_number: int) -> IssueReadResult:
        result = self.transport.get_issue(repository, issue_number)
        if not isinstance(result, SingleIssueTransportResult):
            raise TypeError(
                "transport.get_issue must return a SingleIssueTransportResult"
            )

        if result.outcome != SingleIssueTransportOutcome.OK:
            return IssueReadResult(status=_OUTCOME_TO_STATUS[result.outcome])

        item = result.item
        if not isinstance(item, Mapping):
            return IssueReadResult(status=IssueReadStatus.MALFORMED_RESPONSE)

        reported_number = item.get("number")
        if (
            reported_number is not None
            and not isinstance(reported_number, bool)
            and isinstance(reported_number, int)
            and reported_number != issue_number
        ):
            # The transport answered a different issue than requested; that is
            # a truthful "the response does not describe what was asked for"
            # failure, never a guessed OK for the wrong issue.
            return IssueReadResult(status=IssueReadStatus.MALFORMED_RESPONSE)

        return IssueReadResult(status=IssueReadStatus.OK, item=dict(item))
