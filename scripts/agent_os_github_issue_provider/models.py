from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


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
