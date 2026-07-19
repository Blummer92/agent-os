import json
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.cli import _report_to_dict, main
from scripts.agent_os_issue_acceptance.models import AcceptanceInput
from scripts.agent_os_issue_acceptance.policy import evaluate_acceptance

FIXTURES = Path(__file__).parent / "fixtures"


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
