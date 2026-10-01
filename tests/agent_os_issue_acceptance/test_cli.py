import json
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.cli import _report_to_dict, main
from scripts.agent_os_issue_acceptance.models import AcceptanceInput
from scripts.agent_os_issue_acceptance.policy import evaluate_acceptance


def test_transport_arguments_are_optional_when_absent(tmp_path, capsys):
    issue = tmp_path / "issue.md"
    issue.write_text("Issue body", encoding="utf-8")
    pr_body = tmp_path / "pr_body.md"
    pr_body.write_text("Closes #323", encoding="utf-8")
    changed_files = tmp_path / "changed_files.txt"
    changed_files.write_text("scripts/agent_os_issue_acceptance/cli.py\n", encoding="utf-8")

    exit_code = main(
        [
            "--issue",
            str(issue),
            "--pr-body",
            str(pr_body),
            "--changed-files",
            str(changed_files),
        ]
    )

    assert exit_code in {0, 1}
    output = capsys.readouterr().out
    assert "overall_status" in output or output.strip()

FIXTURES = Path(__file__).parent / "fixtures"


def test_cli_marks_supplied_empty_diff_as_manual_review(tmp_path, capsys):
    empty_diff = tmp_path / "diff.patch"
    empty_diff.write_text("", encoding="utf-8")

    main(
        [
            "--issue",
            str(FIXTURES / "issue_valid.md"),
            "--pr-body",
            str(FIXTURES / "pr_body_valid.md"),
            "--changed-files",
            str(FIXTURES / "changed_files_valid.txt"),
            "--diff",
            str(empty_diff),
            "--format",
            "json",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert output["overall_status"] == "manual-review"
    banned = next(check for check in output["checks"] if check["name"] == "banned patterns")
    assert banned["status"] == "manual-review"
    assert "input=diff; state=empty-supplied" in banned["evidence"]
    assert "diff_supplied=true" in output["evidence"]


def test_json_report_distinguishes_manual_review_from_none():
    body = (FIXTURES / "pr_body_valid.md").read_text().replace(
        "Closes #164", "Closes #223\nFixes #224"
    )
    report = evaluate_acceptance(
        AcceptanceInput(
            issue_body=(FIXTURES / "issue_valid.md").read_text(),
            pr_body=body,
            changed_files=[
                line.strip()
                for line in (FIXTURES / "changed_files_valid.txt").read_text().splitlines()
                if line.strip()
            ],
            diff_text=(FIXTURES / "diff_clean.patch").read_text(),
        )
    )

    data = _report_to_dict(report)

    assert data["linked_issue"] is None
    assert data["linked_issue_status"] == "manual-review"
    assert data["linked_issue_reasons"]
    assert {candidate["issue_number"] for candidate in data["linked_issue_candidates"]} == {223, 224}


def test_legacy_preflight_cli_outputs_bounded_json(tmp_path, capsys):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "evaluator_sha": "abc123",
                "issues": [
                    {
                        "number": 317,
                        "title": "Implementation issue",
                        "state": "open",
                        "body": "Issue tier: tier:0\n\n## Objective\n\nTest.\n\n## Owner\n\nQA.\n\n## Allowed files\n\ntests/\n\n## Validation\n\nRun tests.\n\n## Completion\n\nDone.",
                        "labels": ["status:ready"],
                        "updated_at": "2026-07-19T00:00:00Z",
                        "open_pr_numbers": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--legacy-preflight-snapshot",
            str(snapshot),
            "--format",
            "json",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["evaluator_sha"] == "abc123"
    assert output["metrics"]["would_change_ready_to_needs_decision"] == 1
    assert output["issues"][0]["reason_codes"] == [
        "currently-labeled-ready",
        "legacy-metadata-missing",
    ]
    assert "body" not in output["issues"][0]


def test_legacy_preflight_cli_rejects_mixed_acceptance_inputs(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text('{"issues": []}', encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        main(
            [
                "--legacy-preflight-snapshot",
                str(snapshot),
                "--issue",
                "issue.md",
            ]
        )

    assert error.value.code == 2


def test_acceptance_mode_still_requires_original_inputs():
    with pytest.raises(SystemExit) as error:
        main([])

    assert error.value.code == 2


# Executable-boundary complements (issue #2773): the workflow tests in
# test_issue_acceptance_workflow.py assert only that the workflow text passes
# --changed-files-incomplete, --diff-retrieval-failed, and
# --transport-issue-body-retrieval-failed to this CLI. These tests prove the
# flags actually downgrade evidence at the real adapter boundary instead of
# being dead strings in the workflow YAML.


def _base_acceptance_args(fixtures, tmp_path):
    issue = tmp_path / "issue.md"
    issue.write_text((fixtures / "issue_valid.md").read_text(encoding="utf-8"), encoding="utf-8")
    pr_body = tmp_path / "pr_body.md"
    pr_body.write_text(
        (fixtures / "pr_body_valid.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    changed_files = tmp_path / "changed_files.txt"
    changed_files.write_text(
        (fixtures / "changed_files_valid.txt").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return [
        "--issue",
        str(issue),
        "--pr-body",
        str(pr_body),
        "--changed-files",
        str(changed_files),
        "--diff",
        str(fixtures / "diff_clean.patch"),
        "--format",
        "json",
    ]


def test_cli_changed_files_incomplete_adds_manual_review_check(tmp_path, capsys):
    main([*_base_acceptance_args(FIXTURES, tmp_path), "--changed-files-incomplete"])

    output = json.loads(capsys.readouterr().out)
    check = next(
        check for check in output["checks"] if check["name"] == "changed files completeness"
    )
    assert check["status"] == "manual-review"
    assert "authoritative pull request changed-file count" in check["message"]
    assert check["message"] in output["manual_review_items"]
    assert "changed_files_incomplete=true" in output["evidence"]
    assert check["message"] in output["remaining_risks"]
    assert output["overall_status"] == "manual-review"


def test_cli_without_evidence_flags_omits_completeness_checks(tmp_path, capsys):
    main(_base_acceptance_args(FIXTURES, tmp_path))

    output = json.loads(capsys.readouterr().out)
    names = {check["name"] for check in output["checks"]}
    assert "changed files completeness" not in names
    assert "diff retrieval" not in names
    assert "changed_files_incomplete=true" not in output["evidence"]
    assert "diff_retrieval_failed=true" not in output["evidence"]


def test_cli_diff_retrieval_failed_adds_manual_review_check(tmp_path, capsys):
    main([*_base_acceptance_args(FIXTURES, tmp_path), "--diff-retrieval-failed"])

    output = json.loads(capsys.readouterr().out)
    check = next(check for check in output["checks"] if check["name"] == "diff retrieval")
    assert check["status"] == "manual-review"
    assert "diff-dependent evidence is unavailable" in check["message"]
    assert check["message"] in output["manual_review_items"]
    assert "diff_retrieval_failed=true" in output["evidence"]
    assert output["overall_status"] == "manual-review"


def test_cli_evidence_completeness_flags_compose(tmp_path, capsys):
    main(
        [
            *_base_acceptance_args(FIXTURES, tmp_path),
            "--changed-files-incomplete",
            "--diff-retrieval-failed",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    names = {check["name"] for check in output["checks"]}
    assert {"changed files completeness", "diff retrieval"} <= names
    assert output["overall_status"] == "manual-review"


def _transport_args(tmp_path, *, retrieval_failed: bool):
    body = tmp_path / "transport_issue_body.md"
    body.write_text("Transport issue body", encoding="utf-8")
    fresh_body = tmp_path / "transport_fresh_issue_body.md"
    fresh_body.write_text("Transport issue body", encoding="utf-8")
    args = [
        "--transport-repository",
        "Blummer92/agent-os",
        "--transport-issue-number",
        "2773",
        "--transport-issue-body-file",
        str(body),
        "--transport-pr-number",
        "9999",
        "--transport-pr-head-sha",
        "abc123",
        "--transport-evaluator-sha",
        "def456",
        "--transport-workflow-run-id",
        "12345",
        "--transport-workflow-run-attempt",
        "1",
        "--transport-fresh-issue-body-file",
        str(fresh_body),
        "--transport-fresh-pr-head-sha",
        "abc123",
        "--transport-observed-at",
        "2026-09-30T12:00:00Z",
    ]
    if retrieval_failed:
        args.append("--transport-issue-body-retrieval-failed")
    return args


def test_cli_transport_issue_body_retrieval_failed_yields_missing_provenance(
    tmp_path, capsys
):
    main(
        [
            *_base_acceptance_args(FIXTURES, tmp_path),
            *_transport_args(tmp_path, retrieval_failed=True),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    transport = output["transport"]
    assert transport["transport_state"] == "missing-provenance"
    assert "missing-provenance" in transport["reason_codes"]
    # The report itself still renders alongside the degraded transport payload.
    assert output["report"]["overall_status"]


def test_cli_transport_without_retrieval_failure_reaches_snapshot_current(
    tmp_path, capsys
):
    main(
        [
            *_base_acceptance_args(FIXTURES, tmp_path),
            *_transport_args(tmp_path, retrieval_failed=False),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    transport = output["transport"]
    assert transport["transport_state"] == "snapshot-current"
    assert transport["reason_codes"] == []
