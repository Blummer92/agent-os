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


def test_fresh_discovery_requires_explicit_new_bug_intent_or_incidental_defect():
    text = rule()
    assert "Fresh defect discovery is allowed only when the user explicitly requests new bug discovery/logging" in text
    assert "distinct defect is discovered incidentally during authorized work" in text


def test_new_bugs_do_not_substitute_for_existing_backlog_count_without_approval():
    text = rule()
    assert "do not count toward a user-requested existing-backlog implementation count" in text
    assert "unless the user explicitly approves that substitution" in text


def test_exhausted_backlog_reports_honest_shortfall_instead_of_padding_count():
    text = rule()
    assert "report the honest shortfall rather than creating issues merely to pad the count" in text


def test_ambiguous_find_bugs_uses_backlog_but_explicit_new_bugs_allows_discovery():
    text = rule()
    assert "ambiguous wording such as `find 10 bugs` resolves to the existing canonical backlog" in text
    assert "explicit wording such as `find 10 new bugs` authorizes fresh defect discovery" in text


def test_blocked_or_already_fixed_candidates_do_not_end_parent_batch():
    text = rule()
    assert "blocked-item-local" in text
    assert "already-fixed/completed" in text
    assert "non-terminal for the parent batch" in text
