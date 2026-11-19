from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXECUTION_SERVICE_SRC = ROOT / "08_Tooling/agent-os-execution-service/src"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EXECUTION_SERVICE_SRC))

from agent_os_execution_service.command_planning import _COMMAND_REGISTRY
from scripts.agent_os_remote_validation import ValidationPlan, validate_validation_plan

_PICTURE_PERFECT_TESTS = (
    "src/overlayIntegrity.test.ts",
    "src/exactComposite.test.ts",
    "src/exactCompositeSuite.test.ts",
    "src/framePlan.test.ts",
    "src/executorContract.test.ts",
    "src/provenanceValidator.test.ts",
)
_PICTURE_PERFECT_FOCUSED = (
    "cd 08_Tooling/instructional-materials-coach/picture-perfect-coach && npm test -- "
    + " ".join(_PICTURE_PERFECT_TESTS)
)
_PICTURE_PERFECT_DIR = (
    ROOT / "08_Tooling/instructional-materials-coach/picture-perfect-coach"
)
_CAPTURE_DIR = ROOT / "08_Tooling/instructional-materials-coach/capture"
_CAPTURE_COMMANDS = {
    "cd 08_Tooling/instructional-materials-coach/capture && npm ci": ("npm", "ci"),
    "cd 08_Tooling/instructional-materials-coach/capture && npm test": ("npm", "test"),
    "cd 08_Tooling/instructional-materials-coach/capture && npm run check": (
        "npm",
        "run",
        "check",
    ),
}
_UI_CROSS_PLATFORM_REFERENCE_DIR = ROOT / "05_Examples/ui-cross-platform-reference"
_UI_CROSS_PLATFORM_REFERENCE_COMMANDS = {
    "cd 05_Examples/ui-cross-platform-reference && npm install": ("npm", "install"),
    "cd 05_Examples/ui-cross-platform-reference && npm test": ("npm", "test"),
}
_TEACHER_OS_DIR = ROOT / "08_Tooling/teacher-os-web"
_TEACHER_OS_COMMANDS = {
    "cd 08_Tooling/teacher-os-web && npm ci": ("npm", "ci"),
    "cd 08_Tooling/teacher-os-web && npm run build": ("npm", "run", "build"),
    "cd 08_Tooling/teacher-os-web && npm run test:unit": ("npm", "run", "test:unit"),
    "cd 08_Tooling/teacher-os-web && npx playwright install chromium": ("npx", "playwright", "install", "chromium"),
    "cd 08_Tooling/teacher-os-web && npx playwright test": ("npx", "playwright", "test"),
}
_CI_VALIDATION_SELF_TEST = "python -m pytest tests/test_agent_os_ci_validation.py"
# Match the authoritative runner: these plugins can produce passing-looking
# JUnit without executing test bodies.
_PYTEST_EXECUTION_GUARD = ("-p", "no:setuponly", "-p", "no:setupplan")

# D07 Track A (G2/G3): the 10 newly mapped Python suites, keyed by their exact
# focused command string. The command string keeps the existing root-relative
# form (``python -m pytest 08_Tooling/<dir>/tests``) so the command-plan
# registry still binds the canonical root-relative argv, but the bounded
# executor resolves suite-locally: the suite directory is the working
# directory and ``tests`` is the target. That is exactly how
# ``scripts/validate-all.sh`` runs each suite, and it is required, not
# cosmetic -- five of the ten packages (notion-operational-guidance-writer,
# visual-asset-drive-writer, visual-asset-ingestion-coordinator,
# visual-asset-notion-writer, visual-asset-routing) are not importable from
# the repository root, so a plain root-relative run fails at collection with
# ModuleNotFoundError. Suite-local execution also applies each suite's own
# pytest configuration (e.g. reusable-capability-registry's norecursedirs
# exclusion of its fixtures file, dashboard-migration-verification's
# pythonpath) instead of the root pytest.ini.
_PYTHON_FOCUSED_SUITE_COMMANDS = {
    "python -m pytest 08_Tooling/agent-memory-context-manager/tests": (
        ROOT / "08_Tooling/agent-memory-context-manager"
    ),
    "python -m pytest 08_Tooling/dashboard-migration-verification/tests": (
        ROOT / "08_Tooling/dashboard-migration-verification"
    ),
    "python -m pytest 08_Tooling/notion-compute-decision-writer/tests": (
        ROOT / "08_Tooling/notion-compute-decision-writer"
    ),
    "python -m pytest 08_Tooling/notion-operational-guidance-writer/tests": (
        ROOT / "08_Tooling/notion-operational-guidance-writer"
    ),
    "python -m pytest 08_Tooling/reusable-capability-registry/tests": (
        ROOT / "08_Tooling/reusable-capability-registry"
    ),
    "python -m pytest 08_Tooling/visual-asset-drive-writer/tests": (
        ROOT / "08_Tooling/visual-asset-drive-writer"
    ),
    "python -m pytest 08_Tooling/visual-asset-ingestion-coordinator/tests": (
        ROOT / "08_Tooling/visual-asset-ingestion-coordinator"
    ),
    "python -m pytest 08_Tooling/visual-asset-intake/tests": (
        ROOT / "08_Tooling/visual-asset-intake"
    ),
    "python -m pytest 08_Tooling/visual-asset-notion-writer/tests": (
        ROOT / "08_Tooling/visual-asset-notion-writer"
    ),
    "python -m pytest 08_Tooling/visual-asset-routing/tests": (
        ROOT / "08_Tooling/visual-asset-routing"
    ),
}
_PYTHON_FOCUSED_SUITE_DIRS = frozenset(_PYTHON_FOCUSED_SUITE_COMMANDS.values())


def _decode_plan(encoded: str) -> ValidationPlan:
    try:
        raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("validation plan payload is malformed") from exc
    if type(payload) is not dict:
        raise TypeError("validation plan payload must be an object")
    expected = {
        "schema_name",
        "schema_version",
        "selector_version",
        "repository",
        "pull_request",
        "base_sha",
        "head_sha",
        "profile",
        "commands",
        "command_set_digest",
        "reason_codes",
        "remote_build_required",
        "execution_authorized",
        "side_effects_performed",
    }
    if set(payload) != expected:
        raise ValueError("validation plan payload fields do not match canonical schema")
    if payload["execution_authorized"] is not False or payload["side_effects_performed"] is not False:
        raise ValueError("validation plan authority fields must remain false")
    if type(payload["commands"]) is not list or type(payload["reason_codes"]) is not list:
        raise TypeError("validation plan commands and reasons must be lists")
    plan = ValidationPlan(
        selector_version=payload["selector_version"],
        repository=payload["repository"],
        pull_request=payload["pull_request"],
        base_sha=payload["base_sha"],
        head_sha=payload["head_sha"],
        profile=payload["profile"],
        commands=tuple(payload["commands"]),
        command_set_digest=payload["command_set_digest"],
        reason_codes=tuple(payload["reason_codes"]),
        remote_build_required=payload["remote_build_required"],
    )
    reasons = validate_validation_plan(plan)
    if reasons:
        raise ValueError("validation plan failed canonical validation: " + ",".join(reasons))
    return plan


def _current_head() -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout.strip()


def _resolve_command(command: str) -> tuple[tuple[str, ...], Path]:
    suite_dir = _PYTHON_FOCUSED_SUITE_COMMANDS.get(command)
    if suite_dir is not None:
        # Checked before the registry on purpose: the registry binds the
        # canonical root-relative argv, but these suites must execute from
        # their own directory (see _PYTHON_FOCUSED_SUITE_COMMANDS).
        return ("python", "-m", "pytest", "tests"), suite_dir
    argv = _COMMAND_REGISTRY.get(command)
    if argv is not None:
        return argv, ROOT
    if command == _PICTURE_PERFECT_FOCUSED:
        return ("npm", "test", "--", *_PICTURE_PERFECT_TESTS), _PICTURE_PERFECT_DIR
    capture_argv = _CAPTURE_COMMANDS.get(command)
    if capture_argv is not None:
        return capture_argv, _CAPTURE_DIR
    ui_cross_platform_argv = _UI_CROSS_PLATFORM_REFERENCE_COMMANDS.get(command)
    if ui_cross_platform_argv is not None:
        return ui_cross_platform_argv, _UI_CROSS_PLATFORM_REFERENCE_DIR
    teacher_argv = _TEACHER_OS_COMMANDS.get(command)
    if teacher_argv is not None:
        return teacher_argv, _TEACHER_OS_DIR
    if command == _CI_VALIDATION_SELF_TEST:
        return ("python", "-m", "pytest", "tests/test_agent_os_ci_validation.py"), ROOT
    raise ValueError(f"validation command is not in the bounded CI executor: {command}")


def _command_env(cwd: Path) -> dict[str, str]:
    """Supply the repository-root import path the canonical driver already uses.

    ``scripts/validate-all.sh`` runs every root-scoped focused pytest target with
    ``PYTHONPATH=src`` so root suites can import the ``src`` distributions. This
    executor runs the same bounded commands and must resolve imports identically;
    the command text itself stays exactly what the bounded registry owns.
    """
    env = dict(os.environ)
    if cwd != ROOT:
        if cwd in _PYTHON_FOCUSED_SUITE_DIRS and (cwd / "src").is_dir():
            # Suite-local focused execution (see _PYTHON_FOCUSED_SUITE_COMMANDS):
            # mirror validate-all.sh, which runs ``PYTHONPATH=src python -m
            # pytest tests`` inside a suite directory when it has a src/
            # layout. Suites without src/ (dashboard-migration-verification)
            # get no PYTHONPATH addition, exactly as validate-all.sh runs them.
            src_entry = str(cwd / "src")
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = (
                src_entry + os.pathsep + existing if existing else src_entry
            )
        return env
    src_entry = str(ROOT / "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        src_entry + os.pathsep + existing if existing else src_entry
    )
    return env


def _junit_path_for_command(command: str, junit_dir: Path, index: int) -> Path:
    """Unique JUnit path for one bounded command. Index guarantees uniqueness
    even when the same command string appears twice; the sanitized command
    keeps the file name human-readable. Never applied to npm commands."""
    sanitized = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in command.replace("/", "__"))
    return junit_dir / f"{index:02d}_{sanitized}.xml"


def _is_pytest_argv(argv: tuple[str, ...]) -> bool:
    return len(argv) >= 3 and argv[0] in ("python", "python3") and argv[1] == "-m" and argv[2] == "pytest"


def _junit_counts(path: Path, *, check_cases: bool = False) -> dict[str, int] | None:
    """Read JUnit counts; a successful child also needs consistent case nodes."""
    try:
        from xml.etree import ElementTree as _ET

        root = _ET.fromstring(path.read_bytes())
    except (OSError, ValueError, _ET.ParseError):
        return None
    suites = [root] if root.tag == "testsuite" else list(root) if root.tag == "testsuites" else []
    if not suites or any(x.tag != "testsuite" for x in suites):
        return None
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        totals = {}
        try:
            for field in counts:
                raw = suite.attrib.get(field, "")
                if not raw.isascii() or not raw.isdecimal():
                    return None
                totals[field] = int(raw)
        except ValueError:
            return None
        if check_cases:
            observed = dict.fromkeys(counts, 0)
            outcome_fields = {"failure": "failures", "error": "errors", "skipped": "skipped"}
            for case in suite.findall("testcase"):
                if not case.get("name"):
                    return None
                outcomes = [outcome_fields[child.tag] for child in case if child.tag in outcome_fields]
                if len(outcomes) > 1:
                    return None
                observed["tests"] += 1
                if outcomes:
                    observed[outcomes[0]] += 1
            if totals != observed:
                return None
        for field, total in totals.items():
            counts[field] += total
    return counts


def _sha256_file(path: Path) -> str | None:
    try:
        import hashlib as _hashlib

        return _hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _pytest_evidence_error(junit_counts: dict[str, int] | None) -> str | None:
    if junit_counts is None:
        return "pytest exited 0 without fresh, valid, count-consistent JUnit"
    if junit_counts["failures"] or junit_counts["errors"]:
        return "pytest exited 0 but JUnit reports failures or errors"
    if junit_counts["tests"] <= junit_counts["skipped"]:
        return "pytest exited 0 without executing a passing test"
    return None


def execute_focused(plan: ValidationPlan, *, expected_head_sha: str) -> None:
    if plan.profile != "focused":
        raise ValueError("bounded CI executor accepts focused plans only")
    if plan.head_sha != expected_head_sha:
        raise ValueError("validation plan head does not match expected PR head")
    checked_out = _current_head()
    if checked_out != expected_head_sha:
        raise ValueError(
            f"checked-out SHA {checked_out} does not match expected PR head {expected_head_sha}"
        )
    junit_dir_raw = os.environ.get("CI_JUNIT_DIR", "")
    junit_dir = Path(junit_dir_raw).resolve() if junit_dir_raw else None
    private_junit: tempfile.TemporaryDirectory[str] | None = None
    if junit_dir is not None:
        junit_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, str]] = []
    receipt_commands: list[dict] = []
    first_failure: BaseException | None = None
    try:
        for index, command in enumerate(plan.commands):
            try:
                argv, cwd = _resolve_command(command)
            except ValueError as exc:
                # Unresolvable selected command: record it as not executed
                # instead of dropping every later selected command silently.
                manifest.append({"command": command, "classification": "NOT_EXECUTED", "junit_file": ""})
                receipt_commands.append(
                    {
                        "command_id": f"cmd-{index:02d}",
                        "command": command,
                        "argv": [],
                        "cwd": "",
                        "language": "unknown",
                        "exit_code": None,
                        "classification": "NOT_EXECUTED",
                        "junit_file": "",
                        "junit_sha256": None,
                        "junit_counts": None,
                        "error": str(exc),
                    }
                )
                if first_failure is None:
                    first_failure = exc
                continue
            language = "python" if argv and argv[0] in ("python", "python3") else "npm" if argv and argv[0] == "npm" else "other"
            junit_path = None
            run_argv = argv
            code: int | None = None
            error: str | None = None
            evidence_error: str | None = None
            junit_counts = None
            try:
                env = _command_env(cwd)
                if _is_pytest_argv(argv):
                    # Fix the selected command environment, not the parent process.
                    env.pop("PYTEST_ADDOPTS", None)
                    evidence_dir = junit_dir
                    if evidence_dir is None:
                        if private_junit is None:
                            private_junit = tempfile.TemporaryDirectory(prefix="agent-os-focused-")
                        evidence_dir = Path(private_junit.name)
                    junit_path = _junit_path_for_command(command, evidence_dir, index)
                    # A successful no-op may not borrow an earlier report.
                    junit_path.unlink(missing_ok=True)
                    run_argv = (*argv, f"--junitxml={junit_path}", *_PYTEST_EXECUTION_GUARD)
                subprocess.run(run_argv, cwd=cwd, check=True, env=env)
                code = 0
            except subprocess.CalledProcessError as exc:
                code = int(exc.returncode)
                error = str(exc)
            except OSError as exc:
                error = str(exc)
            if junit_path is not None and code is not None:
                junit_counts = _junit_counts(junit_path, check_cases=code == 0)
                if code == 0:
                    evidence_error = _pytest_evidence_error(junit_counts)
                    if evidence_error is not None:
                        error = evidence_error
            if junit_dir is not None:
                if junit_path is not None:
                    if code is None or evidence_error is not None:
                        classification = "NOT_EXECUTED_SETUP_FAILURE"
                    elif code == 0:
                        classification = "EXECUTED_PASS"
                    elif code == 5:
                        classification = "ZERO_COLLECTED"
                    else:
                        classification = "EXECUTED_FAIL"
                    entry = {"command": command, "classification": classification, "junit_file": str(junit_path)}
                elif language == "npm":
                    classification = "EXECUTED_FAIL" if (code is not None and code != 0) or code is None else "NODE_REPORTER_NOT_AVAILABLE"
                    entry = {"command": command, "classification": classification, "junit_file": ""}
                else:
                    classification = "EXECUTED_FAIL" if (code is not None and code != 0) or code is None else "NO_JUNIT_INSTRUMENTATION"
                    entry = {"command": command, "classification": classification, "junit_file": ""}
                manifest.append(entry)
                receipt_commands.append(
                    {
                        "command_id": f"cmd-{index:02d}",
                        "command": command,
                        "argv": list(run_argv),
                        "cwd": str(cwd),
                        "language": language,
                        "exit_code": code,
                        "classification": classification,
                        "junit_file": str(junit_path) if junit_path is not None else "",
                        "junit_sha256": _sha256_file(junit_path) if junit_path is not None and junit_path.is_file() else None,
                        "junit_counts": junit_counts,
                        "error": error,
                    }
                )
            if code is None or code != 0 or evidence_error is not None:
                # Record the first failure, keep executing the remaining
                # selected commands so the receipt covers the whole plan,
                # then fail the step at the end with the first code.
                failure: BaseException
                if code is None:
                    failure = OSError(error or "command could not be executed")
                elif evidence_error is not None:
                    failure = ValueError(evidence_error)
                else:
                    failure = subprocess.CalledProcessError(code, run_argv)
                if first_failure is None:
                    first_failure = failure
    finally:
        if private_junit is not None:
            private_junit.cleanup()
        if junit_dir is not None:
            lines = ["command\tjunit_file\tclassification"]
            for entry in manifest:
                lines.append(f"{entry['command']}\t{entry['junit_file']}\t{entry['classification']}")
            (junit_dir / "manifest.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
            receipt = {
                "schema": "agent-os-ci-command-receipt/1",
                "repository": plan.repository,
                "pull_request": plan.pull_request,
                "head_sha": plan.head_sha,
                "base_sha": plan.base_sha,
                "profile": plan.profile,
                "selector_version": plan.selector_version,
                "command_set_digest": plan.command_set_digest,
                "commands": receipt_commands,
                "selected_count": len(plan.commands),
                "executed_count": sum(1 for c in receipt_commands if c["exit_code"] is not None),
                "note": "Selected-vs-executed receipt only; it is not a merge, Ready, or aggregate decision.",
            }
            (junit_dir / "manifest.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if first_failure is not None:
        raise first_failure


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-base64", required=True)
    parser.add_argument("--expected-head-sha", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    plan = _decode_plan(args.plan_base64)
    execute_focused(plan, expected_head_sha=args.expected_head_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
