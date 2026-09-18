"""Guarded local GitHub Git-object publication capability."""

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


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    from importlib import import_module

    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
