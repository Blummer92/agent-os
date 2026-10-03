from __future__ import annotations

import json
import re
from dataclasses import dataclass

RECOVERY_AUTHORIZATION_SCHEMA = "agent-os-main-health-recovery-authorization-v1"
MAX_RECOVERY_PATHS = 16

_REFERENCE_RE = re.compile(
    r"<!--\s*agent-os-main-health-recovery-issue:(?P<issue>[1-9][0-9]{0,9})\s*-->",
    re.ASCII,
)
_AUTHORIZATION_RE = re.compile(
    r"<!--\s*agent-os-main-health-recovery\s+(?P<payload>\{.*?\})\s*-->",
    re.DOTALL | re.ASCII,
)
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_PATH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,512}$", re.ASCII)
_DETAILS_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/"
    r"actions/runs/(?P<run>[1-9][0-9]*)/job/(?P<job>[1-9][0-9]*)$",
    re.ASCII,
)


@dataclass(frozen=True, slots=True)
class MainHealthRecoveryAuthorization:
    repository: str
    issue_number: int
    main_sha: str
    pull_request: int
    head_sha: str
    main_check_details_url: str
    repair_paths: tuple[str, ...]
    authorized_by: str


def recovery_issue_reference(pull_request_body: object) -> int | None:
    """Return one exact recovery issue reference from a PR body or fail closed."""
    if type(pull_request_body) is not str:
        return None
    matches = list(_REFERENCE_RE.finditer(pull_request_body))
    if len(matches) != 1:
        return None
    return int(matches[0].group("issue"))


def evaluate_recovery_authorization(
    issue_body: object,
    *,
    repository: object,
    repository_owner: object,
    issue_number: object,
    issue_author: object,
    current_main_sha: object,
    pull_request: object,
    current_head_sha: object,
    main_check_details_url: object,
    changed_files: object,
) -> MainHealthRecoveryAuthorization | None:
    """Validate a reusable owner-authored red-main recovery authorization.

    This record authorizes candidate validation only. It does not authorize
    merge, revert, issue closure, workflow mutation, protected-setting mutation,
    credentials, permissions, production, or any external write.
    """
    required_text = (
        issue_body,
        repository,
        repository_owner,
        issue_author,
        current_main_sha,
        current_head_sha,
        main_check_details_url,
    )
    if any(type(value) is not str or not value for value in required_text):
        return None
    if type(issue_number) is not int or issue_number <= 0:
        return None
    if type(pull_request) is not int or pull_request <= 0:
        return None
    if issue_author != repository_owner:
        return None
    if _SHA40_RE.fullmatch(current_main_sha) is None:
        return None
    if _SHA40_RE.fullmatch(current_head_sha) is None:
        return None
    if type(changed_files) not in (list, tuple):
        return None
    changed = {path for path in changed_files if type(path) is str}

    matches = list(_AUTHORIZATION_RE.finditer(issue_body))
    if len(matches) != 1:
        return None
    try:
        payload = json.loads(matches[0].group("payload"))
    except (TypeError, ValueError):
        return None
    if type(payload) is not dict:
        return None

    required_keys = {
        "schema",
        "repository",
        "issue_number",
        "main_sha",
        "pull_request",
        "head_sha",
        "main_check_details_url",
        "repair_paths",
        "authorized_by",
    }
    if set(payload) != required_keys:
        return None
    if payload.get("schema") != RECOVERY_AUTHORIZATION_SCHEMA:
        return None

    expected = {
        "repository": repository,
        "issue_number": issue_number,
        "main_sha": current_main_sha,
        "pull_request": pull_request,
        "head_sha": current_head_sha,
        "main_check_details_url": main_check_details_url,
        "authorized_by": repository_owner,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        return None

    details_match = _DETAILS_RE.fullmatch(main_check_details_url)
    if details_match is None:
        return None
    if f"{details_match.group('owner')}/{details_match.group('repo')}" != repository:
        return None

    repair_paths = payload.get("repair_paths")
    if (
        type(repair_paths) is not list
        or not repair_paths
        or len(repair_paths) > MAX_RECOVERY_PATHS
    ):
        return None
    if any(not _canonical_path(path) for path in repair_paths):
        return None
    canonical_paths = tuple(sorted(set(repair_paths)))
    if repair_paths != list(canonical_paths):
        return None
    if any(path not in changed for path in canonical_paths):
        return None

    return MainHealthRecoveryAuthorization(
        repository=repository,
        issue_number=issue_number,
        main_sha=current_main_sha,
        pull_request=pull_request,
        head_sha=current_head_sha,
        main_check_details_url=main_check_details_url,
        repair_paths=canonical_paths,
        authorized_by=repository_owner,
    )


def _canonical_path(value: object) -> bool:
    if type(value) is not str or _PATH_RE.fullmatch(value) is None:
        return False
    if value.startswith("/") or value.endswith("/"):
        return False
    parts = value.split("/")
    return all(part not in ("", ".", "..") for part in parts)
