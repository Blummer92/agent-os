from pathlib import Path


AGENTS = Path("AGENTS.md").read_text(encoding="utf-8")


def test_candidate_local_skips_cannot_end_five_item_bug_mission():
    assert "candidate-local terminal dispositions are non-terminal for the parent batch" in AGENTS
    requested_count = 5
    delivered_count = 1
    assert delivered_count < requested_count


def test_bug_discovery_is_not_limited_to_managed_type_labels():
    title = "BUG: unlabelled but explicit defect"
    assert "bug" in title.casefold()
    assert "reconcile that existing open bug backlog before fresh defect discovery" in AGENTS


def test_no_count_padding():
    assert "Do not create issues merely to pad a requested count" in AGENTS
