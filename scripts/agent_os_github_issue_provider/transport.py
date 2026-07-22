from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from github import Github
from github.GithubException import GithubException, RateLimitExceededException
import requests.exceptions

from .models import TransportAttempt, TransportResponse


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
        url = f"/repos/{repository}/issues"
        attempts: list[TransportAttempt] = []
        for attempt_number in range(1, self.max_attempts + 1):
            try:
                headers, payload = self.client.requester.requestJsonAndCheck(
                    "GET",
                    url,
                    parameters={"page": page, "per_page": per_page, "state": state},
                    headers={
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2026-03-10",
                    },
                )
                attempts.append(TransportAttempt(attempt_number))
                if not isinstance(headers, dict):
                    raise GitHubTransportError(
                        "malformed-response", tuple(attempts)
                    )
                return TransportResponse(
                    status=200,
                    headers={str(key): str(value) for key, value in headers.items()},
                    payload=payload,
                    attempts=tuple(attempts),
                )
            except RateLimitExceededException as error:
                attempts.append(TransportAttempt(attempt_number, "rate-limited"))
                raise GitHubTransportError("rate-limited", tuple(attempts)) from error
            except GithubException as error:
                kind = _github_error_kind(error.status)
                attempts.append(TransportAttempt(attempt_number, kind))
                if kind != "api-error" or attempt_number == self.max_attempts:
                    raise GitHubTransportError(kind, tuple(attempts)) from error
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                TimeoutError,
                ConnectionError,
            ) as error:
                attempts.append(TransportAttempt(attempt_number, "api-error"))
                if attempt_number == self.max_attempts:
                    raise GitHubTransportError("api-error", tuple(attempts)) from error
            except Exception as error:
                # Wrap any other internal library exceptions to prevent leak
                attempts.append(TransportAttempt(attempt_number, "api-error"))
                raise GitHubTransportError("api-error", tuple(attempts)) from error
        raise GitHubTransportError("api-error", tuple(attempts))


def _github_error_kind(status: int | None) -> str:
    if status in {401, 403}:
        return "permission-denied"
    if status == 404:
        return "source-inaccessible"
    if status == 429:
        return "rate-limited"
    if status == 408:
        return "api-error"
    if status is not None and 400 <= status < 500:
        return "malformed-response"
    return "api-error"
