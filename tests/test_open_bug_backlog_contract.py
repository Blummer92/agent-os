from pathlib import Path


AGENTS = Path("AGENTS.md")


def bounded_bug_rule() -> str:
    text = AGENTS.read_text(encoding="utf-8")
    start = text.index("7. For bounded bug-work requests")
    end = text.index("\n8. When a process/tooling bug", start)
    return text[start:end]


def test_current_bug_candidates_are_open_only_at_enumeration():
    rule = bounded_bug_rule()
    assert "currently open GitHub issues only" in rule
    assert "`is:issue is:open`" in rule
    assert "Closed issues" in rule
    assert "must not enter candidate enumeration" in rule


def test_closed_history_cannot_promote_actionable_work():
    rule = bounded_bug_rule()
    assert "historical evidence never promotes a closed issue into actionable work" in rule
    assert "Never fall back to closed issues as replacement candidates" in rule


def test_candidate_local_dispositions_advance_cursor():
    rule = bounded_bug_rule()
    assert "candidate-local terminal dispositions are non-terminal for the parent batch" in rule
    assert "immediately advance to the next independent open candidate" in rule
