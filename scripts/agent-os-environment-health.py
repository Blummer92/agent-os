#!/usr/bin/env python3
"""Bounded, fail-closed health check for the agent-os-codespaces-v1 profile.

Single-command, deterministic evidence report. Performs no retries, no
silent runtime substitution, and no GitHub/network writes. See
`docs/AGENT_OS_CODESPACES_RUNBOOK.md` for the operator-facing contract and
`scripts/verify-repo-state-contract.md` / `scripts/prepare-issue-worktree-contract.md`
for the repository-state and worktree contracts this check reuses rather than
re-implements.

Exit codes: 0 pass, 1 one or more checks failed (fail-closed), 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

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

# Bounded prohibited-credential patterns. This scans only the evidence this
# script is about to emit -- it is not a repository-wide secret scanner and
# does not duplicate `run_secret_scanning`-style tooling.
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

# All authority fields stay false; only a separate canonical authorization
# contract may change them, matching prepare-issue-worktree.sh's convention.
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


def check_repository_identity(repo_root: Path) -> dict:
    ok, origin_url = _run(["git", "remote", "get-url", "origin"], cwd=repo_root)
    actual = None
    if ok:
        stripped = origin_url.strip()
        stripped = stripped[:-4] if stripped.endswith(".git") else stripped
        match = re.search(r"[:/]([^/:]+/[^/:]+)$", stripped)
        actual = match.group(1) if match else stripped
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

    # Fail closed only when the *primary* (non-linked) checkout has been
    # renamed to impersonate the reserved `issue-<n>` worktree naming
    # convention from scripts/prepare-issue-worktree-contract.md -- a real
    # linked worktree at that path is the expected, passing case.
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
            tools[name] = {"available": False, "version": None}
            all_ok = False
            continue
        ok, version = _run([name, "--version"])
        tools[name] = {"available": ok, "version": version if ok else None}
        all_ok = all_ok and ok
    tools["python"] = {"available": True, "version": sys.version.split()[0]}
    return {"name": "tooling", "passed": all_ok, "detail": tools}


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


def check_github_auth_capability() -> dict:
    import os

    if os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
        return {
            "name": "github-auth-capability",
            "passed": True,
            "detail": {"capable": True, "source": "env"},
        }
    gh_path = shutil.which("gh")
    if gh_path is not None:
        try:
            result = subprocess.run(
                ["gh", "auth", "status"],
                check=False,
                text=True,
                capture_output=True,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
            capable = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            capable = False
        return {
            "name": "github-auth-capability",
            "passed": capable,
            "detail": {"capable": capable, "source": "gh-cli"},
        }
    return {
        "name": "github-auth-capability",
        "passed": False,
        "detail": {"capable": False, "source": "none"},
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


def build_evidence(repo_root: Path, network_mode: str, min_free_mb: int) -> dict:
    checks = [
        check_repository_identity(repo_root),
        check_checkout_identity(repo_root),
        check_tooling(repo_root),
        check_disk_space(repo_root, min_free_mb),
        check_validation_commands(repo_root),
        check_github_auth_capability(),
    ]
    failures = [c["name"] for c in checks if not c["passed"]]
    evidence = {
        "schema": SCHEMA,
        "profile_id": PROFILE_ID,
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
    return redacted_evidence


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument(
        "--network-mode",
        choices=("local-only", "github-connected"),
        default=None,
    )
    parser.add_argument("--min-free-mb", type=int, default=DEFAULT_MIN_FREE_MB)
    parser.add_argument("--check", choices=("repository-identity",), default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    import os

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

    evidence = build_evidence(repo_root, network_mode, args.min_free_mb)
    print(json.dumps(evidence, sort_keys=True, indent=2))
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
