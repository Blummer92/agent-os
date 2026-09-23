from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping


_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True, slots=True)
class TrustedRepositoryIdentity:
    """Caller-supplied repository identity verified outside pagination parsing.

    GitHub repository identity lookup is ASCII case-insensitive. The original
    spelling remains available as evidence while ``repository_key`` is used for
    canonical comparisons.
    """

    repository: str
    repository_id: int

    def __post_init__(self) -> None:
        if not isinstance(self.repository, str) or not _REPOSITORY_RE.fullmatch(
            self.repository
        ):
            raise ValueError("repository must use owner/name form")
        if (
            not isinstance(self.repository_id, int)
            or isinstance(self.repository_id, bool)
            or self.repository_id <= 0
        ):
            raise ValueError("repository_id must be a positive integer")

    @property
    def repository_key(self) -> str:
        """Return the canonical case-insensitive repository lookup key."""

        return self.repository.lower()


@dataclass(frozen=True, slots=True)
class TransportAttempt:
    number: int
    error_kind: str | None = None


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]
    payload: object
    attempts: tuple[TransportAttempt, ...]


@dataclass(frozen=True, slots=True)
class IssuePageEnvelope:
    repository: str
    requested_state: str
    requested_page: int
    per_page: int
    items: tuple[Mapping[str, object], ...]
    next_page: int | None
    terminal_page_proven: bool
    response_status: int
    etag: str | None
    attempts: tuple[TransportAttempt, ...]
    error_kind: str | None = None
