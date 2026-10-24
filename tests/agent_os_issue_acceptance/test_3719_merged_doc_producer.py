"""Producer gates for cumulative merged-docs evidence (#3719).

The workflow producer must discover candidates only from GitHub-generated
timeline associations and must verify merge-commit ancestry through the
compare API. These tests pin the pure helpers without any network access.
"""
from scripts.agent_os_issue_acceptance.build_merged_doc_evidence import (
    build_records,
    cross_referenced_prs,
    is_merge_ancestor,
)

MERGE_SHA = "4954b05c52a24744f566b74b75753259801e41dd"
BASE_SHA = "fe0ab9e756b852a5210142c31ef308b184c40a11"


def test_timeline_extracts_only_cross_referenced_prs():
    timeline = [
        {"event": "cross-referenced", "source": {"type": "issue", "issue": {"repository": {"full_name": "Blummer92/agent-os"}, "number": 3681, "pull_request": {"url": "x"}}}},
        {"event": "cross-referenced", "source": {"type": "issue", "issue": {"repository": {"full_name": "Blummer92/agent-os"}, "number": 3678}}},
        {"event": "referenced", "commit_id": MERGE_SHA},
        {"event": "labeled"},
    ]
    assert cross_referenced_prs(timeline, "Blummer92/agent-os") == {3681}
    assert cross_referenced_prs({"not": "a list"}, "Blummer92/agent-os") == set()


def test_timeline_ignores_cross_references_from_other_repositories():
    timeline = [
        {"event": "cross-referenced", "source": {"type": "issue", "issue": {"repository": {"full_name": "someone/fork"}, "number": 3681, "pull_request": {"url": "x"}}}},
        {"event": "cross-referenced", "source": {"type": "issue", "issue": {"number": 3682, "pull_request": {"url": "x"}}}},
    ]
    assert cross_referenced_prs(timeline, "Blummer92/agent-os") == set()


def test_ancestor_requires_merge_base_and_not_behind():
    assert is_merge_ancestor({"merge_base_commit": {"sha": MERGE_SHA}, "behind_by": 0}, MERGE_SHA) is True
    assert is_merge_ancestor({"merge_base_commit": {"sha": BASE_SHA}, "behind_by": 0}, MERGE_SHA) is False
    assert is_merge_ancestor({"merge_base_commit": {"sha": MERGE_SHA}, "behind_by": 1}, MERGE_SHA) is False
    assert is_merge_ancestor({}, MERGE_SHA) is False


class _FakeGh:
    """REST fake keyed by path; a missing path raises like a failed ``gh api``."""

    def __init__(self, responses):
        self.responses = dict(responses)

    def _read(self, path):
        if path not in self.responses:
            raise RuntimeError(f"gh api {path} failed")
        return self.responses[path]

    get = _read
    get_all = _read


def _fake_3681():
    return _FakeGh(
        {
            "repos/Blummer92/agent-os/issues/3677/timeline": [
                {"event": "cross-referenced", "source": {"type": "issue", "issue": {"repository": {"full_name": "Blummer92/agent-os"}, "number": 3681, "pull_request": {"url": "x"}}}},
                {"event": "cross-referenced", "source": {"type": "issue", "issue": {"repository": {"full_name": "Blummer92/agent-os"}, "number": 3709, "pull_request": {"url": "x"}}}},
            ],
            "repos/Blummer92/agent-os/pulls/3681": {
                "number": 3681,
                "merged_at": "2026-10-20T18:28:24Z",
                "merge_commit_sha": MERGE_SHA,
                "body": "Part of #3677\n\n## Summary\nx",
                "title": "#3677: criterion preservation",
            },
            f"repos/Blummer92/agent-os/compare/{MERGE_SHA}...{BASE_SHA}?per_page=1": {
                "merge_base_commit": {"sha": MERGE_SHA},
                "behind_by": 0,
            },
            "repos/Blummer92/agent-os/pulls/3681/files": [
                {"filename": "01_Shared_Standards/github/issue-lifecycle-standard.md"}
            ],
        }
    )


def _build(gh):
    return build_records(
        gh=gh,
        repository="Blummer92/agent-os",
        issue_number=3677,
        current_pr_number=3709,
        base_sha=BASE_SHA,
        required_docs=["01_Shared_Standards/github/issue-lifecycle-standard.md"],
    )


def test_build_records_accepts_3681_like_candidate():
    records = _build(_fake_3681())
    assert records == [
        {
            "source_pr_number": 3681,
            "linked_issue_number": 3677,
            "association_basis": "timeline-cross-reference",
            "merge_commit_sha": MERGE_SHA,
            "merged": True,
            "merge_commit_in_evaluated_base": True,
            "declared_required_docs": ["01_Shared_Standards/github/issue-lifecycle-standard.md"],
            "files": ["01_Shared_Standards/github/issue-lifecycle-standard.md"],
        }
    ]


def test_build_records_rejects_non_ancestor_merge():
    gh = _fake_3681()
    gh.responses[f"repos/Blummer92/agent-os/compare/{MERGE_SHA}...{BASE_SHA}?per_page=1"] = {
        "merge_base_commit": {"sha": BASE_SHA},
        "behind_by": 0,
    }
    assert _build(gh) == []


def test_build_records_rejects_unmerged_and_other_issue_candidates():
    gh = _fake_3681()
    gh.responses["repos/Blummer92/agent-os/pulls/3681"] = {**gh.responses["repos/Blummer92/agent-os/pulls/3681"], "merged_at": None}
    assert _build(gh) == []
    gh = _fake_3681()
    gh.responses["repos/Blummer92/agent-os/pulls/3681"] = {
        **gh.responses["repos/Blummer92/agent-os/pulls/3681"],
        "body": "Part of #3677 and #3678",
    }
    assert _build(gh) == []


def test_unreadable_candidate_is_skipped_without_dropping_others():
    gh = _fake_3681()
    gh.responses["repos/Blummer92/agent-os/issues/3677/timeline"].append(
        {"event": "cross-referenced", "source": {"type": "issue", "issue": {"repository": {"full_name": "Blummer92/agent-os"}, "number": 3700, "pull_request": {"url": "x"}}}}
    )
    records = _build(gh)
    assert [record["source_pr_number"] for record in records] == [3681]


def test_malformed_candidate_is_skipped_without_dropping_others():
    gh = _fake_3681()
    gh.responses["repos/Blummer92/agent-os/issues/3677/timeline"].append(
        {"event": "cross-referenced", "source": {"type": "issue", "issue": {"repository": {"full_name": "Blummer92/agent-os"}, "number": 3600, "pull_request": {"url": "x"}}}}
    )
    gh.responses["repos/Blummer92/agent-os/pulls/3600"] = {"merged_at": "x", "merge_commit_sha": MERGE_SHA, "body": 123, "title": "t"}
    assert [record["source_pr_number"] for record in _build(gh)] == [3681]
