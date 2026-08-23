import json
from pathlib import Path

from scripts.agent_os_issue_acceptance.cli import main


FIXTURES = Path(__file__).parent / "fixtures"


def _run_with_flag(tmp_path, capsys, flag: str) -> dict[str, object]:
    changed_files = tmp_path / "changed_files.txt"
    changed_files.write_text(
        "\n".join(f"scripts/example_{index}.py" for index in range(100)) + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--issue",
            str(FIXTURES / "issue_valid.md"),
            "--pr-body",
            str(FIXTURES / "pr_body_valid.md"),
            "--changed-files",
            str(changed_files),
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


def test_incomplete_changed_file_evidence_forces_manual_review(tmp_path, capsys):
    output = _run_with_flag(tmp_path, capsys, "--changed-files-incomplete")

    check = next(
        item for item in output["checks"] if item["name"] == "changed files completeness"
    )
    assert check["status"] == "manual-review"
    assert "input=changed-files; state=incomplete" in check["evidence"]
    assert "changed_files_incomplete=true" in output["evidence"]


def test_diff_retrieval_failure_forces_manual_review(tmp_path, capsys):
    output = _run_with_flag(tmp_path, capsys, "--diff-retrieval-failed")

    check = next(item for item in output["checks"] if item["name"] == "diff retrieval")
    assert check["status"] == "manual-review"
    assert "input=diff; state=retrieval-failed" in check["evidence"]
    assert "diff_retrieval_failed=true" in output["evidence"]
