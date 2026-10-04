"""#3282: issue-quality and metadata-validation checks run report-only.

Both checkers are implemented and tested but the acceptance policy never ran
them. They are registered in policy.py as strictly informational evidence via
AcceptanceReport.informational_checks (the reuse_readiness.py precedent). They
must never enter report.checks, overall_status, blockers, manual_review_items,
remaining_risks, or the workflow exit code.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.checks import issue_quality
from scripts.agent_os_issue_acceptance.cli import main as cli_main
from scripts.agent_os_issue_acceptance.models import (
    AcceptanceInput,
    Status,
    strongest_status,
)
from scripts.agent_os_issue_acceptance.policy import evaluate_acceptance
from scripts.agent_os_issue_acceptance.report import exit_code_for

FIXTURES = Path(__file__).parent / "fixtures"
QUALITY_FIXTURES = FIXTURES / "issue_quality"

# The eight real-edge checks policy.py has always run. Registration must not
# add, remove, or rename any of them (cf. test_policy.py's report.checks guard).
_CANONICAL_CHECK_NAMES = frozenset(
    {
        "linked issue",
        "required PR report fields",
        "required files",
        "forbidden paths",
        "required docs",
        "required tests",
        "banned patterns",
        "validation commands",
    }
)

_FAMILY_FIXTURES = {
    issue_quality.IssueFamily.ROADMAP: "roadmap.md",
    issue_quality.IssueFamily.IMPLEMENTATION: "strong_implementation.md",
    issue_quality.IssueFamily.VALIDATION: "validation.md",
    issue_quality.IssueFamily.GOVERNANCE: "governance.md",
    issue_quality.IssueFamily.CLEANUP: "cleanup.md",
}

# Required sections per family, mirroring the issue-quality taxonomy table.
_REQUIRED_BY_FAMILY = {
    issue_quality.IssueFamily.ROADMAP: ("goal", "scope", "dependencies"),
    issue_quality.IssueFamily.IMPLEMENTATION: (
        "goal",
        "scope",
        "acceptance criteria",
        "definition of done",
        "tests / validation",
    ),
    issue_quality.IssueFamily.VALIDATION: (
        "goal",
        "scope",
        "acceptance criteria",
        "definition of done",
        "tests / validation",
    ),
    issue_quality.IssueFamily.GOVERNANCE: (
        "goal",
        "scope",
        "acceptance criteria",
        "definition of done",
    ),
    issue_quality.IssueFamily.CLEANUP: ("goal", "scope"),
}


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _changed(name: str) -> list[str]:
    return [line.strip() for line in _read(name).splitlines() if line.strip()]


def _accept(issue_body: str):
    return evaluate_acceptance(
        AcceptanceInput(
            issue_body=issue_body,
            pr_body=_read("pr_body_valid.md"),
            changed_files=_changed("changed_files_valid.txt"),
            diff_text=_read("diff_clean.patch"),
        )
    )


def _by_name(report) -> dict:
    return {check.name: check for check in report.informational_checks}


def test_gap_reproduction_both_checks_appear_as_report_only():
    """Gap: neither check reached any acceptance report. Now both must."""
    body = "## Issue tier\ntier:1-standard-implementation\n\n" + (
        QUALITY_FIXTURES / "strong_implementation.md"
    ).read_text(encoding="utf-8")
    report = _accept(body)
    names = [check.name for check in report.informational_checks]
    assert any(name.startswith("issue-quality: ") for name in names), (
        "issue-quality evidence is absent from the acceptance report"
    )
    assert any(name.startswith("metadata:") for name in names), (
        "metadata-validation evidence is absent from the acceptance report"
    )


def test_report_only_checks_never_enter_report_checks():
    """Registration must not create real edges: report.checks is untouched."""
    body = (
        "## Issue tier\ntier:1-standard-implementation\n\n"
        "## Readiness candidate\nstatus:needs-decision\n\n"
        "## Documentation impact\ndocs-required\n\n"
        "## Primary owner\nowner:qa-test-agent\n\n"
        "## Source of truth\nGitHub\n\n"
        "## External write boundary\nno-external-write\n\n"
        + (QUALITY_FIXTURES / "strong_implementation.md").read_text(encoding="utf-8")
    )
    report = _accept(body)
    check_names = {check.name for check in report.checks}
    info_names = {check.name for check in report.informational_checks}
    assert check_names == _CANONICAL_CHECK_NAMES
    assert not (check_names & info_names)
    assert not any(
        name.startswith(("issue-quality:", "metadata:"))
        for name in check_names
    )


def test_exit_code_unchanged_when_informational_checks_fail():
    """Informational FAILs must not move overall_status or the exit code."""
    # The valid fixture body carries the metadata block (so the canonical
    # checks pass and manual_review_items stays empty) but no issue-quality
    # sections; with tier:1 (implementation family) the informational channel
    # therefore carries real FAILs while the canonical report stays PASS.
    body = _read("issue_valid.md") + "\n## Issue tier\ntier:1-standard-implementation\n"
    report = _accept(body)
    info = _by_name(report)
    assert info["issue-quality: section: scope"].status == Status.FAIL
    assert report.overall_status == Status.PASS
    assert report.overall_status == strongest_status(report.checks)
    assert report.blockers == []
    assert report.manual_review_items == []
    assert exit_code_for(report.overall_status) == 0


@pytest.mark.parametrize(
    ("tier_value", "probe_check", "expected"),
    [
        # tier:0 -> cleanup: acceptance criteria is only recommended -> warn.
        (
            "tier:0-small-maintenance",
            "issue-quality: section: acceptance criteria",
            Status.WARN,
        ),
        # tier:1 -> implementation: tests / validation is required -> fail.
        (
            "tier:1-standard-implementation",
            "issue-quality: section: tests / validation",
            Status.FAIL,
        ),
        # tier:2 -> governance: tests / validation is recommended -> warn.
        (
            "tier:2-governed-cross-system",
            "issue-quality: section: tests / validation",
            Status.WARN,
        ),
    ],
)
def test_tier_to_family_mapping(tier_value, probe_check, expected):
    body = f"## Issue tier\n{tier_value}\n\n## Goal\nDo the thing.\n\n## Scope\nNarrow.\n"
    report = _accept(body)
    assert _by_name(report)[probe_check].status == expected


def test_unknown_tier_runs_family_independent_checks_only():
    """No canonical tier value: no family is guessed; note records the skip."""
    body = "## Goal\nDo the thing.\n\n## Scope\nNarrow.\n"
    report = _accept(body)
    names = set(_by_name(report))
    assert "issue-quality: parent reference" in names
    assert "issue-quality: related references" in names
    assert "issue-quality: blocker quality" in names
    assert not any(name.startswith("issue-quality: section:") for name in names)
    note = _by_name(report)["issue-quality: family"]
    assert note.status == Status.MANUAL_REVIEW


def test_metadata_field_extraction_contract():
    """Each mapped body section becomes one metadata check; all canonical."""
    body = (
        "## Issue tier\ntier:1-standard-implementation\n\n"
        "## Readiness candidate\nstatus:needs-decision\n\n"
        "## Documentation impact\ndocs-required\n\n"
        "## Primary owner\nowner:qa-test-agent\n\n"
        "## Source of truth\nGitHub\n\n"
        "## External write boundary\nno-external-write\n"
    )
    info = _by_name(_accept(body))
    for field in (
        "issue_tier",
        "readiness_candidate",
        "documentation_impact",
        "primary_owner",
        "source_route",
        "external_write_boundary",
    ):
        assert info[f"metadata:{field}"].status == Status.PASS, field


def test_metadata_absent_or_placeholder_sections_emit_no_checks():
    """No evidence means no check: unfilled fields never emit review noise."""
    body = (
        "## Issue tier\ntier:1-standard-implementation\n\n"
        "## Documentation impact\n_No response_\n"
    )
    names = set(_by_name(_accept(body)))
    assert "metadata:issue_tier" in names
    assert "metadata:documentation_impact" not in names
    assert "metadata:readiness_candidate" not in names
    assert "metadata:primary_owner" not in names
    assert "metadata:source_route" not in names
    assert "metadata:external_write_boundary" not in names


def test_metadata_legacy_tokens_evaluated_only_when_present():
    with_legacy = _accept(
        "## Issue tier\ntier:1-standard-implementation\n\n"
        "Legacy metadata risk:live-write applies.\n"
    )
    info = _by_name(with_legacy)
    assert info["metadata:legacy_metadata"].status == Status.MANUAL_REVIEW

    without_legacy = _accept("## Issue tier\ntier:1-standard-implementation\n")
    assert "metadata:legacy_metadata" not in _by_name(without_legacy)


@pytest.mark.parametrize("family,fixture", sorted(_FAMILY_FIXTURES.items(), key=lambda kv: kv[1]))
def test_family_fixture_satisfies_family_contract(family, fixture):
    """One fixture per issue family; each passes its family's required sections."""
    body = (QUALITY_FIXTURES / fixture).read_text(encoding="utf-8")
    results = {
        result.name: result
        for result in issue_quality.check_completeness(body, family)
    }
    for section in _REQUIRED_BY_FAMILY[family]:
        assert results[f"section: {section}"].status == Status.PASS, (
            family.value,
            section,
        )


def test_json_report_includes_informational_checks(tmp_path, capsys):
    """--format json carries the report-only evidence for machine consumers."""
    issue = tmp_path / "issue.md"
    pr_body = tmp_path / "pr_body.md"
    changed = tmp_path / "changed.txt"
    diff = tmp_path / "diff.patch"
    issue.write_text(
        "## Issue tier\ntier:1-standard-implementation\n\n",
        encoding="utf-8",
    )
    pr_body.write_text(_read("pr_body_valid.md"), encoding="utf-8")
    changed.write_text(_read("changed_files_valid.txt"), encoding="utf-8")
    diff.write_text(_read("diff_clean.patch"), encoding="utf-8")
    assert cli_main(
        [
            "--issue", str(issue),
            "--pr-body", str(pr_body),
            "--changed-files", str(changed),
            "--diff", str(diff),
            "--format", "json",
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)
    names = [check["name"] for check in output["informational_checks"]]
    assert any(name.startswith("issue-quality: ") for name in names)
    assert any(name.startswith("metadata:") for name in names)
