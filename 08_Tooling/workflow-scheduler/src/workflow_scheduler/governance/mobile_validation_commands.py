"""Bounded one-paste mobile validation command renderer (CLI-UX2, #1572).

Renders self-contained, single-paste validation commands ONLY from the
canonical developer-validation profile catalog (#1566,
:mod:`workflow_scheduler.governance.dev_validation_profiles`). The renderer is
pure, deterministic, and non-authorizing:

- Input is finite: one canonical profile id plus one supported shell family.
- No freeform shell text is accepted or produced. Every token of the rendered
  command comes from the catalog's fixed argv, quoted safely for the shell.
- Missing environment prerequisites are returned as a displayed checklist,
  never silently embedded as installs, auth, config changes, or bootstrap.
- Unknown profile id, unsupported shell, unmapped runtime id, or an
  over-long command fails closed with :class:`ValueError`.

There is deliberately no universal bootstrap: the rendered command assumes
the prerequisites listed on the envelope are already satisfied on the device
that runs it.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .dev_validation_profiles import (
    RunnerKind,
    canonical_profile_id,
    get_profile,
    profile_argv,
)

# The only shell family this renderer targets. Mobile terminals vary wildly;
# claiming a universal bootstrap would violate the #1572 environment premise,
# so the envelope names its shell explicitly and nothing else is offered.
SHELL_POSIX_SH = "posix-sh"
_SUPPORTED_SHELLS = frozenset({SHELL_POSIX_SH})

# One-paste sanity bound for mobile copy/paste. The catalog already bounds
# targets (32 max, 240 chars each), so this is a backstop, not the mechanism.
MAX_COMMAND_CHARS = 4000

_TIMEOUT_NOTES: Mapping[str, str] = MappingProxyType(
    {
        "focused-120s": "expected to finish within about 2 minutes",
        "artifact-300s": "expected to finish within about 5 minutes",
    }
)

# Explicit, human-readable prerequisites per catalog runtime id. A runtime id
# with no mapping fails closed instead of inventing install instructions.
_RUNTIME_PREREQUISITES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "python-pytest-8.3.5": (
            "Python 3.11+ available as `python`",
            "pytest 8.3.5 installed for that interpreter",
            "a Blummer92/agent-os checkout at the validated SHA",
        ),
        "python-pytest-8.3.5-materials-imports": (
            "Python 3.11+ available as `python`",
            "pytest 8.3.5 installed for that interpreter",
            "instructional-materials-coach Python dependencies importable",
            "a Blummer92/agent-os checkout at the validated SHA",
        ),
        "node22-vitest-4.1.10": (
            "Node.js 22 available as `node`",
            "picture-perfect-coach node_modules installed",
            "a Blummer92/agent-os checkout at the validated SHA",
        ),
        "python-system-script-compat": (
            "Python 3 available as `python`",
            "a Blummer92/agent-os checkout at the validated SHA",
        ),
        "host-python-eia-paddleocr": (
            "a host with PaddleOCR provisioned by your execution host "
            "(not runnable on a bare mobile device)",
            "a Blummer92/agent-os checkout at the validated SHA",
        ),
        "network-capable-ephemeral-python-resolver": (
            "an ephemeral Python resolver with network access, provisioned by "
            "your execution host (not runnable on a bare mobile device)",
            "a Blummer92/agent-os checkout at the validated SHA",
        ),
        "governed-sheets-readonly": (
            "governed read-only Google Sheets access, provisioned by your "
            "execution host (not runnable on a bare mobile device)",
            "a Blummer92/agent-os checkout at the validated SHA",
        ),
        "governed-github-app-readonly": (
            "governed read-only GitHub App access, provisioned by your "
            "execution host (not runnable on a bare mobile device)",
            "a Blummer92/agent-os checkout at the validated SHA",
        ),
    }
)

# Tokens that must never appear in a rendered command: installs, auth, config
# changes, and network bootstrap. Checked by tests as defense-in-depth.
_FORBIDDEN_TOKENS = frozenset(
    {
        "pip install",
        "pip3 install",
        "apt",
        "apt-get",
        "brew install",
        "npm install",
        "npm ci",
        "curl",
        "wget",
        "ssh",
        "gcloud",
        "gh ",
        "export ",
        "sudo",
        ";",
        "&&&",
    }
)


@dataclass(frozen=True, slots=True)
class MobileValidationCommand:
    """One bounded, deterministic, mobile-pasteable validation command."""

    profile_id: str
    shell: str
    command: str
    prerequisites: tuple[str, ...]
    runtime_id: str
    timeout_note: str
    runner_kind: RunnerKind


def _quote_posix(argv: tuple[str, ...]) -> str:
    if type(argv) is not tuple or not argv:
        raise ValueError("command argv must be a non-empty tuple")
    quoted = [shlex.quote(arg) for arg in argv]
    if any(type(arg) is not str or not arg for arg in argv):
        raise ValueError("command argv must be non-empty text")
    return " ".join(quoted)


def render_mobile_command(
    profile_id: object, *, shell: object = SHELL_POSIX_SH
) -> MobileValidationCommand:
    """Render one bounded mobile validation command from a canonical profile.

    The command runs the profile's fixed argv and nothing else. Profiles with
    a fixed working directory are wrapped in a side-effect-free subshell
    ``(cd <dir> && <argv...>)`` so a single paste does not change the user's
    shell directory.
    """
    if type(shell) is not str or shell not in _SUPPORTED_SHELLS:
        raise ValueError(f"unsupported shell: {shell!r}")
    canonical = canonical_profile_id(profile_id)
    profile = get_profile(canonical)
    argv = profile_argv(canonical)

    body = _quote_posix(argv)
    if profile.fixed_working_directory is not None:
        body = (
            f"(cd {_quote_posix((profile.fixed_working_directory,))}"
            f" && {body})"
        )
    if len(body) > MAX_COMMAND_CHARS:
        raise ValueError("rendered command exceeds the mobile paste bound")

    prerequisites = _RUNTIME_PREREQUISITES.get(profile.runtime_id)
    if prerequisites is None:
        raise ValueError(
            f"no prerequisite mapping for runtime id: {profile.runtime_id!r}"
        )
    timeout_note = _TIMEOUT_NOTES.get(profile.timeout_class)
    if timeout_note is None:
        raise ValueError(
            f"no timeout note for timeout class: {profile.timeout_class!r}"
        )

    return MobileValidationCommand(
        profile_id=canonical,
        shell=shell,
        command=body,
        prerequisites=prerequisites,
        runtime_id=profile.runtime_id,
        timeout_note=timeout_note,
        runner_kind=profile.runner_kind,
    )


def render_all_mobile_commands(
    *, shell: object = SHELL_POSIX_SH
) -> Mapping[str, MobileValidationCommand]:
    """Render every catalog profile (aliases included), keyed by profile id."""
    from .dev_validation_profiles import PROFILE_ALIASES, PROFILE_CATALOG

    rendered = {
        profile_id: render_mobile_command(profile_id, shell=shell)
        for profile_id in PROFILE_CATALOG
    }
    rendered.update(
        {
            alias: render_mobile_command(alias, shell=shell)
            for alias in PROFILE_ALIASES
        }
    )
    return MappingProxyType(rendered)


__all__ = [
    "MAX_COMMAND_CHARS",
    "SHELL_POSIX_SH",
    "MobileValidationCommand",
    "render_all_mobile_commands",
    "render_mobile_command",
]
