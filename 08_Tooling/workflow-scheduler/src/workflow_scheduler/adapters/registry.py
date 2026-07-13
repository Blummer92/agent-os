"""Small resolver/registry for local (noop + fake) adapters, plus the
real external adapters: GitHub read-only (Phase 3A), Notion read-only
(Phase 3B), and GitHub PR comment -- the first write-capable adapter,
gated entirely by the scheduler's existing approval flow (Phase 3C).

See docs/ADAPTER_CONTRACT_FUTURE.md for the (still not implemented)
formal JSON-Schema request/result contract a future phase might add.
"""
from __future__ import annotations

from typing import Callable, Dict

from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.adapters.fake_adapters import (
    FakeFailureAdapter,
    FakeMalformedReturnAdapter,
    FakeNeverCalledAdapter,
    FakeRaisingAdapter,
    FakeRetryableAdapter,
    FakeSlowAdapter,
    FakeSuccessAdapter,
)
from workflow_scheduler.adapters.github_pr_comment_adapter import GitHubPRCommentAdapter
from workflow_scheduler.adapters.github_readonly_adapter import GitHubReadOnlyAdapter
from workflow_scheduler.adapters.noop_adapter import NoopAdapter
from workflow_scheduler.adapters.notion_readonly_adapter import NotionReadOnlyAdapter

_REGISTRY: Dict[str, Callable[[], TaskAdapter]] = {
    "noop": NoopAdapter,
    "fake-success": FakeSuccessAdapter,
    "fake-failure": FakeFailureAdapter,
    "fake-retryable": FakeRetryableAdapter,
    "fake-never-called": FakeNeverCalledAdapter,
    "fake-slow": FakeSlowAdapter,
    "fake-malformed": FakeMalformedReturnAdapter,
    "fake-raising": FakeRaisingAdapter,
    "github_readonly": GitHubReadOnlyAdapter,
    "notion_readonly": NotionReadOnlyAdapter,
    "github_pr_comment": GitHubPRCommentAdapter,
}


def available_adapters() -> list[str]:
    """Names of every adapter this registry can resolve, sorted."""
    return sorted(_REGISTRY)


def resolve_adapter(name: str) -> TaskAdapter:
    """Construct a fresh adapter instance by registry name.

    Raises ValueError with the list of valid names on an unknown name --
    never a bare KeyError.
    """
    try:
        factory = _REGISTRY[name]
    except KeyError:
        raise ValueError(f"Unknown adapter: {name!r}. Available: {available_adapters()}") from None
    return factory()
