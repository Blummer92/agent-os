from __future__ import annotations

from dataclasses import dataclass, field


_MANAGED_FAMILIES: dict[str, tuple[str, ...]] = {
    "lifecycle": ("pr:draft", "pr:ready-for-review", "pr:merge-ready", "pr:blocked"),
    "validation": ("validation:pending", "validation:failing", "validation:green"),
    "branch": ("branch:current", "branch:behind", "branch:conflicted"),
    "review": ("review:clear", "review:needs-attention"),
}
_MANAGED_LABELS = frozenset(label for labels in _MANAGED_FAMILIES.values() for label in labels)


@dataclass(frozen=True, slots=True)
class PullRequestLabelEvidence:
    repository: str
    pr_number: int
    head_sha: str
    draft: bool
    mergeable: bool
    conflicted: bool
    behind: bool
    validation_state: str
    blocking_review_threads: int
    current_labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        repository = self.repository.strip()
        if repository.count("/") != 1 or any(not part for part in repository.split("/")):
            raise ValueError("repository must be exact owner/name")
        head_sha = self.head_sha.lower()
        if len(head_sha) != 40 or any(c not in "0123456789abcdef" for c in head_sha):
            raise ValueError("head_sha must be a full 40-character hexadecimal commit identity")
        if self.pr_number < 1:
            raise ValueError("pr_number must be positive")
        if self.validation_state not in {"pending", "failing", "green"}:
            raise ValueError("validation_state must be pending, failing, or green")
        if self.blocking_review_threads < 0:
            raise ValueError("blocking_review_threads cannot be negative")
        normalized = tuple(sorted(set(label.strip() for label in self.current_labels if label.strip())))
        object.__setattr__(self, "repository", repository)
        object.__setattr__(self, "head_sha", head_sha)
        object.__setattr__(self, "current_labels", normalized)


@dataclass(frozen=True, slots=True)
class PullRequestLabelPlan:
    repository: str
    pr_number: int
    head_sha: str
    desired_managed_labels: tuple[str, ...]
    current_managed_labels: tuple[str, ...]
    labels_to_add: tuple[str, ...]
    labels_to_remove: tuple[str, ...]
    unmanaged_labels_preserved: tuple[str, ...]
    reason_codes: tuple[str, ...]
    external_write_authorized: bool = field(default=False, init=False)
    side_effects_performed: bool = field(default=False, init=False)


def managed_label_families() -> dict[str, tuple[str, ...]]:
    return dict(_MANAGED_FAMILIES)


def managed_labels() -> frozenset[str]:
    return _MANAGED_LABELS


def plan_pull_request_labels(evidence: PullRequestLabelEvidence) -> PullRequestLabelPlan:
    current = set(evidence.current_labels)
    lifecycle = _lifecycle_label(evidence)
    branch = _branch_label(evidence)
    desired = {
        lifecycle,
        f"validation:{evidence.validation_state}",
        branch,
        "review:needs-attention" if evidence.blocking_review_threads else "review:clear",
    }
    current_managed = current & _MANAGED_LABELS
    unmanaged = current - _MANAGED_LABELS

    return PullRequestLabelPlan(
        repository=evidence.repository,
        pr_number=evidence.pr_number,
        head_sha=evidence.head_sha,
        desired_managed_labels=tuple(sorted(desired)),
        current_managed_labels=tuple(sorted(current_managed)),
        labels_to_add=tuple(sorted(desired - current_managed)),
        labels_to_remove=tuple(sorted(current_managed - desired)),
        unmanaged_labels_preserved=tuple(sorted(unmanaged)),
        reason_codes=tuple(sorted({
            f"lifecycle.{lifecycle.split(':', 1)[1]}",
            f"validation.{evidence.validation_state}",
            f"branch.{branch.split(':', 1)[1]}",
            "review.needs-attention" if evidence.blocking_review_threads else "review.clear",
        })),
    )


def plan_matches_head(plan: PullRequestLabelPlan, current_head_sha: str) -> bool:
    return plan.head_sha == current_head_sha.lower()


def _lifecycle_label(evidence: PullRequestLabelEvidence) -> str:
    if evidence.conflicted or evidence.validation_state == "failing" or evidence.blocking_review_threads:
        return "pr:blocked"
    if evidence.draft:
        return "pr:draft"
    if evidence.validation_state == "green" and evidence.mergeable and not evidence.behind:
        return "pr:merge-ready"
    return "pr:ready-for-review"


def _branch_label(evidence: PullRequestLabelEvidence) -> str:
    if evidence.conflicted:
        return "branch:conflicted"
    if evidence.behind:
        return "branch:behind"
    return "branch:current"
