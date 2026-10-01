"""Exact-head tests for the bounded one-paste mobile command renderer (#1572)."""
from __future__ import annotations

import shlex
import json
import shutil
import subprocess

import pytest

from workflow_scheduler.governance.dev_validation_profiles import (
    PROFILE_ALIASES,
    PROFILE_CATALOG,
    get_profile,
)
from workflow_scheduler.governance.mobile_validation_commands import (
    MAX_COMMAND_CHARS,
    SHELL_POSIX_SH,
    _FORBIDDEN_TOKENS,
    render_all_mobile_commands,
    render_mobile_command,
)


def test_every_catalog_profile_renders_bounded_envelope() -> None:
    for profile_id, profile in PROFILE_CATALOG.items():
        envelope = render_mobile_command(profile_id)
        assert envelope.profile_id == profile_id
        assert envelope.shell == SHELL_POSIX_SH
        assert type(envelope.command) is str and envelope.command
        assert len(envelope.command) <= MAX_COMMAND_CHARS
        assert envelope.prerequisites
        assert all(type(item) is str and item for item in envelope.prerequisites)
        assert envelope.runtime_id == profile.runtime_id
        assert envelope.timeout_note
        assert envelope.runner_kind is profile.runner_kind


def test_aliases_render_to_canonical_profile_id() -> None:
    envelope = render_mobile_command("remote-validation-suite")
    assert envelope.profile_id == "remote-validation"
    assert envelope.command == render_mobile_command("remote-validation").command


def test_unknown_profile_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown developer-validation profile"):
        render_mobile_command("not-a-profile")


def test_unsupported_shell_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported shell"):
        render_mobile_command("remote-validation", shell="powershell")


def test_quoting_is_injection_safe_round_trip() -> None:
    # Defense-in-depth: even adversarial argv tokens must survive a
    # shell parse as exactly one argument each.
    adversarial = (
        "python",
        "-m",
        "pytest",
        "tests/a b;rm -rf ~",
        "$(evil)",
        "`evil`",
        "a'b",
    )
    quoted = " ".join(shlex.quote(arg) for arg in adversarial)
    assert shlex.split(quoted) == list(adversarial)


def test_rendered_command_parses_back_to_catalog_argv() -> None:
    # Injection/quoting evidence: the rendered text carries exactly the
    # catalog's fixed argv and nothing else.
    envelope = render_mobile_command("pr-remediation")
    assert shlex.split(envelope.command) == [
        "python",
        "-m",
        "pytest",
        "tests/agent_os_pr_remediation",
    ]


def test_cwd_profile_uses_side_effect_free_subshell() -> None:
    envelope = render_mobile_command("picture-perfect")
    profile = get_profile("picture-perfect")
    assert profile.fixed_working_directory is not None
    assert envelope.command.startswith(
        "(cd 08_Tooling/instructional-materials-coach/picture-perfect-coach && "
    )
    assert envelope.command.endswith(")")
    inner = envelope.command[len("(cd ") : -1]
    _, _, rest = inner.partition(" && ")
    assert shlex.split(rest) == list(profile.fixed_working_directory and (
        "node",
        "node_modules/vitest/vitest.mjs",
        "run",
        "src/overlayIntegrity.test.ts",
        "src/exactComposite.test.ts",
        "src/exactCompositeSuite.test.ts",
        "src/framePlan.test.ts",
        "src/executorContract.test.ts",
        "src/provenanceValidator.test.ts",
    ))


def test_prerequisites_are_displayed_not_embedded() -> None:
    for profile_id in PROFILE_CATALOG:
        envelope = render_mobile_command(profile_id)
        lowered = envelope.command.lower()
        for token in _FORBIDDEN_TOKENS:
            assert token not in lowered, (profile_id, token)
        assert "install" not in lowered
        assert "export" not in lowered


def test_host_provisioned_runtimes_say_so_explicitly() -> None:
    envelope = render_mobile_command("issue-scanner-proof")
    joined = " ".join(envelope.prerequisites).lower()
    assert "not runnable on a bare mobile device" in joined
    assert "governed read-only github app access" in joined


def test_render_is_deterministic() -> None:
    first = render_mobile_command("workflow-scheduler")
    second = render_mobile_command("workflow-scheduler")
    assert first == second


def test_render_all_covers_catalog_and_aliases() -> None:
    rendered = render_all_mobile_commands()
    for profile_id in PROFILE_CATALOG:
        assert profile_id in rendered
    for alias, canonical in PROFILE_ALIASES.items():
        assert alias in rendered
        assert rendered[alias].profile_id == canonical


def test_vitest_local_entry_resolves_as_a_node_script(tmp_path) -> None:
    """#1572: exercise the rendered command, not only shlex on invented tokens."""
    node = shutil.which("node")
    assert node is not None, "the registered Node command executor is required"
    profile = get_profile("picture-perfect")
    package = tmp_path / profile.fixed_working_directory
    entry = package / "node_modules/vitest/vitest.mjs"
    entry.parent.mkdir(parents=True)
    entry.write_text("console.log(JSON.stringify(process.argv.slice(2)));\n")
    command = render_mobile_command("picture-perfect").command
    result = subprocess.run(["sh", "-c", command], cwd=tmp_path, capture_output=True,
                            text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["run", *profile.fixed_targets]
    # The synthetic entry proves Node path/argv resolution, not Vitest or UI compatibility.
