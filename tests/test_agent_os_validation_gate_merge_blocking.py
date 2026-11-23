import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _validate_job_header(content: str) -> str:
    start = content.index("  validate:\n")
    end = content.index("    runs-on:", start)
    return content[start:end]


def test_ready_for_review_event_rechecks_exact_head_gate() -> None:
    content = _workflow()
    pull_request = content.index("pull_request:")
    push = content.index("push:")
    trigger_block = content[pull_request:push]
    assert "ready_for_review" in trigger_block


def test_ready_pull_request_aggregate_gate_is_not_profile_skippable() -> None:
    header = _validate_job_header(_workflow())
    assert "github.event.pull_request.draft == false" in header
    assert "needs.plan.outputs.profile" not in header


def test_draft_pull_request_still_defers_automatic_aggregate_cost() -> None:
    header = _validate_job_header(_workflow())
    assert "github.event.pull_request.draft == false" in header
    assert "github.event_name != 'pull_request'" in header


def test_aggregate_command_remains_the_authoritative_gate_command() -> None:
    content = _workflow()
    assert content.count("./scripts/validate-all.sh") == 1
    assert "name: Run aggregate validation" in content


def test_exact_head_final_candidate_dispatch_remains_available_for_drafts() -> None:
    content = _workflow()
    assert "workflow_dispatch:" in content
    assert 'echo "mode=final-candidate" >> "$GITHUB_OUTPUT"' in content
    assert 'if [ "$GITHUB_SHA" != "$EXPECTED_HEAD_SHA" ]' in content
    assert "dispatch the workflow on a ref resolving to the exact PR head" in content


def test_ready_event_does_not_cancel_equivalent_in_flight_same_pr_validation() -> None:
    content = _workflow()
    assert (
        "cancel-in-progress: ${{ github.event_name == 'pull_request' "
        "&& github.event.action != 'ready_for_review' }}"
    ) in content


def _steps() -> dict:
    workflow = yaml.safe_load(_workflow())
    return {step["name"]: step for step in workflow["jobs"]["validate"]["steps"]}


def test_ready_always_enters_fresh_authoritative_aggregate() -> None:
    content = _workflow()
    steps = _steps()
    assert "aggregate_evidence" not in content
    assert "Reuse valid exact-head aggregate evidence" not in steps
    assert steps["Publish authoritative aggregate pending status"]["if"] == (
        "${{ steps.authority.outputs.authoritative == 'true' }}"
    )
    assert "if" not in steps["Run aggregate validation"]
    assert steps["Run aggregate validation"]["run"] == "bash ./scripts/validate-all.sh"
    terminal = yaml.safe_load(content)["jobs"]["aggregate-gate"]["steps"]
    publish = next(step for step in terminal if step["name"] == "Publish terminal authoritative aggregate status")
    assert "REUSED" not in publish["env"]


def test_pending_supersedes_prior_green_before_current_tests(tmp_path: Path) -> None:
    """Execute the actual pending shell using a local-only GitHub CLI stub."""
    statuses = tmp_path / "statuses.json"
    statuses.write_text(json.dumps([_status(1, "success")]), encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "assert args[:3] == ['api', '-X', 'POST']\n"
        "assert args[3] == '/repos/Blummer92/agent-os/statuses/' + os.environ['STATUS_SHA']\n"
        "assert 'state=pending' in args and 'context=agent-os/authoritative-aggregate' in args\n"
        "path = pathlib.Path(os.environ['GH_FIXTURE'])\n"
        "statuses = json.loads(path.read_text())\n"
        "statuses.append(dict(id=2, state='pending', context='agent-os/authoritative-aggregate'))\n"
        "path.write_text(json.dumps(statuses))\n"
        "assert args[-2:] == ['--jq', '.id']\n"
        "print(2)\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    steps = _steps()
    names = list(steps)
    pending_name = "Publish authoritative aggregate pending status"
    # The shell step below must actually be admitted even with prior success.
    assert steps[pending_name]["if"] == "${{ steps.authority.outputs.authoritative == 'true' }}"
    assert not steps[pending_name].get("continue-on-error")
    assert names.index(pending_name) < names.index("Check out repository")
    assert names.index(pending_name) < names.index("Run aggregate validation")
    subprocess.run(
        ["bash", "-c", steps[pending_name]["run"]],
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GH_FIXTURE": str(statuses),
            "GITHUB_OUTPUT": str(tmp_path / "outputs"),
            "GITHUB_REPOSITORY": "Blummer92/agent-os",
            "STATUS_SHA": "d3501c232181963deda648483c9c65f4290f8ba7",
            "TARGET_URL": "https://example.invalid/actions/runs/123",
        },
        check=True,
    )
    from scripts.agent_os_aggregate_gate import latest_authoritative_state

    assert latest_authoritative_state(json.loads(statuses.read_text())) == "pending"
    assert (tmp_path / "outputs").read_text() == "id=2\n"


def test_dispatch_modes_keep_their_authority_contract() -> None:
    steps = _steps()
    admission = steps["Admit exact-head Draft final candidate"]
    authority = steps["Resolve authoritative candidate identity"]
    assert admission["if"] == "${{ github.event_name == 'workflow_dispatch' }}"
    for mode in ("diagnostic", "final-candidate", "ready-recovery"):
        assert f"mode={mode}" in admission["run"]
    assert "DISPATCH_MODE" in authority["env"] and 'echo "authoritative=false"' in authority["run"]
    assert "run_required" not in admission["if"]


def _status(status_id: int, state: str, context: str = "agent-os/authoritative-aggregate") -> dict:
    return {"id": status_id, "state": state, "context": context}


# (statuses newest-first as GitHub returns them, expected state, run_required)
REUSE_MATRIX = [
    ([], "missing", "true"),
    ([_status(1, "success")], "success", "false"),
    ([_status(2, "pending"), _status(1, "success")], "pending", "true"),
    # #2761: older success -> newer failure must not be reused.
    ([_status(2, "failure"), _status(1, "success")], "failure", "true"),
    ([_status(2, "error"), _status(1, "success")], "error", "true"),
    # Newer success after a failure is the governing evidence.
    ([_status(3, "success"), _status(2, "failure")], "success", "false"),
    # Ordering of the response must not matter; the highest id governs.
    ([_status(1, "success"), _status(2, "failure")], "failure", "true"),
    # Other contexts never count, however new or green.
    ([_status(9, "success", "ci/other")], "missing", "true"),
    ([_status(9, "success", "ci/other"), _status(2, "failure")], "failure", "true"),
]


@pytest.mark.parametrize("statuses,state,run_required", REUSE_MATRIX)
def test_latest_authoritative_status_helper_preserves_history_ordering(
    statuses: list[dict], state: str, run_required: str
) -> None:
    from scripts.agent_os_aggregate_gate import evaluate_reuse

    assert evaluate_reuse(statuses) == (run_required == "false", state)


_SHA = "a" * 40
_TARGET = "https://github.com/Blummer92/agent-os/actions/runs/123"


def _terminal_status(tmp_path: Path, statuses: list[dict], *,
                     pending_id: str = "10", outcome: str = "success",
                     read_failure: bool = False) -> tuple[subprocess.CompletedProcess, list[dict]]:
    """Replay the exact terminal shell and real gate CLI with a disk-only fake gh."""
    fixture = tmp_path / "terminal-statuses.json"
    fixture.write_text(json.dumps(statuses), encoding="utf-8")
    gh = tmp_path / "gh"
    gh.write_text(
        """#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
repo = os.environ["GITHUB_REPOSITORY"]
sha = os.environ["STATUS_SHA"]
store = pathlib.Path(os.environ["GH_FIXTURE"])
statuses = json.loads(store.read_text())
if args[:2] == ["api", "--paginate"]:
    assert args[2:] == [f"/repos/{repo}/commits/{sha}/statuses?per_page=100"]
    if os.environ["READ_FAILURE"] == "yes":
        sys.exit(1)
    print(json.dumps(statuses[:2]))
    print(json.dumps(statuses[2:]))
elif args[:3] == ["api", "-X", "POST"]:
    assert args[3] == f"/repos/{repo}/statuses/{sha}"
    fields = dict(item.split("=", 1) for item in args[5::2])
    statuses.append(dict(id=1 + max((row["id"] for row in statuses), default=0), **fields))
    store.write_text(json.dumps(statuses))
else:
    raise AssertionError(args)
""",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    job = yaml.safe_load(_workflow())["jobs"]["aggregate-gate"]
    step = next(s for s in job["steps"] if s["name"] == "Publish terminal authoritative aggregate status")
    env = dict(
        os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}", GH_FIXTURE=str(fixture),
        GITHUB_REPOSITORY="Blummer92/agent-os", STATUS_SHA=_SHA, TARGET_URL=_TARGET,
        PENDING_STATUS_ID=pending_id, READ_FAILURE="yes" if read_failure else "no",
        AUTHORITATIVE="true", VALIDATE_RESULT=outcome, AGGREGATE_OUTCOME=outcome,
        PLAN_RESULT="success", FRONTEND_RESULT="success", FRONTEND_REQUIRED="true",
        FRONTEND_EXPECTED_SHA=_SHA, FRONTEND_TESTED_SHA=_SHA,
        MAIN_HEALTH_OUTCOME="", MAIN_RECOVERY_STOP_OUTCOME="", REUSED="false",
    )
    result = subprocess.run(["bash", "-c", step["run"]], cwd=ROOT, env=env, capture_output=True, text=True)
    return result, json.loads(fixture.read_text())


def _own_pending() -> dict:
    return dict(_status(10, "pending"), target_url=_TARGET)


def test_late_old_success_cannot_overwrite_already_published_ready_failure(tmp_path: Path) -> None:
    # Deliberately put the governing status on the second provider page.
    statuses = [_status(15, "success", "ci/unrelated"), _own_pending(),
                _status(11, "pending"), _status(12, "failure")]
    result, after = _terminal_status(tmp_path, statuses)
    assert result.returncode != 0, after
    assert after == statuses
    assert "no longer owns" in result.stderr


def test_terminal_accepts_own_current_pending_and_ignores_other_contexts(tmp_path: Path) -> None:
    statuses = [_own_pending(), _status(15, "failure", "ci/unrelated")]
    result, after = _terminal_status(tmp_path, statuses)
    assert result.returncode == 0, result.stderr
    assert after[-1]["state"] == "success"


@pytest.mark.parametrize("pending_id,read_failure,replace_url", [
    ("", False, False), ("10", True, False), ("10", False, True),
])
def test_terminal_success_fails_closed_without_current_owned_receipt(
    tmp_path: Path, pending_id: str, read_failure: bool, replace_url: bool,
) -> None:
    statuses = [_own_pending()]
    if replace_url:
        statuses[0]["target_url"] = "https://github.com/Blummer92/agent-os/actions/runs/124"
    result, after = _terminal_status(tmp_path, statuses, pending_id=pending_id, read_failure=read_failure)
    assert result.returncode != 0, after
    assert after == statuses


def test_terminal_failure_stays_available_when_pending_was_not_established(tmp_path: Path) -> None:
    result, after = _terminal_status(tmp_path, [], pending_id="", outcome="failure")
    assert result.returncode == 0, result.stderr
    assert after[-1]["state"] == "failure"
