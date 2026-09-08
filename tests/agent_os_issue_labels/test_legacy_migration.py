from pathlib import Path

from scripts.agent_os_issue_labels.issue_metadata import (
    load_issue_form_fields,
    parse_issue_form_body,
)
from scripts.agent_os_issue_labels.issue_reconciler import (
    LiveIssueSnapshot,
    reconcile_issue_labels,
)
from scripts.agent_os_issue_labels.legacy_migration import build_legacy_issue_migration

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"

# Shape taken from the pre-migration portion of real legacy issue #1944.
LEGACY_BODY = """## Summary

A classroom-material request for a worksheet PDF returned prose instead of the requested artifact.

## Reproduction

1. Ask for the worksheet PDF.
2. Receive prose only.

## Acceptance criteria

- The requested artifact format is honored.
- A prose-only description is not treated as completion.
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
    def __init__(self, body: str):
        self.snapshot = LiveIssueSnapshot("Blummer92/agent-os", 1944, body, ())

    def read(self, repository, issue_number):
        return self.snapshot

    def available_labels(self, repository):
        return (
            "agent-os",
            "owner:github-service-agent",
            "status:ready",
            "type:bug",
        )

    def add_label(self, repository, issue_number, label):
        raise AssertionError("migration test must remain read-only")

    def remove_label(self, repository, issue_number, label):
        raise AssertionError("migration test must remain read-only")


def migrate(body=LEGACY_BODY, evidence=EVIDENCE):
    return build_legacy_issue_migration(
        body,
        evidence,
        issue_form_path=FORM,
        label_map_path=MAP,
    )


def test_real_legacy_shape_migrates_and_reaches_existing_readiness_projection():
    result = migrate()

    assert result.disposition == "migrated"
    assert result.metadata_contract == "tiered"
    assert result.mutation_performed is False
    assert result.body.startswith(LEGACY_BODY.rstrip())
    assert result.body.rstrip().endswith("no-external-write")

    fields = load_issue_form_fields(FORM)
    metadata = parse_issue_form_body(result.body, fields)
    assert metadata["tier"] == ["tier:1-standard-implementation"]
    assert metadata["owner"] == ["owner:github-service-agent"]
    assert metadata["status"] == ["status:ready"]
    assert metadata["type"] == ["type:bug"]
    assert metadata["source-of-truth"] == ["GitHub"]
    assert metadata["external-write"] == ["no-external-write"]

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
    assert set(reconciliation.labels_to_add) == {
        "agent-os",
        "owner:github-service-agent",
        "status:ready",
        "type:bug",
    }
    assert reconciliation.side_effects_performed is False


def test_missing_required_evidence_fails_closed_and_names_field():
    evidence = dict(EVIDENCE)
    evidence.pop("tier")

    result = migrate(evidence=evidence)

    assert result.disposition == "manual-review"
    assert result.body == LEGACY_BODY
    assert "missing-canonical-evidence:tier" in result.reason_codes


def test_trailing_legacy_content_stays_before_canonical_block():
    body = LEGACY_BODY + "\nOperator note: preserve this trailing legacy prose.\n"

    result = migrate(body=body)

    assert result.disposition == "migrated"
    assert result.body.index("Operator note") < result.body.index("## Canonical metadata")
    fields = load_issue_form_fields(FORM)
    metadata = parse_issue_form_body(result.body, fields)
    assert metadata["external-write"] == ["no-external-write"]


def test_existing_tiered_body_is_unchanged_and_not_duplicated():
    first = migrate()

    second = migrate(body=first.body)

    assert second.disposition == "already-canonical"
    assert second.body == first.body
    assert second.body.count("## Canonical metadata") == 1


def test_partial_existing_canonical_metadata_routes_to_manual_review():
    body = "### Primary owner\n\nowner:github-service-agent\n\nLegacy prose follows.\n"

    result = migrate(body=body)

    assert result.disposition == "manual-review"
    assert result.body == body
    assert result.reason_codes == ("existing-canonical-metadata-incomplete",)


def test_retired_owner_alias_is_not_accepted_as_new_canonical_metadata():
    evidence = dict(EVIDENCE)
    evidence["owner"] = "owner:integration-manager"

    result = migrate(evidence=evidence)

    assert result.disposition == "manual-review"
    assert result.reason_codes == (
        "noncanonical-form-evidence:owner=owner:integration-manager",
    )


def test_multiline_metadata_value_cannot_inject_trailing_content():
    evidence = dict(EVIDENCE)
    evidence["status"] = "status:ready\nUnexpected prose"

    result = migrate(evidence=evidence)

    assert result.disposition == "manual-review"
    assert "multiline-canonical-evidence:status" in result.reason_codes
    assert result.body == LEGACY_BODY
