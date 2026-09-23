"""Canonical bounded PyGithub request execution for Agent OS adapters.

This module owns only commodity requester mechanics: one PyGithub requester
boundary, bounded read retries, normalized low-level failure evidence, and
header normalization. Domain packages still own authorization, currentness,
pagination interpretation, mutation admission, and domain-specific status
vocabularies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import requests.exceptions
from github.GithubException import GithubException, RateLimitExceededException

DEFAULT_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2026-03-10",
}


@dataclass(frozen=True, slots=True)
class GitHubRequestAttempt:
    number: int
    error_kind: str | None = None


@dataclass(frozen=True, slots=True)
class GitHubRequestResult:
    headers: Mapping[str, str]
    payload: object
    attempts: tuple[GitHubRequestAttempt, ...]


class GitHubRequestError(RuntimeError):
    """Bounded requester failure without domain interpretation."""

    def __init__(
        self,
        kind: str,
        *,
        status: int | None,
        attempts: tuple[GitHubRequestAttempt, ...],
    ) -> None:
        super().__init__(kind)
        self.kind = kind
        self.status = status
        self.attempts = attempts


def request_json(
    client: object,
    method: str,
    path: str,
    *,
    parameters: Mapping[str, object] | None = None,
    input_payload: object | None = None,
    max_attempts: int = 1,
    retry_server_errors: bool = False,
    retry_statuses: frozenset[int] = frozenset(),
    retry_transport_errors: bool = False,
    headers: Mapping[str, str] | None = None,
) -> GitHubRequestResult:
    """Execute one bounded PyGithub request and return raw transport evidence.

    The caller chooses retry policy explicitly. Writes should normally use one
    attempt so domain code can classify uncertain mutation outcomes itself.
    """
    if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts must be an exact int from 1 to 3")
    requester = getattr(client, "requester", None)
    if requester is None or not hasattr(requester, "requestJsonAndCheck"):
        raise TypeError("client must expose the canonical PyGithub requester")

    attempts: list[GitHubRequestAttempt] = []
    request_headers = dict(DEFAULT_HEADERS if headers is None else headers)
    for attempt_number in range(1, max_attempts + 1):
        try:
            kwargs: dict[str, object] = {"headers": request_headers}
            if parameters is not None:
                kwargs["parameters"] = dict(parameters)
            if input_payload is not None:
                kwargs["input"] = input_payload
            response_headers, payload = requester.requestJsonAndCheck(
                method,
                path,
                **kwargs,
            )
            attempts.append(GitHubRequestAttempt(attempt_number))
            if not isinstance(response_headers, Mapping):
                raise GitHubRequestError(
                    "malformed-response",
                    status=None,
                    attempts=tuple(attempts),
                )
            return GitHubRequestResult(
                headers={str(key): str(value) for key, value in response_headers.items()},
                payload=payload,
                attempts=tuple(attempts),
            )
        except GitHubRequestError:
            raise
        except RateLimitExceededException as error:
            attempts.append(GitHubRequestAttempt(attempt_number, "rate-limited"))
            raise GitHubRequestError(
                "rate-limited",
                status=getattr(error, "status", None),
                attempts=tuple(attempts),
            ) from error
        except GithubException as error:
            status = getattr(error, "status", None)
            attempts.append(GitHubRequestAttempt(attempt_number, "http-error"))
            retryable = (
                (retry_server_errors and status is not None and 500 <= status < 600)
                or status in retry_statuses
            )
            if retryable and attempt_number < max_attempts:
                continue
            raise GitHubRequestError(
                "http-error",
                status=status,
                attempts=tuple(attempts),
            ) from error
        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            TimeoutError,
            ConnectionError,
        ) as error:
            attempts.append(GitHubRequestAttempt(attempt_number, "transport-unavailable"))
            if retry_transport_errors and attempt_number < max_attempts:
                continue
            raise GitHubRequestError(
                "transport-unavailable",
                status=None,
                attempts=tuple(attempts),
            ) from error
        except Exception as error:
            attempts.append(GitHubRequestAttempt(attempt_number, "internal-error"))
            raise GitHubRequestError(
                "internal-error",
                status=None,
                attempts=tuple(attempts),
            ) from error

    raise GitHubRequestError(
        "transport-unavailable",
        status=None,
        attempts=tuple(attempts),
    )
