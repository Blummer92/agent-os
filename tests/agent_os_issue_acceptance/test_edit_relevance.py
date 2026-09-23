from __future__ import annotations

import json

from scripts.agent_os_issue_acceptance.edit_relevance import (
    classify_acceptance_event,
    main,
    normalize_acceptance_pr_body,
)


SHA = "9ed0caa46e8db1658491c306c31709d236b4b172"


def _edited(*, old_body: str = "same", new_body: str = "same", changes=None):
    if changes is None:
        changes = {"body": {"from": old_body}}
    return {
        "action": "edited",
        "changes": changes,
        "pull_request": {"body": new_body, "title": "Example"},
    }


def test_non_edited_events_remain_reportable():
    for action in ("opened", "reopened", "synchronize"):
        assert classify_acceptance_event({"action": action}) == (True, "non-edited-event")


def test_edited_without_consumed_field_is_suppressed():
    assert classify_acceptance_event(_edited(changes={"milestone": {"from": None}})) == (
        False,
        "edited-without-consumed-field",
    )


def test_title_and_base_edits_remain_reportable():
    assert classify_acceptance_event(_edited(changes={"title": {"from": "Old"}})) == (
        True,
        "title-changed",
    )
    assert classify_acceptance_event(_edited(changes={"base": {"ref": {"from": "old"}}})) == (
        True,
        "base-changed",
    )


def test_meaningful_body_edit_remains_reportable():
    assert classify_acceptance_event(_edited(old_body="Fixes #1", new_body="Fixes #2")) == (
        True,
        "body-input-changed",
    )


def test_exact_head_acceptance_evidence_only_edit_is_suppressed():
    old = "## Tests\npytest tests/agent_os_issue_acceptance"
    new = (
        old
        + f"\n\nExact-head `Agent OS Issue Acceptance Report`: **passed** on `{SHA}`."
    )
    assert classify_acceptance_event(_edited(old_body=old, new_body=new)) == (
        False,
        "acceptance-evidence-only-body-edit",
    )


def test_evidence_normalization_does_not_hide_other_body_changes():
    old = "## Tests\npytest tests/agent_os_issue_acceptance"
    new = (
        "## Tests\npytest tests/agent_os_issue_acceptance/test_policy.py"
        + f"\n\nExact-head `Agent OS Issue Acceptance Report`: **passed** on `{SHA}`."
    )
    assert normalize_acceptance_pr_body(old) != normalize_acceptance_pr_body(new)
    assert classify_acceptance_event(_edited(old_body=old, new_body=new)) == (
        True,
        "body-input-changed",
    )


def test_missing_changes_fails_open_to_report():
    assert classify_acceptance_event({"action": "edited", "pull_request": {"body": "x"}}) == (
        True,
        "edited-event-missing-changes",
    )


def test_cli_emits_github_output_compatible_pairs(tmp_path, capsys):
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(_edited(changes={"milestone": {"from": None}})),
        encoding="utf-8",
    )
    assert main([str(event)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "should_run=false",
        "reason=edited-without-consumed-field",
    ]
