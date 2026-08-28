from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCHEDULER_SRC = ROOT / "08_Tooling" / "workflow-scheduler" / "src"
if str(SCHEDULER_SRC) not in sys.path:
    sys.path.insert(0, str(SCHEDULER_SRC))

from workflow_scheduler.governance import dev_validation
from workflow_scheduler.governance import dev_validation_gce
from workflow_scheduler.governance.github_issue_comment_ingress import admit_issue_comment_event

REPOSITORY = "Blummer92/agent-os"
ACTOR = "Blummer92"
SHA = "a" * 40
BRANCH = "agent/1454-fixed-materials-curriculum-validation"
MATERIALS_ID = "instructional-materials-current-curriculum-suite"
REMOTE_ID = "remote-validation-suite"


def _event(validation_id: str, *, branch: str = BRANCH, sha: str = SHA) -> dict[str, object]:
    body = f"/agent-os dev-validate {branch} {sha} {validation_id}"
    return {
        "action": "created",
        "repository": {"full_name": REPOSITORY},
        "issue": {"number": 1454},
        "comment": {"id": 1, "body": body, "user": {"login": ACTOR}},
        "sender": {"login": ACTOR},
    }


def _admit(validation_id: str, *, branch: str = BRANCH, sha: str = SHA):
    return admit_issue_comment_event(
        _event(validation_id, branch=branch, sha=sha),
        expected_repository=REPOSITORY,
        allowed_actor=ACTOR,
        run_attempt=1,
    )


def _request(validation_id: str):
    return dev_validation.build_dev_validation_request(
        repository=REPOSITORY,
        issue_number=1454,
        branch=BRANCH,
        source_sha=SHA,
        validation_id=validation_id,
    )


def test_new_identity_and_existing_identity_are_exactly_admitted() -> None:
    materials = _admit(MATERIALS_ID)
    remote = _admit(REMOTE_ID)
    assert (materials.status, materials.reason, materials.dev_validation_id_or_none) == (
        "accepted", "accepted-dev-validation-envelope", MATERIALS_ID
    )
    assert (remote.status, remote.reason, remote.dev_validation_id_or_none) == (
        "accepted", "accepted-dev-validation-envelope", REMOTE_ID
    )
    assert materials.execution_authorized is False
    assert materials.scheduler_invoked is False


def test_unknown_identity_and_injection_fail_closed() -> None:
    unknown = _admit("arbitrary-suite")
    injected = _admit(MATERIALS_ID + ";rm-rf")
    extra = _event(MATERIALS_ID)
    extra["comment"]["body"] += " tests/whatever"
    extra_result = admit_issue_comment_event(extra, expected_repository=REPOSITORY, allowed_actor=ACTOR, run_attempt=1)
    assert (unknown.status, unknown.reason) == ("ignored", "malformed-trigger")
    assert (injected.status, injected.reason) == ("ignored", "malformed-trigger")
    assert (extra_result.status, extra_result.reason) == ("ignored", "malformed-trigger")


def test_protected_branch_and_malformed_sha_fail_closed() -> None:
    protected = _admit(MATERIALS_ID, branch="main")
    bad_sha = _admit(MATERIALS_ID, sha="abc")
    assert (protected.status, protected.reason) == ("ignored", "malformed-trigger")
    assert (bad_sha.status, bad_sha.reason) == ("ignored", "malformed-trigger")


def test_registry_maps_each_identity_to_one_fixed_repository_owned_argv() -> None:
    assert dev_validation.validation_argv(_request(REMOTE_ID)) == (
        "python", "-m", "pytest", "tests/agent_os_remote_validation"
    )
    materials_argv = dev_validation.validation_argv(_request(MATERIALS_ID))
    assert materials_argv == dev_validation.MATERIALS_VALIDATION_ARGV
    assert materials_argv[0:3] == ("python", "-m", "pytest")
    assert "tests/test_current_curriculum_state.py" in materials_argv
    assert "tests/test_current_curriculum_evidence.py" in materials_argv
    assert all(";" not in value for value in materials_argv)


def test_request_builder_rejects_caller_supplied_command_surface() -> None:
    with pytest.raises(ValueError):
        _request("python -m pytest tests/whatever")
    with pytest.raises(ValueError):
        _request(MATERIALS_ID + " --maxfail=1")


def test_host_runner_owns_both_test_selections_and_uses_validated_identity() -> None:
    source = dev_validation_gce._HOST_RUNNER_SOURCE
    assert '"remote-validation-suite":("-m","pytest","tests/agent_os_remote_validation")' in source
    assert '"instructional-materials-current-curriculum-suite"' in source
    assert "test_args=VALIDATION_ARGS[validation_id]" in source
    assert "(TEST_PYTHON,*test_args)" in source
    assert "sys.argv[7:]" not in source
    assert "shell=True" not in source
    assert "pip install" not in source
    assert "sudo" not in source


def test_materials_identity_uses_only_fixed_repository_import_roots() -> None:
    source = dev_validation_gce._HOST_RUNNER_SOURCE
    assert 'MATERIALS_ID="instructional-materials-current-curriculum-suite"' in source
    assert 'MATERIALS_IMPORT_ROOTS=("src","08_Tooling/instructional-materials-coach/src")' in source
    assert 'if validation_id==MATERIALS_ID:' in source
    assert 'env["PYTHONPATH"]=os.pathsep.join(os.path.join(repo,path) for path in MATERIALS_IMPORT_ROOTS)' in source
    assert 'import instructional_materials_coach, instructional_workflow_contracts' in source
    assert 'validation-import-preflight-failed' in source
    assert 'os.environ.get("PYTHONPATH"' not in source
    assert 'sys.argv[7:]' not in source
    assert 'pip install' not in source
    assert 'shell=True' not in source


def test_host_command_carries_only_fixed_runner_plus_identity_arguments() -> None:
    request = _request(MATERIALS_ID)
    command = dev_validation_gce._host_command(request)
    argv = shlex.split(command)
    assert argv[0:3] == [dev_validation_gce.HOST_PYTHON, "-c", dev_validation_gce._HOST_RUNNER_SOURCE]
    assert argv[3:] == [REPOSITORY, "1454", BRANCH, SHA, MATERIALS_ID, request.request_id]


def test_existing_remote_validation_mapping_is_behaviorally_unchanged() -> None:
    assert dev_validation.VALIDATION_ID == REMOTE_ID
    assert dev_validation.VALIDATION_ARGV == (
        "python", "-m", "pytest", "tests/agent_os_remote_validation"
    )
    source = dev_validation_gce._HOST_RUNNER_SOURCE
    assert '"remote-validation-suite":("-m","pytest","tests/agent_os_remote_validation")' in source
