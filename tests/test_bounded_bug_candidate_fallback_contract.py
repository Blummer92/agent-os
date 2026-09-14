from pathlib import Path


AGENTS = Path("AGENTS.md")


def rule() -> str:
    text = AGENTS.read_text(encoding="utf-8")
    start = text.index("7. For bounded bug-work requests")
    end = text.index("\n8. When a process/tooling bug", start)
    return text[start:end]


def test_existing_open_bug_backlog_is_reconciled_before_discovery():
    text = rule()
    assert "reconcile that existing open bug backlog before fresh defect discovery" in text
    assert "use eligible existing bugs first" in text


def test_discovery_is_allowed_when_reconciled_open_backlog_cannot_satisfy_count():
    text = rule()
    assert "discover new bugs only when the reconciled open backlog cannot satisfy the requested count" in text


def test_count_cannot_be_padded_with_synthetic_issues():
    assert "Do not create issues merely to pad a requested count" in rule()


def test_blocked_or_already_fixed_candidates_do_not_end_parent_batch():
    text = rule()
    assert "blocked-item-local" in text
    assert "already-fixed/completed" in text
    assert "non-terminal for the parent batch" in text
