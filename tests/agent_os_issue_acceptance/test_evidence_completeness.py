import json
from pathlib import Path

from scripts.agent_os_issue_acceptance.cli import main


FIXTURES = Path(__file__).parent / "fixtures"


def _run_with_flag(capsys, flag: str) -> dict[str, object]:
    exit_code = main(
        [
            "--issue",
            str(FIXTURES / "issue_valid.md"),
            "--pr-body",
            str(FIXTURES / "pr_body_valid.md"),
            "--changed-files",
            str(FIXTURES / "changed_files_valid.txt"),
            "--diff",
            str(FIXTURES / "diff_clean.patch"),
            flag,
            "--format",
            "json",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["overall_status"] == "manual-review"
    return output


def test_incomplete_changed_file_evidence_forces_manual_review(capsys):
    output = _run_with_flag(capsys, "--changed-files-incomplete")

    check = next(
        item for item in output["checks"] if item["name"] == "changed files completeness"
    )
    assert check["status"] == "manual-review"
    assert "input=changed-files; state=incomplete" in check["evidence"]
    assert "changed_files_incomplete=true" in output["evidence"]


def test_diff_retrieval_failure_forces_manual_review(capsys):
    output = _run_with_flag(capsys, "--diff-retrieval-failed")

    check = next(item for item in output["checks"] if item["name"] == "diff retrieval")
    assert check["status"] == "manual-review"
    assert "input=diff; state=retrieval-failed" in check["evidence"]
    assert "diff_retrieval_failed=true" in output["evidence"]
