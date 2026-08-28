"""Host-execution-interface hook adapter for the #1237 governed-route preflight.

Claude Code exposes repository-owned hooks that run *before* the model selects
any tool: ``UserPromptSubmit`` fires on every submitted request, and
``PreToolUse`` fires before a ``Bash`` command executes. Those hooks are the
concrete pre-tool routing surface #1237 needs, and they are configured from
this repository in ``.claude/settings.json``.

This module owns only the host-shaped edges of that seam: reading the hook
payload, recognizing which repository and issue the request already names,
resolving the descriptor-store location the host composition configured, and
rendering the bounded routing notice. The decision itself is delegated to
:func:`resolve_governed_route_preflight`, which in turn delegates the lookup to
the existing #1237 read-only locator. Nothing here routes, authorizes,
persists, dispatches, or executes.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .governed_route_preflight import (
    GovernedRoutePreflightResult,
    GovernedRoutePreflightStatus,
    is_governed_checkout,
    resolve_governed_route_preflight,
)

#: Host composition supplies the existing #1218 descriptor store location.
#: There is deliberately no default: an unset value is "unavailable", not a
#: path for this adapter to invent.
STORE_ROOT_ENV = "AGENT_OS_CHECKPOINT_STORE_ROOT"
#: Optional explicit override for the governed repository identity.
REPOSITORY_ENV = "AGENT_OS_EXECUTION_INTERFACE_REPOSITORY"

_ISSUE_RE = re.compile(r"#(\d{1,7})(?![\w#])", re.ASCII)
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", re.ASCII)
_REMOTE_URL_RE = re.compile(
    r"github\.com[:/]+(?P<owner>[A-Za-z0-9_.-]+)/(?P<name>[A-Za-z0-9_.-]+?)(?:\.git)?\s*$",
    re.ASCII,
)
#: ``gh`` used as a standalone word: ``gh pr create``, ``which gh``,
#: ``command -v gh``, ``gh --version``. The guard is advisory-only, so a rare
#: false positive costs one extra context line and nothing else.
_LOCAL_GH_RE = re.compile(r"(?<![\w./-])gh(?![\w./-])", re.ASCII)

_MAX_PROMPT_BYTES = 65_536
_MAX_COMMAND_BYTES = 16_384
_MAX_GIT_CONFIG_BYTES = 262_144

_INVARIANT = (
    "Local `gh` availability is capability evidence about one execution surface "
    "only. A missing local `gh` is never evidence that Agent OS execution is "
    "unavailable and must not become a task blocker."
)
_NON_AUTHORITY = (
    "Discovery is a locator, not authorization or currentness. It grants no "
    "implementation, cloud, merge, issue-closure, or publication authority, and "
    "the identity must still pass the existing #1218/#1253 reconstruction, "
    "authorization, source/scope, checkpoint, ResumePlan, environment, and "
    "Scheduler lease checks before any execution."
)
_PUBLICATION_CONTINUATION = (
    "No existing handoff is a predecessor-publication condition, not evidence "
    "that the Agent OS mission is unavailable. Reacquire the current authorized "
    "mission and its canonical request, route, authorization, checkpoint, "
    "ResumePlan, CandidatePacket, runtime, dependency-readiness, and pilot "
    "evidence. If those current bindings select the governed runner, call the "
    "repository execution-interface adapter publish_current_pre_pr_handoff(...), "
    "which delegates to the existing #1243 publish_governed_handoff(...) owner. "
    "This advisory hook does not itself publish a handoff or complete external "
    "ChatGPT product integration. After durable publication, repeat discovery "
    "and resume only the exact immutable handoff returned. Do not synthesize a "
    "handoff identity. Do not fabricate a descriptor or handoff and do not "
    "silently fall back to local git/gh tooling."
)


def extract_issue_numbers(text: object) -> tuple[int, ...]:
    """Extract ``#<n>`` lookup keys from request text, in first-seen order.

    The extracted number is a lookup key for the existing locator and nothing
    else. Prompt text never becomes authorization, currentness, route
    selection, or command input on this path.
    """
    if type(text) is not str:
        return ()
    bounded = text[:_MAX_PROMPT_BYTES]
    seen: dict[int, None] = {}
    for match in _ISSUE_RE.finditer(bounded):
        value = int(match.group(1))
        if value >= 1:
            seen.setdefault(value, None)
    return tuple(seen)


def resolve_repository_identity(checkout_root: Path | str | None) -> str | None:
    """Resolve ``owner/name`` from explicit configuration, else the git remote.

    The git remote is read as a file; this adapter runs no subprocess and makes
    no network call.
    """
    configured = os.environ.get(REPOSITORY_ENV, "").strip()
    if configured:
        return configured if _REPOSITORY_RE.fullmatch(configured) else None
    if checkout_root is None:
        return None
    try:
        config_path = Path(checkout_root) / ".git" / "config"
        if not config_path.is_file():
            return None
        raw = config_path.read_text(encoding="utf-8", errors="replace")[
            :_MAX_GIT_CONFIG_BYTES
        ]
    except OSError:
        return None

    in_origin = False
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_origin = stripped.replace(" ", "").lower().startswith('[remote"origin"]')
            continue
        if not in_origin or not stripped.lower().startswith("url"):
            continue
        _, _, value = stripped.partition("=")
        match = _REMOTE_URL_RE.search(value.strip())
        if match is None:
            return None
        candidate = f"{match.group('owner')}/{match.group('name')}"
        return candidate if _REPOSITORY_RE.fullmatch(candidate) else None
    return None


def resolve_store_root() -> str | None:
    """Return the host-configured descriptor-store root, or ``None``."""
    value = os.environ.get(STORE_ROOT_ENV, "").strip()
    return value or None


def references_local_gh(command: object) -> bool:
    """Return whether a shell command uses the local ``gh`` CLI as a program."""
    if type(command) is not str:
        return False
    return _LOCAL_GH_RE.search(command[:_MAX_COMMAND_BYTES]) is not None


def render_preflight_notice(result: GovernedRoutePreflightResult) -> str:
    """Render the bounded routing notice, or the empty string when silent."""
    if type(result) is not GovernedRoutePreflightResult:
        raise TypeError("result must be an exact GovernedRoutePreflightResult")
    if result.status is GovernedRoutePreflightStatus.NOT_APPLICABLE:
        return ""

    reasons = ", ".join(item.value for item in result.reason_codes)
    header = (
        "Agent OS governed-route preflight (#1237) — resolved before generic "
        "GitHub publish tooling."
    )
    target = (
        f"repository={result.repository} issue=#{result.issue_number}"
        if result.repository and result.issue_number
        else f"repository={result.repository or 'unresolved'}"
    )

    if result.status is GovernedRoutePreflightStatus.GOVERNED_RESUME_AVAILABLE:
        body = (
            f"status=governed-resume-available {target}\n"
            f"Exactly one existing immutable handoff matched: {result.handoff_id}\n"
            f"Use the existing bounded governed resume ingress: {result.resume_command}\n"
            "Do not select generic GitHub publish tooling and do not check local "
            "git/gh prerequisites for this route.\n"
            "Preserve the existing branch/PR/checkpoint/invocation lineage; do not "
            "open a shadow lineage."
        )
    elif result.status is GovernedRoutePreflightStatus.NOT_FOUND:
        body = (
            f"status=publication-required {target} ({reasons})\n"
            "continuation=execution-interface-adapter owner=#1237 publication-owner=#1243 scheduler_invoked=false\n"
            f"{_PUBLICATION_CONTINUATION}"
        )
    else:
        body = (
            f"status=needs-decision {target} ({reasons})\n"
            "Fail closed. Do not choose a 'latest' or newest-looking descriptor, do "
            "not infer currentness from timestamps, issue status, or branch names, "
            "and do not silently fall back to local git/gh tooling."
        )
    return f"{header}\n{body}\n{_NON_AUTHORITY}\n{_INVARIANT}"


def _load_payload(raw: str) -> dict:
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except (TypeError, ValueError):
        return {}
    return payload if type(payload) is dict else {}


def _checkout_root(payload: dict) -> str:
    candidate = payload.get("cwd")
    if type(candidate) is str and candidate.strip():
        return candidate
    return os.environ.get("CLAUDE_PROJECT_DIR", "") or os.getcwd()


def run_user_prompt_submit_hook(raw_payload: str) -> str:
    """Resolve the governed route for a submitted request; stay silent if N/A."""
    payload = _load_payload(raw_payload)
    checkout_root = _checkout_root(payload)
    result = resolve_governed_route_preflight(
        checkout_root=checkout_root,
        repository=resolve_repository_identity(checkout_root),
        issue_numbers=extract_issue_numbers(payload.get("prompt")),
        store_root=resolve_store_root(),
    )
    return render_preflight_notice(result)


def run_pre_tool_use_hook(raw_payload: str) -> str:
    """Restate the #1237 invariant before a local ``gh`` command is treated as a gate.

    The guard never denies, never rewrites, and never grants permission; it only
    prevents a missing local CLI from being read as an Agent OS execution
    blocker. Non-Agent-OS checkouts and commands that do not use ``gh`` produce
    no output at all, so generic behavior is unchanged.
    """
    payload = _load_payload(raw_payload)
    if payload.get("tool_name") != "Bash":
        return ""
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if type(tool_input) is dict else None
    if not references_local_gh(command):
        return ""
    if not is_governed_checkout(_checkout_root(payload)):
        return ""
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": (
                    "Agent OS governed-route guard (#1237): "
                    f"{_INVARIANT} If this repository's governed route is selected, "
                    "use the existing bounded `/agent-os resume "
                    "executor-handoff:<sha256>` ingress instead of a local `gh` "
                    "prerequisite. Local CLI prerequisites apply only after a local "
                    "CLI surface has actually been selected."
                ),
            }
        },
        sort_keys=True,
        separators=(",", ":"),
    )
