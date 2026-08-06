"""Two-phase guarded atomic commit orchestration for existing Git blobs."""

from __future__ import annotations

import hashlib
import json

from .models import (
    AtomicCommitConfirmation,
    AtomicCommitPlan,
    AtomicCommitReason,
    AtomicCommitRequest,
    AtomicCommitResult,
    AtomicCommitStatus,
    MutationState,
)
from .transport import GitHubGitObjectTransport, GitObjectTransportError


def prepare_atomic_commit_from_blobs(
    request: AtomicCommitRequest,
    transport: GitHubGitObjectTransport,
) -> tuple[AtomicCommitPlan | None, AtomicCommitResult]:
    try:
        ref = transport.get_ref(request.repository, request.branch)
        if ref.commit_sha != request.expected_head_sha:
            return None, _blocked(
                AtomicCommitReason.INITIAL_HEAD_MISMATCH,
                starting=ref.commit_sha,
                diagnostic="branch head does not match expected head",
            )
        commit = transport.get_commit(request.repository, request.expected_head_sha)
        if commit.sha != request.expected_head_sha or len(commit.parent_shas) != 1:
            return None, _blocked(
                AtomicCommitReason.COMMIT_SHAPE_UNSUPPORTED,
                starting=ref.commit_sha,
                diagnostic="head commit must be an ordinary single-parent commit",
            )
        for entry in request.entries:
            try:
                blob = transport.get_blob(request.repository, entry.sha)
            except GitObjectTransportError as error:
                if error.kind in {"not-found", "malformed-response"}:
                    return None, _blocked(
                        AtomicCommitReason.BLOB_MISSING_OR_MISMATCHED,
                        starting=ref.commit_sha,
                        parent_tree=commit.tree_sha,
                        diagnostic=f"blob unavailable for {entry.path}",
                    )
                raise
            if blob.sha != entry.sha:
                return None, _blocked(
                    AtomicCommitReason.BLOB_MISSING_OR_MISMATCHED,
                    starting=ref.commit_sha,
                    parent_tree=commit.tree_sha,
                    diagnostic=f"blob identity mismatch for {entry.path}",
                )
        fingerprint = _operation_fingerprint(request, commit.tree_sha)
        if fingerprint in request.prior_fingerprints:
            return None, _blocked(
                AtomicCommitReason.REPEAT_INVOCATION,
                starting=ref.commit_sha,
                parent_tree=commit.tree_sha,
                fingerprint=fingerprint,
                diagnostic="operation fingerprint already completed",
            )
        plan = AtomicCommitPlan(request, commit.tree_sha, fingerprint)
        return plan, AtomicCommitResult(
            status=AtomicCommitStatus.PLANNED,
            reason=AtomicCommitReason.PLAN_READY,
            operation_fingerprint=fingerprint,
            starting_branch_sha=ref.commit_sha,
            ending_branch_sha=ref.commit_sha,
            parent_tree_sha=commit.tree_sha,
            created_tree_sha=None,
            created_commit_sha=None,
            confirmation_requested=True,
            mutation_state=MutationState.NOT_ATTEMPTED,
        )
    except GitObjectTransportError as error:
        return None, _blocked(
            AtomicCommitReason.TRANSPORT_FAILURE,
            diagnostic=f"{error.operation}:{error.kind}",
            mutation_state=error.mutation_state,
        )


def execute_atomic_commit_from_blobs(
    plan: AtomicCommitPlan,
    confirmation: AtomicCommitConfirmation | None,
    transport: GitHubGitObjectTransport,
) -> AtomicCommitResult:
    request = plan.request
    if confirmation is None:
        return _blocked(
            AtomicCommitReason.CONFIRMATION_MISSING,
            starting=request.expected_head_sha,
            parent_tree=plan.parent_tree_sha,
            fingerprint=plan.operation_fingerprint,
            confirmation_requested=True,
        )
    if confirmation.confirmed is False:
        return _blocked(
            AtomicCommitReason.CONFIRMATION_CANCELLED,
            starting=request.expected_head_sha,
            parent_tree=plan.parent_tree_sha,
            fingerprint=plan.operation_fingerprint,
            confirmation_requested=True,
        )
    if not _confirmation_matches(plan, confirmation):
        return _blocked(
            AtomicCommitReason.CONFIRMATION_MISMATCHED,
            starting=request.expected_head_sha,
            parent_tree=plan.parent_tree_sha,
            fingerprint=plan.operation_fingerprint,
            confirmation_requested=True,
        )

    created_tree: str | None = None
    created_commit: str | None = None
    try:
        pre_ref = transport.get_ref(request.repository, request.branch)
        if pre_ref.commit_sha != request.expected_head_sha:
            return _blocked(
                AtomicCommitReason.CONCURRENCY_STOP,
                starting=pre_ref.commit_sha,
                parent_tree=plan.parent_tree_sha,
                fingerprint=plan.operation_fingerprint,
                confirmation_requested=True,
                confirmation_matched=True,
                execution_attempted=True,
                diagnostic="branch moved before tree creation",
            )
        try:
            created_tree = transport.create_tree(
                request.repository,
                base_tree_sha=plan.parent_tree_sha,
                entries=request.entries,
            )
        except GitObjectTransportError as error:
            return _write_failure(
                error,
                AtomicCommitReason.TREE_CREATE_FAILED,
                AtomicCommitReason.TREE_CREATE_UNCERTAIN,
                plan,
                pre_ref.commit_sha,
            )
        try:
            created_commit = transport.create_commit(
                request.repository,
                tree_sha=created_tree,
                parent_sha=request.expected_head_sha,
                message=request.message,
            )
        except GitObjectTransportError as error:
            return _write_failure(
                error,
                AtomicCommitReason.COMMIT_CREATE_FAILED,
                AtomicCommitReason.COMMIT_CREATE_UNCERTAIN,
                plan,
                pre_ref.commit_sha,
                created_tree=created_tree,
            )

        comparison = transport.compare(
            request.repository,
            base_sha=request.expected_head_sha,
            head_sha=created_commit,
        )
        expected = {entry.path: entry.sha for entry in request.entries}
        actual = {item.path: item for item in comparison.changed_files}
        valid_compare = (
            comparison.status == "ahead"
            and comparison.ahead_by == 1
            and comparison.behind_by == 0
            and comparison.total_commits == 1
            and set(actual) == set(expected)
            and all(item.status in {"added", "modified"} for item in actual.values())
            and all(item.previous_path is None for item in actual.values())
            and all(actual[path].blob_sha == sha for path, sha in expected.items())
        )
        if not valid_compare:
            return _blocked(
                AtomicCommitReason.UNATTACHED_VALIDATION_STOP,
                starting=pre_ref.commit_sha,
                ending=pre_ref.commit_sha,
                parent_tree=plan.parent_tree_sha,
                created_tree=created_tree,
                created_commit=created_commit,
                fingerprint=plan.operation_fingerprint,
                confirmation_requested=True,
                confirmation_matched=True,
                execution_attempted=True,
                mutation_state=MutationState.CONFIRMED,
                unattached=(created_tree, created_commit),
                diagnostic="unattached commit comparison failed exact-path validation",
            )
        created_tree_snapshot = transport.get_tree(
            request.repository, created_tree, recursive=True
        )
        created_entries = {entry.path: entry.sha for entry in created_tree_snapshot.entries}
        if created_tree_snapshot.truncated or any(
            created_entries.get(path) != sha for path, sha in expected.items()
        ):
            return _blocked(
                AtomicCommitReason.UNATTACHED_VALIDATION_STOP,
                starting=pre_ref.commit_sha,
                ending=pre_ref.commit_sha,
                parent_tree=plan.parent_tree_sha,
                created_tree=created_tree,
                created_commit=created_commit,
                fingerprint=plan.operation_fingerprint,
                confirmation_requested=True,
                confirmation_matched=True,
                execution_attempted=True,
                mutation_state=MutationState.CONFIRMED,
                unattached=(created_tree, created_commit),
                diagnostic="created tree does not contain the expected blob identities",
            )

        final_guard = transport.get_ref(request.repository, request.branch)
        if final_guard.commit_sha != request.expected_head_sha:
            return _blocked(
                AtomicCommitReason.CONCURRENCY_STOP,
                starting=pre_ref.commit_sha,
                ending=final_guard.commit_sha,
                parent_tree=plan.parent_tree_sha,
                created_tree=created_tree,
                created_commit=created_commit,
                fingerprint=plan.operation_fingerprint,
                confirmation_requested=True,
                confirmation_matched=True,
                execution_attempted=True,
                mutation_state=MutationState.CONFIRMED,
                unattached=(created_tree, created_commit),
                diagnostic="branch moved before ref update",
            )
        try:
            updated = transport.update_ref(
                request.repository,
                branch=request.branch,
                commit_sha=created_commit,
                force=False,
            )
        except GitObjectTransportError as error:
            reason = (
                AtomicCommitReason.REF_UPDATE_UNCERTAIN
                if error.mutation_state is MutationState.UNCERTAIN
                else AtomicCommitReason.REF_UPDATE_FAILED
            )
            return _blocked(
                reason,
                starting=pre_ref.commit_sha,
                parent_tree=plan.parent_tree_sha,
                created_tree=created_tree,
                created_commit=created_commit,
                fingerprint=plan.operation_fingerprint,
                confirmation_requested=True,
                confirmation_matched=True,
                execution_attempted=True,
                ref_update_attempted=True,
                mutation_state=error.mutation_state,
                unattached=(created_tree, created_commit),
                diagnostic=f"{error.operation}:{error.kind}",
            )
        observed = transport.get_ref(request.repository, request.branch)
        if updated.commit_sha != created_commit or observed.commit_sha != created_commit:
            return _blocked(
                AtomicCommitReason.POST_UPDATE_MISMATCH,
                starting=pre_ref.commit_sha,
                ending=observed.commit_sha,
                parent_tree=plan.parent_tree_sha,
                created_tree=created_tree,
                created_commit=created_commit,
                fingerprint=plan.operation_fingerprint,
                confirmation_requested=True,
                confirmation_matched=True,
                execution_attempted=True,
                ref_update_attempted=True,
                mutation_state=MutationState.UNCERTAIN,
                diagnostic="post-update branch head does not match created commit",
            )
        return AtomicCommitResult(
            status=AtomicCommitStatus.REF_UPDATED,
            reason=AtomicCommitReason.REF_UPDATED,
            operation_fingerprint=plan.operation_fingerprint,
            starting_branch_sha=pre_ref.commit_sha,
            ending_branch_sha=observed.commit_sha,
            parent_tree_sha=plan.parent_tree_sha,
            created_tree_sha=created_tree,
            created_commit_sha=created_commit,
            changed_paths=tuple(sorted(actual)),
            additions=comparison.additions,
            deletions=comparison.deletions,
            confirmation_requested=True,
            confirmation_matched=True,
            execution_attempted=True,
            ref_update_attempted=True,
            mutation_state=MutationState.CONFIRMED,
        )
    except GitObjectTransportError as error:
        unattached = tuple(value for value in (created_tree, created_commit) if value)
        return _blocked(
            AtomicCommitReason.TRANSPORT_FAILURE,
            starting=request.expected_head_sha,
            parent_tree=plan.parent_tree_sha,
            created_tree=created_tree,
            created_commit=created_commit,
            fingerprint=plan.operation_fingerprint,
            confirmation_requested=True,
            confirmation_matched=True,
            execution_attempted=True,
            mutation_state=error.mutation_state,
            unattached=unattached,
            diagnostic=f"{error.operation}:{error.kind}",
        )


def _operation_fingerprint(request: AtomicCommitRequest, parent_tree_sha: str) -> str:
    payload = {
        "repository": request.repository,
        "branch": request.branch,
        "expected_head_sha": request.expected_head_sha,
        "parent_tree_sha": parent_tree_sha,
        "allowed_paths": list(request.allowed_paths),
        "entries": [
            {"path": entry.path, "mode": entry.mode, "type": entry.type, "sha": entry.sha}
            for entry in request.entries
        ],
        "message": request.message,
        "invocation_id": request.invocation_id,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _confirmation_matches(plan: AtomicCommitPlan, confirmation: AtomicCommitConfirmation) -> bool:
    request = plan.request
    return (
        confirmation.invocation_id == request.invocation_id
        and confirmation.operation_fingerprint == plan.operation_fingerprint
        and confirmation.repository == request.repository
        and confirmation.branch == request.branch
        and confirmation.expected_head_sha == request.expected_head_sha
    )


def _write_failure(
    error: GitObjectTransportError,
    failed_reason: AtomicCommitReason,
    uncertain_reason: AtomicCommitReason,
    plan: AtomicCommitPlan,
    starting: str,
    *,
    created_tree: str | None = None,
) -> AtomicCommitResult:
    reason = uncertain_reason if error.mutation_state is MutationState.UNCERTAIN else failed_reason
    return _blocked(
        reason,
        starting=starting,
        parent_tree=plan.parent_tree_sha,
        created_tree=created_tree,
        fingerprint=plan.operation_fingerprint,
        confirmation_requested=True,
        confirmation_matched=True,
        execution_attempted=True,
        mutation_state=error.mutation_state,
        unattached=(created_tree,) if created_tree else (),
        diagnostic=f"{error.operation}:{error.kind}",
    )


def _blocked(
    reason: AtomicCommitReason,
    *,
    starting: str | None = None,
    ending: str | None = None,
    parent_tree: str | None = None,
    created_tree: str | None = None,
    created_commit: str | None = None,
    fingerprint: str | None = None,
    confirmation_requested: bool = False,
    confirmation_matched: bool = False,
    execution_attempted: bool = False,
    ref_update_attempted: bool = False,
    mutation_state: MutationState = MutationState.NOT_ATTEMPTED,
    unattached: tuple[str, ...] = (),
    diagnostic: str = "",
) -> AtomicCommitResult:
    status = AtomicCommitStatus.UNCERTAIN if mutation_state is MutationState.UNCERTAIN else AtomicCommitStatus.BLOCKED
    return AtomicCommitResult(
        status=status,
        reason=reason,
        operation_fingerprint=fingerprint,
        starting_branch_sha=starting,
        ending_branch_sha=ending or starting,
        parent_tree_sha=parent_tree,
        created_tree_sha=created_tree,
        created_commit_sha=created_commit,
        confirmation_requested=confirmation_requested,
        confirmation_matched=confirmation_matched,
        execution_attempted=execution_attempted,
        ref_update_attempted=ref_update_attempted,
        mutation_state=mutation_state,
        unattached_objects=tuple(value for value in unattached if value),
        sanitized_diagnostic=diagnostic[:1024],
        retry_allowed=False,
    )
