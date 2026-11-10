import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"
AGGREGATE_RUNNER = ROOT / "scripts/validate-all.sh"
NAVIGATION_WORKFLOW = ROOT / ".github/workflows/navigation-registry-offline-tests.yml"
ISSUE_ACCEPTANCE_WORKFLOW = ROOT / ".github/workflows/agent-os-issue-acceptance-report.yml"
CLOUD_BUILD = ROOT / "cloudbuild.yaml"
SHARED_ACTION = ROOT / ".github/actions/setup-python-dev/action.yml"
REQUIREMENTS_DEV = ROOT / "requirements-dev.txt"

_REQUIREMENTS_INSTALL = re.compile(
    r"python -m pip install -r [\"']?([^\s\"']+)[\"']?"
)
_EDITABLE_INSTALL = re.compile(
    r"python -m pip install -e [\"']\./([^\"'\[]+)"
    r"(?:\[[^\"']+\])?[\"']"
)


def _cache_dependency_paths(content: str) -> set[str]:
    lines = content.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("cache-dependency-path:"):
            continue
        value = stripped.split(":", 1)[1].strip()
        if value and value != "|":
            return {value.strip("\"'")}
        parent_indent = len(line) - len(line.lstrip())
        paths: set[str] = set()
        for candidate in lines[index + 1 :]:
            if not candidate.strip():
                continue
            indent = len(candidate) - len(candidate.lstrip())
            if indent <= parent_indent:
                break
            paths.add(candidate.strip().strip("\"'"))
        return paths
    return set()


def _installed_dependency_manifests(content: str) -> set[str]:
    manifests = set(_REQUIREMENTS_INSTALL.findall(content))
    for package_path in _EDITABLE_INSTALL.findall(content):
        manifests.add(f"{package_path}/pyproject.toml")
    return manifests


def _assert_dependency_cache_parity(content: str) -> None:
    installed = _installed_dependency_manifests(content)
    cached = _cache_dependency_paths(content)
    missing = sorted(installed - cached)
    stale = sorted(cached - installed)
    assert not missing and not stale, (
        "dependency cache paths must exactly match installed dependency manifests; "
        f"missing={missing}, stale={stale}"
    )


def test_validation_gate_executes_only_canonical_aggregate_command():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert content.count("./scripts/validate-all.sh") == 1
    assert "bash 07_Agent_Tests/validate-repo-structure.sh" not in content
    assert "Cloud Build validation migration notice" not in content


def test_validation_gate_preserves_pr_head_validation_without_path_exemptions():
    content = WORKFLOW.read_text(encoding="utf-8")
    pull_request = content.index("pull_request:")
    push = content.index("push:")
    trigger_block = content[pull_request:push]
    assert "main" in trigger_block
    assert "synchronize" in trigger_block
    assert "paths:" not in trigger_block
    assert "paths-ignore:" not in trigger_block


def test_validation_gate_validates_every_canonical_main_push_without_path_exemptions():
    content = WORKFLOW.read_text(encoding="utf-8")
    push = content.index("push:")
    workflow_dispatch = content.index("workflow_dispatch:")
    trigger_block = content[push:workflow_dispatch]

    assert "branches:" in trigger_block
    assert re.search(r"(?m)^\s*- main\s*$", trigger_block)
    assert "paths:" not in trigger_block
    assert "paths-ignore:" not in trigger_block


def test_validation_gate_dispatch_supports_diagnostic_and_exact_head_candidate_modes():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in content
    assert "pr_number:" in content
    assert "expected_head_sha:" in content
    assert content.count("required: false") >= 2
    assert "PR_NUMBER: ${{ inputs.pr_number }}" in content
    assert "EXPECTED_HEAD_SHA: ${{ inputs.expected_head_sha }}" in content
    assert 'if [ -z "$PR_NUMBER" ] && [ -z "$EXPECTED_HEAD_SHA" ]' in content
    assert 'echo "mode=diagnostic" >> "$GITHUB_OUTPUT"' in content
    assert 'if [ -z "$PR_NUMBER" ] || [ -z "$EXPECTED_HEAD_SHA" ]' in content
    assert "must be provided together for final-candidate validation" in content
    assert 'gh pr view "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --json state,isDraft,headRefOid' in content
    assert 'if [ "$state" != "OPEN" ]' in content
    assert 'if [ "$is_draft" != "true" ]' in content
    assert 'if [ "$current_head" != "$EXPECTED_HEAD_SHA" ]' in content
    assert "stale final-candidate request" in content
    assert "^[0-9a-f]{40}$" in content
    assert 'echo "mode=final-candidate" >> "$GITHUB_OUTPUT"' in content


def test_validation_gate_final_candidate_requires_dispatch_ref_to_resolve_to_exact_head():
    content = WORKFLOW.read_text(encoding="utf-8")
    diagnostic_exit = content.index('echo "mode=diagnostic" >> "$GITHUB_OUTPUT"')
    dispatch_guard = content.index('if [ "$GITHUB_SHA" != "$EXPECTED_HEAD_SHA" ]')
    final_candidate = content.index('echo "mode=final-candidate" >> "$GITHUB_OUTPUT"')
    aggregate = content.index("- name: Run aggregate validation")
    assert diagnostic_exit < dispatch_guard < final_candidate < aggregate
    assert "final-candidate dispatch SHA $GITHUB_SHA does not match admitted candidate $EXPECTED_HEAD_SHA" in content
    assert "dispatch the workflow on a ref resolving to the exact PR head" in content


def test_validation_gate_dispatch_checks_out_and_verifies_admitted_candidate_only():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "steps.candidate.outputs.head_sha" in content
    assert "steps.candidate.outputs.mode == 'final-candidate'" in content
    assert "checked_out_sha=\"$(git rev-parse HEAD)\"" in content
    assert (
        '[ "$DISPATCH_MODE" = "final-candidate" ]'
        ' && [ "$checked_out_sha" != "$EXPECTED_HEAD_SHA" ]'
    ) in content
    assert (
        "checked-out SHA $checked_out_sha does not match admitted candidate "
        "$EXPECTED_HEAD_SHA"
    ) in content


def test_validation_gate_pull_request_aggregate_verifies_the_exact_pull_request_head():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert (
        "ref: ${{ github.event_name == 'pull_request'"
        " && github.event.pull_request.head.sha || github.sha }}"
    ) in content
    assert (
        '[ "$GITHUB_EVENT_NAME" = "pull_request" ]'
        ' && [ "$checked_out_sha" != "$PR_HEAD_SHA" ]'
    ) in content
    assert (
        "checked-out SHA $checked_out_sha does not match pull request head "
        "$PR_HEAD_SHA"
    ) in content


def test_cloud_build_executes_only_canonical_aggregate_command():
    content = CLOUD_BUILD.read_text(encoding="utf-8")
    assert content.count("./scripts/validate-all.sh") == 1
    assert "bash 07_Agent_Tests/validate-repo-structure.sh" not in content


def test_validation_gate_preserves_required_workflow_and_job_names():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "name: Agent OS Validation Gate" in content
    assert "name: Run aggregate validation" in content


def test_pre_aggregate_failure_writes_not_executed_receipt_before_upload():
    """A 502 (or any pre-aggregate failure, PR #3813 run 42393965702)
    must leave a machine-readable NOT_EXECUTED_INFRASTRUCTURE receipt
    instead of a second misleading "no files" upload error, while the
    aggregate step's own failure (tests executed) must not be
    rewritten as not-executed."""
    content = WORKFLOW.read_text(encoding="utf-8")
    receipt = content.index("- name: Record not-executed infrastructure receipt")
    upload = content.index("- name: Upload aggregate JUnit evidence")
    aggregate = content.index("- name: Run aggregate validation")
    assert aggregate < receipt < upload
    block = content[receipt:upload]
    assert "NOT_EXECUTED_INFRASTRUCTURE" in block
    assert "not-executed-infrastructure.json" in block
    assert "failure()" in block
    assert "steps.aggregate.outcome != 'success'" in block
    assert "steps.aggregate.outcome != 'failure'" in block
    # The note says what actually happened to the aggregate step: only
    # a skipped step means "not executed"; a cancelled step may have
    # run some suites before it stopped.
    assert "were not executed" in block
    assert "were cancelled before completing" in block
    assert "produced no verdict" in block
    assert "if-no-files-found: error" in content[upload:upload + 600]


def test_scheduler_validation_is_owned_by_the_canonical_aggregate_runner():
    assert not (ROOT / ".github/workflows/workflow-scheduler-validation.yml").exists()
    content = AGGREGATE_RUNNER.read_text(encoding="utf-8")
    assert 'suite_name" = "08_Tooling/workflow-scheduler"' in content
    # The runner appends coverage flags to the executed command exactly once and
    # mirrors them into the operator-visible display string; only the executed
    # command proves single ownership (#2126).
    assert content.count('command+=("--cov=src/workflow_scheduler" "--cov-report=term")') == 1
    assert content.count("--cov=src/workflow_scheduler") == 2
    assert "--cov-fail-under" not in content


def test_validation_gate_uses_read_only_permissions_and_bounded_execution():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "contents: read" in content
    assert "pull-requests: read" in content
    assert "checks: read" in content
    assert "contents: write" not in content
    assert "pull-requests: write" not in content
    assert "checks: write" not in content
    assert "timeout-minutes: 30" in content
    assert "concurrency:" in content
    assert "group:" in content
    assert "cancel-in-progress:" in content
    assert "github.event.pull_request.number" in content
    assert "github.run_id" in content
    assert (
        "cancel-in-progress: ${{ github.event_name == 'pull_request' "
        "&& github.event.action != 'ready_for_review' }}"
    ) in content


def test_validation_gate_installs_same_dependencies_as_cloud_build():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    cloudbuild = CLOUD_BUILD.read_text(encoding="utf-8")
    requirements = REQUIREMENTS_DEV.read_text(encoding="utf-8")
    direct_bootstrap = [
        "requirements-dev.txt",
        "08_Tooling/workflow-scheduler/requirements.txt",
        "08_Tooling/instructional-materials-coach[test]",
        "08_Tooling/notion-navigation-client[test]",
    ]
    for dependency in direct_bootstrap:
        assert dependency in workflow
        assert dependency in cloudbuild
    assert "-e ./08_Tooling/reusable-capability-registry[test]" in requirements
    assert 'pip install -e "./08_Tooling/reusable-capability-registry[test]"' not in workflow
    assert 'pip install -e "./08_Tooling/reusable-capability-registry[test]"' not in cloudbuild


def test_governed_validation_paths_do_not_upgrade_pip_unconditionally():
    for path in (WORKFLOW, CLOUD_BUILD, SHARED_ACTION):
        content = path.read_text(encoding="utf-8")
        assert "pip install --upgrade pip" not in content, path


def test_validation_gate_cache_paths_match_installed_dependency_manifests():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "uses: actions/setup-python@v7" in content
    assert 'cache: "pip"' in content
    _assert_dependency_cache_parity(content)


def test_parity_check_fails_when_new_install_manifest_is_not_cached():
    incomplete = """
      cache-dependency-path: requirements-dev.txt
      run: |
        python -m pip install -r requirements-dev.txt
        python -m pip install -r added-requirements.txt
    """
    with pytest.raises(AssertionError, match="added-requirements.txt"):
        _assert_dependency_cache_parity(incomplete)


def test_parity_check_fails_when_required_cache_path_is_removed():
    incomplete = """
      cache-dependency-path: |
        requirements-dev.txt
      run: |
        python -m pip install -r requirements-dev.txt
        python -m pip install -e "./08_Tooling/example-package[test]"
    """
    with pytest.raises(AssertionError, match="example-package/pyproject.toml"):
        _assert_dependency_cache_parity(incomplete)


def test_cache_configuration_does_not_replace_install_or_validation_commands():
    aggregate_workflow = WORKFLOW.read_text(encoding="utf-8")
    aggregate_runner = AGGREGATE_RUNNER.read_text(encoding="utf-8")
    assert "python -m pip install -r requirements-dev.txt" in aggregate_workflow
    assert "python -m pip install -r 08_Tooling/workflow-scheduler/requirements.txt" in aggregate_workflow
    assert "./scripts/validate-all.sh" in aggregate_workflow
    assert "--cov=src/workflow_scheduler" in aggregate_runner
    assert "--cov-report=term" in aggregate_runner


def test_cloud_build_does_not_use_github_actions_cache_configuration():
    content = CLOUD_BUILD.read_text(encoding="utf-8")
    assert "actions/setup-python" not in content
    assert "cache-dependency-path" not in content
    assert 'cache: "pip"' not in content


def test_navigation_registry_workflow_uses_bounded_same_lineage_concurrency():
    content = NAVIGATION_WORKFLOW.read_text(encoding="utf-8")
    assert "group: navigation-registry-offline-${{ github.event.pull_request.number || github.ref }}" in content
    assert "cancel-in-progress: ${{ github.run_attempt == 1 }}" in content


def test_navigation_registry_workflow_is_pr_only_path_triggered_and_preserves_job_and_test_command():
    content = NAVIGATION_WORKFLOW.read_text(encoding="utf-8")
    assert "name: Navigation Registry Offline Tests" in content
    assert "pull_request:" in content
    assert "\n  push:" not in content
    assert '"08_Tooling/notion-navigation-client/**"' in content
    assert '"tests/navigation_registry/**"' in content
    assert '"04_Registry/navigation-alias-registry.md"' in content
    assert '".github/workflows/navigation-registry-offline-tests.yml"' in content
    assert "offline-notion-connector-tests:" in content
    assert "pytest tests/navigation_registry/test_notion_read_only_connector.py" in content


def test_navigation_registry_workflow_does_not_cross_event_dedupe():
    content = NAVIGATION_WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.pull_request.number || github.ref" in content
    assert "github.sha" not in content
    assert "github.head_ref" not in content


def test_issue_acceptance_runs_only_on_demand_without_pr_event_churn():
    content = ISSUE_ACCEPTANCE_WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in content
    assert "\n  pull_request:" not in content
    assert "name: Classify acceptance inputs" not in content
    assert "needs: relevance" not in content
    assert "group: issue-acceptance-${{ inputs.pr_number || github.run_id }}" in content
    assert "cancel-in-progress: true" in content
    assert "pull-requests: read" in content
    assert 'exit "$checker_exit_code"' in content
    assert "Report-only boundary" in content


# --- Track B: Node setup is derived from the selected plan, not a substring ---

import subprocess  # noqa: E402
import sys  # noqa: E402
import textwrap  # noqa: E402

import yaml  # noqa: E402

_PPC_LOCK = "08_Tooling/instructional-materials-coach/picture-perfect-coach/package-lock.json"
_TEACHER_LOCK = "08_Tooling/teacher-os-web/package-lock.json"


def _plan_job_steps() -> dict:
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    return {step["name"]: step for step in jobs["plan"]["steps"]}


def _run_plan_script(tmp_path: Path, changed: list[str]) -> dict:
    """Execute the workflow's real plan heredoc and parse its GITHUB_OUTPUT text."""
    script = _plan_job_steps()["Compute canonical validation plan"]["run"]
    body = script.split("python - <<'PY' >> \"$GITHUB_OUTPUT\"\n", 1)[1].rsplit("\nPY", 1)[0]
    (tmp_path / "changed-files.txt").write_text("\n".join(changed) + "\n", encoding="utf-8")
    env = {
        "PATH": "/usr/bin:/bin",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_REPOSITORY": "Blummer92/agent-os",
        "PR_NUMBER": "1",
        "BASE_SHA": "a" * 40,
        "HEAD_SHA": "b" * 40,
        "PYTHONPATH": str(ROOT),
    }
    done = subprocess.run(
        # No "-I": the workflow itself runs plain `python -`, with the checkout
        # root on sys.path. Isolated mode ignores PYTHONPATH and drops the
        # working directory, so "-I" makes this harness unable to import the
        # real snippet in any environment; it never ran the plan code at all.
        [sys.executable, "-c", textwrap.dedent(body)],
        env=env, cwd=ROOT, capture_output=True, text=True, check=True,
    )
    outputs, lines = {}, iter(done.stdout.splitlines())
    for line in lines:
        if "<<" in line:
            name, delimiter = line.split("<<", 1)
            block = []
            for inner in lines:
                if inner == delimiter:
                    break
                block.append(inner)
            outputs[name] = "\n".join(block)
        else:
            name, value = line.split("=", 1)
            outputs[name] = value
    return outputs


def test_plan_outputs_teacher_only_uses_teacher_lock_and_no_ppc_install(tmp_path):
    out = _run_plan_script(tmp_path, ["08_Tooling/teacher-os-web/src/TeacherApp.tsx"])
    assert out["profile"] == "focused"
    assert out["needs_node"] == "true"
    assert out["needs_node_cache"] == "true"
    assert out["needs_picture_perfect_install"] == "false"
    assert out["node_lock_paths"] == _TEACHER_LOCK


def test_plan_outputs_teacher_lockfile_only_runs_react_commands(tmp_path):
    out = _run_plan_script(tmp_path, [_TEACHER_LOCK])
    assert out["profile"] == "focused"
    assert out["needs_node"] == "true"
    assert out["node_lock_paths"] == _TEACHER_LOCK


def test_plan_outputs_picture_perfect_only_keeps_original_install(tmp_path):
    out = _run_plan_script(
        tmp_path, ["08_Tooling/instructional-materials-coach/picture-perfect-coach/src/framePlan.ts"]
    )
    assert out["needs_node"] == "true"
    assert out["needs_picture_perfect_install"] == "true"
    assert out["node_lock_paths"] == _PPC_LOCK


def test_plan_outputs_combined_caches_both_locks(tmp_path):
    out = _run_plan_script(
        tmp_path,
        [
            "08_Tooling/instructional-materials-coach/picture-perfect-coach/src/framePlan.ts",
            "08_Tooling/teacher-os-web/src/style.css",
        ],
    )
    assert out["needs_picture_perfect_install"] == "true"
    assert out["node_lock_paths"].splitlines() == [_PPC_LOCK, _TEACHER_LOCK]


def test_plan_outputs_python_only_has_no_node(tmp_path):
    out = _run_plan_script(tmp_path, ["scripts/agent_os_issue_acceptance/anything.py"])
    assert out["profile"] == "focused"
    assert out["needs_node"] == "false"
    assert out["needs_node_cache"] == "false"
    assert out["needs_picture_perfect_install"] == "false"
    assert out["node_lock_paths"] == ""


_CAPTURE_LOCK = "08_Tooling/instructional-materials-coach/capture/package-lock.json"


def test_plan_outputs_capture_only_uses_capture_lock(tmp_path):
    out = _run_plan_script(tmp_path, ["08_Tooling/instructional-materials-coach/capture/README.md"])
    assert out["profile"] == "focused"
    assert out["needs_node"] == "true"
    assert out["needs_node_cache"] == "true"
    assert out["needs_picture_perfect_install"] == "false"
    assert out["node_lock_paths"] == _CAPTURE_LOCK


def test_plan_outputs_ui_reference_only_gets_no_cache_node(tmp_path):
    out = _run_plan_script(tmp_path, ["05_Examples/ui-cross-platform-reference/package.json"])
    assert out["profile"] == "focused"
    assert out["needs_node"] == "true"
    assert out["needs_node_cache"] == "false"
    assert out["needs_picture_perfect_install"] == "false"
    assert out["node_lock_paths"] == ""


def test_plan_outputs_teacher_plus_ui_reference_caches_only_the_teacher_lock(tmp_path):
    out = _run_plan_script(
        tmp_path,
        [
            "08_Tooling/teacher-os-web/src/style.css",
            "05_Examples/ui-cross-platform-reference/package.json",
        ],
    )
    assert out["needs_node"] == "true"
    assert out["needs_node_cache"] == "true"
    assert out["node_lock_paths"] == _TEACHER_LOCK


def test_node_steps_consume_plan_derived_outputs_only():
    steps = _plan_job_steps()
    setup = steps["Set up Node for focused validation"]
    assert setup["with"]["cache-dependency-path"] == "${{ steps.plan.outputs.node_lock_paths }}"
    assert "needs_node == 'true'" in setup["if"]
    assert "needs_node_cache == 'true'" in setup["if"]
    no_cache = steps["Set up Node for focused validation (no lockfile cache)"]
    assert "cache" not in no_cache["with"]
    assert "needs_node == 'true'" in no_cache["if"]
    assert "needs_node_cache == 'false'" in no_cache["if"]
    install = steps["Install Picture Perfect Coach dependencies"]
    assert "needs_picture_perfect_install == 'true'" in install["if"]
    assert "needs_node" not in install["if"].replace("needs_picture_perfect_install", "")
    script = steps["Compute canonical validation plan"]["run"]
    assert 'in command for command in plan.commands' not in script


@pytest.mark.parametrize("job,kind", [("jscpd-advisory", "jscpd"), ("pyan3-advisory", "pyan3")])
def test_advisory_jobs_fail_visibly_via_guard_after_upload(job, kind):
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"][job]["steps"]
    names = [step["name"] for step in steps]
    guard = next(step for step in steps if "scripts.advisory_evidence_guard" in step.get("run", ""))
    assert names.index(guard["name"]) > names.index("Upload advisory evidence")
    assert guard["if"] == "always()"
    assert "continue-on-error" not in guard
    assert f"--kind {kind}" in guard["run"] and "--sha" in guard["run"]


def test_advisory_guard_never_becomes_a_gate_dependency():
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    # `frontend` is a mandatory quality job (agent_os_frontend_checks.py), not advisory.
    assert jobs["aggregate-gate"]["needs"] == ["plan", "validate", "frontend"]
    assert "jscpd-advisory" not in jobs["aggregate-gate"]["needs"]
    assert "pyan3-advisory" not in jobs["aggregate-gate"]["needs"]
    assert "jscpd-advisory" not in jobs["validate"].get("needs", [])
    assert "pyan3-advisory" not in jobs["validate"].get("needs", [])


def test_terminal_status_step_receives_plan_result():
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    step = next(s for s in jobs["aggregate-gate"]["steps"] if s["name"] == "Publish terminal authoritative aggregate status")
    assert step["env"]["PLAN_RESULT"] == "${{ needs.plan.result }}"
