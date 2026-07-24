import json
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.cli import _report_to_dict, main
from scripts.agent_os_issue_acceptance.models import AcceptanceInput
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


def _docs_required_issue_body() -> str:
    return """# Build issue

```yaml
agent_os_issue_acceptance:
  owner_agent: qa-test-agent
  source_of_truth: GitHub
  external_writes: none
  required_files:
    - scripts/agent_os_issue_acceptance/
  forbidden_paths:
    - 00_Governance/
  required_tests:
    - tests/agent_os_issue_acceptance/
  required_docs:
    - scripts/agent_os_issue_acceptance/README.md
  banned_patterns:
    - import requests
  manual_review: []
  documentation_impact: docs-required
  documentation_expected_change: Document advisory evidence.
  documentation_exemption_reason: null
```
"""


def _write_acceptance_inputs(tmp_path):
    issue = tmp_path / "issue.md"
    issue.write_text(_docs_required_issue_body(), encoding="utf-8")
    pr_body = tmp_path / "pr_body.md"
    pr_body.write_text((FIXTURES / "pr_body_valid.md").read_text(), encoding="utf-8")
    changed_files = tmp_path / "changed_files.txt"
    changed_files.write_text(
        (FIXTURES / "changed_files_valid.txt").read_text(),
        encoding="utf-8",
    )
    diff = tmp_path / "diff.patch"
    diff.write_text((FIXTURES / "diff_clean.patch").read_text(), encoding="utf-8")
    return issue, pr_body, changed_files, diff


def test_cli_default_output_remains_byte_compatible_without_advisory_flag(
    tmp_path,
    capsys,
):
    issue, pr_body, changed_files, diff = _write_acceptance_inputs(tmp_path)
    issue_body = issue.read_text(encoding="utf-8")
    pr_text = pr_body.read_text(encoding="utf-8")
    changed = [
        line.strip()
        for line in changed_files.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    expected = render_report(
        evaluate_acceptance(
            AcceptanceInput(
                issue_body=issue_body,
                pr_body=pr_text,
                changed_files=changed,
                diff_text=diff.read_text(encoding="utf-8"),
            )
        )
    )

    exit_code = main(
        [
            "--issue",
            str(issue),
            "--pr-body",
            str(pr_body),
            "--changed-files",
            str(changed_files),
            "--diff",
            str(diff),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert output == expected
    assert "documentation_advisory=present" not in output


def test_cli_attaches_advisory_before_transport_hashing(tmp_path, capsys):
    issue, pr_body, changed_files, diff = _write_acceptance_inputs(tmp_path)
    base_args = [
        "--issue",
        str(issue),
        "--pr-body",
        str(pr_body),
        "--changed-files",
        str(changed_files),
        "--diff",
        str(diff),
        "--format",
        "json",
        "--transport-repository",
        "Blummer92/agent-os",
        "--transport-issue-number",
        "164",
        "--transport-issue-body-file",
        str(issue),
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
        str(issue),
        "--transport-fresh-pr-head-sha",
        "pr-head-sha",
        "--transport-observed-at",
        "2026-07-24T00:00:00Z",
    ]

    assert main(base_args) == 0
    base = json.loads(capsys.readouterr().out)
    assert main([*base_args, "--documentation-advisory"]) == 0
    advisory = json.loads(capsys.readouterr().out)

    assert "documentation_advisory=present" not in base["report"]["evidence"]
    assert "documentation_advisory=present" in advisory["report"]["evidence"]
    assert (
        base["transport"]["report_sha256"]
        != advisory["transport"]["report_sha256"]
    )


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
