from dataclasses import replace

import pytest

from scripts.agent_os_issue_labels.pr_branch_refresh import (
    BranchRefreshMutationResult,
    BranchRefreshValidationResult,
    PullRequestBranchRefreshRequest,
    PullRequestBranchRefreshResult,
    PullRequestBranchSnapshot,
    refresh_pull_request_branch,
)

OLD = "a" * 40
BASE = "b" * 40
NEW = "c" * 40
PATH = "scripts/agent_os_issue_labels/pr_branch_refresh.py"


class FakeProvider:
    def __init__(
        self,
        *,
        branch_state="behind",
        mergeability="mergeable",
        changed_paths=(PATH,),
        mutation_status="updated",
        validation_status="green",
    ):
        self.branch = PullRequestBranchSnapshot(
            "Blummer92/agent-os",
            1187,
            "main",
            BASE,
            "agent/1187-pr-lifecycle-refresh",
            OLD,
            BASE,
            branch_state,
            mergeability,
            changed_paths,
        )
        self.mutation_status = mutation_status
        self.validation_status = validation_status
        self.rebases = 0
        self.validations = 0

    def read_branch(self, repository, pr_number):
        return self.branch

    def rebase_onto_main(self, repository, pr_number, **kwargs):
        self.rebases += 1
        if self.mutation_status != "updated":
            return BranchRefreshMutationResult(
                self.mutation_status,
                OLD,
                None,
                f"refresh.{self.mutation_status}",
            )
        self.branch = replace(self.branch, head_sha=NEW, branch_state="current")
        return BranchRefreshMutationResult("updated", OLD, NEW)

    def run_required_validation(self, repository, pr_number, *, head_sha, command_ids):
        self.validations += 1
        return BranchRefreshValidationResult(head_sha, self.validation_status, command_ids)


def request(**overrides):
    values = dict(
        repository="Blummer92/agent-os",
        pr_number=1187,
        base_branch="main",
        expected_base_sha=BASE,
        expected_head_sha=OLD,
        current_main_sha=BASE,
        authorization_id="auth:1187",
        authorization_current=True,
        allowed_changed_paths=(PATH,),
        forbidden_paths=(".github/workflows/x.yml",),
        required_validation_command_ids=("pytest:pr-branch-refresh",),
        branch_refresh_authorized=True,
    )
    values.update(overrides)
    return PullRequestBranchRefreshRequest(**values)


def test_successful_refresh_invalidates_old_head_evidence_validates_and_proves_current_branch():
    provider = FakeProvider()
    result = refresh_pull_request_branch(provider, request())
    assert result.status == "converged"
    assert result.old_head_sha == OLD and result.new_head_sha == NEW
    assert provider.rebases == 1 and provider.validations == 1
    assert "tested-sha" in result.invalidated_head_evidence
    assert "branch.current-proven" in result.reason_codes


def test_current_branch_is_noop_blocked_before_mutation():
    provider = FakeProvider(branch_state="current")
    result = refresh_pull_request_branch(provider, request())
    assert result.reason_codes == ("branch.refresh-not-required",)
    assert provider.rebases == 0


def test_conflicted_or_unknown_branch_fails_closed():
    for state, mergeability in (("conflicted", "conflicted"), ("behind", "unknown")):
        provider = FakeProvider(branch_state=state, mergeability=mergeability)
        result = refresh_pull_request_branch(provider, request())
        assert result.status == "blocked" and provider.rebases == 0


def test_stale_authorization_fails_before_mutation():
    provider = FakeProvider()
    result = refresh_pull_request_branch(provider, request(authorization_current=False))
    assert result.reason_codes == ("authorization.refresh-required",)
    assert provider.rebases == 0


def test_moved_head_or_base_fails_before_mutation():
    provider = FakeProvider()
    provider.branch = replace(provider.branch, head_sha=NEW)
    assert refresh_pull_request_branch(provider, request()).reason_codes == ("head.moved-before-refresh",)

    provider = FakeProvider()
    provider.branch = replace(provider.branch, current_main_sha=NEW)
    assert refresh_pull_request_branch(provider, request()).reason_codes == ("base.moved-before-refresh",)


def test_forbidden_or_expanded_scope_fails_closed():
    provider = FakeProvider(changed_paths=(".github/workflows/x.yml",))
    assert refresh_pull_request_branch(provider, request()).reason_codes == ("scope.forbidden-path",)

    provider = FakeProvider(changed_paths=("other.py",))
    assert refresh_pull_request_branch(provider, request()).reason_codes == ("scope.expanded-after-refresh",)


def test_conflict_or_remote_race_result_never_retries():
    for status in ("conflict", "remote-race"):
        provider = FakeProvider(mutation_status=status)
        result = refresh_pull_request_branch(provider, request())
        assert result.status == "blocked"
        assert provider.rebases == 1 and provider.validations == 0


def test_ambiguous_transport_requires_manual_review_and_no_retry():
    provider = FakeProvider(mutation_status="ambiguous")
    result = refresh_pull_request_branch(provider, request())
    assert result.status == "manual-review"
    assert provider.rebases == 1 and provider.validations == 0


def test_post_refresh_scope_expansion_blocks_before_validation():
    class ExpandingProvider(FakeProvider):
        def rebase_onto_main(self, *args, **kwargs):
            outcome = super().rebase_onto_main(*args, **kwargs)
            self.branch = replace(self.branch, changed_paths=("other.py",))
            return outcome

    provider = ExpandingProvider()
    result = refresh_pull_request_branch(provider, request())
    assert result.reason_codes == ("scope.expanded-after-refresh",)
    assert provider.validations == 0
    assert result.side_effects_performed is True


def test_validation_failure_reports_failure_without_label_reconciliation():
    provider = FakeProvider(validation_status="failing")
    result = refresh_pull_request_branch(provider, request())
    assert result.status == "validation-failing"
    assert result.validation.status == "failing"


def test_3056_missing_or_pending_validation_is_not_reported_as_test_failure():
    for status in ("unavailable", "pending", "not-triggered"):
        provider = FakeProvider(validation_status=status)
        result = refresh_pull_request_branch(provider, request())
        assert result.status == "manual-review"
        assert result.side_effects_performed is True
        assert "refresh.rebased" in result.reason_codes
        assert f"validation.{status}" in result.reason_codes


def test_main_moves_before_final_proof_returns_stale_not_second_refresh():
    class MovingMainProvider(FakeProvider):
        def __init__(self):
            super().__init__()
            self.branch_reads = 0

        def read_branch(self, repository, pr_number):
            self.branch_reads += 1
            if self.branch_reads >= 3:
                return replace(self.branch, current_main_sha=NEW)
            return self.branch

    provider = MovingMainProvider()
    result = refresh_pull_request_branch(provider, request())
    assert result.status == "stale"
    assert result.reason_codes == ("main.moved-before-final-proof",)
    assert provider.rebases == 1


def test_no_lifecycle_merge_retry_workflow_or_repository_setting_authority_is_granted():
    result = refresh_pull_request_branch(FakeProvider(), request())
    assert result.automatic_retry_authorized is False
    assert result.merge_authorized is False
    assert result.ready_for_review_authorized is False
    assert result.issue_closure_authorized is False
    assert result.repository_setting_authorized is False
    assert result.workflow_authorized is False


def test_2850_one_bounded_readback_retry_accepts_remote_head_propagation_lag():
    class LaggingReadbackProvider(FakeProvider):
        def __init__(self):
            super().__init__()
            self.branch_reads = 0
            self.stale_after_update = None

        def read_branch(self, repository, pr_number):
            self.branch_reads += 1
            if self.rebases == 1 and self.branch_reads == 2:
                return self.stale_after_update
            return self.branch

        def rebase_onto_main(self, *args, **kwargs):
            self.stale_after_update = self.branch
            return super().rebase_onto_main(*args, **kwargs)

    provider = LaggingReadbackProvider()
    result = refresh_pull_request_branch(provider, request())

    assert result.status == "converged"
    assert result.reason_codes == ("branch.current-proven", "head-evidence.invalidated", "refresh.rebased")
    assert provider.rebases == 1
    assert provider.validations == 1


def test_2850_persistent_remote_head_mismatch_still_fails_closed_without_mutation_retry():
    class PersistentlyStaleReadbackProvider(FakeProvider):
        def __init__(self):
            super().__init__()
            self.before_update = None

        def read_branch(self, repository, pr_number):
            if self.rebases == 1:
                return self.before_update
            return self.branch

        def rebase_onto_main(self, *args, **kwargs):
            self.before_update = self.branch
            return super().rebase_onto_main(*args, **kwargs)

    provider = PersistentlyStaleReadbackProvider()
    result = refresh_pull_request_branch(provider, request())

    assert result.status == "blocked"
    assert result.reason_codes == ("refresh.remote-head-mismatch",)
    assert provider.rebases == 1
    assert provider.validations == 0


# ---------------------------------------------------------------------------
# Compound-guard oracles. Every guard below joins several independent checks with
# ``or``. Each case drives exactly ONE invalid condition so a guard that only fires
# when all of its conditions hold at once (``or`` weakened to ``and``) is detected.
# Canonical reads happen in a fixed order: 1 = admission, 2 = post-refresh, 3 = final.
# ---------------------------------------------------------------------------

OTHER = "d" * 40


class ScriptedProvider(FakeProvider):
    """FakeProvider that counts canonical reads and can rewrite one numbered read."""

    def __init__(self, *, edit_read=None, **kwargs):
        super().__init__(**kwargs)
        self.read_calls = 0
        self.edit_read = edit_read or {}

    def read_branch(self, repository, pr_number):
        self.read_calls += 1
        edit = self.edit_read.get(self.read_calls)
        return edit(self.branch) if edit else self.branch


class ReportingProvider(ScriptedProvider):
    """Rebase transport that reports a chosen mutation result and leaves a chosen branch behind."""

    def __init__(self, *, status, old, new, branch_after, **kwargs):
        super().__init__(**kwargs)
        self.reported = (status, old, new)
        self.branch_after = branch_after

    def rebase_onto_main(self, repository, pr_number, **kwargs):
        self.rebases += 1
        self.branch = replace(self.branch, **self.branch_after)
        status, old, new = self.reported
        return BranchRefreshMutationResult(status, old, new)


@pytest.mark.parametrize("field", ["expected_base_sha", "expected_head_sha", "current_main_sha"])
@pytest.mark.parametrize(
    "value",
    ["a" * 39, "a" * 41, "g" * 40, ""],
    ids=["39-hex-too-short", "41-hex-too-long", "40-chars-not-hex", "empty"],
)
def test_each_malformed_commit_identity_alone_is_rejected_before_any_read(field, value):
    provider = ScriptedProvider()
    with pytest.raises(ValueError, match=f"{field} must be a full 40-character hexadecimal commit identity"):
        refresh_pull_request_branch(provider, request(**{field: value}))
    assert provider.read_calls == 0 and provider.rebases == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"pr_number": 0},
        {"pr_number": -1},
        {"repository": "agent-os"},
        {"repository": "Blummer92/agent-os/extra"},
        {"repository": ""},
    ],
    ids=["pr-zero", "pr-negative", "repo-no-slash", "repo-two-slashes", "repo-empty"],
)
def test_pr_number_or_repository_alone_must_be_exact_before_any_read(overrides):
    provider = ScriptedProvider()
    with pytest.raises(ValueError, match="repository and pr_number must be exact"):
        refresh_pull_request_branch(provider, request(**overrides))
    assert provider.read_calls == 0 and provider.rebases == 0


def test_pr_number_one_is_a_valid_exact_pull_request():
    provider = ScriptedProvider()
    provider.branch = replace(provider.branch, pr_number=1)
    result = refresh_pull_request_branch(provider, request(pr_number=1))
    assert result.status == "converged" and result.pr_number == 1


@pytest.mark.parametrize(
    "drift",
    [{"repository": "Blummer92/other"}, {"pr_number": 1188}, {"base_branch": "release"}],
    ids=["repository-only", "pr-number-only", "base-branch-only"],
)
def test_snapshot_identity_mismatch_in_any_single_field_blocks_before_mutation(drift):
    provider = ScriptedProvider()
    provider.branch = replace(provider.branch, **drift)
    result = refresh_pull_request_branch(provider, request())
    assert result.status == "blocked"
    assert result.reason_codes == ("identity.mismatch",)
    assert provider.rebases == 0 and provider.read_calls == 1


def test_incomplete_updated_result_blocks_without_claiming_a_refresh():
    provider = ReportingProvider(status="updated", old=OLD, new=None, branch_after={})
    result = refresh_pull_request_branch(provider, request())
    assert result.status == "blocked"
    assert result.reason_codes == ("refresh.updated",)
    assert result.new_head_sha is None and result.invalidated_head_evidence == ()
    assert result.side_effects_performed is False and result.mutation_attempted is True
    assert provider.read_calls == 1 and provider.validations == 0


@pytest.mark.parametrize(
    "status,expected_status",
    [("conflict", "blocked"), ("remote-race", "blocked"), ("ambiguous", "manual-review")],
)
def test_non_updated_result_never_proceeds_even_when_it_names_a_new_head(status, expected_status):
    provider = ReportingProvider(
        status=status, old=OLD, new=NEW, branch_after={"head_sha": NEW, "branch_state": "current"}
    )
    result = refresh_pull_request_branch(provider, request())
    assert result.status == expected_status
    assert result.reason_codes == (f"refresh.{status}",)
    assert result.new_head_sha is None and result.side_effects_performed is False
    assert provider.rebases == 1 and provider.validations == 0 and provider.read_calls == 1


@pytest.mark.parametrize(
    "old,new,branch_after",
    [
        (OTHER, NEW, {"head_sha": NEW, "branch_state": "current"}),
        (OLD, OLD, {"branch_state": "current"}),
    ],
    ids=["reported-old-head-is-not-the-admitted-head", "update-reports-no-head-change"],
)
def test_refresh_head_identity_is_invalid_when_either_reported_head_is_wrong(old, new, branch_after):
    provider = ReportingProvider(status="updated", old=old, new=new, branch_after=branch_after)
    result = refresh_pull_request_branch(provider, request())
    assert result.status == "blocked"
    assert result.reason_codes == ("refresh.head-identity-invalid",)
    assert provider.rebases == 1 and provider.validations == 0


@pytest.mark.parametrize(
    "state",
    [{"branch_state": "behind"}, {"mergeability": "conflicted"}],
    ids=["after-refresh-not-current", "after-refresh-conflicted"],
)
def test_post_refresh_state_each_unproven_condition_alone_blocks_before_validation(state):
    provider = ScriptedProvider(edit_read={2: lambda snapshot: replace(snapshot, **state)})
    result = refresh_pull_request_branch(provider, request())
    assert result.status == "blocked"
    assert result.reason_codes == ("refresh.current-state-not-proven",)
    assert provider.rebases == 1 and provider.validations == 0
    assert result.side_effects_performed is True


@pytest.mark.parametrize(
    "drift",
    [{"head_sha": OTHER}, {"branch_state": "behind"}, {"mergeability": "conflicted"}],
    ids=["final-head-moved", "final-not-current", "final-conflicted"],
)
def test_final_readback_each_unproven_condition_alone_blocks_current_proof(drift):
    provider = ScriptedProvider(edit_read={3: lambda snapshot: replace(snapshot, **drift)})
    result = refresh_pull_request_branch(provider, request())
    assert result.status == "blocked"
    assert result.reason_codes == ("branch.current-not-proven",)
    assert result.new_head_sha == NEW and result.side_effects_performed is True
    assert provider.read_calls == 3 and provider.validations == 1


@pytest.mark.parametrize(
    "authority",
    [
        "automatic_retry_authorized",
        "merge_authorized",
        "ready_for_review_authorized",
        "issue_closure_authorized",
        "repository_setting_authorized",
        "workflow_authorized",
    ],
)
def test_result_authority_flags_cannot_be_supplied_by_a_caller(authority):
    required = dict(
        repository="Blummer92/agent-os",
        pr_number=1187,
        status="converged",
        old_head_sha=OLD,
        new_head_sha=NEW,
        invalidated_head_evidence=(),
        validation=None,
        reason_codes=(),
        branch_refresh_authorized=True,
        side_effects_performed=True,
    )
    assert getattr(PullRequestBranchRefreshResult(**required), authority) is False
    with pytest.raises(TypeError):
        PullRequestBranchRefreshResult(**required, **{authority: True})
