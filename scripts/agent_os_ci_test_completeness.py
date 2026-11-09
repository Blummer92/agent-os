"""Reconcile a suite's executed JUnit against a runner-owned reference collection.

Why (PR #3816, run 42395721554): ``--deselect`` in ``pytest.ini`` addopts let
the authoritative aggregate pass while the regression tests never ran,
because ``validate-all.sh`` treated "pytest exit 0 and a JUnit file exists"
as ``EXECUTED_PASS``. A suite that passes must also have *executed* every
test the repository defines.

How: after a suite passes, collect the tests once with options the runner
owns -- ``addopts`` emptied and every discovery option reset to pytest's
defaults, so no candidate config file can narrow or suppress the reference --
and require each reference test to appear as a ``<testcase>`` in the suite's
real JUnit report (read with ``agent_os_ci_junit_diff.node_ids``). The
reference collection must exit 0: a collection error that the candidate
hides (``--ignore``, ``norecursedirs``) fails it, so hidden broken modules
are caught too. Tests whose parameters are regenerated on every collection
(``secrets.token_urlsafe``) are paired by base id.

``validate-all.sh`` also runs suites with ``-p no:setuponly -p no:setupplan``
so pytest itself rejects ``--setup-only`` / ``--setup-plan`` (which write
passing-looking JUnit without running test bodies) from any config source.
``--collect-only`` writes no ``<testcase>`` and fails reconciliation.

Proven boundary: configuration. NOT covered: ``conftest.py`` and plugins that
narrow or mutate collection identically for the reference and the real run
(``collect_ignore``, ``pytest_collection_modifyitems``,
``pytest_ignore_collect``); the check is not CI trust certification. Focused
runs are explicit selections and are not checked.

Exit codes: 0 COMPLETE, 1 INCOMPLETE, 2 ERROR (comparison not established).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path

from agent_os_ci_junit_diff import node_ids

SCHEMA = "agent-os-ci-test-completeness/1"
_NODE_LINE = re.compile(r"^\S+?\.py::.+$")
# pytest's default test-discovery settings; the reference never reads the candidate's.
_NORECURSE_DEFAULT = [".*", "build", "dist", "CVS", "_darcs", "{arch}", "*.egg", "venv", "node_modules"]
# Intentional exclusions the repo relies on (validation fixtures are example test files).
_NORECURSE_ALLOWLIST = {"08_Tooling/reusable-capability-registry": ["fixtures", "__pycache__"]}
_MISSING_CAP = 100


def _identity(nodeid: str) -> str:
    """Node id as pytest's JUnit writer names it: ``a/b.py::T::t[p]`` -> ``a.b.T::t[p]``."""
    path, bracket, params = nodeid.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += bracket + params
    return ".".join(names[:-1]) + "::" + names[-1]


def reference_argv(python_bin: str, suite_name: str) -> list[str]:
    norecurse = _NORECURSE_DEFAULT + _NORECURSE_ALLOWLIST.get(suite_name, [])
    resets = [
        "addopts=",
        "python_files=test_*.py *_test.py",
        "python_classes=Test*",
        "python_functions=test_*",
        "collect_imported_tests=true",
        "norecursedirs=" + " ".join(norecurse),
    ]
    argv = [python_bin, "-m", "pytest", "tests", "--collect-only", "-q", "-p", "no:cacheprovider"]
    for reset in resets:
        argv += ["-o", reset]
    return argv


def check_suite(
    python_bin: str, suite_dir: Path, suite_name: str, junit: Path, *, timeout: int = 300
) -> dict:
    argv = reference_argv(python_bin, suite_name)
    result: dict = {
        "schema": SCHEMA,
        "suite_name": suite_name,
        "verdict": "ERROR",
        "error": None,
        "reference_command": " ".join(argv),
        "reference_returncode": None,
        "expected_count": None,
        "executed_count": None,
        "missing_count": 0,
        "missing": [],
        "regenerated_param_count": 0,
    }
    env = {key: value for key, value in os.environ.items() if key != "PYTEST_ADDOPTS"}
    try:
        proc = subprocess.run(
            argv, cwd=suite_dir, env=env, text=True, capture_output=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["error"] = f"reference collection did not run: {exc}"
        return result
    result["reference_returncode"] = proc.returncode
    if proc.returncode != 0:
        tail = (proc.stdout + proc.stderr)[-500:].strip()
        result["error"] = (
            f"reference collection exited {proc.returncode} (collection error, hidden broken "
            f"module, or unreadable config); completeness cannot be established: {tail}"
        )
        return result
    try:
        executed = node_ids(junit.read_bytes())
    except (OSError, ValueError) as exc:
        result["error"] = f"executed JUnit report rejected: {exc}"
        return result
    expected = {_identity(line) for line in proc.stdout.splitlines() if _NODE_LINE.match(line)}
    missing, extra = sorted(expected - executed), sorted(executed - expected)
    # A reference test missing from the report is only explained by an executed test
    # on the same base id (regenerated parameter), counted one for one.
    gone = Counter(node.split("[", 1)[0] for node in missing)
    new = Counter(node.split("[", 1)[0] for node in extra)
    unpaired = {base: count - new[base] for base, count in gone.items() if count > new[base]}
    omitted = [node for node in missing if node.split("[", 1)[0] in unpaired]
    result.update(
        expected_count=len(expected),
        executed_count=len(executed),
        missing_count=sum(unpaired.values()),
        missing=omitted[:_MISSING_CAP],
        regenerated_param_count=len(missing) - sum(unpaired.values()),
    )
    if unpaired:
        result["verdict"] = "INCOMPLETE"
        result["error"] = (
            f"{result['missing_count']} test(s) in the reference collection were not "
            "executed by the suite run; test selection is narrowed or execution suppressed"
        )
    else:
        result["verdict"] = "COMPLETE"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", required=True, type=Path)
    parser.add_argument("--suite-name", required=True)
    parser.add_argument("--junit", required=True, type=Path)
    parser.add_argument("--python-bin", default="python3")
    parser.add_argument("--receipt", type=Path, default=None)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)
    result = check_suite(
        args.python_bin, args.suite_dir, args.suite_name, args.junit, timeout=args.timeout
    )
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.receipt is not None:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(text, encoding="utf-8")
    print(text, end="")
    return {"COMPLETE": 0, "INCOMPLETE": 1, "ERROR": 2}[result["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
