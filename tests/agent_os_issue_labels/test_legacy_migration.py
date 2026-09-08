from pathlib import Path

from scripts.agent_os_issue_labels.issue_metadata import load_issue_form_fields, parse_issue_form_body
from scripts.agent_os_issue_labels.issue_reconciler import LiveIssueSnapshot, reconcile_issue_labels
from scripts.agent_os_issue_labels.legacy_migration import migrate_legacy_issue_body

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"

LEGACY_BODY = """## Summary

A classroom-material request returned prose instead of the requested artifact.

## Reproduction

1. Request the artifact.
2. Receive prose only.

## Acceptance criteria

- Produce the requested artifact when authorized.
"""

EVIDENCE = {
    "tier": "tier:1-standard-implementation",
    "owner": "owner:github-service-agent",
    "status": "status:ready",
    "type": "type:bug",
    "source-of-truth": "GitHub",
    "external-write": "no-external-write",
}


class Provider:
    def __init__(self, body):
        self.body = body

    def read(self, repository, issue_number):
        return LiveIssueSnapshot(repository, issue_number, self.body, ())

    def available_labels(self, repository):
        return ("agent-os", "owner:github-service-agent", "status:ready", "type:bug")

    def add_label(self, repository, issue_number, label):
        raise AssertionError("dry-run must not write")

    def remove_label(self, repository, issue_number, label):
        raise AssertionError("dry-run must not write")


def test_real_legacy_shape_can_reach_existing_canonical_reconciler():
    result = migrate_legacy_issue_body(LEGACY_BODY, EVIDENCE, issue_form_path=FORM)

    assert result.status == "ready-for-canonical-reconciliation"
    assert result.metadata_contract == "tiered"
    assert result.mutation_performed is False
    assert result.write_authorized is False
    reconciliation = reconcile_issue_labels(
        Provider(result.body),
        "Blummer92/agent-os",
        1944,
        issue_form_path=FORM,
        label_map_path=MAP,
        dry_run=True,
        label_write_authorized=False,
    )
    assert reconciliation.convergence_status == "would-change"
    assert "status:ready" in reconciliation.labels_to_add


def test_missing_evidence_fails_closed_and_names_field():
    evidence = dict(EVIDENCE)
    evidence.pop("tier")

    result = migrate_legacy_issue_body(LEGACY_BODY, evidence, issue_form_path=FORM)

    assert result.status == "manual-review"
    assert result.missing_fields == ("tier",)
    assert result.reason_codes == ("missing-canonical-evidence:tier",)
    assert result.body == LEGACY_BODY


def test_ambiguous_evidence_fails_closed_without_rendering_metadata():
    evidence = dict(EVIDENCE)
    evidence["status"] = ("status:ready", "status:blocked")

    result = migrate_legacy_issue_body(LEGACY_BODY, evidence, issue_form_path=FORM)

    assert result.status == "manual-review"
    assert "ambiguous-canonical-evidence:status" in result.reason_codes
    assert "missing-canonical-evidence:status" in result.reason_codes
    assert result.body == LEGACY_BODY


def test_canonical_block_is_last_so_trailing_content_cannot_corrupt_final_field():
    body = LEGACY_BODY + "\n## Historical notes\n\nThis prose must remain outside canonical fields.\n"
    result = migrate_legacy_issue_body(body, EVIDENCE, issue_form_path=FORM)
    fields = load_issue_form_fields(FORM)
    parsed = parse_issue_form_body(result.body, fields)

    assert result.status == "ready-for-canonical-reconciliation"
    assert result.body.rstrip().endswith("no-external-write")
    assert parsed["external-write"] == ["no-external-write"]
    assert "Historical notes" in result.body


def test_existing_tiered_body_is_unchanged():
    first = migrate_legacy_issue_body(LEGACY_BODY, EVIDENCE, issue_form_path=FORM)
    second = migrate_legacy_issue_body(first.body, EVIDENCE, issue_form_path=FORM)

    assert second.status == "already-tiered"
    assert second.body == first.body
    assert second.metadata_contract == "tiered"
