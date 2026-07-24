import json
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.cli import _report_to_dict, main
from scripts.agent_os_issue_acceptance.models import (
    AcceptanceInput,
    AcceptanceReport,
    IssueMetadata,
    Status,
)
from scripts.agent_os_issue_acceptance.policy import evaluate_acceptance
from scripts.agent_os_issue_acceptance.report import render_report


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


def test_documentation_advisory_flag_is_opt_in(monkeypatch, tmp_path, capsys):
    issue = tmp_path / "issue.md"
    issue.write_text("issue", encoding="utf-8")
    pr_body = tmp_path / "pr.md"
    pr_body.write_text("Closes #553", encoding="utf-8")
    changed_files = tmp_path / "files.txt"
    changed_files.write_text("scripts/example.py\n", encoding="utf-8")

    base_report = AcceptanceReport(
        linked_issue=553,
        overall_status=Status.PASS,
        checks=[],
        evidence=["base-evidence"],
    )
    advisory_report = AcceptanceReport(
        linked_issue=553,
        overall_status=Status.PASS,
        checks=[],
        evidence=["base-evidence", "documentation_advisory=present"],
    )
    metadata = IssueMetadata(present=True, documentation_impact="docs-required")
    calls = []

    monkeypatch.setattr(
        "scripts.agent_os_issue_acceptance.cli.evaluate_acceptance",
        lambda *_args, **_kwargs: base_report,
    )
    monkeypatch.setattr(
        "scripts.agent_os_issue_acceptance.cli.scan_issue_metadata",
        lambda body: (calls.append(("scan", body)), "scan-result")[1],
    )
    monkeypatch.setattr(
        "scripts.agent_os_issue_acceptance.cli.project_issue_metadata",
        lambda scan: (calls.append(("project", scan)), metadata)[1],
    )
    monkeypatch.setattr(
        "scripts.agent_os_issue_acceptance.cli.attach_documentation_advisory",
        lambda report, projected: (
            calls.append(("attach", report, projected)),
            advisory_report,
        )[1],
    )

    args = [
        "--issue",
        str(issue),
        "--pr-body",
        str(pr_body),
        "--changed-files",
        str(changed_files),
    ]
    assert main(args) == 0
    assert capsys.readouterr().out == render_report(base_report)
    assert calls == []

    assert main([*args, "--documentation-advisory"]) == 0
    assert capsys.readouterr().out == render_report(advisory_report)
    assert calls == [
        ("scan", "issue"),
        ("project", "scan-result"),
        ("attach", base_report, metadata),
    ]


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
