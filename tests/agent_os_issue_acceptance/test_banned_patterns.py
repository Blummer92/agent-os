from scripts.agent_os_issue_acceptance.checks import banned_patterns
from scripts.agent_os_issue_acceptance.models import IssueMetadata, Status


def _assignment(name: str) -> str:
    return name + ' = "synthetic-fixture"'


def test_deleted_fixture_and_unmodified_context_are_not_new_secrets():
    for marker in ("-", " "):
        diff = "diff --git a/retired.py b/retired.py\n--- a/retired.py\n+++ /dev/null\n@@ -1 +0,0 @@\n" + marker + _assignment("secret") + "\n"
        assert banned_patterns.check(IssueMetadata.empty(), diff).status is Status.PASS


def test_added_secret_and_api_key_are_still_blocked():
    for key in ("secret", "api_key", "password"):
        diff = "@@ -0,0 +1 @@\n+" + _assignment(key) + "\n"
        assert banned_patterns.check(IssueMetadata.empty(), diff).status is Status.FAIL


def test_removed_secret_and_added_safe_line_passes():
    diff = "@@ -1 +1 @@\n-" + _assignment("secret") + "\n+safe = True\n"
    assert banned_patterns.check(IssueMetadata.empty(), diff).status is Status.PASS


def test_removed_secret_and_new_secret_does_not_mask_the_addition():
    diff = "@@ -1 +1 @@\n-" + _assignment("secret") + "\n+" + _assignment("secret") + "\n"
    assert banned_patterns.check(IssueMetadata.empty(), diff).status is Status.FAIL


def test_issue_banned_pattern_still_checks_additions():
    metadata = IssueMetadata(present=True, banned_patterns=["import requests"])
    assert banned_patterns.check(metadata, "+import requests\n").status is Status.FAIL
    assert banned_patterns.check(metadata, "-import requests\n").status is Status.PASS


def test_bad_issue_regex_still_fails_closed_without_additions():
    metadata = IssueMetadata(present=True, banned_patterns=["("])
    result = banned_patterns.check(metadata, "-old code\n")
    assert result.status is Status.FAIL
    assert result.evidence == ["invalid pattern: ("]


def test_header_is_not_added_content():
    diff = "+++ b/" + _assignment("secret") + "\n"
    assert banned_patterns.check(IssueMetadata.empty(), diff).status is Status.PASS


def test_multiline_added_run_preserved_but_not_unchanged_bridging():
    metadata = IssueMetadata(present=True, banned_patterns=["foo\\nbar"])
    assert banned_patterns.check(metadata, "+foo\n+bar\n").status is Status.FAIL
    assert banned_patterns.check(metadata, "+foo\n same\n+bar\n").status is Status.PASS
