from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from github import Github

from .models import TransportAttempt, TransportResponse
from .request import GitHubRequestError, request_json


class GitHubTransportError(RuntimeError):
    def __init__(self, kind: str, attempts: tuple[TransportAttempt, ...]) -> None:
        super().__init__(kind)
        self.kind = kind
        self.attempts = attempts


class GitHubRestTransport(Protocol):
    def get_issue_page(
        self,
        repository: str,
        *,
        page: int,
        per_page: int,
        state: str,
    ) -> TransportResponse:
        """Retrieve one issue page without applying scanner semantics."""


@dataclass(slots=True)
class PyGithubRestTransport:
    client: Github
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be from 1 to 3")

    def get_issue_page(
        self,
        repository: str,
        *,
        page: int,
        per_page: int,
        state: str,
    ) -> TransportResponse:
        try:
            result = request_json(
                self.client,
                "GET",
                f"/repos/{repository}/issues",
                parameters={"page": page, "per_page": per_page, "state": state},
                max_attempts=self.max_attempts,
                retry_server_errors=True,
                retry_statuses=frozenset({408}),
                retry_transport_errors=True,
            )
        except GitHubRequestError as error:
            attempts = tuple(
                TransportAttempt(
                    item.number,
                    _request_error_kind(error) if item.error_kind is not None else None,
                )
                for item in error.attempts
            )
            raise GitHubTransportError(_request_error_kind(error), attempts) from error

        return TransportResponse(
            status=200,
            headers=dict(result.headers),
            payload=result.payload,
            attempts=tuple(TransportAttempt(item.number) for item in result.attempts),
        )


def _request_error_kind(error: GitHubRequestError) -> str:
    if error.kind == "rate-limited" or error.status == 429:
        return "rate-limited"
    if error.status in {401, 403}:
        return "permission-denied"
    if error.status == 404:
        return "source-inaccessible"
    if error.status is not None and 400 <= error.status < 500 and error.status != 408:
        return "malformed-response"
    return "api-error"
