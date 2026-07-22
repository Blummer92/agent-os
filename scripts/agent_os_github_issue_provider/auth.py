from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from github import Auth, Github


class GitHubAppSecretProvider(Protocol):
    def private_key(self) -> str:
        """Return the GitHub App private key without logging it."""


@dataclass(frozen=True, slots=True)
class GitHubAppConfig:
    app_id: int
    installation_id: int

    def __post_init__(self) -> None:
        if self.app_id <= 0 or self.installation_id <= 0:
            raise ValueError("GitHub App identifiers must be positive integers")


def build_installation_client(
    config: GitHubAppConfig,
    secrets: GitHubAppSecretProvider,
) -> Github:
    key = secrets.private_key()
    if not isinstance(key, str) or not key.strip():
        raise ValueError("GitHub App private key is unavailable")
    app_auth = Auth.AppAuth(config.app_id, key)
    installation_auth = app_auth.get_installation_auth(config.installation_id)
    return Github(
        auth=installation_auth,
        retry=None,
        lazy=False,
        user_agent="agent-os-github-issue-provider/1",
    )
