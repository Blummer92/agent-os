from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
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
BRANCH = "agent/1515-semantic-ownership-devval"
MATERIALS_ID = "instructional-materials-current-curriculum-suite"
REMOTE_ID = "remote-validation-suite"
SEMANTIC_OWNERSHIP_ID = "semantic-ownership-advisory"


def _event(validation_id: str, *, branch: str = BRANCH, sha: str = SHA) -> dict[str, object]:
    body = f"/agent-os dev-validate {branch} {sha} {validation_id}"
    return {
        "action": "created",
        "repository": {"full_name": REPOSITORY},
        "issue": {"number": 1515},
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
        issue_number=1515,
        branch=BRANCH,
        source_sha=SHA,
        validation_id=validation_id,
    )


def test_registered_identities_are_exactly_admitted() -> None:
    for validation_id in (MATERIALS_ID, REMOTE_ID, SEMANTIC_OWNERSHIP_ID):
        result = _admit(validation_id)
        assert (result.status, result.reason, result.dev_validation_id_or_none) == (
            "accepted", "accepted-dev-validation-envelope", validation_id
        )
        assert result.execution_authorized is False
        assert result.scheduler_invoked is False


def test_unknown_identity_and_injection_fail_closed() -> None:
    unknown = _admit("arbitrary-suite")
    injected = _admit(SEMANTIC_OWNERSHIP_ID + ";rm-rf")
    extra = _event(SEMANTIC_OWNERSHIP_ID)
    extra["comment"]["body"] += " tests/whatever"
    extra_result = admit_issue_comment_event(extra, expected_repository=REPOSITORY, allowed_actor=ACTOR, run_attempt=1)
    assert (unknown.status, unknown.reason) == ("ignored", "malformed-trigger")
    assert (injected.status, injected.reason) == ("ignored", "malformed-trigger")
    assert (extra_result.status, extra_result.reason) == ("ignored", "malformed-trigger")


def test_protected_branch_and_malformed_sha_fail_closed() -> None:
    protected = _admit(SEMANTIC_OWNERSHIP_ID, branch="main")
    bad_sha = _admit(SEMANTIC_OWNERSHIP_ID, sha="abc")
    assert (protected.status, protected.reason) == ("ignored", "malformed-trigger")
    assert (bad_sha.status, bad_sha.reason) == ("ignored", "malformed-trigger")


def test_registry_maps_each_identity_to_one_fixed_repository_owned_argv() -> None:
    assert dev_validation.validation_argv(_request(REMOTE_ID)) == (
        "python", "-m", "pytest", "tests/agent_os_remote_validation"
    )
    materials_argv = dev_validation.validation_argv(_request(MATERIALS_ID))
    assert materials_argv == dev_validation.MATERIALS_VALIDATION_ARGV
    semantic_argv = dev_validation.validation_argv(_request(SEMANTIC_OWNERSHIP_ID))
    assert semantic_argv == (
        "python", "07_Agent_Tests/run-semantic-ownership-advisory-validation.py"
    )
    assert all(";" not in value for value in semantic_argv)


def test_request_builder_rejects_caller_supplied_command_surface() -> None:
    with pytest.raises(ValueError):
        _request("python -m pytest tests/whatever")
    with pytest.raises(ValueError):
        _request(SEMANTIC_OWNERSHIP_ID + " --maxfail=1")


def test_host_runner_owns_fixed_selections_and_uses_validated_identity() -> None:
    source = dev_validation_gce._HOST_RUNNER_SOURCE
    assert '"remote-validation-suite":("-m","pytest","tests/agent_os_remote_validation")' in source
    assert '"instructional-materials-current-curriculum-suite"' in source
    assert '"semantic-ownership-advisory":("07_Agent_Tests/run-semantic-ownership-advisory-validation.py",)' in source
    assert "test_args=VALIDATION_ARGS[validation_id]" in source
    assert "sys.argv[7:]" not in source
    assert "shell=True" not in source
    assert "pip install" not in source
    assert "sudo" not in source


def test_semantic_ownership_entrypoint_is_fixed_and_rejects_arguments() -> None:
    path = ROOT / "07_Agent_Tests" / "run-semantic-ownership-advisory-validation.py"
    source = path.read_text(encoding="utf-8")
    assert 'PYTEST_TARGET = "tests/test_registry_consistency.py"' in source
    assert 'STRUCTURE_VALIDATOR = "07_Agent_Tests/validate-repo-structure.sh"' in source
    assert "arguments" in source
    completed = subprocess.run(
        (sys.executable, str(path), "tests/whatever"),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert "accepts no arguments" in completed.stderr


def test_materials_identity_uses_only_fixed_repository_import_roots() -> None:
    source = dev_validation_gce._HOST_RUNNER_SOURCE
    assert 'MATERIALS_ID="instructional-materials-current-curriculum-suite"' in source
    assert 'MATERIALS_IMPORT_ROOTS=("src","08_Tooling/instructional-materials-coach/src")' in source
    assert 'MATERIALS_IMPORT_PRELUDE=' in source
    assert "sys.path[:0]=[os.path.join(repo,path)" in source
    assert 'import instructional_materials_coach,instructional_workflow_contracts' in source
    assert 'validation-import-preflight-failed' in source
    assert '(TEST_PYTHON,"-c",MATERIALS_PYTEST_RUNNER,*test_args[2:])' in source
    assert 'env["PYTHONPATH"]' not in source
    assert 'os.environ.get("PYTHONPATH"' not in source
    assert 'sys.argv[7:]' not in source
    assert 'pip install' not in source
    assert 'shell=True' not in source


def test_fixed_materials_import_bootstrap_executes_bounded_suite() -> None:
    bootstrap = (
        "import os,sys;repo=os.getcwd();"
        "sys.path[:0]=[os.path.join(repo,path) for path in "
        "('src','08_Tooling/instructional-materials-coach/src')];"
        "import instructional_materials_coach,instructional_workflow_contracts;"
        "import pytest;raise SystemExit(pytest.main(list(sys.argv[1:])))"
    )
    runtime = Path(dev_validation_gce.DEV_VALIDATION_PYTHON)
    fixed_runtime_available = runtime.is_file()
    executable = str(runtime) if fixed_runtime_available else sys.executable
    with tempfile.TemporaryDirectory(prefix="agent-os-materials-bootstrap-") as temp_dir:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": temp_dir,
            "TMPDIR": temp_dir,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        if fixed_runtime_available:
            env["PYTHONNOUSERSITE"] = "1"
        completed = subprocess.run(
            (
                executable,
                "-c",
                bootstrap,
                *dev_validation.MATERIALS_VALIDATION_ARGV[3:],
            ),
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "passed" in completed.stdout


def test_host_command_carries_only_fixed_runner_plus_identity_arguments() -> None:
    request = _request(SEMANTIC_OWNERSHIP_ID)
    command = dev_validation_gce._host_command(request)
    argv = shlex.split(command)
    assert argv[0:3] == [dev_validation_gce.HOST_PYTHON, "-c", dev_validation_gce._HOST_RUNNER_SOURCE]
    assert argv[3:] == [REPOSITORY, "1515", BRANCH, SHA, SEMANTIC_OWNERSHIP_ID, request.request_id]


def test_existing_remote_validation_mapping_is_behaviorally_unchanged() -> None:
    assert dev_validation.VALIDATION_ID == REMOTE_ID
    assert dev_validation.VALIDATION_ARGV == (
        "python", "-m", "pytest", "tests/agent_os_remote_validation"
    )
    source = dev_validation_gce._HOST_RUNNER_SOURCE
    assert '"remote-validation-suite":("-m","pytest","tests/agent_os_remote_validation")' in source
