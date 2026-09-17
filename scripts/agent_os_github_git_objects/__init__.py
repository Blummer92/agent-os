"""Guarded local GitHub Git-object publication capability.

Pure data-model imports must not require the optional PyGithub transport. Public
execution/transport exports remain available through lazy attribute loading.
"""

from __future__ import annotations

from .models import (
    AtomicCommitConfirmation,
    AtomicCommitPlan,
    AtomicCommitReason,
    AtomicCommitRequest,
    AtomicCommitResult,
    AtomicCommitStatus,
    ExpectedHeadBranchUpdateRequest,
    ExpectedHeadBranchUpdateResult,
    ExpectedHeadBranchUpdateStatus,
    GitBlobSnapshot,
    GitChangedFile,
    GitCommitSnapshot,
    GitCompareSnapshot,
    GitRefSnapshot,
    GitTreeEntry,
    GitTreeSnapshot,
    MutationState,
)

_LAZY_EXPORTS = {
    "execute_atomic_commit_from_blobs": (".atomic_commit", "execute_atomic_commit_from_blobs"),
    "prepare_atomic_commit_from_blobs": (".atomic_commit", "prepare_atomic_commit_from_blobs"),
    "BranchUpdateObservation": (".branch_update", "BranchUpdateObservation"),
    "BranchUpdateRunner": (".branch_update", "BranchUpdateRunner"),
    "update_branch_with_expected_head": (".branch_update", "update_branch_with_expected_head"),
    "GitHubGitObjectTransport": (".transport", "GitHubGitObjectTransport"),
    "GitObjectTransportError": (".transport", "GitObjectTransportError"),
    "PyGithubGitObjectTransport": (".transport", "PyGithubGitObjectTransport"),
}


def __getattr__(name: str) -> object:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


__all__ = [
    "AtomicCommitConfirmation",
    "AtomicCommitPlan",
    "AtomicCommitReason",
    "AtomicCommitRequest",
    "AtomicCommitResult",
    "AtomicCommitStatus",
    "BranchUpdateObservation",
    "BranchUpdateRunner",
    "ExpectedHeadBranchUpdateRequest",
    "ExpectedHeadBranchUpdateResult",
    "ExpectedHeadBranchUpdateStatus",
    "GitBlobSnapshot",
    "GitChangedFile",
    "GitCommitSnapshot",
    "GitCompareSnapshot",
    "GitHubGitObjectTransport",
    "GitObjectTransportError",
    "GitRefSnapshot",
    "GitTreeEntry",
    "GitTreeSnapshot",
    "MutationState",
    "PyGithubGitObjectTransport",
    "execute_atomic_commit_from_blobs",
    "prepare_atomic_commit_from_blobs",
    "update_branch_with_expected_head",
]
