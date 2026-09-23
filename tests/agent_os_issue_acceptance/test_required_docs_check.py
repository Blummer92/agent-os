"""DOC3 (#473) characterization of the required-docs coverage check.

Proves the check delegates every path comparison to the canonical
``declared_path_matches`` contract, fails closed on invalid declarations with
stable ``DeclaredPathError`` codes, and reports declared-path coverage only.

Intentional differences from the retired unrestricted ``fnmatch`` matcher are
named in dedicated ``test_intentional_difference_*`` cases and repeated in the
PR final report:

1. ``**``, ``?``, and bracket-class patterns, plus absolute, traversal,
   backslash, repeated-separator, trailing-separator, and dot-prefix
   declarations, now fail closed with a stable error code instead of being
   passed to ``fnmatch``.
2. ``*`` is segment-local (never crosses ``/``); legacy ``fnmatch`` ``*``
   crossed ``/``.
"""
import inspect

import pytest

from scripts.agent_os_issue_acceptance.checks import required_docs
from scripts.agent_os_issue_acceptance.models import IssueMetadata, Status


def _metadata(required_docs_list: list[str]) -> IssueMetadata:
    return IssueMetadata(present=True, required_docs=list(required_docs_list))


def _check(required_docs_list: list[str], changed_files: list[str]):
    return required_docs.check(_metadata(required_docs_list), list(changed_files))


def _evidence(value: str, code: str) -> str:
    return f"field=required_docs; value={value!r}; code={code}"


# --- delegation and grammar ownership ---------------------------------------


def test_module_does_not_import_or_implement_fnmatch():
    source = inspect.getsource(required_docs)
    assert "fnmatch" not in source
    assert not hasattr(required_docs, "fnmatch")
    # Every comparison delegates to the canonical path contract.
    assert "declared_path_matches" in source


# --- metadata presence and empty declarations -------------------------------


def test_missing_metadata_is_manual_review():
    result = required_docs.check(IssueMetadata.empty(), ["docs/guide.md"])
    assert result.name == "required docs"
    assert result.status == Status.MANUAL_REVIEW
    assert result.evidence == []


def test_empty_required_docs_is_pass():
    assert _check([], ["scripts/a.py"]).status == Status.PASS
    assert _check([], []).status == Status.PASS


# --- result shape compatibility ---------------------------------------------


def test_pass_result_shape_is_compatible():
    result = _check(["docs/guide.md"], ["docs/guide.md"])
    assert (result.name, result.status, result.message) == (
        "required docs",
        Status.PASS,
        "Declared required docs are satisfied.",
    )
    assert result.evidence == []


def test_fail_result_message_is_preserved():
    result = _check(["docs/guide.md"], ["docs/other.md"])
    assert result.name == "required docs"
    assert result.status == Status.FAIL
    assert result.message == "Declared required docs were not changed."


# --- exact files ------------------------------------------------------------


def test_exact_file_declaration_matches_only_that_file():
    assert _check(["docs/guide.md"], ["docs/guide.md"]).status == Status.PASS
    for changed in (["docs/guide.mdx"], ["docs/guide.md.bak"], ["docs/other.md"]):
        result = _check(["docs/guide.md"], changed)
        assert result.status == Status.FAIL
        assert result.evidence == [_evidence("docs/guide.md", "unmatched")]


# --- bounded directories ----------------------------------------------------


def test_bounded_directory_matches_descendants():
    assert _check(["docs"], ["docs/guide.md"]).status == Status.PASS
    assert _check(["docs"], ["docs/a/b/c.md"]).status == Status.PASS
    assert _check(["docs"], ["docs"]).status == Status.PASS


def test_bounded_directory_rejects_similarly_prefixed_sibling():
    result = _check(["docs"], ["docs-old/guide.md"])
    assert result.status == Status.FAIL
    assert result.evidence == [_evidence("docs", "unmatched")]


def test_dot_github_paths_are_supported():
    assert _check([".github/workflows"], [".github/workflows/ci.yml"]).status == Status.PASS
    assert (
        _check([".github/workflows/*.yml"], [".github/workflows/ci.yml"]).status == Status.PASS
    )


# --- case sensitivity -------------------------------------------------------


def test_matching_is_case_sensitive():
    result = _check(["Docs/Guide.md"], ["docs/guide.md"])
    assert result.status == Status.FAIL
    assert result.evidence == [_evidence("Docs/Guide.md", "unmatched")]


# --- segment-local wildcard -------------------------------------------------


def test_segment_local_wildcard_matches_one_segment():
    assert _check(["src/*.py"], ["src/main.py"]).status == Status.PASS
    assert _check(["src/*.py"], ["src/main.js"]).status == Status.FAIL


def test_intentional_difference_star_is_segment_local():
    # Legacy fnmatch '*' crossed '/'; the canonical contract stops at a segment.
    assert _check(["docs/*"], ["docs/a.md"]).status == Status.PASS
    nested = _check(["docs/*"], ["docs/a/b.md"])
    assert nested.status == Status.FAIL
    assert nested.evidence == [_evidence("docs/*", "unmatched")]


# --- unsupported / invalid declarations fail closed -------------------------


@pytest.mark.parametrize(
    ("declaration", "code"),
    [
        ("src/**/x.py", "unsupported-double-star"),
        ("src/file?.py", "unsupported-question-mark"),
        ("src/[ab].py", "unsupported-bracket-class"),
        ("/etc/passwd", "absolute-posix"),
        ("//server/share", "absolute-posix"),
        ("C:/repo/x.py", "absolute-windows-drive"),
        ("\\\\server\\share\\file.txt", "absolute-unc"),
        ("folder\\file.txt", "backslash"),
        ("../secrets.txt", "traversal"),
        ("docs//x.md", "noncanonical-separator"),
        ("docs/x.md/", "noncanonical-separator"),
        ("./docs/x.md", "noncanonical-dot-prefix"),
        ("", "empty"),
    ],
)
def test_invalid_declaration_fails_closed_with_stable_code(declaration, code):
    result = _check([declaration], ["docs/x.md"])
    assert result.status == Status.FAIL
    assert len(result.evidence) == 1
    assert result.evidence[0].startswith("field=required_docs; value=")
    assert result.evidence[0].endswith(f"; code={code}")


def test_invalid_declaration_fails_even_with_empty_changed_files():
    # An invalid declaration must fail closed regardless of the changed-file list.
    result = _check(["docs/**"], [])
    assert result.status == Status.FAIL
    assert result.evidence == [_evidence("docs/**", "unsupported-double-star")]


def test_intentional_difference_double_star_now_fails_closed():
    # Legacy fnmatch interpreted '**'; the canonical contract rejects it.
    result = _check(["docs/**"], ["docs/a/b.md"])
    assert result.status == Status.FAIL
    assert result.evidence == [_evidence("docs/**", "unsupported-double-star")]


def test_invalid_declarations_are_not_repaired_or_broadened():
    # A path that a permissive matcher might have accepted does not rescue an
    # invalid declaration; it stays a coded failure.
    result = _check(["docs/[a].md"], ["docs/a.md"])
    assert result.status == Status.FAIL
    assert result.evidence == [_evidence("docs/[a].md", "unsupported-bracket-class")]


# --- coverage requirement ---------------------------------------------------


def test_every_declaration_must_match_at_least_one_changed_file():
    result = _check(["docs/a.md", "docs/b.md"], ["docs/a.md", "scripts/x.py"])
    assert result.status == Status.FAIL
    assert result.evidence == [_evidence("docs/b.md", "unmatched")]


def test_valid_declaration_with_no_changed_files_is_unmatched():
    result = _check(["docs/a.md"], [])
    assert result.status == Status.FAIL
    assert result.evidence == [_evidence("docs/a.md", "unmatched")]


def test_all_declarations_covered_is_pass():
    result = _check(["docs", "src/*.py"], ["docs/x.md", "src/main.py"])
    assert result.status == Status.PASS
    assert result.evidence == []


# --- changed-file robustness ------------------------------------------------


def test_unparseable_changed_file_is_skipped_without_raising():
    # A valid declaration still matches a valid changed file even when another
    # supplied path is lexically invalid.
    covered = _check(["docs/a.md"], ["../evil", "docs/a.md"])
    assert covered.status == Status.PASS
    # An unparseable changed file cannot satisfy a declaration.
    only_invalid = _check(["docs/a.md"], ["../evil"])
    assert only_invalid.status == Status.FAIL
    assert only_invalid.evidence == [_evidence("docs/a.md", "unmatched")]


def test_check_is_lexical_and_does_not_touch_the_filesystem():
    # Paths that do not exist on disk still evaluate purely by the path contract.
    assert _check(["nonexistent/dir"], ["nonexistent/dir/file.md"]).status == Status.PASS


# --- deterministic, bounded, sorted, deduplicated evidence ------------------


def test_missing_and_invalid_evidence_is_sorted_and_deduplicated():
    result = _check(
        ["z/missing.md", "a/missing.md", "z/missing.md", "src/**/x.py"],
        ["docs/other.md"],
    )
    assert result.status == Status.FAIL
    assert result.evidence == sorted(result.evidence)
    assert len(result.evidence) == len(set(result.evidence))
    assert result.evidence == [
        _evidence("a/missing.md", "unmatched"),
        _evidence("src/**/x.py", "unsupported-double-star"),
        _evidence("z/missing.md", "unmatched"),
    ]


def test_duplicate_changed_files_do_not_change_status_or_evidence():
    duplicated = _check(["docs/a.md"], ["docs/a.md", "docs/a.md", "docs/a.md"])
    single = _check(["docs/a.md"], ["docs/a.md"])
    assert duplicated == single
    assert duplicated.status == Status.PASS


def test_evidence_value_is_bounded():
    long_declaration = "docs/" + "a" * 500 + ".md"
    result = _check([long_declaration], ["docs/other.md"])
    assert result.status == Status.FAIL
    assert len(result.evidence) == 1
    assert len(result.evidence[0]) < len(long_declaration)
    assert result.evidence[0].endswith("...; code=unmatched")


def test_repeated_identical_inputs_produce_identical_output():
    args = (["docs", "src/*.py", "src/**/x.py"], ["docs/x.md", "src/other.js"])
    assert _check(*args) == _check(*args)
