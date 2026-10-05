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

RUNTIME_REASON_CODES = frozenset({"runtime.incompatible"})

#: Bounded family of capability-absence cause codes (B4 / AI-navigation).
#:
#: `reason_code` classifies *why* a capability is absent; the free-text `reason`
#: field on CapabilityEvidence is annotation only and never the cause carrier.
#: The family distinguishes:
#: - ``unavailable``: probed and found absent right now.
#: - ``undiscovered``: never probed, or the cause was never classified. This is
#:   also the bounded vocabulary-miss fallback: unknown cause input maps here,
#:   never to a bare error and never to an optimistic default.
#: - ``permission-missing``: a probe or use was denied by permissions.
#: - ``connector-limitation``: the connector cannot express or reach the
#:   capability.
#: - ``native-host-limitation``: the host cannot provide the capability.
#: - ``external-provider-failure``: an external provider errored.
#: - ``retired`` / ``never-existed``: lifecycle knowledge the caller may carry
#:   when it knows the capability was removed versus never present.
ABSENCE_CAUSE_CODES = frozenset(
    {
        "capability-absence.unavailable",
        "capability-absence.undiscovered",
        "capability-absence.permission-missing",
        "capability-absence.connector-limitation",
        "capability-absence.native-host-limitation",
        "capability-absence.external-provider-failure",
        "capability-absence.retired",
        "capability-absence.never-existed",
    }
)

#: Bounded fallback for an unclassified absence cause (vocabulary miss).
ABSENCE_CAUSE_FALLBACK = "capability-absence.undiscovered"


def is_absence_cause_code(value: object) -> bool:
    """Report whether `value` is a member of the bounded absence-cause family."""
    return isinstance(value, str) and value in ABSENCE_CAUSE_CODES


def normalize_absence_cause(value: object) -> str:
    """Return the bounded absence cause for `value`.

    Members of the absence-cause family pass through unchanged. Anything else
    (unknown strings, None, non-strings, missing input) maps to the bounded
    fallback ``capability-absence.undiscovered``. This function never raises and
    never reports the capability as available: a vocabulary miss is a bounded
    code, not a bare ValueError and not an optimistic default.
    """
    if isinstance(value, str) and value in ABSENCE_CAUSE_CODES:
        return value
    return ABSENCE_CAUSE_FALLBACK

DEPENDENCY_REASON_CODES = frozenset(
    {
        "dependency.open-ended-requirements",
        "dependency.resolved-evidence-missing",
        "dependency.lock-mismatch",
        "dependency.hash-evidence-missing",
        "dependency.package-source-drift",
        "dependency.editable-source-drift",
        "dependency.transitive-drift",
        "dependency.manifest-drift",
        "dependency.lock-required",
        "dependency.package-manager-unavailable",
        "dependency.source-unavailable",
        "dependency.package-unavailable",
        "dependency.cache-incomplete",
        "dependency.preparation-failed",
        "dependency.source-update-required",
        "dependency.environment-stale",
        "dependency.environment-surface-mismatch",
        "dependency.validation-command-missing",
        "dependency.undeclared-package-source",
        "dependency.undeclared-local-project",
        "dependency.unsupported-source-indirection",
        "dependency.post-preparation-drift",
    }
)

APPROVED_REASON_CODES = frozenset(
    set(SCHEMA_REASON_CODES)
    | set(ADAPTER_REASON_CODES)
    | set(REPOSITORY_REASON_CODES)
    | set(REF_REASON_CODES)
    | set(WORKTREE_REASON_CODES)
    | set(RUNTIME_REASON_CODES)
    | set(DEPENDENCY_REASON_CODES)
    | set(ABSENCE_CAUSE_CODES)
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
