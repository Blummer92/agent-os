from __future__ import annotations

import pytest

from workflow_scheduler.governance.dev_validation import (
    INSTRUCTIONAL_MATERIALS_VALIDATION_ARGV,
    INSTRUCTIONAL_MATERIALS_VALIDATION_ID,
    REPOSITORY,
    VALIDATION_ARGV,
    VALIDATION_ID,
    build_dev_validation_request,
    validation_argv,
)

SHA = "a" * 40


def build(**overrides):
    values = {
        "repository": REPOSITORY,
        "issue_number": 1271,
        "branch": "agent/1271-validation-profile-path-coverage",
        "source_sha": SHA,
        "validation_id": VALIDATION_ID,
    }
    values.update(overrides)
    return build_dev_validation_request(**values)


def test_exact_identity_maps_to_one_fixed_argv() -> None:
    request = build()
    assert validation_argv(request) == VALIDATION_ARGV
    assert request.execution_authorized is False
    assert request.scheduler_invoked is False
    assert request.publication_invoked is False
    assert request.merge_authorized is False


def test_materials_identity_maps_to_bounded_fixed_argv() -> None:
    request = build(
        issue_number=1416,
        branch="agent/1416-curriculum-evidence-materials-context",
        validation_id=INSTRUCTIONAL_MATERIALS_VALIDATION_ID,
    )
    assert validation_argv(request) == INSTRUCTIONAL_MATERIALS_VALIDATION_ARGV
    joined = " ".join(validation_argv(request))
    assert "instructional-materials-coach/tests" in joined
    assert "test_current_curriculum_state.py" in joined
    assert "test_material_requirement_contract.py" in joined
    assert "test_dev_validation_gce.py" in joined
    assert "-c" not in validation_argv(request)
    assert "shell" not in joined
    assert request.execution_authorized is False
    assert request.merge_authorized is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"repository": "someone/else"},
        {"issue_number": 0},
        {"branch": "main"},
        {"branch": "agent/../main"},
        {"branch": "agent/x;rm-rf"},
        {"source_sha": "abc"},
        {"validation_id": "python -m pytest whatever"},
        {"validation_id": "remote-validation-suite; rm -rf /"},
        {"validation_id": "instructional-materials-current-curriculum --collect-only"},
    ],
)
def test_untrusted_or_arbitrary_inputs_fail_closed(overrides) -> None:
    with pytest.raises(ValueError):
        build(**overrides)


def test_request_identity_changes_with_exact_sha() -> None:
    first = build()
    second = build(source_sha="b" * 40)
    assert first.request_id != second.request_id


def test_request_identity_changes_with_branch() -> None:
    first = build()
    second = build(branch="agent/1271-other")
    assert first.request_id != second.request_id


def test_request_identity_changes_with_validation_identity() -> None:
    first = build()
    second = build(validation_id=INSTRUCTIONAL_MATERIALS_VALIDATION_ID)
    assert first.request_id != second.request_id
