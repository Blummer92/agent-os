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

Skipped bodies (NC07, hosted 2026-11-08): a ``<testcase>`` with a
``<skipped>`` child is present in the report, so identity reconciliation
passes even though the body never ran. A skipped identity therefore vetoes
``COMPLETE`` unless it is on the committed per-suite skip allowlist
(``agent_os_ci_skipped_allowlist.json`` next to this script), seeded from the
trusted baseline. Identities are compared by base id (parameters stripped),
the same pairing the regenerated-parameter reconciliation uses. A missing
allowlist file means no skip is allowed (any skip vetoes); a malformed file
or an allowlist entry that appears in neither the reference collection nor
the executed report is stale and fails closed with ERROR. A candidate that
rewrites the allowlist to admit its own skip shows up as an explicit,
reviewable allowlist change in the PR diff. The allowlist is a detection
boundary, not adversarial proof: a candidate that edits the check itself
is out of scope here, as for every other runner-owned check.

Independent reference (NC08, hosted 2026-11-08): the reference collection
above loads the suite's ``conftest.py`` files, so a ``collect_ignore`` or a
``pytest_collection_modifyitems`` hook that drops a test narrows the
reference and the real run identically and the check passes. The reference
is therefore collected a second time with ``--noconftest`` and PYTHONPATH
supplied with every src dir a conftest may insert (see
``_NOCONFTEST_PATHS``); the two reference collections must agree on the
multiplicity of each base id (parameters stripped, but individual parameter
cases counted). A hook that drops one parameterized case must fail even when
another parameter of that test remains. Any disagreement — or a failed independent collection
— is ERROR and fails closed. A conftest that only adds markers, registers
fixtures, or inserts a listed src dir collects identically in both runs and
is unaffected. If a new conftest inserts another src dir, the independent
collection fails closed until the dir is added here: a reviewable one-line
change, not a silent pass.

Proven boundary: configuration, plus conftest collection influence via the
independent reference. Plugins loaded only through a conftest are covered the same way. NOT
covered: plugins loaded in both collection paths (e.g. installed entry-point
plugins or plugins loaded by test modules), or a candidate that edits this
check (or its runner) itself; the check is not CI trust certification. Focused runs are explicit selections and are not checked.

Cost: the reference collection runs twice per suite (root ~+15s measured;
all other suites add <=3s each).

NC09: failed or errored executed JUnit outcomes veto a pass, even when pytest's
exit status was swallowed. This check uses the same XML bytes as NC07.

Exit codes: 0 COMPLETE, 1 INCOMPLETE or OUTCOME_FAILED, 2 ERROR.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path

from agent_os_ci_junit_diff import junit_outcomes, node_ids, skipped_node_ids

SCHEMA = "agent-os-ci-test-completeness/1"
SKIP_ALLOWLIST_SCHEMA = "agent-os-ci-skipped-allowlist/1"
SKIP_ALLOWLIST_FILENAME = "agent_os_ci_skipped_allowlist.json"
_NODE_LINE = re.compile(r"^\S+?\.py::.+$")
# pytest's default test-discovery settings; the reference never reads the candidate's.
_NORECURSE_DEFAULT = [".*", "build", "dist", "CVS", "_darcs", "{arch}", "*.egg", "venv", "node_modules"]
# Intentional exclusions the repo relies on (validation fixtures are example test files).
_NORECURSE_ALLOWLIST = {"08_Tooling/reusable-capability-registry": ["fixtures", "__pycache__"]}
# Src dirs a conftest.py may insert into sys.path that no installed
# distribution provides (requirements-dev.txt installs -e ./src,
# -e ./08_Tooling/agent-memory-context-manager,
# -e ./08_Tooling/reusable-capability-registry[test],
# -e ./08_Tooling/workflow-scheduler and -e ./08_Tooling/visual-asset-intake;
# the CI workflow additionally installs the IMC and notion-client test
# extras). The repo root itself is NOT listed: pytest's basedir insertion
# supplies it (tests/__init__.py exists), so a --noconftest collection still
# resolves repo-root imports; if tests/__init__.py is ever removed, the
# independent collection fails closed until the root is added here.
# The --noconftest reference collection loads no conftest, so the runner
# supplies these explicitly; entries that do not exist are harmless to
# PYTHONPATH. A new conftest src insert must be added here or the
# independent collection fails closed (ERROR) — a reviewable one-line change.
_NOCONFTEST_PATHS = (
    "src",
    "08_Tooling/agent-os-execution-service/src",
    "08_Tooling/agent-os-execution-service",
    "08_Tooling/workflow-scheduler/src",
    "08_Tooling/visual-asset-ingestion-coordinator/src",
    "08_Tooling/visual-asset-drive-writer/src",
    "08_Tooling/visual-asset-notion-writer/src",
)
_MISSING_CAP = 100


def _identity(nodeid: str) -> str:
    """Node id as pytest's JUnit writer names it: ``a/b.py::T::t[p]`` -> ``a.b.T::t[p]``."""
    path, bracket, params = nodeid.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += bracket + params
    return ".".join(names[:-1]) + "::" + names[-1]


def _base_id(nodeid: str) -> str:
    """Identity without regenerated ``[params]`` for reference counts and skips."""
    return nodeid.split("[", 1)[0]


def _reference_counts(output: str) -> Counter[str]:
    """Count cases per base id: dropping one parameter must change the reference."""
    return Counter(_base_id(line) for line in output.splitlines() if _NODE_LINE.match(line))


def _load_skip_allowlist(path: Path) -> dict[str, list[str]]:
    """Committed per-suite skip allowlist: ``{"schema": ..., "suites": {...}}``.

    A missing file is NOT an error: it means no skip is allowed (the caller
    treats it as an empty allowlist), so fixture repositories that never
    exercise skips need no allowlist file. A present but malformed file
    fails closed. ``FileNotFoundError`` propagates so the caller can tell
    the two cases apart.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, ValueError) as exc:
        raise ValueError(f"skip allowlist unreadable: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != SKIP_ALLOWLIST_SCHEMA:
        raise ValueError(f"skip allowlist schema must be {SKIP_ALLOWLIST_SCHEMA}")
    suites = payload.get("suites")
    if not isinstance(suites, dict):
        raise ValueError("skip allowlist 'suites' must be an object")
    out: dict[str, list[str]] = {}
    for suite, entries in suites.items():
        if not isinstance(suite, str) or not isinstance(entries, list) or not all(
            isinstance(entry, str) for entry in entries
        ):
            raise ValueError("skip allowlist entries must be lists of identity strings")
        out[suite] = list(entries)
    return out


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
    python_bin: str,
    suite_dir: Path,
    suite_name: str,
    junit: Path,
    *,
    timeout: int = 300,
    skip_allowlist: Path | None = None,
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
        "skipped_count": 0,
        "skipped_allowlisted": [],
        "skipped_mandatory": [],
        "skip_allowlist_stale": [],
        "skip_allowlist_missing": False,
        "outcome": None,
        "reference_noconftest_command": None,
        "reference_noconftest_returncode": None,
        "reference_noconftest_count": None,
        "reference_only": [],
        "reference_noconftest_only": [],
    }
    env = {key: value for key, value in os.environ.items() if key != "PYTEST_ADDOPTS"}
    if skip_allowlist is None:
        skip_allowlist = Path(__file__).resolve().parent / SKIP_ALLOWLIST_FILENAME
    try:
        allowlisted = {_base_id(entry) for entry in _load_skip_allowlist(skip_allowlist).get(suite_name, [])}
    except FileNotFoundError:
        # No allowlist file: no skip is allowed. Fixture repositories that
        # never exercise skips need no file; a real skip without one vetoes.
        result["skip_allowlist_missing"] = True
        allowlisted = set()
    except ValueError as exc:
        result["error"] = str(exc)
        return result
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
    # Independent reference (NC08): the same collection with no conftest
    # loaded. A hook that narrows collection identically for both runs shows
    # up here as a disagreement between the two reference sets.
    repo_root = Path(__file__).resolve().parents[1]
    noconftest_env = dict(env)
    noconftest_paths = [str(repo_root / rel) for rel in _NOCONFTEST_PATHS]
    if noconftest_env.get("PYTHONPATH"):
        noconftest_paths.append(noconftest_env["PYTHONPATH"])
    noconftest_env["PYTHONPATH"] = os.pathsep.join(noconftest_paths)
    noconftest_argv = argv + ["--noconftest"]
    result["reference_noconftest_command"] = " ".join(noconftest_argv)
    try:
        noconftest_proc = subprocess.run(
            noconftest_argv,
            cwd=suite_dir,
            env=noconftest_env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["error"] = f"independent reference collection did not run: {exc}"
        return result
    result["reference_noconftest_returncode"] = noconftest_proc.returncode
    if noconftest_proc.returncode != 0:
        tail = (noconftest_proc.stdout + noconftest_proc.stderr)[-500:].strip()
        result["error"] = (
            f"independent reference collection exited {noconftest_proc.returncode} "
            f"(no conftest loaded; a new conftest src insert may need adding to "
            f"_NOCONFTEST_PATHS); completeness cannot be established: {tail}"
        )
        return result
    expected_counts = _reference_counts(proc.stdout)
    independent_counts = _reference_counts(noconftest_proc.stdout)
    result["reference_noconftest_count"] = sum(independent_counts.values())
    # Counter subtraction preserves parameter-case multiplicity; sets would
    # hide a single missing case whenever its base test still has other cases.
    only_reference = sorted((expected_counts - independent_counts).elements())
    only_independent = sorted((independent_counts - expected_counts).elements())
    result["reference_only"] = only_reference[:_MISSING_CAP]
    result["reference_noconftest_only"] = only_independent[:_MISSING_CAP]
    if only_reference or only_independent:
        result["error"] = (
            "reference collections disagree: the conftest-loaded collection and the "
            f"independent (--noconftest) collection differ by {len(only_reference)} "
            f"test(s) only in the reference and {len(only_independent)} only in the "
            "independent collection; a conftest hook is narrowing or mutating "
            f"collection: {', '.join((only_reference + only_independent)[:5])}"
        )
        return result
    try:
        junit_bytes = junit.read_bytes()
    except OSError as exc:
        result["error"] = f"executed JUnit report rejected: {exc}"
        return result
    try:
        executed = node_ids(junit_bytes)
        skipped = skipped_node_ids(junit_bytes)
        outcome = junit_outcomes(junit_bytes)
    except ValueError as exc:
        result["error"] = f"executed JUnit report rejected: {exc}"
        return result
    result["outcome"] = outcome
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
    # NC07 skip veto, by base id: a skipped body never ran, so it is an
    # omission unless the committed allowlist names it. An allowlist entry
    # in neither the reference collection nor the executed report is stale
    # (a deleted test must leave the allowlist with it); collection-skipped
    # modules appear in the report but not the reference, so both sides count.
    skipped_base = {_base_id(node) for node in skipped}
    expected_base = {_base_id(node) for node in expected}
    executed_base = {_base_id(node) for node in executed}
    mandatory = sorted(skipped_base - allowlisted)
    stale = sorted(allowlisted - expected_base - executed_base)
    result["skipped_count"] = len(skipped_base)
    result["skipped_allowlisted"] = sorted(skipped_base & allowlisted)[:_MISSING_CAP]
    result["skipped_mandatory"] = mandatory[:_MISSING_CAP]
    result["skip_allowlist_stale"] = stale[:_MISSING_CAP]
    # Verdict precedence: ERROR > OUTCOME_FAILED > INCOMPLETE > COMPLETE.
    errors: list[str] = []
    if stale:
        result["verdict"] = "ERROR"
        result["error"] = (
            f"{len(stale)} skip-allowlist entr(ies) are in neither the reference "
            f"collection nor the executed report: {', '.join(stale[:5])}"
        )
        return result
    if outcome["failures"] or outcome["errors"]:
        result["verdict"] = "OUTCOME_FAILED"
        result["error"] = (
            f"executed JUnit contains {outcome['failures']} failure(s) and "
            f"{outcome['errors']} error(s); outcome vetoes runner exit 0"
        )
        return result
    if unpaired:
        errors.append(
            f"{result['missing_count']} test(s) in the reference collection were not "
            "executed by the suite run; test selection is narrowed or execution suppressed"
        )
    if mandatory:
        errors.append(
            f"{len(mandatory)} test(s) were skipped but are not in the skip allowlist; "
            f"a skipped test body is not an executed test: {', '.join(mandatory[:5])}"
        )
    if errors:
        result["verdict"] = "INCOMPLETE"
        result["error"] = "; ".join(errors)
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
    parser.add_argument("--skip-allowlist", type=Path, default=None)
    args = parser.parse_args(argv)
    result = check_suite(
        args.python_bin,
        args.suite_dir,
        args.suite_name,
        args.junit,
        timeout=args.timeout,
        skip_allowlist=args.skip_allowlist,
    )
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.receipt is not None:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(text, encoding="utf-8")
    print(text, end="")
    return {"COMPLETE": 0, "INCOMPLETE": 1, "OUTCOME_FAILED": 1, "ERROR": 2}[result["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
