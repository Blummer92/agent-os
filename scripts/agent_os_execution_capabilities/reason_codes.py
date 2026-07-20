from __future__ import annotations

SCHEMA_REASON_CODES = frozenset(
    {
        "schema.malformed-version",
        "schema.unsupported-version",
        "schema.unknown-field",
    }
)

ADAPTER_REASON_CODES = frozenset({"adapter.incompatible"})

REPOSITORY_REASON_CODES = frozenset(
    {
        "repo.identity-mismatch",
        "repo.fork-upstream-mismatch",
    }
)

REF_REASON_CODES = frozenset(
    {
        "ref.base-mismatch",
        "ref.head-mismatch",
        "ref.stale-sha",
        "ref.branch-moved",
        "ref.contract-mismatch",
        "ref.test-sha-mismatch",
        "ref.build-sha-mismatch",
        "ref.pr-head-mismatch",
    }
)

WORKTREE_REASON_CODES = frozenset(
    {
        "worktree.uncommitted",
        "worktree.dirty",
        "worktree.untracked",
        "worktree.ignored-relevant",
        "worktree.operation-unresolved",
        "worktree.detached-head",
        "worktree.shallow-history",
        "worktree.indeterminate",
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
    if isinstance(values, str) or not isinstance(
        values, (tuple, list, set, frozenset)
    ):
        raise TypeError("reason codes must be a collection of strings")
    normalized = tuple(sorted(set(values)))
    if not all(is_approved_reason_code(value) for value in normalized):
        raise ValueError("reason codes must use the bounded GEX vocabulary")
    return normalized
