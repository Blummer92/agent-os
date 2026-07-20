from __future__ import annotations

SCHEMA_REASON_CODES = frozenset(
    {
        "schema.name-mismatch",
        "schema.version-missing",
        "schema.version-malformed",
        "schema.version-unsupported",
        "schema.unknown-field",
        "schema.unknown-enum",
        "schema.duplicate-capability",
        "schema.incomplete",
        "schema.contradictory",
        "schema.secret-like-value",
    }
)

ADAPTER_REASON_CODES = frozenset(
    {
        "adapter.missing",
        "adapter.malformed",
        "adapter.scope-mismatch",
        "adapter.evidence-unproven",
        "adapter.evidence-observed",
        "adapter.evidence-exercised",
    }
)

REPOSITORY_REASON_CODES = frozenset(
    {
        "repo.identity-mismatch",
        "repo.fork-upstream-mismatch",
        "repo.default-branch-mismatch",
    }
)

REF_REASON_CODES = frozenset(
    {
        "ref.base-mismatch",
        "ref.head-mismatch",
        "ref.branch-moved",
        "ref.requested-tested-mismatch",
        "ref.observed-sha-stale",
        "ref.tested-sha-missing",
        "ref.tested-sha-ambiguous",
        "ref.tested-sha-mismatch",
        "ref.build-sha-mismatch",
        "ref.pushed-sha-mismatch",
        "ref.pr-head-mismatch",
        "ref.contract-mismatch",
        "ref.evidence-type-mismatch",
    }
)

WORKTREE_REASON_CODES = frozenset(
    {
        "worktree.dirty",
        "worktree.untracked",
        "worktree.ignored-relevant",
        "worktree.detached",
        "worktree.shallow",
        "worktree.unresolved-operation",
        "worktree.uncommitted",
    }
)

APPROVED_REASON_CODES = frozenset(
    set(SCHEMA_REASON_CODES)
    | set(ADAPTER_REASON_CODES)
    | set(REPOSITORY_REASON_CODES)
    | set(REF_REASON_CODES)
    | set(WORKTREE_REASON_CODES)
)


def is_approved_reason_code(value: object) -> bool:
    return isinstance(value, str) and value in APPROVED_REASON_CODES


def normalize_reason_codes(values: object) -> tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, (tuple, list, set, frozenset)):
        raise TypeError("reason codes must be a collection of strings")
    normalized = tuple(sorted(set(values)))
    if not all(is_approved_reason_code(value) for value in normalized):
        raise ValueError("reason codes must use the bounded GEX vocabulary")
    return normalized
