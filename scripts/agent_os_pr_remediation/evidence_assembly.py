"""Bounded read-only live GitHub evidence assembly for PR remediation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .models import AUTHORITY_FIELDS, EvidenceValidationError, canonical_json, deterministic_id
from .normalization import normalize_pr_snapshot, normalize_review_threads

MAX_FILES = 5_000
MAX_THREADS = 5_000
MAX_CHECKS = 1_000


class GitHubEvidenceReader(Protocol):
    """Injected read-only GitHub boundary; implementations must not expose writes."""

    def get_pull_request(self, repository: str, pr_number: int) -> dict[str, Any]: ...
    def list_changed_files(self, repository: str, pr_number: int) -> list[str]: ...
    def list_review_threads(self, repository: str, pr_number: int) -> list[dict[str, Any]]: ...
    def list_checks(self, repository: str, head_sha: str) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class EvidenceAssemblyResult:
    status: str
    envelope: dict[str, Any] | None
    initial_head_sha: str | None
    final_head_sha: str | None
    reason_codes: tuple[str, ...]
    execution_authorized: bool = False
    external_write_authorized: bool = False
    merge_authorized: bool = False
    side_effects_performed: bool = False

    def __post_init__(self) -> None:
        if any(
            value is not False
            for value in (
                self.execution_authorized,
                self.external_write_authorized,
                self.merge_authorized,
                self.side_effects_performed,
            )
        ):
            raise EvidenceValidationError("EvidenceAssemblyResult authority fields must be false")

    @property
    def evidence_id(self) -> str:
        return deterministic_id(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "envelope": self.envelope,
            "initial_head_sha": self.initial_head_sha,
            "final_head_sha": self.final_head_sha,
            "reason_codes": list(self.reason_codes),
            **{field: False for field in AUTHORITY_FIELDS},
        }


def _exact(value: Any, expected: type, field: str) -> None:
    if type(value) is not expected:
        raise EvidenceValidationError(f"{field} must be exactly {expected.__name__}")


def _repository(value: Any) -> str:
    _exact(value, str, "repository")
    if not value or value.count("/") != 1 or len(value) > 500:
        raise EvidenceValidationError("repository must be bounded owner/name")
    return value


def _pr_number(value: Any) -> int:
    _exact(value, int, "pr_number")
    if value <= 0:
        raise EvidenceValidationError("pr_number must be positive")
    return value


def _sha(value: Any, field: str) -> str:
    _exact(value, str, field)
    lowered = value.lower()
    if len(lowered) != 40 or any(char not in "0123456789abcdef" for char in lowered):
        raise EvidenceValidationError(f"{field} must be a 40-character hexadecimal SHA")
    return lowered


def _bounded_list(value: Any, field: str, maximum: int) -> list[Any]:
    _exact(value, list, field)
    if len(value) > maximum:
        raise EvidenceValidationError(f"{field} exceeds size limit")
    return value


def _snapshot_payload(repository: str, pr_number: int, raw: dict[str, Any], files: list[str]) -> dict[str, Any]:
    _exact(raw, dict, "pull request evidence")
    required = {"base_branch", "head_branch", "head_sha", "state", "merged", "draft"}
    missing = required - set(raw)
    if missing:
        raise EvidenceValidationError("missing pull request evidence: " + ", ".join(sorted(missing)))
    return {
        "repository": repository,
        "pr_number": pr_number,
        "base_branch": raw["base_branch"],
        "base_sha": raw.get("base_sha"),
        "head_branch": raw["head_branch"],
        "head_sha": raw["head_sha"],
        "state": raw["state"],
        "merged": raw["merged"],
        "draft": raw["draft"],
        "changed_files": files,
        "captured_at": raw.get("captured_at"),
        "source_revision": raw.get("source_revision"),
    }


def _thread_payload(raw: dict[str, Any]) -> dict[str, Any]:
    _exact(raw, dict, "review thread evidence")
    comments = raw.get("comments")
    _exact(comments, list, "review thread comments")
    if not comments:
        raise EvidenceValidationError("review thread must contain a top-level comment")
    top = comments[0]
    _exact(top, dict, "top-level review comment")
    author = top.get("author") or {}
    _exact(author, dict, "review comment author")
    return {
        "thread_id": raw.get("id"),
        "top_level_comment_id": top.get("id"),
        "reviewer": author.get("login"),
        "body": top.get("body"),
        "path": raw.get("path"),
        "line": raw.get("line"),
        "original_line": raw.get("original_line"),
        "side": raw.get("diff_side"),
        "start_line": raw.get("start_line"),
        "start_side": raw.get("start_diff_side"),
        "resolved": raw.get("is_resolved"),
        "outdated": raw.get("is_outdated"),
        "superseded": False,
        "created_at": top.get("created_at"),
        "updated_at": top.get("updated_at"),
        "reply_ids": [str(comment.get("id")) for comment in comments[1:]],
        "supersession_evidence": [],
    }


def _validation_payload(raw: dict[str, Any], head_sha: str) -> dict[str, Any]:
    _exact(raw, dict, "check evidence")
    name = raw.get("name")
    _exact(name, str, "check name")
    if not name or len(name) > 10_000:
        raise EvidenceValidationError("check name must be bounded non-empty text")
    tested_sha = _sha(raw.get("tested_sha", head_sha), "tested_sha")
    conclusion = raw.get("conclusion")
    if conclusion in {"success", "SUCCESS"}:
        execution_status = "aggregate-pass"
        available, complete = True, True
        reasons: list[str] = []
    elif conclusion in {"failure", "FAILURE"}:
        execution_status = "aggregate-fail"
        available, complete = True, True
        reasons = ["check-failed"]
    elif conclusion in {None, "", "pending", "PENDING"}:
        execution_status = "unavailable"
        available, complete = False, False
        reasons = ["check-incomplete"]
    else:
        execution_status = "unavailable"
        available, complete = True, False
        reasons = ["unsupported-check-conclusion"]
    stable_id = deterministic_id({"name": name, "tested_sha": tested_sha})
    return {
        "category": name,
        "profile": "aggregate",
        "validation_plan_id": f"live-check:{stable_id}",
        "command_plan_id": f"live-check:{stable_id}",
        "execution_evidence_id": f"live-check:{stable_id}",
        "expected_sha": head_sha,
        "tested_sha": tested_sha,
        "execution_status": execution_status,
        "aggregate_pending": not complete,
        "evidence_complete": complete,
        "evidence_available": available,
        "reason_codes": reasons,
    }


def assemble_prr_evidence(repository: str, pr_number: int, reader: GitHubEvidenceReader) -> EvidenceAssemblyResult:
    """Acquire one PR's evidence with a final head recheck and no mutation path."""

    repository = _repository(repository)
    pr_number = _pr_number(pr_number)
    initial = reader.get_pull_request(repository, pr_number)
    _exact(initial, dict, "pull request evidence")
    initial_head = _sha(initial.get("head_sha"), "head_sha")

    files = _bounded_list(reader.list_changed_files(repository, pr_number), "changed files", MAX_FILES)
    if any(type(path) is not str or not path or len(path) > 10_000 for path in files):
        raise EvidenceValidationError("changed files must contain bounded non-empty strings")
    if len(set(files)) != len(files):
        raise EvidenceValidationError("changed files contain duplicates")

    raw_threads = _bounded_list(reader.list_review_threads(repository, pr_number), "review threads", MAX_THREADS)
    threads = [_thread_payload(item) for item in raw_threads]
    normalize_review_threads(threads)

    raw_checks = _bounded_list(reader.list_checks(repository, initial_head), "checks", MAX_CHECKS)
    checks = [_validation_payload(item, initial_head) for item in raw_checks]
    if len({item["category"] for item in checks}) != len(checks):
        raise EvidenceValidationError("checks contain duplicate categories")
    checks.sort(key=lambda item: (item["category"], item["tested_sha"]))

    final = reader.get_pull_request(repository, pr_number)
    _exact(final, dict, "final pull request evidence")
    final_head = _sha(final.get("head_sha"), "final head_sha")
    if final_head != initial_head:
        return EvidenceAssemblyResult(
            status="stale-moved-head",
            envelope=None,
            initial_head_sha=initial_head,
            final_head_sha=final_head,
            reason_codes=("head-moved-during-acquisition",),
        )

    snapshot = normalize_pr_snapshot(_snapshot_payload(repository, pr_number, initial, sorted(files)))
    envelope = {
        "snapshot": snapshot.to_dict(),
        "review_threads": threads,
        "expected_head": initial_head,
        "allowed_files": list(snapshot.changed_files),
        "draft_allowed": True,
        "candidates": [],
        "changed_files": list(snapshot.changed_files),
        "finding_fixes": [],
        "validation_evidence": checks,
        "current_head_sha": initial_head,
        "final_captured_head_sha": final_head,
        **{field: False for field in AUTHORITY_FIELDS},
    }
    canonical_json(envelope)
    return EvidenceAssemblyResult(
        status="assembled",
        envelope=envelope,
        initial_head_sha=initial_head,
        final_head_sha=final_head,
        reason_codes=(),
    )