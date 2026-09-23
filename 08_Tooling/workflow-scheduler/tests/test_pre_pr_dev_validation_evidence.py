from __future__ import annotations

import pytest

from scripts.agent_os_remote_validation import (
    PrePrValidationPlan,
    PrePrValidationSubject,
    compute_command_set_digest,
    pre_pr_validation_plan_id,
)
from workflow_scheduler.governance.pre_pr_dev_validation_evidence import (
    ObservedDevValidationCommand,
    supplied_command_results_from_dev_validation,
)

COMMAND = "python -m pytest tests/agent_os_remote_validation"


def _plan(command: str = COMMAND) -> PrePrValidationPlan:
    subject = PrePrValidationSubject(
        repository="Blummer92/agent-os",
        issue_number=1985,
        invocation_id="pre-pr-1985",
        base_branch="main",
        base_sha="a" * 40,
        branch="agent/issue-1985-pre-validation-evidence-part2",
        expected_source_sha="b" * 40,
        tested_sha="b" * 40,
        allowed_files=("tests/agent_os_remote_validation",),
        forbidden_paths=(".github/workflows",),
        required_command_identities=(command,),
        approval_id="approval:" + "1" * 64,
        approval_revision=1,
        projection_id="projection:" + "2" * 64,
        implementation_contract_fingerprint="3" * 64,
        expected_changed_paths=("tests/agent_os_remote_validation",),
        candidate_bound=True,
    )
    return PrePrValidationPlan(
        selector_version="1.0.0",
        subject=subject,
        commands=(command,),
        command_set_digest=compute_command_set_digest("1.0.0", (command,)),
        reason_codes=("profile.focused-package",),
    )


def _observed(profile_id: str = "remote-validation") -> ObservedDevValidationCommand:
    return ObservedDevValidationCommand(
        profile_id=profile_id,
        runner_id="dev-validation:remote-validation",
        started_at="2026-09-08T17:00:00Z",
        completed_at="2026-09-08T17:00:01Z",
        status="passed",
        exit_code=0,
        diagnostic_summary="passed",
    )


def test_fixed_profile_observation_maps_to_canonical_supplied_result() -> None:
    plan = _plan()
    results = supplied_command_results_from_dev_validation(plan, (_observed(),))

    assert len(results) == 1
    result = results[0]
    assert result.plan_id == pre_pr_validation_plan_id(plan)
    assert result.command == COMMAND
    assert result.command_ordinal == 0
    assert result.source_head_sha == "b" * 40
    assert result.tested_sha == "b" * 40
    assert result.status == "passed"
    assert result.exit_code == 0


def test_unknown_profile_fails_closed_before_result_construction() -> None:
    with pytest.raises(ValueError, match="unknown dev-validation profile"):
        supplied_command_results_from_dev_validation(_plan(), (_observed("not-a-profile"),))


def test_plan_command_not_exactly_owned_by_profile_fails_closed() -> None:
    with pytest.raises(ValueError, match="not represented by the fixed profile catalog"):
        supplied_command_results_from_dev_validation(
            _plan("python -m pytest tests/agent_os_remote_validation -q"),
            (_observed(),),
        )


def test_adapter_has_no_caller_argv_or_shell_surface() -> None:
    fields = ObservedDevValidationCommand.__dataclass_fields__
    assert "argv" not in fields
    assert "shell" not in fields
    assert "command" not in fields
