from dataclasses import replace

import pytest

from scripts.agent_os_issue_labels.pr_reconciler import LivePullRequestSnapshot


BASE = LivePullRequestSnapshot(
    repository="Blummer92/agent-os", pr_number=1, head_sha="a" * 40,
    draft=True, mergeable=True, conflicted=False, behind=False,
    validation_state="pending", blocking_review_threads=0,
    labels=("human:keep",), base_ref="main", head_ref="agent/test",
)


@pytest.mark.parametrize(
    "field,value",
    [
        ("draft", False),
        ("mergeable", False),
        ("conflicted", True),
        ("behind", True),
        ("validation_state", "success"),
        ("blocking_review_threads", 1),
        ("labels", ("human:keep", "pr:draft")),
    ],
)
def test_same_head_planner_relevant_drift_changes_evidence(field, value):
    changed = replace(BASE, **{field: value})
    assert changed.head_sha == BASE.head_sha
    assert changed.evidence() != BASE.evidence()


def test_non_planner_refs_do_not_change_planner_evidence():
    changed = replace(BASE, base_ref="release", head_ref="agent/renamed")
    assert changed.evidence() == BASE.evidence()
