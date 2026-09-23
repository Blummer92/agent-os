from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

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


def build_token_client(
    environment: Mapping[str, str],
    *,
    user_agent: str = "agent-os-github/1",
) -> Github:
    """Build the canonical token-backed PyGithub client used by Agent OS.

    Credential discovery is deliberately limited to the repository's existing
    ``GITHUB_TOKEN``/``GH_TOKEN`` convention.  This helper creates no authority,
    performs no GitHub request, and never stores or reports the token outside
    PyGithub's auth object.
    """
    token = environment.get("GITHUB_TOKEN") or environment.get("GH_TOKEN")
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError("GITHUB_TOKEN or GH_TOKEN is required")
    if not isinstance(user_agent, str) or not user_agent.strip():
        raise ValueError("user_agent must be non-empty text")
    return Github(
        auth=Auth.Token(token.strip()),
        retry=None,
        lazy=False,
        user_agent=user_agent.strip(),
    )
