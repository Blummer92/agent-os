"""Host-execution-interface hook adapter for governed Agent OS route re-entry.

Claude Code exposes repository-owned hooks at prompt submission, before tool use,
and at turn stop. This module owns only those host-shaped edges. It never grants
authority, persists state, or implements a second continuation classifier.

The Stop seam consumes an already-structured continuation observation and reuses
the bounded #2137 continuation driver. If no structured observation is supplied,
the evaluator fails, the mission is terminal/blocked/stalled, or the host is
already processing a blocked Stop, the hook allows the turn to end. This keeps
the seam finite and fail-open while still preventing an unfinished authorized
mission from silently ending when the host has already produced an executable
next action.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from .continuation_driver import (
    ContinuationDecision,
    drive_governed_continuation,
)
from .governed_route_preflight import (
    GovernedRoutePreflightReason,
    GovernedRoutePreflightResult,
    GovernedRoutePreflightStatus,
    is_governed_checkout,
    resolve_governed_route_preflight,
)

STORE_ROOT_ENV = "AGENT_OS_CHECKPOINT_STORE_ROOT"
REPOSITORY_ENV = "AGENT_OS_EXECUTION_INTERFACE_REPOSITORY"

_ISSUE_RE = re.compile(r"#(\d{1,7})(?![\w#])", re.ASCII)
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", re.ASCII)
# GitHub remote forms only: scp-like ``git@github.com:owner/name`` and
# ``https|ssh://[userinfo@]host[:port]/owner/name``. The URL is parsed (not
# searched) so the real host is checked: ``github.com`` (or ``ssh.github.com`` for
# ssh), never a look-alike host or a ``#``/``?``/``\\`` userinfo trick.
_SCP_REMOTE_RE = re.compile(
    r"^(?:[A-Za-z0-9_.-]+@)?github\.com:(?P<path>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$",
    re.ASCII | re.IGNORECASE,
)
_REMOTE_PATH_RE = re.compile(
    r"^/(?P<path>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$", re.ASCII
)
_REMOTE_HOSTS = {"https": frozenset({"github.com"}), "ssh": frozenset({"github.com", "ssh.github.com"})}
_REMOTE_PORTS = {"https": frozenset({443}), "ssh": frozenset({22, 443})}
_LOCAL_GH_RE = re.compile(r"(?<![\w./-])gh(?![\w./-])", re.ASCII)
_GOVERNED_MUTATION_TOOL_RE = re.compile(
    r"^(?:Bash|Edit|Write|NotebookEdit|mcp__github__.*|mcp__notion__.*|mcp__google_drive__.*|mcp__google_calendar__.*|mcp__gmail__.*)$",
    re.ASCII,
)

_MAX_PROMPT_BYTES = 65_536
_MAX_COMMAND_BYTES = 16_384
_MAX_GIT_CONFIG_BYTES = 262_144
_MAX_GIT_POINTER_BYTES = 4_096
MAX_CONSECUTIVE_STOP_BLOCKS = 1

_INVARIANT = (
    "Local `gh` availability is capability evidence about one execution surface "
    "only. A missing local `gh` is never evidence that Agent OS execution is "
    "unavailable and must not become a task blocker."
)
_NON_AUTHORITY = (
    "Discovery and continuation routing are not authorization or currentness. "
    "They grant no implementation, execution, GitHub-write, merge, issue-closure, "
    "publication, production, credential, or external-write authority."
)
_PUBLICATION_CONTINUATION = (
    "No existing handoff is a predecessor-publication condition, not evidence "
    "that the Agent OS mission is unavailable. Reacquire the current authorized "
    "mission and its canonical request, route, authorization, checkpoint, "
    "ResumePlan, CandidatePacket, runtime, dependency-readiness, and pilot "
    "evidence. If those current bindings select the governed runner, call the "
    "repository execution-interface adapter publish_current_pre_pr_handoff(...), "
    "which delegates to the existing #1243 publish_governed_handoff(...) owner. "
    "This advisory hook does not itself publish a handoff. After durable "
    "publication, repeat discovery and resume only the exact immutable handoff "
    "returned. Do not synthesize a handoff identity and do not silently fall "
    "back to local git/gh tooling."
)


_SURFACE_CAPABILITY_REASONS = frozenset(
    {
        GovernedRoutePreflightReason.DESCRIPTOR_STORE_NOT_CONFIGURED,
        GovernedRoutePreflightReason.DISCOVERY_STORE_UNAVAILABLE,
        GovernedRoutePreflightReason.DISCOVERY_DEPENDENCY_UNAVAILABLE,
    }
)
_SURFACE_CAPABILITY_SCOPE = (
    "Scope: the governed-resume route is simply unavailable on this execution "
    "surface (capability evidence; no owner decision is requested for it). This "
    "does not relax the fail-closed instruction above: do not fall back to local "
    "git/gh for governed resume or publication, and it authorizes no GitHub write. "
    "It also does not revoke authorization the owner already gave for read-only or "
    "local worktree work; a surface with the descriptor store (for example the "
    "fixed Codespaces route) owns governed resume."
)
_IDENTITY_GAP_SCOPE = (
    "Scope: repository identity could not be established from a validated GitHub "
    "`origin` remote (ordinary clone or linked worktree) or "
    f"{REPOSITORY_ENV}. This is an identity gap, not a mission decision: repair the "
    "checkout metadata, or have the owner set that variable. Never infer the repository from "
    "a directory name or prompt text."
)


def extract_issue_numbers(text: object) -> tuple[int, ...]:
    if type(text) is not str:
        return ()
    bounded = text[:_MAX_PROMPT_BYTES]
    seen: dict[int, None] = {}
    for match in _ISSUE_RE.finditer(bounded):
        value = int(match.group(1))
        if value >= 1:
            seen.setdefault(value, None)
    return tuple(seen)


def _read_pointer_file(path: Path) -> str | None:
    """Read a tiny git metadata file (``.git``, ``commondir``, ``gitdir``) or fail closed."""
    try:
        if not path.is_file():
            return None
        with path.open("rb") as handle:
            data = handle.read(_MAX_GIT_POINTER_BYTES + 1)
        if len(data) > _MAX_GIT_POINTER_BYTES or b"\0" in data:
            return None
        return data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _resolve_dir(base: Path, value: str) -> Path | None:
    target = Path(value)
    try:
        resolved = (target if target.is_absolute() else base / target).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    return resolved if resolved.is_dir() else None


def _linked_worktree_config(checkout: Path, dot_git: Path) -> Path | None:
    """Locate the shared config of a validated ``git worktree`` checkout.

    A linked worktree's ``.git`` is a one-line ``gitdir: <common>/worktrees/<id>``
    file and ``remote.origin`` lives in the common directory. The pointer is only
    trusted when it round-trips: the admin dir's ``commondir`` must name its own
    grandparent and its ``gitdir`` back-link must name this checkout's ``.git``.
    Separate-git-dir, submodule, copied, or stale pointers fail closed.
    """
    raw = _read_pointer_file(dot_git)
    if raw is None:
        return None
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) != 1 or not lines[0].startswith("gitdir:"):
        return None
    admin = _resolve_dir(checkout, lines[0][len("gitdir:"):].strip())
    if admin is None or admin.parent.name != "worktrees":
        return None
    common = admin.parent.parent

    commondir_raw = _read_pointer_file(admin / "commondir")
    if commondir_raw is None or _resolve_dir(admin, commondir_raw.strip()) != common:
        return None
    backlink_raw = _read_pointer_file(admin / "gitdir")
    if backlink_raw is None:
        return None
    backlink = Path(backlink_raw.strip())
    try:
        # Git >= 2.48 may store a path relative to the admin dir.
        if (backlink if backlink.is_absolute() else admin / backlink).resolve(strict=True) != dot_git.resolve(strict=True):
            return None
    except (OSError, RuntimeError):
        return None
    return common / "config"


def _git_config_path(checkout_root: Path | str) -> Path | None:
    checkout = Path(checkout_root)
    dot_git = checkout / ".git"
    try:
        if dot_git.is_dir():
            return dot_git / "config"
        if dot_git.is_file():
            return _linked_worktree_config(checkout, dot_git)
    except OSError:
        return None
    return None


def _parse_github_remote(url: str) -> str | None:
    url = url.strip()
    if not url or any(character in url for character in "\\ \t\r\n\0"):
        return None
    if "://" not in url:
        match = _SCP_REMOTE_RE.fullmatch(url)
        candidate = match.group("path") if match else None
    else:
        try:
            parts = urlsplit(url)
            scheme = parts.scheme.lower()
            port = parts.port
        except ValueError:
            return None
        if (
            scheme not in _REMOTE_HOSTS
            or (parts.hostname or "") not in _REMOTE_HOSTS[scheme]
            or (port is not None and port not in _REMOTE_PORTS[scheme])
            or parts.query
            or parts.fragment
        ):
            return None
        match = _REMOTE_PATH_RE.fullmatch(parts.path)
        candidate = match.group("path") if match else None
    if candidate is None or any(part in {".", "..", ".git"} for part in candidate.split("/")):
        return None
    return candidate if _REPOSITORY_RE.fullmatch(candidate) else None


def resolve_repository_identity(checkout_root: Path | str | None) -> str | None:
    """Resolve ``owner/name`` from the checkout's ``origin`` remote, failing closed.

    Supports ordinary clones (``.git`` directory) and validated linked worktrees
    (``.git`` pointer file). Absent, malformed, unvalidated, non-GitHub, or
    conflicting origin URLs return ``None``; the directory name is never used.
    """
    configured = os.environ.get(REPOSITORY_ENV, "").strip()
    if configured:
        return configured if _REPOSITORY_RE.fullmatch(configured) else None
    if checkout_root is None:
        return None
    config_path = _git_config_path(checkout_root)
    if config_path is None:
        return None
    try:
        if not config_path.is_file():
            return None
        with config_path.open("rb") as handle:
            data = handle.read(_MAX_GIT_CONFIG_BYTES + 1)
    except OSError:
        return None
    if len(data) > _MAX_GIT_CONFIG_BYTES:
        return None
    raw = data.decode("utf-8", errors="replace")

    in_origin = False
    candidates: set[str | None] = set()
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_origin = stripped.replace(" ", "").lower().startswith('[remote"origin"]')
            continue
        if not in_origin:
            continue
        key, separator, value = stripped.partition("=")
        if separator and key.strip().lower() == "url":
            candidates.add(_parse_github_remote(value))
    if len(candidates) != 1:
        return None
    return next(iter(candidates))


def resolve_store_root() -> str | None:
    value = os.environ.get(STORE_ROOT_ENV, "").strip()
    return value or None


def references_local_gh(command: object) -> bool:
    if type(command) is not str:
        return False
    return _LOCAL_GH_RE.search(command[:_MAX_COMMAND_BYTES]) is not None


def render_preflight_notice(result: GovernedRoutePreflightResult) -> str:
    if type(result) is not GovernedRoutePreflightResult:
        raise TypeError("result must be an exact GovernedRoutePreflightResult")
    if result.status is GovernedRoutePreflightStatus.NOT_APPLICABLE:
        return ""

    reasons = ", ".join(item.value for item in result.reason_codes)
    header = "Agent OS governed-route preflight (#1237) — resolved before generic GitHub publish tooling."
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
            "Do not select generic GitHub publish tooling and do not check local git/gh prerequisites for this route.\n"
            "Preserve the existing branch/PR/checkpoint/invocation lineage; do not open a shadow lineage."
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
            "Fail closed. Do not choose a 'latest' descriptor, infer currentness from timestamps, issue status, or branch names, or silently fall back to local git/gh tooling."
        )
        reason_set = set(result.reason_codes)
        if reason_set and reason_set <= _SURFACE_CAPABILITY_REASONS:
            body += f"\n{_SURFACE_CAPABILITY_SCOPE}"
        elif reason_set == {GovernedRoutePreflightReason.REPOSITORY_IDENTITY_UNRESOLVED}:
            body += f"\n{_IDENTITY_GAP_SCOPE}"
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
    payload = _load_payload(raw_payload)
    checkout_root = _checkout_root(payload)
    result = resolve_governed_route_preflight(
        checkout_root=checkout_root,
        repository=resolve_repository_identity(checkout_root),
        issue_numbers=extract_issue_numbers(payload.get("prompt")),
        store_root=resolve_store_root(),
    )
    return render_preflight_notice(result)


def _is_governed_mutation_tool(tool_name: object) -> bool:
    return type(tool_name) is str and _GOVERNED_MUTATION_TOOL_RE.fullmatch(tool_name) is not None


def run_pre_tool_use_hook(raw_payload: str) -> str:
    """Restate governed-route invariants before a mutation-capable tool executes."""
    payload = _load_payload(raw_payload)
    tool_name = payload.get("tool_name")
    if not _is_governed_mutation_tool(tool_name):
        return ""
    if not is_governed_checkout(_checkout_root(payload)):
        return ""

    if tool_name == "Bash":
        tool_input = payload.get("tool_input")
        command = tool_input.get("command") if type(tool_input) is dict else None
        if not references_local_gh(command):
            return ""

    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": (
                    "Agent OS governed-route guard (#1237/#2139): "
                    f"{_INVARIANT} {_NON_AUTHORITY} Reacquire current repository, "
                    "authorization, scope, checkpoint, and execution evidence before "
                    "any governed mutation."
                ),
            }
        },
        sort_keys=True,
        separators=(",", ":"),
    )


class _StopObservationAdapter:
    def __init__(self, observation: dict) -> None:
        self.observation = observation
        self.actions: list[str] = []

    def observe(self) -> object:
        return self.observation

    def dispatch(self, action: str) -> None:
        # Stop hooks never execute the action. Blocking the stop returns the
        # exact action to the host/model so the still-authorized turn can continue.
        self.actions.append(action)


def _structured_continuation_decision(observation: object) -> ContinuationDecision:
    """Decode a host-produced structured continuation decision without NLP."""
    if type(observation) is not dict:
        raise ValueError("structured continuation observation is required")
    action = observation.get("action", "")
    terminal = observation.get("terminal", False)
    blocked = observation.get("blocked", False)
    stalled = observation.get("stalled", False)
    reason_codes = observation.get("reason_codes", [])
    if type(action) is not str:
        raise TypeError("continuation action must be a string")
    if type(terminal) is not bool or type(blocked) is not bool or type(stalled) is not bool:
        raise TypeError("continuation flags must be booleans")
    if type(reason_codes) is not list or any(type(item) is not str for item in reason_codes):
        raise TypeError("continuation reason_codes must be a string list")
    return ContinuationDecision(
        action=action,
        terminal=terminal,
        blocked=blocked,
        stalled=stalled,
        reason_codes=tuple(reason_codes),
    )


def run_stop_hook(raw_payload: str) -> str:
    """Block one premature Stop when a structured authorized next action exists.

    The host supplies ``agent_os_continuation`` as structured output from the
    canonical continuation/completion classification path. This adapter does not
    infer mission state from transcript prose. ``stop_hook_active`` is the host's
    re-entry marker; once true, the explicit one-block ceiling allows the stop so
    the hook can never trap a turn. Any evaluator/shape error also fails open.
    """
    payload = _load_payload(raw_payload)
    if not is_governed_checkout(_checkout_root(payload)):
        return ""
    if payload.get("stop_hook_active") is True:
        return ""

    observation = payload.get("agent_os_continuation")
    if type(observation) is not dict:
        return ""

    try:
        adapter = _StopObservationAdapter(observation)
        result = drive_governed_continuation(
            adapter,
            _structured_continuation_decision,
            max_transitions=MAX_CONSECUTIVE_STOP_BLOCKS,
        )
    except Exception:
        return ""

    if result.status != "recovery-stalled" or not result.transitions:
        return ""
    # A one-transition drive reaches its finite bound after recording the exact
    # executable action. That is the one case where Stop should be blocked once.
    action = result.transitions[-1]
    reason_codes = ",".join(result.reason_codes) if result.reason_codes else "authorized-next-action"
    return json.dumps(
        {
            "decision": "block",
            "reason": (
                f"Agent OS continuation (#2139): continue the still-authorized mission with `{action}` "
                f"before ending the turn ({reason_codes}). {_NON_AUTHORITY}"
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
