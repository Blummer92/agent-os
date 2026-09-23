#!/usr/bin/env python3
"""Bounded, fail-closed health check for the agent-os-codespaces-v1 profile.

Single-command evidence report. Performs no retries, no silent runtime
substitution, and no GitHub/network writes. See
`docs/AGENT_OS_CODESPACES_RUNBOOK.md` for the operator-facing contract and
`scripts/verify-repo-state-contract.md` / `scripts/prepare-issue-worktree-contract.md`
for the repository-state and worktree contracts this check reuses rather than
re-implements.

Exit codes: 0 pass, 1 one or more checks failed (fail-closed), 2 usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = "agent-os.environment-health.v1"
PROFILE_ID = "agent-os-codespaces-v1"
EXPECTED_REPOSITORY = "Blummer92/agent-os"
REQUIRED_TOOLS = ("git", "pip", "gh")
REQUIRED_VALIDATION_COMMANDS = (
    "scripts/validate-all.sh",
    "07_Agent_Tests/validate-repo-structure.sh",
    "scripts/verify-repo-state.sh",
    "scripts/prepare-issue-worktree.sh",
)
DEFAULT_MIN_FREE_MB = 500
SUBPROCESS_TIMEOUT_SECONDS = 5
MAX_TOOL_VERSION_CHARS = 120
#: One bounded read-only direct GitHub API probe, distinct from generic
#: connector/CLI/token-presence evidence (#1401 / #1363). Overridable only
#: for isolated, offline test fixtures -- never for a live credential swap.
GITHUB_API_PROBE_TIMEOUT_SECONDS = 5
DEFAULT_GITHUB_API_PROBE_URL = "https://api.github.com/user"
_REPOSITORY_COMPONENT = re.compile(r"[A-Za-z0-9_.-]+")
_SURFACE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
_OBSERVED_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

_CREDENTIAL_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"https?://[^/\s:@]+:[^@\s/]+@",
        r"gh[oprsu]_[A-Za-z0-9]{20,}",
        r"github_pat_[A-Za-z0-9_]{20,}",
        r"sk-[A-Za-z0-9]{20,}",
        r"AKIA[0-9A-Z]{16}",
        r"xox[baprs]-[A-Za-z0-9-]{10,}",
        r"AIza[0-9A-Za-z\-_]{35}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    )
)

_AUTHORITY_FIELDS = {
    "repository_implementation_authorized": False,
    "execution_authorized": False,
    "github_writes_authorized": False,
    "ready_for_review_authorized": False,
    "merge_authorized": False,
    "issue_closure_authorized": False,
    "production_authorized": False,
    "external_writes_authorized": False,
}


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=False,
            text=True,
            capture_output=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()[:200]
    return True, (result.stdout or "").strip().splitlines()[0] if result.stdout.strip() else ""


def _canonicalize_repository_remote(origin_url: str) -> str | None:
    """Return only a validated GitHub owner/repository identity or ``None``."""
    remote = origin_url.strip()
    if not remote or any(character.isspace() for character in remote):
        return None

    owner_repo: str | None = None
    scp_match = re.fullmatch(r"[^@/:\s]+@github\.com:([^?#]+)(?:[?#].*)?", remote)
    if scp_match:
        owner_repo = scp_match.group(1)
    else:
        try:
            parsed = urlsplit(remote)
        except ValueError:
            return None
        try:
            hostname = parsed.hostname
            port = parsed.port
        except ValueError:
            return None
        if parsed.scheme not in {"https", "ssh"} or hostname != "github.com":
            return None
        if port not in {None, 22, 443}:
            return None
        owner_repo = parsed.path.lstrip("/")

    if owner_repo.endswith(".git"):
        owner_repo = owner_repo[:-4]
    parts = owner_repo.split("/")
    if len(parts) != 2 or not all(_REPOSITORY_COMPONENT.fullmatch(part) for part in parts):
        return None
    return f"{parts[0]}/{parts[1]}"


def _canonical_observed_at(value: str | None = None) -> str:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if not _OBSERVED_AT.fullmatch(value):
        raise ValueError("observed_at must be canonical UTC YYYY-MM-DDTHH:MM:SSZ")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("observed_at must be a valid UTC timestamp") from exc
    return parsed.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_surface_id(value: str) -> str:
    candidate = value.strip()
    if not _SURFACE_ID.fullmatch(candidate):
        raise ValueError("execution surface id must match [A-Za-z0-9_.:-]{1,80}")
    return candidate


def _execution_surface_id(repo_root: Path, explicit: str | None = None) -> str:
    if explicit:
        return _normalize_surface_id(explicit)
    configured = os.environ.get("AGENT_OS_EXECUTION_SURFACE_ID")
    if configured:
        return _normalize_surface_id(configured)
    codespace = os.environ.get("CODESPACE_NAME")
    if codespace:
        return _normalize_surface_id(f"codespace:{codespace}")
    local_material = f"{socket.gethostname()}\n{repo_root.resolve()}"
    digest = hashlib.sha256(local_material.encode("utf-8")).hexdigest()[:24]
    return f"local:{digest}"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _environment_evidence_id(evidence_without_id: dict) -> str:
    material = {
        key: value
        for key, value in evidence_without_id.items()
        if key != "environment_health_evidence_id"
    }
    payload = "agent-os.environment-health.v1\n" + _canonical_json(material)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def evidence_matches_surface(evidence: dict, execution_surface_id: str) -> bool:
    """Return true only when supplied evidence names the expected surface."""
    try:
        expected = _normalize_surface_id(execution_surface_id)
    except ValueError:
        return False
    return evidence.get("execution_surface_id") == expected


def check_repository_identity(repo_root: Path) -> dict:
    ok, origin_url = _run(["git", "remote", "get-url", "origin"], cwd=repo_root)
    actual = _canonicalize_repository_remote(origin_url) if ok else None
    matches = ok and actual == EXPECTED_REPOSITORY
    return {
        "name": "repository-identity",
        "passed": matches,
        "detail": {"expected": EXPECTED_REPOSITORY, "actual": actual},
    }


def check_checkout_identity(repo_root: Path) -> dict:
    sha_ok, head_sha = _run(["git", "rev-parse", "HEAD"], cwd=repo_root)
    branch_ok, branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)
    git_dir_ok, git_dir = _run(["git", "rev-parse", "--git-dir"], cwd=repo_root)
    common_dir_ok, common_dir = _run(["git", "rev-parse", "--git-common-dir"], cwd=repo_root)

    is_linked_worktree = (
        git_dir_ok
        and common_dir_ok
        and (repo_root / git_dir).resolve() != (repo_root / common_dir).resolve()
    )
    looks_like_issue_worktree_path = bool(re.fullmatch(r"issue-\d+", repo_root.name))
    worktree_role = "issue-worktree" if is_linked_worktree else "primary"
    primary_not_reused = not (worktree_role == "primary" and looks_like_issue_worktree_path)

    passed = sha_ok and branch_ok and git_dir_ok and common_dir_ok and primary_not_reused
    return {
        "name": "checkout-identity",
        "passed": passed,
        "detail": {
            "head_sha": head_sha if sha_ok else None,
            "branch": branch if branch_ok else None,
            "worktree_role": worktree_role,
            "primary_checkout_not_reused_as_issue_worktree": primary_not_reused,
        },
    }


def check_tooling(repo_root: Path) -> dict:
    tools = {}
    all_ok = True
    for name in REQUIRED_TOOLS:
        path = shutil.which(name)
        if path is None:
            tools[name] = {"available": False, "state": "unavailable", "version": None}
            all_ok = False
            continue
        ok, version = _run([name, "--version"])
        tools[name] = {
            "available": ok,
            "state": "available" if ok else "unknown",
            "version": version[:MAX_TOOL_VERSION_CHARS] if ok else None,
        }
        all_ok = all_ok and ok
    tools["python"] = {
        "available": True,
        "state": "available",
        "version": sys.version.split()[0],
    }
    return {"name": "tooling", "passed": all_ok, "detail": tools}


def check_process_execution() -> dict:
    ok, _ = _run([sys.executable, "-c", "pass"])
    return {
        "name": "process-execution",
        "passed": ok,
        "detail": {
            "state": "available" if ok else "unknown",
            "mechanism": "python-subprocess",
        },
    }


def check_disk_space(repo_root: Path, min_free_mb: int) -> dict:
    usage = shutil.disk_usage(repo_root)
    free_mb = usage.free // (1024 * 1024)
    sufficient = free_mb >= min_free_mb
    return {
        "name": "disk-space",
        "passed": sufficient,
        "detail": {"free_mb": int(free_mb), "min_required_mb": min_free_mb},
    }


def check_validation_commands(repo_root: Path) -> dict:
    presence = {cmd: (repo_root / cmd).is_file() for cmd in REQUIRED_VALIDATION_COMMANDS}
    return {"name": "validation-commands", "passed": all(presence.values()), "detail": presence}


def _github_api_probe_url() -> str:
    return os.environ.get(
        "AGENT_OS_GITHUB_API_PROBE_URL", DEFAULT_GITHUB_API_PROBE_URL
    )


def _probe_github_api_authentication(token: str) -> str:
    """Perform exactly one bounded, read-only, credentialed GitHub API GET.

    Returns ``"authenticated"``, ``"unauthenticated"``, or ``"unknown"``.
    Never retries and never raises; the token, request headers, and response
    body never appear in the returned state.
    """
    request = urllib.request.Request(
        _github_api_probe_url(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "agent-os-environment-health",
        },
    )
    try:
        with urllib.request.urlopen(
            request, timeout=GITHUB_API_PROBE_TIMEOUT_SECONDS
        ) as response:
            return "authenticated" if response.status == 200 else "unknown"
    except urllib.error.HTTPError as exc:
        return "unauthenticated" if exc.code in (401, 403) else "unknown"
    except (urllib.error.URLError, OSError, TimeoutError):
        return "unknown"


def check_github_auth_capability(network_mode: str) -> dict:
    """Report direct authenticated GitHub API capability, never generic
    connector/token-presence evidence (#1401, regression for #1363).

    `local-only` performs no network probe -- the capability is simply not
    applicable to that mode. `github-connected` performs exactly one bounded
    read-only authenticated read through the effective token credential path;
    token presence alone is never treated as proof of authentication, and a
    401/403/network error/timeout fails closed to a non-passing state.
    """
    if network_mode == "local-only":
        return {
            "name": "github-auth-capability",
            "passed": True,
            "detail": {
                "capable": False,
                "state": "not-applicable",
                "source": "not-applicable",
            },
        }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return {
            "name": "github-auth-capability",
            "passed": False,
            "detail": {"capable": False, "state": "no-credential", "source": "none"},
        }
    state = _probe_github_api_authentication(token)
    capable = state == "authenticated"
    return {
        "name": "github-auth-capability",
        "passed": capable,
        "detail": {"capable": capable, "state": state, "source": "direct-api"},
    }


def _redact(value):
    if isinstance(value, str):
        for pattern in _CREDENTIAL_PATTERNS:
            if pattern.search(value):
                return "[REDACTED]", True
        return value, False
    if isinstance(value, dict):
        redacted_any = False
        out = {}
        for key, val in value.items():
            new_val, redacted = _redact(val)
            out[key] = new_val
            redacted_any = redacted_any or redacted
        return out, redacted_any
    if isinstance(value, list):
        redacted_any = False
        out = []
        for item in value:
            new_item, redacted = _redact(item)
            out.append(new_item)
            redacted_any = redacted_any or redacted
        return out, redacted_any
    return value, False


def build_evidence(
    repo_root: Path,
    network_mode: str,
    min_free_mb: int,
    execution_surface_id: str | None = None,
    observed_at: str | None = None,
) -> dict:
    surface_id = _execution_surface_id(repo_root, execution_surface_id)
    timestamp = _canonical_observed_at(observed_at)
    checks = [
        check_repository_identity(repo_root),
        check_checkout_identity(repo_root),
        check_tooling(repo_root),
        check_process_execution(),
        check_disk_space(repo_root, min_free_mb),
        check_validation_commands(repo_root),
        check_github_auth_capability(network_mode),
    ]
    failures = [check["name"] for check in checks if not check["passed"]]
    evidence = {
        "schema": SCHEMA,
        "profile_id": PROFILE_ID,
        "execution_surface_id": surface_id,
        "observed_at": timestamp,
        "network_mode": network_mode,
        "checks": checks,
        "failures": failures,
        "authority": dict(_AUTHORITY_FIELDS),
        "status": "pass" if not failures else "fail",
    }
    redacted_evidence, credential_found = _redact(evidence)
    if credential_found:
        redacted_evidence["status"] = "fail"
        redacted_evidence["failures"] = list(redacted_evidence["failures"]) + [
            "prohibited-credential-material-detected"
        ]
    redacted_evidence["environment_health_evidence_id"] = _environment_evidence_id(
        redacted_evidence
    )
    return redacted_evidence


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument(
        "--network-mode",
        choices=("local-only", "github-connected"),
        default=None,
    )
    parser.add_argument("--execution-surface-id", default=None)
    parser.add_argument("--min-free-mb", type=int, default=DEFAULT_MIN_FREE_MB)
    parser.add_argument("--check", choices=("repository-identity",), default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.min_free_mb <= 0:
        print(json.dumps({"error": "--min-free-mb must be a positive integer"}))
        return 2

    repo_root = args.repo_root or Path(__file__).resolve().parent.parent
    if not (repo_root / ".git").exists():
        print(json.dumps({"error": f"not a git checkout: {repo_root}"}))
        return 2

    network_mode = args.network_mode or os.environ.get("AGENT_OS_NETWORK_MODE", "local-only")
    if network_mode not in ("local-only", "github-connected"):
        print(json.dumps({"error": f"unsupported network mode: {network_mode}"}))
        return 2

    if args.check == "repository-identity":
        result = check_repository_identity(repo_root)
        redacted_result, credential_found = _redact(result)
        if credential_found:
            redacted_result["passed"] = False
        print(json.dumps(redacted_result, sort_keys=True))
        return 0 if redacted_result["passed"] else 1

    try:
        evidence = build_evidence(
            repo_root,
            network_mode,
            args.min_free_mb,
            execution_surface_id=args.execution_surface_id,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2

    print(json.dumps(evidence, sort_keys=True, indent=2))
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
