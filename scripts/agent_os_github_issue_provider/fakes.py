from __future__ import annotations

from dataclasses import dataclass, field

from .models import TransportResponse


@dataclass(slots=True)
class ScriptedGitHubRestTransport:
    responses: list[TransportResponse | Exception]
    calls: list[tuple[str, int, int, str]] = field(default_factory=list)

    def get_issue_page(
        self,
        repository: str,
        *,
        page: int,
        per_page: int,
        state: str,
    ) -> TransportResponse:
        self.calls.append((repository, page, per_page, state))
        if not self.responses:
            raise AssertionError("no scripted response remains")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
