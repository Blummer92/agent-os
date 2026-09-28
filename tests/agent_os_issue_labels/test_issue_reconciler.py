from pathlib import Path

from scripts.agent_os_issue_acceptance.issue_operational_state import ReadinessState
from scripts.agent_os_issue_labels.issue_reconciler import (
    LiveIssueSnapshot,
    expected_lineage_from_evidence,
    load_lineage_migration_evidence,
    project_issue_lineage,
    project_issue_lineage_batch,
    reconcile_issue_batch,
    reconcile_issue_labels,
)
from tests.agent_os_issue_labels.lifecycle_admission import admitted_lifecycle_labels

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"
LINEAGE_EVIDENCE = ROOT / "tests/fixtures/agent_os_issue_labels/reconstructed_lineage_migration_evidence_2026-09-21.json"

BODY = """### Issue tier

tier:1-standard-implementation

### Primary owner

owner:github-service-agent

### Readiness candidate

status:ready

### Work type

type:bug

### Source of truth

GitHub

### External write boundary

no-external-write
"""


class Provider:
    def __init__(self, snapshots, available=None, fail_write=False):
        self.snapshots = dict(snapshots)
        self.available = tuple(
            available
            or (
                "agent-os",
                "owner:github-service-agent",
                "owner:chatgpt-orchestrator",
                "status:ready",
                "status:blocked",
                "status:needs-decision",
                "type:bug",
            )
        )
        self.fail_write = fail_write
        self.writes = []

    def read(self, repository, issue_number):
        return self.snapshots[issue_number]

    def available_labels(self, repository):
        return self.available

    def add_label(self, repository, issue_number, label):
        if self.fail_write:
            raise RuntimeError("boom")
        snap = self.snapshots[issue_number]
        self.snapshots[issue_number] = LiveIssueSnapshot(
            snap.repository, snap.issue_number, snap.body, tuple((*snap.labels, label)), snap.state
        )
        self.writes.append(("add", issue_number, label))

    def remove_label(self, repository, issue_number, label):
        if self.fail_write:
            raise RuntimeError("boom")
        snap = self.snapshots[issue_number]
        self.snapshots[issue_number] = LiveIssueSnapshot(
            snap.repository,
            snap.issue_number,
            snap.body,
            tuple(x for x in snap.labels if x != label),
            snap.state,
        )
        self.writes.append(("remove", issue_number, label))


class ReorderedReadProvider(Provider):
    def __init__(self, snapshots, **kwargs):
        super().__init__(snapshots, **kwargs)
        self.read_count = 0

    def read(self, repository, issue_number):
        snap = super().read(repository, issue_number)
        self.read_count += 1
        if self.read_count == 2:
            return LiveIssueSnapshot(snap.repository, snap.issue_number, snap.body, tuple(reversed(snap.labels)), snap.state)
        return snap


class ReadbackMismatchProvider(Provider):
    def read(self, repository, issue_number):
        snap = super().read(repository, issue_number)
        if self.writes:
            return LiveIssueSnapshot(
                snap.repository,
                snap.issue_number,
                snap.body,
                tuple(label for label in snap.labels if label != "status:ready"),
                snap.state,
            )
        return snap


def snap(number=1, labels=(), body=BODY):
    return LiveIssueSnapshot("Blummer92/agent-os", number, body, tuple(labels))


def reconcile(provider, number=1, **kwargs):
    return reconcile_issue_labels(
        provider,
        "Blummer92/agent-os",
        number,
        issue_form_path=FORM,
        label_map_path=MAP,
        **kwargs,
    )


def duplicate_section(body, heading, value, *, alias=None):
    marker = f"### {heading}\n\n"
    insertion = f"### {alias or heading}\n\n{value}\n\n"
    return body.replace(marker, insertion + marker, 1)


def test_zero_label_issue_dry_run_bootstraps_without_writes():
    provider = Provider({1: snap()})
    result = reconcile(provider)
    assert result.convergence_status == "would-change"
    assert set(result.labels_to_add) == {"agent-os", "owner:github-service-agent", "status:ready", "type:bug"}
    assert provider.writes == []


def test_stale_managed_label_removed_but_human_label_preserved():
    provider = Provider({1: snap(labels=("agent-os", "owner:github-service-agent", "status:blocked", "human-note"))})
    result = reconcile(provider, dry_run=False, lifecycle_admission=admitted_lifecycle_labels())
    assert result.convergence_status == "converged"
    assert ("remove", 1, "status:blocked") in provider.writes
    assert "human-note" in provider.snapshots[1].labels



def test_2972_canonical_ready_replaces_stale_needs_decision_and_preserves_human_label():
    provider = Provider({1: snap(labels=(
        "agent-os", "owner:github-service-agent", "status:needs-decision", "type:bug", "human-note",
    ))})
    result = reconcile(
        provider,
        dry_run=False,
        lifecycle_admission=admitted_lifecycle_labels(),
        canonical_readiness=ReadinessState.READY,
    )
    assert result.convergence_status == "converged"
    assert ("add", 1, "status:ready") in provider.writes
    assert ("remove", 1, "status:needs-decision") in provider.writes
    assert "human-note" in provider.snapshots[1].labels


def test_2972_canonical_blocked_replaces_stale_needs_decision():
    provider = Provider({1: snap(labels=(
        "agent-os", "owner:github-service-agent", "status:needs-decision", "type:bug",
    ))})
    result = reconcile(
        provider,
        dry_run=False,
        lifecycle_admission=admitted_lifecycle_labels(),
        canonical_readiness=ReadinessState.BLOCKED,
    )
    assert result.convergence_status == "converged"
    assert ("add", 1, "status:blocked") in provider.writes
    assert ("remove", 1, "status:needs-decision") in provider.writes


def test_2972_canonical_needs_decision_keeps_genuine_decision_state():
    provider = Provider({1: snap(labels=(
        "agent-os", "owner:github-service-agent", "status:needs-decision", "type:bug",
    ))})
    result = reconcile(provider, canonical_readiness=ReadinessState.NEEDS_DECISION)
    assert result.convergence_status == "already-current"
    assert provider.writes == []


def test_2972_canonical_readiness_override_is_fail_closed_for_noncanonical_value():
    provider = Provider({1: snap(labels=("status:needs-decision",))})
    result = reconcile(provider, canonical_readiness="ready")
    assert result.convergence_status == "manual-review"
    assert result.reason_codes == ("canonical-readiness-invalid",)
    assert provider.writes == []


def test_ambiguous_or_incomplete_metadata_routes_to_manual_review():
    provider = Provider({1: snap(body="### Primary owner\n\nowner:github-service-agent\n")})
    assert reconcile(provider).convergence_status == "manual-review"


def test_conflicting_readiness_routes_to_manual_review_without_writes():
    body = BODY.replace("status:ready", "status:ready\nstatus:blocked")
    provider = Provider({1: snap(body=body)})
    result = reconcile(provider, dry_run=False, lifecycle_admission=admitted_lifecycle_labels())
    assert result.convergence_status == "manual-review"
    assert result.reason_codes == ("ambiguous-owner-or-readiness",)
    assert provider.writes == []


def test_repeated_owner_heading_conflict_routes_to_manual_review_without_writes():
    body = duplicate_section(BODY, "Primary owner", "owner:chatgpt-orchestrator")
    provider = Provider({1: snap(body=body)})
    result = reconcile(provider, dry_run=False, lifecycle_admission=admitted_lifecycle_labels())
    assert result.convergence_status == "manual-review"
    assert result.reason_codes == ("ambiguous-owner-or-readiness",)
    assert provider.writes == []


def test_alias_equivalent_owner_heading_conflict_routes_to_manual_review():
    body = duplicate_section(BODY, "Primary owner", "owner:chatgpt-orchestrator", alias="Owner agent")
    provider = Provider({1: snap(body=body)})
    result = reconcile(provider, dry_run=False, lifecycle_admission=admitted_lifecycle_labels())
    assert result.convergence_status == "manual-review"
    assert provider.writes == []


def test_repeated_readiness_heading_conflict_routes_to_manual_review():
    body = duplicate_section(BODY, "Readiness candidate", "status:blocked")
    provider = Provider({1: snap(body=body)})
    result = reconcile(provider, dry_run=False, lifecycle_admission=admitted_lifecycle_labels())
    assert result.convergence_status == "manual-review"
    assert provider.writes == []


def test_identical_duplicate_owner_is_deduplicated_deterministically():
    body = duplicate_section(BODY, "Primary owner", "owner:github-service-agent")
    provider = Provider({1: snap(body=body)})
    assert reconcile(provider).convergence_status == "would-change"


def test_duplicate_conflict_is_order_independent_and_newline_tolerant():
    first = duplicate_section(BODY, "Primary owner", "owner:chatgpt-orchestrator")
    second = first.replace(
        "### Primary owner\n\nowner:chatgpt-orchestrator\n\n### Primary owner\n\nowner:github-service-agent",
        "### Primary owner\r\n\r\n owner:github-service-agent \r\n\r\n### Primary owner\r\n\r\nowner:chatgpt-orchestrator",
    )
    for body in (first, second):
        provider = Provider({1: snap(body=body)})
        result = reconcile(provider, dry_run=False, lifecycle_admission=admitted_lifecycle_labels())
        assert result.convergence_status == "manual-review"
        assert provider.writes == []


def test_legacy_owner_alias_projects_canonical_owner_label():
    body = BODY.replace("owner:github-service-agent", "owner:integration-manager")
    provider = Provider({1: snap(body=body)})
    result = reconcile(provider)
    assert result.convergence_status == "would-change"
    assert "owner:chatgpt-orchestrator" in result.labels_to_add
    assert "owner:integration-manager" not in result.labels_to_add


def test_missing_repository_label_blocks():
    provider = Provider({1: snap()}, available=("agent-os",))
    assert reconcile(provider).convergence_status == "blocked"


def test_write_requires_explicit_authorization():
    provider = Provider({1: snap()})
    result = reconcile(provider, dry_run=False)
    assert result.convergence_status == "blocked"
    assert provider.writes == []


def test_prewrite_currentness_ignores_label_order_only():
    provider = ReorderedReadProvider({1: snap(labels=("human-note", "status:blocked"))})
    result = reconcile(provider, dry_run=False, lifecycle_admission=admitted_lifecycle_labels())
    assert result.convergence_status == "converged"
    assert result.side_effects_performed is True


def test_provider_failure_is_explicit():
    provider = Provider({1: snap()}, fail_write=True)
    result = reconcile(provider, dry_run=False, lifecycle_admission=admitted_lifecycle_labels())
    assert result.convergence_status == "blocked"
    assert result.reason_codes == ("provider-write-failure:RuntimeError",)


def test_readback_mismatch_is_explicit():
    provider = ReadbackMismatchProvider({1: snap()})
    result = reconcile(provider, dry_run=False, lifecycle_admission=admitted_lifecycle_labels())
    assert result.convergence_status == "blocked"
    assert result.reason_codes == ("readback-mismatch",)
    assert result.side_effects_performed is True


def test_unchanged_issue_is_idempotent():
    labels = ("agent-os", "owner:github-service-agent", "status:ready", "type:bug")
    provider = Provider({1: snap(labels=labels)})
    result = reconcile(provider, dry_run=False, lifecycle_admission=admitted_lifecycle_labels())
    assert result.convergence_status == "already-current"
    assert provider.writes == []


def test_batch_continues_past_item_local_failure():
    provider = Provider({1: snap(1, body="bad"), 2: snap(2)})
    results = reconcile_issue_batch(
        provider,
        "Blummer92/agent-os",
        (1, 2),
        issue_form_path=FORM,
        label_map_path=MAP,
    )
    assert results[0].convergence_status == "manual-review"
    assert results[1].convergence_status == "would-change"


def test_issue_closed_during_label_write_cannot_report_convergence():
    class ClosingProvider(Provider):
        def add_label(self, repository, issue_number, label):
            super().add_label(repository, issue_number, label)
            current = self.snapshots[issue_number]
            self.snapshots[issue_number] = LiveIssueSnapshot(
                current.repository, current.issue_number, current.body,
                current.labels, "closed",
            )

    provider = ClosingProvider({1: snap(labels=("human-note",))})
    result = reconcile(provider, dry_run=False, lifecycle_admission=admitted_lifecycle_labels())
    assert result.convergence_status == "blocked"
    assert result.reason_codes == ("issue-state-changed-during-mutation",)
    assert result.side_effects_performed is True
    assert "human-note" in provider.snapshots[1].labels

    # The existing reconciler can clean the terminal projection on reacquisition.
    result = reconcile(provider, dry_run=False, lifecycle_admission=admitted_lifecycle_labels())
    assert result.convergence_status == "converged"
    assert "status:ready" not in provider.snapshots[1].labels
    assert "human-note" in provider.snapshots[1].labels


def test_readiness_body_changed_during_write_cannot_report_convergence():
    class EditingProvider(Provider):
        def add_label(self, repository, issue_number, label):
            super().add_label(repository, issue_number, label)
            current = self.snapshots[issue_number]
            self.snapshots[issue_number] = LiveIssueSnapshot(
                current.repository, current.issue_number,
                current.body.replace("status:ready", "status:blocked"),
                current.labels, current.state,
            )

    provider = EditingProvider({1: snap()})
    result = reconcile(provider, dry_run=False, lifecycle_admission=admitted_lifecycle_labels())
    assert result.convergence_status == "blocked"
    assert result.reason_codes == ("issue-state-changed-during-mutation",)
    assert result.side_effects_performed is True


def lineage_body(*, parent=None, root=None):
    body = BODY
    if parent is not None:
        body += f"\n### Original parent\n\n#{parent}\n"
    if root is not None:
        body += f"\n### Current root-cause owner\n\n#{root}\n"
    return body


def test_lineage_projection_keeps_parent_history_distinct_from_shared_root_cause():
    provider = Provider({
        10: snap(10, body=lineage_body(parent=100, root=1401)),
        11: snap(11, body=lineage_body(parent=101, root=1401)),
        100: snap(100), 101: snap(101), 1401: snap(1401),
    })
    first = project_issue_lineage(provider, "Blummer92/agent-os", 10, issue_form_path=FORM)
    second = project_issue_lineage(provider, "Blummer92/agent-os", 11, issue_form_path=FORM)
    assert (first.original_parent_issue_number, second.original_parent_issue_number) == (100, 101)
    assert first.root_cause_issue_number == second.root_cause_issue_number == 1401


def test_closed_parent_is_historical_but_closed_root_cause_blocks_projection():
    provider = Provider({
        10: snap(10, body=lineage_body(parent=100, root=1401)),
        100: LiveIssueSnapshot("Blummer92/agent-os", 100, BODY, (), "closed"),
        1401: LiveIssueSnapshot("Blummer92/agent-os", 1401, BODY, (), "closed"),
    })
    result = project_issue_lineage(provider, "Blummer92/agent-os", 10, issue_form_path=FORM)
    assert result.projection_status == "blocked"
    assert result.reason_codes == ("root-cause-not-open",)
    assert result.original_parent_issue_number == 100


def test_unresolved_lineage_is_not_guessed_and_is_idempotent():
    provider = Provider({10: snap(10)})
    result = project_issue_lineage(provider, "Blummer92/agent-os", 10, issue_form_path=FORM)
    assert result.projection_status == "already-current"
    assert result.original_parent_issue_number is None
    assert result.root_cause_issue_number is None
    assert provider.writes == []


def test_expected_backfill_is_dry_run_only_and_validates_expected_root_currentness():
    provider = Provider({
        10: snap(10, body=lineage_body(parent=100)),
        100: snap(100),
        1401: snap(1401),
    })
    result = project_issue_lineage(
        provider, "Blummer92/agent-os", 10, issue_form_path=FORM,
        expected_original_parent=100, expected_root_cause=1401,
    )
    assert result.projection_status == "would-change"
    assert result.would_change_fields == ("root_cause_issue_number",)
    assert provider.writes == []


def test_lineage_batch_continues_past_item_local_closed_root():
    provider = Provider({
        10: snap(10, body=lineage_body(root=1401)),
        11: snap(11, body=lineage_body(root=2288)),
        1401: LiveIssueSnapshot("Blummer92/agent-os", 1401, BODY, (), "closed"),
        2288: snap(2288),
    })
    results = project_issue_lineage_batch(
        provider, "Blummer92/agent-os", (10, 11), issue_form_path=FORM
    )
    assert results[0].projection_status == "blocked"
    assert results[1].projection_status == "already-current"


def test_lineage_projection_does_not_touch_labels_or_create_authority():
    provider = Provider({
        10: snap(10, labels=("human-note", "status:blocked"), body=lineage_body(root=1401)),
        1401: snap(1401),
    })
    result = project_issue_lineage(provider, "Blummer92/agent-os", 10, issue_form_path=FORM)
    assert result.projection_status == "already-current"
    assert provider.snapshots[10].labels == ("human-note", "status:blocked")
    assert provider.writes == []


def test_3028_reconstructed_lineage_fixture_is_finite_provenance_bound_and_non_authorizing():
    evidence = load_lineage_migration_evidence(LINEAGE_EVIDENCE)
    assert evidence.schema_version == 1
    assert evidence.artifact_kind == "reconstructed-lineage-migration-evidence"
    assert evidence.mutation_authority is False
    assert len(evidence.entries) == 7
    assert all(entry.evidence for entry in evidence.entries)


def test_3028_fixture_projects_only_explicit_relationships_and_preserves_unresolved_values():
    evidence = load_lineage_migration_evidence(LINEAGE_EVIDENCE)
    expected = expected_lineage_from_evidence(evidence)
    assert expected[2153] == (2090, None)
    assert expected[2636] == (2595, None)
    assert expected[2669] == (2659, None)
    assert expected[2681] == (None, None)
    assert expected[2741] == (None, 2288)
    assert 3028 not in expected


def test_3028_current_closed_root_overrides_historical_fixture_evidence():
    provider = Provider({
        2741: snap(2741),
        2288: LiveIssueSnapshot("Blummer92/agent-os", 2288, BODY, (), "closed"),
    })
    expected = expected_lineage_from_evidence(load_lineage_migration_evidence(LINEAGE_EVIDENCE))
    result = project_issue_lineage_batch(
        provider,
        "Blummer92/agent-os",
        (2741,),
        issue_form_path=FORM,
        expected_lineage=expected,
    )[0]
    assert result.projection_status == "blocked"
    assert result.reason_codes == ("expected-root-cause-not-open",)
    assert provider.writes == []


def test_3028_closed_historical_parent_does_not_block_projection():
    provider = Provider({
        2153: snap(2153),
        2090: LiveIssueSnapshot("Blummer92/agent-os", 2090, BODY, (), "closed"),
    })
    expected = expected_lineage_from_evidence(load_lineage_migration_evidence(LINEAGE_EVIDENCE))
    result = project_issue_lineage_batch(
        provider,
        "Blummer92/agent-os",
        (2153,),
        issue_form_path=FORM,
        expected_lineage=expected,
    )[0]
    assert result.projection_status == "would-change"
    assert result.would_change_fields == ("original_parent_issue_number",)
    assert provider.writes == []
