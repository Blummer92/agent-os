"""Controls for the branch-coverage artifact and aggregate failure path."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPORTS = {
    "workflow-scheduler.json": "workflow_scheduler",
    "reusable-capability-registry.json": "reusable_capability_registry",
    "visual-asset-intake.json": "visual_asset_intake",
}
HEAD = "a" * 40


@pytest.fixture
def reports(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    _create_source_tree(reports / "repo")
    for name, package in REPORTS.items():
        totals = {"covered_lines": 80, "num_statements": 100, "covered_branches": 8, "num_branches": 10}
        (reports / name).write_text(json.dumps({
            "meta": {"version": "7.16.2", "branch_coverage": True},
            "totals": totals,
            "files": {f"src/{package}/core.py": {"summary": totals}},
        }))
    return reports


def _create_source_tree(root):
    for report, package in REPORTS.items():
        source = root / "08_Tooling" / report.removesuffix(".json") / "src" / package
        source.mkdir(parents=True)
        (source / "core.py").write_text("VALUE = 1\n")


def check(reports, **identity):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/agent_os_ci_branch_coverage.py"), str(reports),
         "--validation-exit", "0"],
        cwd=reports / "repo",
        env={**os.environ, "CI_JUNIT_HEAD_SHA": HEAD, "CI_JUNIT_RUN_ID": "4132",
             "CI_JUNIT_RUN_ATTEMPT": "2", **identity},
        capture_output=True, text=True, check=False, timeout=10,
    )


def test_at_exact_floor_records_every_report_and_identity(reports):
    p = check(reports)
    assert p.returncode == 0, p.stderr
    receipt = json.loads((reports / "coverage-receipt.json").read_bytes())
    assert (receipt["head_sha"], receipt["run_id"], receipt["attempt"]) == (HEAD, 4132, 2)
    assert receipt["status"] == "pass"
    assert list(receipt["reports"]) == sorted(REPORTS)
    for name, result in receipt["reports"].items():
        assert result == {
            "status": "pass", "covered": 88, "total": 110, "tool_version": "7.16.2",
            "source_files": 1, "report_sha256": hashlib.sha256((reports / name).read_bytes()).hexdigest(),
        }


@pytest.mark.parametrize("fault,reason", [
    ("missing", "coverage-report-missing"),
    ("low", "coverage-below-floor"),
    ("line-only", "coverage-report-invalid"),
    ("invalid-version", "coverage-report-invalid"),
    ("wrong-source", "coverage-report-file-set-mismatch"),
    ("missing-source-file", "coverage-report-file-set-mismatch"),
    ("phantom-source-file", "coverage-report-file-set-mismatch"),
    ("forged-total", "coverage-report-invalid"),
    ("malformed-json", "coverage-report-invalid"),
])
def test_invalid_evidence_fails_with_bounded_reason(reports, fault, reason):
    name = "visual-asset-intake.json"
    report = reports / name
    data = json.loads(report.read_bytes())
    file = "src/visual_asset_intake/core.py"
    if fault == "missing":
        report.unlink()
    elif fault == "malformed-json":
        report.write_text("{")
    else:
        if fault == "low":
            for counts in (data["files"][file]["summary"], data["totals"]):
                # Lines alone remain at 80%; missing branches take the
                # combined measure below the gate.
                counts["covered_branches"] = 7
        elif fault == "line-only":
            data["meta"]["branch_coverage"] = False
        elif fault == "invalid-version":
            data["meta"]["version"] = "..."
        elif fault == "wrong-source":
            data["files"] = {"src/unrelated/core.py": data["files"][file]}
        elif fault == "missing-source-file":
            extra = reports / "repo/08_Tooling/visual-asset-intake/src/visual_asset_intake/unmeasured.py"
            extra.write_text("VALUE = 2\n")
        elif fault == "phantom-source-file":
            data["files"] = {"src/visual_asset_intake/phantom.py": data["files"][file]}
        elif fault == "forged-total":
            data["totals"]["covered_lines"] = 100
        report.write_text(json.dumps(data))
    p = check(reports)
    assert p.returncode == 1, p.stderr
    receipt = json.loads((reports / "coverage-receipt.json").read_bytes())
    assert receipt["status"] == "fail"
    assert receipt["reports"][name]["reason_code"] == reason
    assert all(receipt["reports"][n]["status"] == "pass" for n in REPORTS if n != name)


def test_workflow_uses_required_coverage_artifact_on_aggregate_only():
    path = ROOT / ".github/workflows/agent-os-validation.yml"
    jobs = yaml.safe_load(path.read_text())["jobs"]
    steps = jobs["validate"]["steps"]
    aggregate = next(s for s in steps if s.get("id") == "aggregate")
    assert aggregate["env"]["CI_COVERAGE_DIR"] == "${{ runner.temp }}/branch-coverage"
    script = aggregate["run"]
    assert script.count("bash ./scripts/validate-all.sh") == 1
    assert "scripts/agent_os_ci_branch_coverage.py" in script
    assert "validation_status" in script
    assert "continue-on-error" not in aggregate
    upload = next(s for s in steps if s.get("name") == "Upload branch coverage evidence")
    assert upload["with"]["name"] == "branch-coverage-aggregate-${{ github.run_attempt }}"
    assert upload["with"]["path"] == "${{ runner.temp }}/branch-coverage/"
    assert upload["with"]["if-no-files-found"] == "error"
    assert "validate" in jobs["aggregate-gate"]["needs"]
    assert all("CI_COVERAGE_DIR" not in step.get("env", {}) for step in jobs["plan"]["steps"])


@pytest.mark.parametrize("fault,exit_code", [
    ("none", 0), ("missing", 1), ("low", 1), ("runner-crash", 2),
])
def test_aggregate_step_cannot_greenwash_missing_or_failed_coverage(reports, tmp_path, fault, exit_code):
    # Execute the actual workflow's shell body, not a second implementation
    # of its exit policy. Only the aggregate producer is a synthetic fixture.
    jobs = yaml.safe_load((ROOT / ".github/workflows/agent-os-validation.yml").read_text())["jobs"]
    workload = next(s["run"] for s in jobs["validate"]["steps"] if s.get("id") == "aggregate")
    staged = tmp_path / "stage"
    shutil.copytree(reports, staged)
    report_path = staged / "visual-asset-intake.json"
    if fault == "missing":
        report_path.unlink()
    elif fault == "low":
        data = json.loads(report_path.read_bytes())
        data["totals"]["covered_branches"] = 7
        data["files"]["src/visual_asset_intake/core.py"]["summary"]["covered_branches"] = 7
        report_path.write_text(json.dumps(data))

    root = tmp_path / "repo"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    _create_source_tree(root)
    shutil.copy(ROOT / "scripts/agent_os_ci_branch_coverage.py", scripts)
    (scripts / "validate-all.sh").write_text(
        'cp "$STAGED_REPORTS"/*.json "$CI_COVERAGE_DIR/"\n'
        'exit "$FAKE_EXIT"\n'
    )
    args = ["bash", "-c", workload]
    env = {
        **os.environ, "CI_COVERAGE_DIR": str(reports), "STAGED_REPORTS": str(staged),
        "CI_JUNIT_HEAD_SHA": HEAD, "CI_JUNIT_RUN_ID": "4132", "CI_JUNIT_RUN_ATTEMPT": "2",
        "FAKE_EXIT": "2" if fault == "runner-crash" else "0",
    }
    result = subprocess.run(args, cwd=root, env=env, text=True,
                            capture_output=True, check=False, timeout=10)
    assert result.returncode == exit_code, result.stdout + result.stderr
    receipt = json.loads((reports / "coverage-receipt.json").read_bytes())
    assert receipt["status"] == ("pass" if fault == "none" else "fail")
    assert receipt["validation_exit"] == (2 if fault == "runner-crash" else 0)
    if fault == "runner-crash":
        assert receipt["reason_code"] == "coverage-validation-failed"
        assert receipt["reports"]["visual-asset-intake.json"]["status"] == "pass"

    if fault == "missing":
        assert not (reports / "visual-asset-intake.json").exists()
        assert receipt["reports"]["visual-asset-intake.json"]["reason_code"] == "coverage-report-missing"


@pytest.mark.parametrize(("key", "value"), [
    ("CI_JUNIT_HEAD_SHA", "deadbeef"),
    ("CI_JUNIT_RUN_ID", "0"),
    ("CI_JUNIT_RUN_ATTEMPT", "0"),
])
def test_bad_provenance_prevents_receipt_success_even_with_complete_reports(reports, key, value):
    process = check(reports, **{key: value})
    assert process.returncode == 1, process.stdout + process.stderr
    receipt = json.loads((reports / "coverage-receipt.json").read_bytes())
    assert receipt["status"] == "fail"
    assert receipt["reason_code"] == "coverage-run-binding-invalid"
    assert all(receipt[k] is None for k in ("head_sha", "run_id", "attempt"))
    assert all(item["status"] == "pass" for item in receipt["reports"].values())


@pytest.mark.parametrize("fault", ["duplicate", "truthy-branch-flag", "no-branches", "bool-count", "oversize"])
def test_file_shape_controls_reject_self_consistent_bad_evidence(reports, fault):
    from scripts.agent_os_ci_branch_coverage import MAX_REPORT_BYTES

    name = "visual-asset-intake.json"
    path = reports / name
    report = json.loads(path.read_bytes())
    per_file = report["files"]["src/visual_asset_intake/core.py"]["summary"]
    if fault == "truthy-branch-flag":
        report["meta"]["branch_coverage"] = "true"
    elif fault == "no-branches":
        for summary in (per_file, report["totals"]):
            summary["covered_branches"] = summary["num_branches"] = 0
    elif fault == "bool-count":
        for summary in (per_file, report["totals"]):
            summary["num_branches"] = summary["covered_branches"] = True

    serialized = json.dumps(report)
    if fault == "duplicate":
        serialized = serialized.replace('"branch_coverage": true',
                                        '"branch_coverage": false, "branch_coverage": true')
    path.write_text(serialized)
    if fault == "oversize":
        with path.open("a") as handle:
            handle.write(" " * (MAX_REPORT_BYTES + 1 - len(serialized)))

    process = check(reports)
    assert process.returncode == 1, process.stdout + process.stderr
    receipt = json.loads((reports / "coverage-receipt.json").read_bytes())
    assert receipt["status"] == "fail"
    assert receipt["reports"][name] == {"status": "fail", "reason_code": "coverage-report-invalid"}


@pytest.mark.parametrize(("validate_result", "aggregate_outcome", "state"), [
    ("success", "success", "success"),
    ("failure", "success", "error"),  # upload failed after aggregate executed
    ("failure", "failure", "failure"),
    ("skipped", "", "error"),
])
def test_existing_publisher_rejects_failed_or_missing_aggregate_job(validate_result, aggregate_outcome, state):
    commands = [
        ([sys.executable, str(ROOT / "scripts/agent_os_aggregate_gate.py"), "status"], 0),
        ([sys.executable, str(ROOT / "scripts/agent_os_aggregate_gate.py")], int(state != "success")),
    ]
    env = {**os.environ, "AUTHORITATIVE": "true", "REUSED": "false",
           "VALIDATE_RESULT": validate_result, "AGGREGATE_OUTCOME": aggregate_outcome,
           "PLAN_RESULT": "success", "FRONTEND_RESULT": "skipped", "FRONTEND_REQUIRED": "false"}
    for cmd, expected in commands:
        run = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False, timeout=10)
        assert run.returncode == expected, run.stdout + run.stderr
        if cmd[-1] == "status":
            assert json.loads(run.stdout)["state"] == state
