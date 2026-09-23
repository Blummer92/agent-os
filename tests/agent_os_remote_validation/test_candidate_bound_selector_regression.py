from __future__ import annotations

import copy

from scripts.agent_os_remote_validation import (
    PrePrValidationSubject,
    load_rule_map,
    select_pre_pr_validation_plan,
)

PILOT_COMMAND = (
    "python -m pytest "
    "08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py"
)
PILOT_PATH = "08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py"
PILOT_FORBIDDEN = (".github/workflows", "cloudbuild.yaml", "scripts/validate-all.sh")


def test_candidate_bound_selector_accepts_non_legacy_bindings() -> None:
    rules = copy.deepcopy(load_rule_map())
    rules["repository"] = "ExampleOrg/example-repo"
    subject = PrePrValidationSubject(
        repository="ExampleOrg/example-repo",
        issue_number=754,
        invocation_id="invocation:754:non-default",
        base_branch="trunk",
        base_sha="a" * 40,
        branch="agent/754-validation-packet",
        expected_source_sha="d" * 40,
        tested_sha="e" * 40,
        allowed_files=(PILOT_PATH,),
        forbidden_paths=PILOT_FORBIDDEN,
        required_command_identities=(PILOT_COMMAND,),
        approval_id="approval:754:0001",
        approval_revision=1,
        projection_id="projection:754:0001",
        implementation_contract_fingerprint="f" * 64,
        execution_mode="candidate-validation",
        candidate_bound=True,
    )

    plan = select_pre_pr_validation_plan(subject, rules)

    assert plan.subject.repository == "ExampleOrg/example-repo"
    assert plan.subject.base_branch == "trunk"
    assert plan.subject.execution_mode == "candidate-validation"
    assert plan.subject.expected_source_sha == "d" * 40
    assert plan.subject.tested_sha == "e" * 40
    assert plan.subject.expected_source_sha != plan.subject.tested_sha
    assert plan.commands == (PILOT_COMMAND,)
    assert plan.execution_authorized is False
    assert plan.merge_authorized is False
    assert plan.side_effects_performed is False
