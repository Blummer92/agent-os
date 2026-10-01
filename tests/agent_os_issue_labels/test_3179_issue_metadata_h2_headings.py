"""Regression tests for #3179: canonical metadata parser must recognize h2 headings.

The canonical metadata parser was h3-only, so host-created issues using
``##`` headings (e.g. #2656, #2660, #2740 with ``## Work type: type:bug``)
parsed to empty metadata and their correctly-applied labels -- including
type:bug -- were reported as extra/removable (false-positive removal
proposals). These tests pin h2/h3 parity at the parser layer and pin the
false-positive scenario at the checker and reconciler layers.
"""

from pathlib import Path

from scripts.agent_os_issue_labels.checker import evaluate_issue_labels
from scripts.agent_os_issue_labels.issue_metadata import (
    load_issue_form_fields,
    metadata_contract,
    parse_issue_form_body,
)
from scripts.agent_os_issue_labels.issue_reconciler import (
    LiveIssueSnapshot,
    reconcile_issue_labels,
)

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"

# Tiered-form body using the real form labels, in the canonical h3 style.
BODY_H3 = """### Issue tier

tier:1-standard-implementation

### Primary owner

owner:chatgpt-orchestrator

### Readiness candidate

status:needs-decision

### Work type

type:bug

### Source of truth

GitHub

### External write boundary

no-external-write
"""

# The same metadata expressed the way host-created issues write it: h2.
BODY_H2 = BODY_H3.replace("### ", "## ")

# The labels the label map projects for this metadata.
EXPECTED_LABELS = (
    "agent-os",
    "owner:chatgpt-orchestrator",
    "status:needs-decision",
    "type:bug",
)


class Provider:
    def __init__(self, snapshots, available=None):
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

    def read(self, repository, issue_number):
        return self.snapshots[issue_number]

    def available_labels(self, repository):
        return self.available

    def add_label(self, repository, issue_number, label):
        raise AssertionError("no writes expected in dry-run reconciliation")

    def remove_label(self, repository, issue_number, label):
        raise AssertionError("no writes expected in dry-run reconciliation")


def snap(body=BODY_H2, labels=()):
    return LiveIssueSnapshot("Blummer92/agent-os", 1, body, tuple(labels))


def test_h2_work_type_heading_is_parsed():
    # The #2656/#2660/#2740 pattern: host-created issues carry h2 metadata.
    metadata = parse_issue_form_body(
        "## Work type\n\ntype:bug\n", {"type": "Work type"}
    )
    assert metadata == {"type": ["type:bug"]}


def test_h2_and_h3_bodies_produce_identical_metadata():
    fields = load_issue_form_fields(FORM)
    assert parse_issue_form_body(BODY_H2, fields) == parse_issue_form_body(
        BODY_H3, fields
    )


def test_h2_tiered_body_reaches_tiered_contract():
    fields = load_issue_form_fields(FORM)
    metadata = parse_issue_form_body(BODY_H2, fields)
    assert metadata_contract(metadata) == "tiered"


def test_h2_headings_do_not_flag_type_bug_as_extra():
    # False-positive pin for #2656/#2660/#2740: pre-fix, the checker reported
    # type:bug as an extra existing label (a removal proposal) on an issue
    # whose body correctly declares ## Work type: type:bug.
    report = evaluate_issue_labels(BODY_H2, list(EXPECTED_LABELS), FORM, MAP)
    extras = next(
        line for line in report.evidence if line.startswith("extra existing labels:")
    )
    assert extras == "extra existing labels: none"
    assert "type:bug" not in extras


def test_reconciler_does_not_propose_removing_type_bug_for_h2_metadata():
    provider = Provider({1: snap(labels=EXPECTED_LABELS)})
    result = reconcile_issue_labels(
        provider,
        "Blummer92/agent-os",
        1,
        issue_form_path=FORM,
        label_map_path=MAP,
        dry_run=True,
    )
    assert result.convergence_status == "already-current"
    assert tuple(result.labels_to_remove) == ()
    assert "type:bug" not in result.labels_to_remove


def test_h4_headings_are_still_not_metadata():
    # The fix is bounded to h2 + h3; deeper headings remain non-metadata.
    metadata = parse_issue_form_body(
        "#### Work type\n\ntype:bug\n", {"type": "Work type"}
    )
    assert metadata == {}
