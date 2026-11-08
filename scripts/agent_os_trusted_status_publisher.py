"""Default-branch-only, data-only publisher for a future trusted CI status.

This is a staged, non-required status; no existing merge rule is changed by it.
Never execute source-run code, checked-out PR code, or downloaded artifacts here.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

CONTEXT = "agent-os/trusted-aggregate-pilot"
SOURCE_PATH = ".github/workflows/agent-os-validation.yml"
# Changes to CI authority need an independently governed change path before this
# pilot status can be required. Conservatively reject source-trust modifications.
AUTHORITY_PATHS = frozenset({
    SOURCE_PATH,
    ".github/workflows/agent-os-trusted-status-pilot.yml",
    "scripts/agent_os_trusted_status_publisher.py",
    "scripts/validate-all.sh",
    "scripts/agent_os_aggregate_gate.py",
    "scripts/agent_os_ci_test_completeness.py",
    "scripts/agent_os_ci_junit_diff.py",
    "scripts/agent_os_frontend_checks.py",
})
AUTHORITY_PREFIXES = ("scripts/agent_os_ci_", "scripts/agent_os_remote_validation/")
AUTHORITY_SUFFIXES = ("/conftest.py",)


def touches_authority(paths: set[str]) -> bool:
    return any(
        path in AUTHORITY_PATHS
        or path in {"pytest.ini", "pyproject.toml", "tests/conftest.py", "07_Agent_Tests/validate-repo-structure.sh"}
        or path.startswith(AUTHORITY_PREFIXES)
        or path.endswith(AUTHORITY_SUFFIXES)
        for path in paths
    )


JOBS = (
    "Run validation plan",
    "Run aggregate validation",
    "Run frontend checks",
    "Agent OS aggregate gate",
)
REQUIRED_STEPS = {
    "Run aggregate validation": (
        "Verify aggregate checkout identity",
        "Run aggregate validation",
        "Upload aggregate JUnit evidence",
    ),
    "Run frontend checks": ("Run applicable frontend checks",),
    "Agent OS aggregate gate": ("Enforce authoritative aggregate disposition",),
}
SHA = re.compile(r"[0-9a-f]{40}\Z")


def result(state: str | None, description: str) -> dict[str, Any]:
    return {"state": state, "description": description[:140], "context": CONTEXT}


def api(endpoint: str) -> Any:
    """Read provider-owned GitHub objects; never print response on API failure."""
    p = subprocess.run(["gh", "api", endpoint], text=True, capture_output=True, check=False, timeout=45)
    if p.returncode:
        raise RuntimeError("GitHub provider request failed")
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub provider response is invalid JSON") from exc


def jobs_for_attempt(repository: str, run_id: int, attempt: int) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for page in range(1, 21):
        data = api(f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page={page}")
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError("provider jobs payload is malformed")
        batch = data["jobs"]
        jobs.extend(batch)
        if len(batch) < 100:
            return jobs
    raise ValueError("provider jobs pagination incomplete")


def changed_paths(repository: str, pr_number: int) -> set[str]:
    paths: set[str] = set()
    for page in range(1, 21):
        data = api(f"repos/{repository}/pulls/{pr_number}/files?per_page=100&page={page}")
        if not isinstance(data, list):
            raise ValueError("provider files payload is malformed")
        for f in data:
            if not isinstance(f, dict) or not isinstance(f.get("filename"), str):
                raise ValueError("provider file entry is malformed")
            paths.add(f["filename"])
            if isinstance(f.get("previous_filename"), str):
                paths.add(f["previous_filename"])
        if len(data) < 100:
            if not paths:
                raise ValueError("PR changed-file set is empty")
            return paths
    raise ValueError("provider files pagination incomplete")


def lookup_pr(repository: str, head_sha: str, branch: str) -> dict[str, Any] | None:
    data = api(f"repos/{repository}/commits/{head_sha}/pulls?per_page=100")
    if not isinstance(data, list):
        raise ValueError("provider associated PRs payload is malformed")
    matches = [p for p in data if isinstance(p, dict)
               and p.get("state") == "open"
               and p.get("draft") is False
               and p.get("base", {}).get("ref") == "main"
               and p.get("base", {}).get("repo", {}).get("full_name") == repository
               and p.get("head", {}).get("sha") == head_sha
               and p.get("head", {}).get("ref") == branch
               and p.get("head", {}).get("repo", {}).get("full_name") == repository]
    if len(matches) > 1:
        raise ValueError("ambiguous source PR association")
    if not matches:
        return None
    candidate = matches[0]
    number = candidate.get("number")
    if type(number) is not int or number <= 0:
        raise ValueError("source PR number is malformed")
    # Check the *current* PR after reading associated commits: a stale head
    # cannot receive fresh trusted success even if the source run once passed.
    current = api(f"repos/{repository}/pulls/{number}")
    if not isinstance(current, dict) or current.get("head", {}).get("sha") != head_sha:
        return None
    if current.get("state") != "open" or current.get("draft") is not False:
        return None
    if current.get("head", {}).get("repo", {}).get("full_name") != repository:
        return None
    if current.get("head", {}).get("ref") != branch:
        return None
    if current.get("base", {}).get("repo", {}).get("full_name") != repository:
        return None
    if current.get("base", {}).get("ref") != "main":
        return None
    return current


def latest_attempt(repository: str, workflow_id: int, sha: str) -> tuple[int, int] | None:
    data = api(f"repos/{repository}/actions/workflows/{workflow_id}/runs?head_sha={sha}&event=pull_request&per_page=100")
    if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
        raise ValueError("source run list is malformed")
    runs = [r for r in data["workflow_runs"] if isinstance(r, dict) and r.get("head_sha") == sha
            and r.get("event") == "pull_request" and r.get("path") == SOURCE_PATH]
    if not runs:
        return None
    newest = max(runs, key=lambda r: (r.get("created_at", ""), r.get("id", -1)))
    if type(newest.get("id")) is not int or type(newest.get("run_attempt")) is not int:
        raise ValueError("latest run identity is malformed")
    return newest["id"], newest["run_attempt"]


def evaluate(source: dict[str, Any], jobs: list[dict[str, Any]], paths: set[str]) -> dict[str, Any]:
    if touches_authority(paths):
        return result("error", "CI authority files changed; require independent trusted validation")
    if source.get("conclusion") != "success":
        return result("failure", "Source validation run did not finish successfully")
    selected = {}
    for name in JOBS:
        matches = [j for j in jobs if j.get("name") == name]
        if len(matches) != 1:
            return result("error", f"Required job missing or ambiguous: {name}")
        selected[name] = matches[0]
        if matches[0].get("conclusion") != "success":
            return result("failure", f"Required job did not succeed: {name}")
    for job_name, step_names in REQUIRED_STEPS.items():
        steps = selected[job_name].get("steps")
        if not isinstance(steps, list):
            return result("error", f"Step evidence unavailable: {job_name}")
        for step_name in step_names:
            matches = [s for s in steps if s.get("name") == step_name]
            if len(matches) != 1 or matches[0].get("conclusion") != "success":
                return result("error", f"Required step not proven: {step_name}")
    return result("success", "Trusted pilot: source jobs and steps passed on exact PR head")


def decide(event: dict[str, Any], repository: str) -> dict[str, Any]:
    source = event.get("workflow_run")
    if not isinstance(source, dict) or source.get("event") != "pull_request":
        return result(None, "Non-PR source: no trusted pilot status published")
    if source.get("path") != SOURCE_PATH or source.get("repository", {}).get("full_name") != repository:
        return result(None, "Wrong source workflow or repository")
    run_id, attempt, workflow_id = source.get("id"), source.get("run_attempt"), source.get("workflow_id")
    sha, branch = source.get("head_sha"), source.get("head_branch")
    if any(type(v) is not int or v <= 0 for v in (run_id, attempt, workflow_id)):
        return result(None, "Invalid run identity")
    if not isinstance(sha, str) or not SHA.fullmatch(sha) or not isinstance(branch, str) or not branch:
        return result(None, "Invalid head identity")
    if source.get("status") != "completed":
        return result(None, "Source run is not completed")
    pr = lookup_pr(repository, sha, branch)
    if pr is None:
        return result(None, "No exact-current Ready PR associated with source run")
    newest = latest_attempt(repository, workflow_id, sha)
    if newest != (run_id, attempt):
        return result(None, "Stale attempt: a newer source run owns this head")
    paths = changed_paths(repository, pr["number"])
    jobs = jobs_for_attempt(repository, run_id, attempt)
    if any(j.get("run_id") != run_id or j.get("run_attempt") != attempt for j in jobs):
        return result("error", "Job identity differs from source run attempt")
    return evaluate(source, jobs, paths)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--event", type=Path, default=Path(os.getenv("GITHUB_EVENT_PATH", "")))
    p.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    p.add_argument("--publish", action="store_true")
    args = p.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        raise SystemExit("Invalid repository identity")
    event = json.loads(args.event.read_text(encoding="utf-8"))
    if not isinstance(event, dict):
        raise SystemExit("Invalid workflow event")
    try:
        outcome = decide(event, args.repository)
    except (ValueError, RuntimeError, subprocess.TimeoutExpired):
        # No state should be minted from incomplete/ambiguous provider data.
        outcome = result(None, "Provider evidence unavailable: no status published")
    safe = {"state": outcome["state"], "context": outcome["context"], "description": outcome["description"]}
    print(json.dumps(safe, sort_keys=True))
    if args.publish and outcome["state"] is not None:
        sha = event["workflow_run"]["head_sha"]
        run_id = event["workflow_run"]["id"]
        cmd = ["gh", "api", "-X", "POST", f"repos/{args.repository}/statuses/{sha}",
               "-f", f"context={CONTEXT}", "-f", f"state={outcome['state']}",
               "-f", f"description={outcome['description']}",
               "-f", f"target_url=https://github.com/{args.repository}/actions/runs/{run_id}"]
        completed = subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=45)
        if completed.returncode:
            raise SystemExit("Provider rejected trusted status publication")
    return 0 if outcome["state"] in (None, "success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
