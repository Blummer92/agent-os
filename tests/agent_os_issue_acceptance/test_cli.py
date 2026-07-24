import json
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.cli import _report_to_dict, main
from scripts.agent_os_issue_acceptance.models import AcceptanceInput
from scripts.agent_os_issue_acceptance.policy import evaluate_acceptance
from scripts.agent_os_issue_acceptance.report import exit_code_for, render_report


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


def _fixture_changed_files() -> list[str]:
    return [
        line.strip()
        for line in (FIXTURES / "changed_files_valid.txt").read_text().splitlines()
        if line.strip()
    ]


def _fixture_cli_args() -> list[str]:
    return [
        "--issue",
        str(FIXTURES / "issue_valid.md"),
        "--pr-body",
        str(FIXTURES / "pr_body_valid.md"),
        "--changed-files",
        str(FIXTURES / "changed_files_valid.txt"),
        "--diff",
        str(FIXTURES / "diff_clean.patch"),
    ]


def test_cli_default_output_is_unchanged_without_advisory_flag(capsys):
    report = evaluate_acceptance(
        AcceptanceInput(
            issue_body=(FIXTURES / "issue_valid.md").read_text(),
            pr_body=(FIXTURES / "pr_body_valid.md").read_text(),
            changed_files=_fixture_changed_files(),
            diff_text=(FIXTURES / "diff_clean.patch").read_text(),
        )
    )

    result = main(_fixture_cli_args())

    assert result == exit_code_for(report.overall_status)
    output = capsys.readouterr().out
    assert output == render_report(report)
    assert "documentation_advisory=present" not in output


def test_cli_attaches_advisory_before_transport_hashing(capsys):
    transport_args = [
        *_fixture_cli_args(),
        "--format",
        "json",
        "--transport-repository",
        "Blummer92/agent-os",
        "--transport-issue-number",
        "164",
        "--transport-issue-body-file",
        str(FIXTURES / "issue_valid.md"),
        "--transport-pr-number",
        "42",
        "--transport-pr-head-sha",
        "pr-head-sha",
        "--transport-evaluator-sha",
        "evaluator-sha",
        "--transport-workflow-run-id",
        "1",
        "--transport-workflow-run-attempt",
        "1",
        "--transport-fresh-issue-body-file",
        str(FIXTURES / "issue_valid.md"),
        "--transport-fresh-pr-head-sha",
        "pr-head-sha",
        "--transport-observed-at",
        "2026-07-24T00:00:00Z",
    ]

    base_exit = main(transport_args)
    base = json.loads(capsys.readouterr().out)
    advisory_exit = main([*transport_args, "--documentation-advisory"])
    advisory = json.loads(capsys.readouterr().out)

    rerun_args = [
        "2" if value == "1" and transport_args[index - 1] == "--transport-workflow-run-id" else value
        for index, value in enumerate(transport_args)
    ]
    rerun_exit = main([*rerun_args, "--documentation-advisory"])
    rerun = json.loads(capsys.readouterr().out)

    assert base_exit == advisory_exit == rerun_exit
    assert "documentation_advisory=present" not in base["report"]["evidence"]
    assert "documentation_advisory=present" in advisory["report"]["evidence"]
    assert base["transport"]["report_sha256"] != advisory["transport"]["report_sha256"]
    assert advisory["transport"]["report_sha256"] == rerun["transport"]["report_sha256"]


def test_json_report_distinguishes_manual_review_from_none():
    body = (FIXTURES / "pr_body_valid.md").read_text().replace(
        "Closes #164", "Closes #223\nFixes #224"
    )
    report = evaluate_acceptance(
        AcceptanceInput(
            issue_body=(FIXTURES / "issue_valid.md").read_text(),
            pr_body=body,
            changed_files=_fixture_changed_files(),
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
