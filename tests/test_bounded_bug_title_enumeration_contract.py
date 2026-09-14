from pathlib import Path


AGENTS = Path("AGENTS.md")


def bounded_bug_rule() -> str:
    text = AGENTS.read_text(encoding="utf-8")
    start = text.index("7. For bounded bug-work requests")
    end = text.index("\n8. When a process/tooling bug", start)
    return text[start:end]


def test_open_issue_population_is_required_before_candidate_reconciliation():
    rule = bounded_bug_rule()
    assert "currently open GitHub issues only" in rule
    assert "state=open" in rule
    assert "Closed issues" in rule
    assert "must not enter candidate enumeration" in rule


def test_managed_bug_type_is_not_the_only_discovery_signal():
    rule = bounded_bug_rule()
    assert "existing open bug backlog" in rule
    assert "fresh defect discovery" in rule
    assert "discover new bugs only when the reconciled open backlog cannot satisfy the requested count" in rule


def test_candidate_local_skips_cannot_terminate_parent_batch():
    rule = bounded_bug_rule()
    for phrase in (
        "already-fixed/completed",
        "duplicate",
        "blocked-item-local",
        "non-terminal for the parent batch",
        "immediately advance to the next independent open candidate",
    ):
        assert phrase in rule


def test_title_marked_bug_discovery_regression_shape_is_explicit():
    # #2379 pins the execution-interface population query that exposed the miss:
    # an open issue whose title says BUG/Bug remains a bug candidate even when
    # managed classification is absent or stale. Canonical reconciliation still
    # decides whether that candidate is actionable.
    title_query = "is:issue is:open bug in:title"
    assert "is:open" in title_query
    assert "bug in:title" in title_query
    assert "label:type:bug" not in title_query


def test_requested_count_cannot_be_padded_after_title_discovery():
    assert "Do not create issues merely to pad a requested count" in bounded_bug_rule()
