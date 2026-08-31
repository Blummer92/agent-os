"""DEVVAL3 (#1495) fixed PPUX/Picture Perfect TypeScript-Vitest validation identity.

The developer-validation lane already carried two fixed pytest identities. Neither
can execute the Picture Perfect Coach TypeScript suite the #1495 developer loop
requires, so a third identity is registered through the same registry, the same
issue-comment grammar, and the same GCE/IAP transport. These tests prove the new
identity adds no caller-controlled command, argv, path, filter, glob, shell, or
environment surface, and that the two existing identities are unchanged.
"""

from __future__ import annotations

import json
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
SHA = "b" * 40
BRANCH = "agent/1495-ppux-overlay-integrity"
PPUX_ID = "ppux-picture-perfect-ts-vitest"
REMOTE_ID = "remote-validation-suite"
MATERIALS_ID = "instructional-materials-current-curriculum-suite"
PACKAGE = ROOT / dev_validation.PPUX_VALIDATION_PACKAGE_DIR


def _admit(body: str):
    event = {
        "action": "created",
        "repository": {"full_name": REPOSITORY},
        "issue": {"number": 1495},
        "comment": {"id": 1, "body": body, "user": {"login": ACTOR}},
        "sender": {"login": ACTOR},
    }
    return admit_issue_comment_event(
        event, expected_repository=REPOSITORY, allowed_actor=ACTOR, run_attempt=1
    )


def _request(validation_id: str = PPUX_ID, *, branch: str = BRANCH, sha: str = SHA):
    return dev_validation.build_dev_validation_request(
        repository=REPOSITORY,
        issue_number=1495,
        branch=branch,
        source_sha=sha,
        validation_id=validation_id,
    )


def test_ingress_admits_the_ppux_identity_without_widening_the_grammar() -> None:
    accepted = _admit(f"/agent-os dev-validate {BRANCH} {SHA} {PPUX_ID}")
    assert (accepted.status, accepted.reason) == ("accepted", "accepted-dev-validation-envelope")
    assert accepted.dev_validation_id_or_none == PPUX_ID
    assert accepted.dev_validation_branch_or_none == BRANCH
    assert accepted.dev_validation_sha_or_none == SHA
    assert accepted.execution_authorized is False
    assert accepted.scheduler_invoked is False
    assert accepted.side_effects_performed is False


@pytest.mark.parametrize(
    "body",
    [
        f"/agent-os dev-validate {BRANCH} {SHA} ppux-picture-perfect-ts-vitest src/anything.test.ts",
        f"/agent-os dev-validate {BRANCH} {SHA} ppux-picture-perfect-ts-vitest --run",
        f"/agent-os dev-validate {BRANCH} {SHA} ppux-picture-perfect-ts-vitest;rm -rf /",
        f"/agent-os dev-validate {BRANCH} {SHA} ppux-picture-perfect",
        f"/agent-os dev-validate {BRANCH} {SHA} vitest",
        f"/agent-os dev-validate main {SHA} {PPUX_ID}",
        f"/agent-os dev-validate {BRANCH} deadbeef {PPUX_ID}",
    ],
)
def test_unknown_identity_and_supplied_arguments_fail_closed(body: str) -> None:
    result = _admit(body)
    assert (result.status, result.reason) == ("ignored", "malformed-trigger")
    assert result.dev_validation_id_or_none is None


def test_registry_maps_the_identity_to_one_fixed_repository_owned_argv() -> None:
    argv = dev_validation.validation_argv(_request())
    assert argv is dev_validation.VALIDATION_REGISTRY[PPUX_ID]
    assert argv == dev_validation.PPUX_VALIDATION_ARGV
    assert argv[0:3] == ("node", "vitest", "run")
    assert argv[3:] == (
        "src/overlayIntegrity.test.ts",
        "src/exactComposite.test.ts",
        "src/exactCompositeSuite.test.ts",
        "src/framePlan.test.ts",
        "src/executorContract.test.ts",
        "src/provenanceValidator.test.ts",
    )


def test_fixed_test_scope_resolves_to_real_repository_owned_files() -> None:
    assert PACKAGE.is_dir()
    assert (PACKAGE / "vite.config.ts").is_file()
    for entry in dev_validation.PPUX_VALIDATION_ARGV[3:]:
        target = PACKAGE / entry
        assert target.is_file(), entry
        assert target.resolve().is_relative_to(PACKAGE.resolve())


def test_fixed_argv_carries_no_shell_filter_glob_or_option_surface() -> None:
    for value in dev_validation.PPUX_VALIDATION_ARGV:
        assert not value.startswith("-")
        assert all(character not in value for character in ";|&$`><*?!\n\"'\\ ")
        assert ".." not in value


def test_request_builder_rejects_caller_supplied_command_and_path_surface() -> None:
    for candidate in (
        "node vitest run src/anything.test.ts",
        PPUX_ID + " --reporter=json",
        PPUX_ID + " -t overlay",
        PPUX_ID + "/../remote-validation-suite",
        "ppux-picture-perfect-ts-vitest\n",
        "PPUX-PICTURE-PERFECT-TS-VITEST",
    ):
        with pytest.raises(ValueError):
            _request(candidate)


def test_validation_request_and_argv_stay_non_authorizing() -> None:
    request = _request()
    assert request.execution_authorized is False
    assert request.scheduler_invoked is False
    assert request.publication_invoked is False
    assert request.merge_authorized is False
    assert request.to_dict()["validation_id"] == PPUX_ID
    drifted = dev_validation.DevValidationRequest(
        repository=request.repository,
        issue_number=request.issue_number,
        branch=request.branch,
        source_sha=request.source_sha,
        validation_id=request.validation_id,
        request_id="dev-validation:" + "0" * 64,
    )
    with pytest.raises(ValueError):
        dev_validation.validation_argv(drifted)


def test_host_runner_owns_the_ppux_selection_and_its_fixed_node_runtime() -> None:
    source = dev_validation_gce._HOST_RUNNER_SOURCE
    assert 'PPUX_ID="ppux-picture-perfect-ts-vitest"' in source
    assert 'PPUX_PACKAGE_DIR="08_Tooling/instructional-materials-coach/picture-perfect-coach"' in source
    assert 'NODE="/usr/local/libexec/agent-os-dev-validation-node"' in source
    assert 'NODE_MODULES="/opt/agent-os/dev-validation-node-runtime/node_modules"' in source
    assert 'VITEST_CLI=NODE_MODULES+"/vitest/vitest.mjs"' in source
    assert "(NODE,VITEST_CLI,*test_args[1:])" in source
    assert "test_args=VALIDATION_ARGS[validation_id]" in source
    assert "test-runtime-unavailable" in source
    assert "test-runtime-invalid" in source
    assert "validation-workspace-unavailable" in source
    for forbidden in ("shell=True", "npm install", "npm ci", "pip install", "sudo", "shutil.which", "sys.argv[7:]"):
        assert forbidden not in source


def test_host_runner_pins_the_same_node_and_vitest_identity_the_package_declares() -> None:
    manifest = json.loads((PACKAGE / "package.json").read_text(encoding="utf-8"))
    assert manifest["devDependencies"]["vitest"] == dev_validation_gce.DEV_VALIDATION_VITEST_VERSION
    assert manifest["engines"]["node"] == ">=22.12 <23"
    source = dev_validation_gce._HOST_RUNNER_SOURCE
    assert f"v!=='{dev_validation_gce.DEV_VALIDATION_VITEST_VERSION}'" in source
    assert "process.versions.node.startsWith('22.')" in source
    assert dev_validation_gce.DEV_VALIDATION_NODE == "/usr/local/libexec/agent-os-dev-validation-node"
    assert dev_validation_gce.DEV_VALIDATION_NODE_MODULES == "/opt/agent-os/dev-validation-node-runtime/node_modules"


def test_host_command_carries_only_the_fixed_runner_plus_identity_arguments() -> None:
    request = _request()
    argv = shlex.split(dev_validation_gce._host_command(request))
    assert argv[0:3] == [dev_validation_gce.HOST_PYTHON, "-c", dev_validation_gce._HOST_RUNNER_SOURCE]
    assert argv[3:] == [REPOSITORY, "1495", BRANCH, SHA, PPUX_ID, request.request_id]


def test_existing_identities_and_their_bindings_are_behaviorally_unchanged() -> None:
    assert dev_validation.VALIDATION_ID == REMOTE_ID
    assert dev_validation.VALIDATION_ARGV == ("python", "-m", "pytest", "tests/agent_os_remote_validation")
    assert dev_validation.MATERIALS_VALIDATION_ID == MATERIALS_ID
    assert dev_validation.MATERIALS_VALIDATION_ARGV[0:3] == ("python", "-m", "pytest")
    assert set(dev_validation.VALIDATION_REGISTRY) == {
        REMOTE_ID,
        MATERIALS_ID,
        PPUX_ID,
        "semantic-ownership-advisory",
    }
    source = dev_validation_gce._HOST_RUNNER_SOURCE
    assert '"remote-validation-suite":("-m","pytest","tests/agent_os_remote_validation")' in source
    assert "(TEST_PYTHON,*test_args)" in source
    assert '(TEST_PYTHON,"-c",MATERIALS_PYTEST_RUNNER,*test_args[2:])' in source
    assert 'TEST_PYTHON="/usr/local/libexec/agent-os-dev-validation-python"' in source
    assert dev_validation_gce.DEV_VALIDATION_PYTHON == "/usr/local/libexec/agent-os-dev-validation-python"


def test_host_runner_source_remains_an_executable_fixed_program() -> None:
    compile(dev_validation_gce._HOST_RUNNER_SOURCE, "<agent-os-dev-validation-host-runner>", "exec")
