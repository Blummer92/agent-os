"""Producer gates for cumulative merged-docs evidence (#3724).

The workflow producer nominates candidates only from same-repository
timeline cross-references, then qualifies each one independently: merged
state, canonical linked-issue association, merge-commit ancestry of the
evaluated base, and an unchanged documentation blob since the merge. These
tests pin those gates with a scripted REST fake and no network access.
"""
from scripts.agent_os_issue_acceptance.build_merged_doc_evidence import (
    build_records,
    canonical_issue_association,
    cross_referenced_prs,
    is_merge_ancestor,
)

REPO = "example/agent-os"
ISSUE = 500
SOURCE_PR = 501
CURRENT_PR = 502
MERGE_SHA = "4954b05c52a24744f566b74b75753259801e41dd"
BASE_SHA = "fe0ab9e756b852a5210142c31ef308b184c40a11"
DOC = "01_Shared_Standards/github/issue-lifecycle-standard.md"
DOC_BLOB = "939d0300ed2408c1811270e34e2f02fc5276b3e3"
OTHER_BLOB = "0a471504242b6f7a75726af3dc3797489e1f4e4b"
LINKED_BODY = f"## Linked issue\nPart of #{ISSUE}\n\nNon-closing: #{ISSUE}\n"


def _xref(number, repository=REPO, pull_request=True):
    issue = {"repository": {"full_name": repository}, "number": number}
    if pull_request:
        issue["pull_request"] = {"url": "x"}
    return {"event": "cross-referenced", "source": {"type": "issue", "issue": issue}}


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


def _contents(ref):
    return f"repos/{REPO}/contents/{DOC}?ref={ref}"


def _fake(**pr_overrides):
    return _FakeGh(
        {
            f"repos/{REPO}/issues/{ISSUE}/timeline": [_xref(SOURCE_PR), _xref(CURRENT_PR)],
            f"repos/{REPO}/pulls/{SOURCE_PR}": {
                "number": SOURCE_PR,
                "merged_at": "2026-10-20T18:28:24Z",
                "merge_commit_sha": MERGE_SHA,
                "body": LINKED_BODY,
                "title": "Deliver lifecycle documentation",
                **pr_overrides,
            },
            f"repos/{REPO}/compare/{MERGE_SHA}...{BASE_SHA}?per_page=1": {
                "merge_base_commit": {"sha": MERGE_SHA},
                "behind_by": 0,
            },
            f"repos/{REPO}/pulls/{SOURCE_PR}/files": [{"filename": DOC}, {"filename": "scripts/x.py"}],
            _contents(MERGE_SHA): {"type": "file", "sha": DOC_BLOB},
            _contents(BASE_SHA): {"type": "file", "sha": DOC_BLOB},
        }
    )


def _build(gh, required_docs=(DOC,)):
    return build_records(
        gh=gh,
        repository=REPO,
        issue_number=ISSUE,
        current_pr_number=CURRENT_PR,
        base_sha=BASE_SHA,
        required_docs=list(required_docs),
    )


# --- discovery and pure helpers ------------------------------------------------


def test_timeline_nominates_only_same_repository_pull_requests():
    timeline = [
        _xref(SOURCE_PR),
        _xref(503, pull_request=False),
        _xref(504, repository="someone/fork"),
        {"event": "cross-referenced", "source": {"type": "issue", "issue": {"number": 505, "pull_request": {"url": "x"}}}},
        {"event": "referenced", "commit_id": MERGE_SHA},
        {"event": "labeled"},
    ]
    assert cross_referenced_prs(timeline, REPO) == {SOURCE_PR}
    assert cross_referenced_prs({"not": "a list"}, REPO) == set()


def test_ancestor_requires_merge_base_and_not_behind():
    assert is_merge_ancestor({"merge_base_commit": {"sha": MERGE_SHA}, "behind_by": 0}, MERGE_SHA) is True
    assert is_merge_ancestor({"merge_base_commit": {"sha": BASE_SHA}, "behind_by": 0}, MERGE_SHA) is False
    assert is_merge_ancestor({"merge_base_commit": {"sha": MERGE_SHA}, "behind_by": 1}, MERGE_SHA) is False
    assert is_merge_ancestor({}, MERGE_SHA) is False


def test_canonical_association_uses_the_linked_issue_parser():
    assert canonical_issue_association(LINKED_BODY, "") == ISSUE
    assert canonical_issue_association(f"Closes #{ISSUE}", "") == ISSUE
    # Bare references without a declared non-closing directive stay manual-review.
    assert canonical_issue_association(f"Part of #{ISSUE}\n\nSee #{ISSUE}.", "") is None
    assert canonical_issue_association(f"Part of #{ISSUE} and #503\n\nNon-closing: #{ISSUE}, #503", "") is None
    assert canonical_issue_association(f"Non-closing: other/repo#{ISSUE}", "") is None


# --- positive record -----------------------------------------------------------


def test_verified_candidate_emits_only_unchanged_required_docs():
    assert _build(_fake()) == [
        {
            "source_pr_number": SOURCE_PR,
            "linked_issue_number": ISSUE,
            "association_basis": "timeline-cross-reference",
            "merge_commit_sha": MERGE_SHA,
            "merged": True,
            "merge_commit_in_evaluated_base": True,
            "declared_required_docs": [DOC],
            "files": [DOC],
        }
    ]


# --- negative gates ------------------------------------------------------------


def test_reverted_documentation_does_not_count():
    gh = _fake()
    gh.responses[_contents(BASE_SHA)] = {"type": "file", "sha": OTHER_BLOB}
    assert _build(gh) == []


def test_deleted_documentation_does_not_count():
    gh = _fake()
    del gh.responses[_contents(BASE_SHA)]
    assert _build(gh) == []


def test_documentation_absent_at_merge_or_not_a_file_does_not_count():
    gh = _fake()
    gh.responses[_contents(MERGE_SHA)] = {"type": "dir", "sha": DOC_BLOB}
    assert _build(gh) == []
    gh = _fake()
    gh.responses[_contents(MERGE_SHA)] = {"type": "file", "sha": "not-a-sha"}
    gh.responses[_contents(BASE_SHA)] = {"type": "file", "sha": "not-a-sha"}
    assert _build(gh) == []


def test_changed_requirements_do_not_count():
    # The issue now requires a document the source PR never delivered.
    assert _build(_fake(), required_docs=("01_Shared_Standards/github/other.md",)) == []


def test_ambiguous_or_bare_linkage_does_not_count():
    assert _build(_fake(body=f"Part of #{ISSUE}\n\n## Summary\nx")) == []
    assert _build(_fake(body=f"Part of #{ISSUE} and #503\n\nNon-closing: #{ISSUE}, #503")) == []
    assert _build(_fake(body="Part of #503\n\nNon-closing: #503")) == []


def test_cross_repository_reference_does_not_count():
    gh = _fake()
    gh.responses[f"repos/{REPO}/issues/{ISSUE}/timeline"] = [_xref(SOURCE_PR, repository="someone/fork")]
    assert _build(gh) == []
    assert _build(_fake(body=f"Non-closing: other/repo#{ISSUE}")) == []


def test_unmerged_or_non_ancestor_candidate_does_not_count():
    assert _build(_fake(merged_at=None)) == []
    gh = _fake()
    gh.responses[f"repos/{REPO}/compare/{MERGE_SHA}...{BASE_SHA}?per_page=1"] = {
        "merge_base_commit": {"sha": BASE_SHA},
        "behind_by": 0,
    }
    assert _build(gh) == []


def test_malformed_or_unreadable_candidates_are_skipped_without_dropping_others():
    gh = _fake()
    gh.responses[f"repos/{REPO}/issues/{ISSUE}/timeline"] += [_xref(510), _xref(511), _xref(512)]
    gh.responses[f"repos/{REPO}/pulls/511"] = {"merged_at": "x", "merge_commit_sha": MERGE_SHA, "body": 123, "title": "t"}
    gh.responses[f"repos/{REPO}/pulls/512"] = ["not", "an", "object"]
    assert [record["source_pr_number"] for record in _build(gh)] == [SOURCE_PR]


def test_malformed_file_list_does_not_count():
    gh = _fake()
    gh.responses[f"repos/{REPO}/pulls/{SOURCE_PR}/files"] = [{"filename": DOC}, {"filename": None}]
    assert _build(gh) == []


def test_non_sha_base_writes_no_evidence(tmp_path):
    from scripts.agent_os_issue_acceptance.build_merged_doc_evidence import main

    issue = tmp_path / "issue.md"
    issue.write_text("body", encoding="utf-8")
    output = tmp_path / "out.json"
    argv = ["--repository", REPO, "--issue-number", str(ISSUE), "--current-pr-number", str(CURRENT_PR)]
    argv += ["--base-sha", "main", "--issue-body-file", str(issue), "--output", str(output)]
    assert main(argv) == 0
    assert output.read_text(encoding="utf-8") == "[]\n"
