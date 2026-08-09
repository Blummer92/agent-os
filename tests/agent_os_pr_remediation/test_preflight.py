import ast
from dataclasses import replace
import json
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_pr_remediation import (
    EvidenceValidationError,
    NormalizedReviewThread,
    normalize_pr_snapshot,
    normalize_review_threads,
    preflight,
)
from scripts.agent_os_pr_remediation.normalization import (
    MAX_CHANGED_FILES,
    MAX_THREADS,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "agent_os_pr_remediation"


def _snapshot():
    payload = json.loads((FIXTURES / "pr_snapshot.json").read_text())
    return normalize_pr_snapshot(payload)


def _threads():
    payload = json.loads((FIXTURES / "review_threads.json").read_text())
    return normalize_review_threads(payload)


def test_matching_head_and_scope_pass():
    result = preflight(
        _snapshot(),
        expected_head="2" * 40,
        allowed_files=["scripts/example.py", "tests/example.py"],
        review_threads=_threads(),
    )
    assert result.overall_status is Status.PASS
    assert result.outside_allowed_files == ()
    assert result.expected_head == "2" * 40
    assert result.allowed_files == ("scripts/example.py", "tests/example.py")
    assert result.execution_authorized is False


def test_moved_head_fails():
    result = preflight(
        _snapshot(),
        expected_head="3" * 40,
        allowed_files=["scripts/example.py", "tests/example.py"],
    )
    assert result.overall_status is Status.FAIL


def test_out_of_scope_file_fails():
    result = preflight(
        _snapshot(),
        expected_head="2" * 40,
        allowed_files=["scripts/example.py"],
    )
    assert result.overall_status is Status.FAIL
    assert result.outside_allowed_files == ("tests/example.py",)


def test_draft_incompatibility_fails():
    result = preflight(
        _snapshot(),
        expected_head="2" * 40,
        allowed_files=["scripts/example.py", "tests/example.py"],
        draft_allowed=False,
    )
    assert result.overall_status is Status.FAIL


def test_incomplete_current_thread_requires_manual_review():
    threads = list(_threads())
    thread = threads[0]
    threads[0] = NormalizedReviewThread(**{**thread.to_dict(), "line": None})
    result = preflight(
        _snapshot(),
        expected_head="2" * 40,
        allowed_files=["scripts/example.py", "tests/example.py"],
        review_threads=tuple(threads),
    )
    assert result.overall_status is Status.MANUAL_REVIEW
    assert result.manual_review_items


def test_duplicate_thread_identity_requires_manual_review():
    threads = _threads()
    result = preflight(
        _snapshot(),
        expected_head="2" * 40,
        allowed_files=["scripts/example.py", "tests/example.py"],
        review_threads=threads + (threads[0],),
    )
    assert result.overall_status is Status.MANUAL_REVIEW
    assert result.duplicate_thread_ids == ("PRRT_1",)


def test_duplicate_top_level_comment_identity_requires_manual_review():
    threads = list(_threads())
    threads[1] = replace(
        threads[1],
        top_level_comment_id=threads[0].top_level_comment_id,
    )
    result = preflight(
        _snapshot(),
        expected_head="2" * 40,
        allowed_files=["scripts/example.py", "tests/example.py"],
        review_threads=tuple(threads),
    )
    assert result.overall_status is Status.MANUAL_REVIEW
    assert result.duplicate_comment_ids == (101,)


def test_oversized_allowlist_fails_closed():
    allowed = [f"scripts/file-{index}.py" for index in range(MAX_CHANGED_FILES + 1)]
    with pytest.raises(EvidenceValidationError):
        preflight(
            _snapshot(),
            expected_head="2" * 40,
            allowed_files=allowed,
        )


def test_oversized_review_thread_tuple_fails_closed():
    threads = (_threads()[0],) * (MAX_THREADS + 1)
    with pytest.raises(EvidenceValidationError):
        preflight(
            _snapshot(),
            expected_head="2" * 40,
            allowed_files=["scripts/example.py", "tests/example.py"],
            review_threads=threads,
        )


def test_package_has_no_external_execution_or_provider_paths():
    package = Path(__file__).parents[2] / "scripts" / "agent_os_pr_remediation"
    banned_import_roots = {
        "aiohttp",
        "anthropic",
        "github",
        "httpx",
        "openai",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    banned_named_calls = {"__import__", "eval", "exec", "open"}
    banned_attribute_calls = {
        "check_call",
        "check_output",
        "import_module",
        "mkdir",
        "popen",
        "rmdir",
        "run",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "system",
        "touch",
        "unlink",
        "urlopen",
        "urlretrieve",
        "write_bytes",
        "write_text",
    }
    banned_source_fragments = {
        "github.",
        "resolve_review_thread",
    }

    for path in package.rglob("*.py"):
        source = path.read_text()
        lowered = source.lower()
        assert all(fragment not in lowered for fragment in banned_source_fragments)
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".", 1)[0] for alias in node.names}
                assert roots.isdisjoint(banned_import_roots)
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".", 1)[0] not in banned_import_roots
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    assert node.func.id not in banned_named_calls
                elif isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in banned_attribute_calls
