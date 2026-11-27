"""Controls for the branch-coverage artifact and aggregate failure path."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from scripts.agent_os_ci_branch_coverage import load_scope
from tests.ci_aggregate_contract import assert_single_hosted_aggregate
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPORTS = {f"{suite}.json": package for suite, package in load_scope().items()}
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


def _write_manifest(reports, manifest):
    manifest.write_text(
        "suite_name\tcoverage_sha256\n" + "".join(
            f"08_Tooling/{name.removesuffix('.json')}\t"
            f"{hashlib.sha256((reports / name).read_bytes()).hexdigest() if (reports / name).is_file() else 'missing'}\n"
            for name in REPORTS
        )
    )


def _init_test_checkout(root, *, source):
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    _create_source_tree(root)
    shutil.copy(ROOT / "08_Tooling/visual-asset-intake/pyproject.toml",
                root / "08_Tooling/visual-asset-intake/pyproject.toml")
    for file in ("ci-local.sh", "agent_os_ci_branch_coverage.py",
                 "ci-coverage-suites.tsv", "agent_os_aggregate_gate.py", "agent_os_ci_black.py"):
        shutil.copy(ROOT / "scripts" / file, scripts)
    _write_manifest(source, source / "manifest.tsv")
    (scripts / "validate-all.sh").write_text(
        'cp "$STAGED_REPORTS"/*.json "$CI_COVERAGE_DIR/"\n'
        'cp "$STAGED_REPORTS/manifest.tsv" "$CI_JUNIT_DIR/manifest.tsv"\n'
        'if [ "${FAKE_REPORT_CHANGED:-}" = "yes" ]; then '
        'printf "\\n" >> "$CI_COVERAGE_DIR/visual-asset-intake.json"; fi\n'
        'if [ "${FAKE_DIRTY:-}" = "yes" ]; then touch dirty-marker; fi\n'
        'exit "${FAKE_EXIT:-0}"\n'
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-qm", "fixture"], cwd=root, check=True)


def check(reports, validation_exit="0", *, snapshot=True, **identity):
    if snapshot:
        _write_manifest(reports, reports / "manifest.tsv")
    command = [sys.executable, str(ROOT / "scripts/agent_os_ci_branch_coverage.py"), str(reports)]
    if validation_exit is not None:
        command.extend(("--validation-exit", validation_exit))
    return subprocess.run(
        command,
        cwd=reports / "repo",
        env={**os.environ, "CI_JUNIT_DIR": str(reports), "CI_JUNIT_HEAD_SHA": HEAD, "CI_JUNIT_RUN_ID": "4132",
             "CI_JUNIT_RUN_ATTEMPT": "2", **identity},
        capture_output=True, text=True, check=False, timeout=10,
    )


def test_at_exact_floor_records_every_report_and_identity(reports):
    p = check(reports)
    assert p.returncode == 0, p.stderr
    receipt = json.loads((reports / "coverage-receipt.json").read_bytes())
    assert (receipt["head_sha"], receipt["run_id"], receipt["attempt"]) == (HEAD, 4132, 2)
    assert receipt["status"] == "pass"
    assert receipt["manifest_sha256"] == hashlib.sha256((reports / "manifest.tsv").read_bytes()).hexdigest()
    assert list(receipt["reports"]) == sorted(REPORTS)
    for name, result in receipt["reports"].items():
        assert result == {
            "status": "pass", "covered": 88, "total": 110, "tool_version": "7.16.2",
            "source_files": 1, "report_sha256": hashlib.sha256((reports / name).read_bytes()).hexdigest(),
            "reason_code": None, "missing_files": [], "extra_files": [],
            "missing_file_count": 0, "extra_file_count": 0,
        }


@pytest.mark.parametrize("fault,reason", [
    ("missing", "coverage-report-missing"),
    ("low", "coverage-below-floor"),
    ("line-only", "coverage-report-invalid"),
    ("invalid-version", "coverage-report-invalid"),
    ("wrong-source", "coverage-report-file-set-mismatch"),
    ("missing-source-file", "coverage-report-file-set-mismatch"),
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
    assert_single_hosted_aggregate(ROOT)
    wrapper = (ROOT / "scripts/ci-local.sh").read_text()
    assert "scripts/agent_os_ci_branch_coverage.py" in wrapper
    assert "continue-on-error" not in aggregate
    upload = next(s for s in steps if s.get("name") == "Upload branch coverage evidence")
    assert upload["with"]["name"] == "branch-coverage-aggregate-${{ github.run_attempt }}"
    assert upload["with"]["path"] == "${{ runner.temp }}/branch-coverage/"
    assert upload["with"]["if-no-files-found"] == "error"
    assert "validate" in jobs["aggregate-gate"]["needs"]
    assert all("CI_COVERAGE_DIR" not in step.get("env", {}) for step in jobs["plan"]["steps"])


@pytest.mark.parametrize("fault,exit_code", [
    ("none", 0), ("black-findings", 1), ("black-missing", 2), ("missing", 1), ("low", 1), ("runner-crash", 2), ("dirty-after", 2), ("changed-after-manifest", 1),
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
    _init_test_checkout(root, source=staged)
    if fault in {"black-findings", "black-missing"}:
        target = (
            "08_Tooling/visual-asset-intake/src/visual_asset_intake/core.py"
            if fault == "black-findings" else "scripts/agent_os_ci_black.py"
        )
        (root / target).write_text("VALUE=1\n" if fault == "black-findings" else "")
        subprocess.run(["git", "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@example.invalid", "commit", "-qam", fault],
                       cwd=root, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    args = ["bash", "-c", workload]
    env = {
        **os.environ, "CI_COVERAGE_DIR": str(reports), "CI_JUNIT_DIR": str(tmp_path / "junit"),
        "STAGED_REPORTS": str(staged),
        "CI_JUNIT_HEAD_SHA": head, "CI_JUNIT_RUN_ID": "4132", "CI_JUNIT_RUN_ATTEMPT": "2",
        "PYTHON_BIN": sys.executable, "FAKE_EXIT": "2" if fault == "runner-crash" else "0",
        "FAKE_DIRTY": "yes" if fault == "dirty-after" else "no",
        "FAKE_REPORT_CHANGED": "yes" if fault == "changed-after-manifest" else "no",
    }
    result = subprocess.run(args, cwd=root, env=env, text=True,
                            capture_output=True, check=False, timeout=10)
    assert result.returncode == exit_code, result.stdout + result.stderr
    receipt = json.loads((reports / "coverage-receipt.json").read_bytes())
    assert receipt["status"] == ("pass" if fault in {"none", "black-findings", "black-missing"} else "fail")
    black = tmp_path / "junit/black-format-receipt.json"
    if fault in {"none", "black-findings"}:
        evidence = json.loads(black.read_text())
        expected = "clean" if fault == "none" else "findings"
        assert (evidence["status"], evidence["head_sha"]) == (expected, head)
        assert evidence["reason_code"] == (None if fault == "none" else "black-formatting-changes")
        if fault == "black-findings":
            assert "would reformat" in evidence["diagnostics"]
    if fault == "black-missing":
        assert not black.exists() and "required receipt missing" in result.stderr
    assert receipt["validation_exit"] == (2 if fault in {"runner-crash", "dirty-after"} else 0)
    if fault == "dirty-after":
        assert "checkout changed during validation" in result.stderr
    if fault in {"runner-crash", "dirty-after"}:
        assert receipt["reason_code"] == "coverage-validation-failed"
        assert receipt["reports"]["visual-asset-intake.json"]["status"] == "pass"

    if fault == "changed-after-manifest":
        assert receipt["reports"]["visual-asset-intake.json"]["reason_code"] == "coverage-report-digest-mismatch"
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
    assert receipt["reports"][name]["status"] == "fail"
    assert receipt["reports"][name]["reason_code"] == "coverage-report-invalid"
    assert receipt["reports"][name]["covered"] is None


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


def test_unreadable_inventory_writes_a_failed_receipt(reports, monkeypatch, capsys):
    from scripts import agent_os_ci_branch_coverage as validator

    original = validator._source_files

    def unreadable(root, suite, package):
        if suite == "visual-asset-intake":
            raise PermissionError("test-only invisible path")
        return original(root, suite, package)

    monkeypatch.chdir(reports / "repo")
    monkeypatch.setattr(validator, "_source_files", unreadable)
    monkeypatch.setattr(sys, "argv", ["coverage", str(reports), "--validation-exit", "0"])
    _write_manifest(reports, reports / "manifest.tsv")
    monkeypatch.setenv("CI_JUNIT_DIR", str(reports))
    monkeypatch.setenv("CI_JUNIT_HEAD_SHA", HEAD)
    monkeypatch.setenv("CI_JUNIT_RUN_ID", "4132")
    monkeypatch.setenv("CI_JUNIT_RUN_ATTEMPT", "2")
    assert validator.main() == 1
    payload = json.loads((reports / "coverage-receipt.json").read_bytes())
    assert payload["reason_code"] == "coverage-reports-failed"
    assert payload["reports"]["visual-asset-intake.json"]["reason_code"] == "coverage-report-invalid"
    assert "invisible path" not in capsys.readouterr().out
    assert payload["reports"]["workflow-scheduler.json"]["status"] == "pass"


def test_file_set_receipt_names_the_difference_and_has_uniform_report_fields(reports):
    name = "visual-asset-intake.json"
    path = reports / name
    data = json.loads(path.read_bytes())
    actual = "src/visual_asset_intake/core.py"
    extra = "src/visual_asset_intake/extra.py"
    data["files"][extra] = data["files"].pop(actual)
    path.write_text(json.dumps(data))
    assert check(reports).returncode == 1
    payload = json.loads((reports / "coverage-receipt.json").read_bytes())
    assert payload["reason_code"] == "coverage-reports-failed"
    observed = payload["reports"][name]
    assert observed["reason_code"] == "coverage-report-file-set-mismatch"
    assert observed["missing_files"] == [actual]
    assert observed["extra_files"] == [extra]
    assert set(observed) == set(payload["reports"]["workflow-scheduler.json"])
    assert observed["covered"] is None and observed["total"] is None


def test_local_wrapper_ignores_inherited_output_and_uses_local_receipt(reports, tmp_path):
    root = tmp_path / "checkout"
    _init_test_checkout(root, source=reports)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    inherited = tmp_path / "outer"
    inherited.mkdir()
    sentinel = inherited / "visual-asset-intake.json"
    sentinel.write_text("do not touch")
    result = subprocess.run(
        ["bash", "./scripts/ci-local.sh"], cwd=root,
        env={**os.environ, "TMPDIR": str(scratch), "CI_COVERAGE_DIR": str(inherited),
             "CI_JUNIT_DIR": str(inherited), "STAGED_REPORTS": str(reports), "PYTHON_BIN": sys.executable},
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert sentinel.read_text() == "do not touch"
    assert list(inherited.iterdir()) == [sentinel]
    outputs = list(scratch.glob("agent-os-ci.*"))
    assert len(outputs) == 1
    receipt = json.loads((outputs[0] / "coverage/coverage-receipt.json").read_text())
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    assert (receipt["origin"], receipt["head_sha"], receipt["status"]) == ("local", head, "pass")
    assert (outputs[0] / "junit/manifest.tsv").read_bytes() == (reports / "manifest.tsv").read_bytes()

@pytest.mark.parametrize("status", [None, "unknown", "256"])
def test_invalid_runner_exit_always_has_failed_receipt(reports, status):
    run = check(reports, validation_exit=status)
    assert run.returncode == 1, run.stdout + run.stderr
    payload = json.loads((reports / "coverage-receipt.json").read_bytes())
    assert (payload["status"], payload["reason_code"], payload["validation_exit"]) == (
        "fail", "coverage-validation-exit-invalid", None
    )


@pytest.mark.parametrize("fault,reason", [
    ("absent", "coverage-manifest-invalid"),
    ("duplicate-suite", "coverage-manifest-invalid"),
    ("changed-bytes", "coverage-report-digest-mismatch"),
])
def test_valid_report_needs_manifest_binding(reports, fault, reason):
    manifest = reports / "manifest.tsv"
    _write_manifest(reports, manifest)
    name = "visual-asset-intake.json"
    if fault == "absent":
        manifest.unlink()
    elif fault == "duplicate-suite":
        with manifest.open("a") as out:
            out.write(manifest.read_text().splitlines()[-1] + "\n")
    else:
        path = reports / name
        path.write_bytes(path.read_bytes() + b"\n")
    result = check(reports, snapshot=False)
    assert result.returncode == 1, result.stdout + result.stderr
    receipt = json.loads((reports / "coverage-receipt.json").read_bytes())
    actual = receipt["reports"][name]["reason_code"] if fault == "changed-bytes" else receipt["reason_code"]
    assert actual == reason
