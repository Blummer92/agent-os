"""Producer gates for cumulative merged-docs evidence (#3719).

The workflow producer must discover candidates only from GitHub-generated
timeline associations and must verify merge-commit ancestry through the
compare API. These tests pin the pure helpers without any network access.
"""
from scripts.agent_os_issue_acceptance.build_merged_doc_evidence import (
    association_basis,
    build_records,
    is_merge_ancestor,
    timeline_associations,
)

MERGE_SHA = "4954b05c52a24744f566b74b75753259801e41dd"
BASE_SHA = "fe0ab9e756b852a5210142c31ef308b184c40a11"


def test_timeline_extracts_cross_referenced_prs_and_referenced_commits():
    timeline = [
        {"event": "cross-referenced", "source": {"type": "issue", "issue": {"number": 3681, "pull_request": {"url": "x"}}}},
        {"event": "cross-referenced", "source": {"type": "issue", "issue": {"number": 3678}}},
        {"event": "referenced", "commit_id": MERGE_SHA},
        {"event": "labeled"},
    ]
    prs, commits = timeline_associations(timeline)
    assert prs == {3681}
    assert commits == {MERGE_SHA}


def test_ancestor_requires_merge_base_and_not_behind():
    assert is_merge_ancestor({"merge_base_commit": {"sha": MERGE_SHA}, "behind_by": 0}, MERGE_SHA) is True
    assert is_merge_ancestor({"merge_base_commit": {"sha": BASE_SHA}, "behind_by": 0}, MERGE_SHA) is False
    assert is_merge_ancestor({"merge_base_commit": {"sha": MERGE_SHA}, "behind_by": 1}, MERGE_SHA) is False
    assert is_merge_ancestor({}, MERGE_SHA) is False


def test_association_basis_prefers_cross_reference_and_accepts_referenced_commit():
    assert association_basis(pr_number=3681, merge_sha=MERGE_SHA, cross_referenced={3681}, referenced=set()) == "timeline-cross-reference"
    assert association_basis(pr_number=3681, merge_sha=MERGE_SHA, cross_referenced=set(), referenced={MERGE_SHA}) == "timeline-referenced-merge-commit"
    assert association_basis(pr_number=3681, merge_sha=MERGE_SHA, cross_referenced=set(), referenced=set()) is None


class _FakeGh:
    def __init__(self, timeline, prs, compare):
        self._timeline = timeline
        self._prs = prs
        self._compare = compare

    def api(self, path):
        if "timeline" in path:
            return self._timeline
        return self._compare

    def pr_view(self, pr_number):
        return self._prs[pr_number]


def _fake_3681():
    return _FakeGh(
        timeline=[
            {"event": "cross-referenced", "source": {"type": "issue", "issue": {"number": 3681, "pull_request": {"url": "x"}}}},
            {"event": "referenced", "commit_id": MERGE_SHA},
        ],
        prs={
            3681: {
                "number": 3681,
                "mergedAt": "2026-10-20T18:28:24Z",
                "mergeCommit": {"oid": MERGE_SHA},
                "files": [{"path": "01_Shared_Standards/github/issue-lifecycle-standard.md"}],
                "body": "Part of #3677\n\n## Summary\nx",
                "title": "#3677: criterion preservation",
            }
        },
        compare={"merge_base_commit": {"sha": MERGE_SHA}, "behind_by": 0},
    )


def test_build_records_accepts_3681_like_candidate():
    records = build_records(
        gh=_fake_3681(),
        repository="Blummer92/agent-os",
        issue_number=3677,
        current_pr_number=3709,
        base_sha=BASE_SHA,
        required_docs=["01_Shared_Standards/github/issue-lifecycle-standard.md"],
    )
    assert len(records) == 1
    assert records[0]["source_pr_number"] == 3681
    assert records[0]["association_basis"] == "timeline-cross-reference"
    assert records[0]["merge_commit_in_evaluated_base"] is True


def test_build_records_rejects_non_ancestor_merge():
    gh = _fake_3681()
    gh._compare = {"merge_base_commit": {"sha": BASE_SHA}, "behind_by": 0}
    records = build_records(
        gh=gh,
        repository="Blummer92/agent-os",
        issue_number=3677,
        current_pr_number=3709,
        base_sha=BASE_SHA,
        required_docs=["01_Shared_Standards/github/issue-lifecycle-standard.md"],
    )
    assert records == []
