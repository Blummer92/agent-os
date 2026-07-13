"""Small resolver/registry for local (noop + fake) adapters.

Local-only, on purpose: no real external adapter belongs here yet. See
docs/ADAPTER_CONTRACT_FUTURE.md for how a future external-adapter
registry might be formalized (Phase 2H+).
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
from workflow_scheduler.adapters.noop_adapter import NoopAdapter

_REGISTRY: Dict[str, Callable[[], TaskAdapter]] = {
    "noop": NoopAdapter,
    "fake-success": FakeSuccessAdapter,
    "fake-failure": FakeFailureAdapter,
    "fake-retryable": FakeRetryableAdapter,
    "fake-never-called": FakeNeverCalledAdapter,
    "fake-slow": FakeSlowAdapter,
    "fake-malformed": FakeMalformedReturnAdapter,
    "fake-raising": FakeRaisingAdapter,
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
