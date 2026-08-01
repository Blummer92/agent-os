"""Resolve secrets and repo location inside a Colab runtime.

Secrets come from Colab's secret store, never from a literal in a cell and
never from a committed file. Falls back to the environment for local runs.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

GEMINI_API_KEY = "GEMINI_API_KEY"
NOTION_TOKEN = "NOTION_TOKEN"


class MissingSecretError(RuntimeError):
    """Raised when a required secret is absent from every supported source."""


def in_colab() -> bool:
    """True when running inside a Colab runtime."""
    try:
        import google.colab  # noqa: F401
    except ImportError:
        return False
    return True


def get_secret(name: str, *, required: bool = True) -> Optional[str]:
    """Read a secret from Colab's secret store, else the environment.

    Never logs or echoes the value. Raises rather than returning an empty
    string, so a missing secret fails loudly instead of producing an
    unauthenticated call later.
    """
    value: Optional[str] = None

    if in_colab():
        try:
            from google.colab import userdata

            value = userdata.get(name)
        except Exception:
            # Secret not granted to this notebook, or store unavailable.
            value = None

    if not value:
        value = os.getenv(name)

    if not value and required:
        raise MissingSecretError(
            f"{name} is not set. In Colab, add it under Secrets and grant this "
            f"notebook access; locally, export it. Never paste it into a cell."
        )
    return value or None


def resolve_repo_root(explicit: Optional[str] = None) -> Path:
    """Locate the agent-os checkout so standards files can be rendered."""
    if explicit:
        root = Path(explicit).expanduser().resolve()
    else:
        env_root = os.getenv("AGENT_OS_ROOT")
        root = Path(env_root).expanduser().resolve() if env_root else Path.cwd().resolve()

    if not (root / "01_Shared_Standards").is_dir():
        raise FileNotFoundError(
            f"{root} does not look like an agent-os checkout (no 01_Shared_Standards/). "
            "Clone the repo in Colab and pass its path, or set AGENT_OS_ROOT."
        )
    return root
