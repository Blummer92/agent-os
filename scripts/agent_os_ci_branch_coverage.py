"""Validate the aggregate's bounded branch-coverage reports and emit a receipt."""
import argparse
import hashlib
import json
import os
import stat
import tempfile
import re
from pathlib import Path

SCOPE = Path(__file__).with_name("ci-coverage-suites.tsv")


def load_scope():
    packages = {}
    for line in SCOPE.read_text(encoding="utf-8").splitlines():
        suite, package, display = line.split("\t")
        if (suite in packages or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", suite)
                or not re.fullmatch(r"[a-z][a-z0-9_]*", package)
                or display not in {"term", "term-missing"}):
            raise ValueError("invalid coverage scope")
        packages[suite] = package
    if not packages:
        raise ValueError("empty coverage scope")
    return packages


FLOOR = 80
KEYS = ("covered_lines", "num_statements", "covered_branches", "num_branches")
MAX_REPORT_BYTES = 20 * 1024 * 1024


def _counts(summary):
    if not isinstance(summary, dict):
        raise ValueError
    counts = tuple(summary.get(key) for key in KEYS)
    if any(type(n) is not int or n < 0 for n in counts):
        raise ValueError
    if counts[0] > counts[1] or counts[2] > counts[3]:
        raise ValueError
    return counts


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _raise_walk_error(error):
    raise error


def _source_files(root, suite, package):
    project = root / "08_Tooling" / suite
    paths = set()
    # Unlike Path.rglob, onerror makes an unreadable subtree observable.
    for directory, children, files in os.walk(project / "src" / package, onerror=_raise_walk_error):
        for name in children + files:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError("symlinked coverage source")
            if name.endswith(".py") and stat.S_ISREG(mode):
                paths.add(path.relative_to(project).as_posix())
    if not paths:
        raise ValueError("empty coverage source")
    return paths


def _report(reason=None, **fields):
    return {
        "status": "fail" if reason else "pass", "reason_code": reason,
        "covered": None, "total": None, "tool_version": None, "source_files": None,
        "report_sha256": None, "missing_files": [], "extra_files": [],
        "missing_file_count": 0, "extra_file_count": 0, **fields,
    }


def _measure(path, expected_files):
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_REPORT_BYTES + 1)
        if len(data) > MAX_REPORT_BYTES:
            raise ValueError
        report = json.loads(data, object_pairs_hook=_unique_object)
        meta = report["meta"]
        version = meta["version"]
        if meta["branch_coverage"] is not True or not re.fullmatch(r"[0-9]{1,5}(?:\.[0-9]{1,5}){2}", version):
            raise ValueError
        lines, statements, branches, branch_total = totals = _counts(report["totals"])
        if not statements or not branch_total:
            raise ValueError
        raw = report["files"]
        if not isinstance(raw, dict) or not raw:
            raise ValueError
        if not expected_files or raw.keys() != expected_files:
            missing = sorted(expected_files - raw.keys())
            extra = sorted(raw.keys() - expected_files)
            return _report(
                "coverage-report-file-set-mismatch", missing_files=missing[:100],
                extra_files=extra[:100], missing_file_count=len(missing), extra_file_count=len(extra),
            )
        files = [_counts(item["summary"]) for item in raw.values()]
        if tuple(map(sum, zip(*files))) != totals:
            raise ValueError
    except FileNotFoundError:
        return _report("coverage-report-missing")
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return _report("coverage-report-invalid")

    covered, total = lines + branches, statements + branch_total
    return _report(
        "coverage-below-floor" if covered * 100 < FLOOR * total else None,
        covered=covered, total=total, tool_version=version, source_files=len(expected_files),
        report_sha256=hashlib.sha256(data).hexdigest(),
    )


def _suite_report(directory, name, package):
    try:
        files = _source_files(Path.cwd(), name, package)
    except (OSError, ValueError):
        return _report("coverage-report-invalid")
    return _measure(directory / f"{name}.json", files)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--validation-exit", metavar="0..255")
    args = parser.parse_args()
    raw_exit = args.validation_exit or ""
    validation_exit = int(raw_exit) if re.fullmatch(r"[0-9]{1,3}", raw_exit) else None
    if validation_exit is not None and validation_exit > 255:
        validation_exit = None
    head = os.environ.get("CI_JUNIT_HEAD_SHA", "")
    run = os.environ.get("CI_JUNIT_RUN_ID", "")
    attempt = os.environ.get("CI_JUNIT_RUN_ATTEMPT", "")
    bound = bool(re.fullmatch(r"[a-f0-9]{40}", head) and all(
        re.fullmatch(r"[1-9][0-9]{0,19}", value) for value in (run, attempt)
    ))
    reason = None
    try:
        scope = load_scope()
    except (OSError, ValueError):
        scope = {}
        reason = "coverage-scope-invalid"
    reports = {
        f"{name}.json": _suite_report(args.directory, name, package)
        for name, package in scope.items()
    }
    if not bound:
        reason = "coverage-run-binding-invalid"
    elif validation_exit is None:
        reason = "coverage-validation-exit-invalid"
    elif validation_exit:
        reason = "coverage-validation-failed"
    elif reason is None and any(report["status"] != "pass" for report in reports.values()):
        reason = "coverage-reports-failed"
    passed = reason is None
    receipt = {
        "schema": "agent-os-ci-branch-coverage/1", "status": "pass" if passed else "fail",
        "head_sha": head if bound else None, "run_id": int(run) if bound else None,
        "attempt": int(attempt) if bound else None, "floor": FLOOR, "reports": reports,
        "validation_exit": validation_exit,
        "origin": "local" if os.environ.get("CI_COVERAGE_ORIGIN") == "local" else "hosted",
    }
    receipt["reason_code"] = reason
    try:
        args.directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", dir=args.directory, encoding="utf-8", delete=False
        ) as output:
            path = Path(output.name)
            try:
                output.write(json.dumps(receipt, sort_keys=True) + "\n")
                output.close()
                path.replace(args.directory / "coverage-receipt.json")
            finally:
                path.unlink(missing_ok=True)
    except OSError:
        # A volume that cannot be written cannot hold a receipt. Never
        # certify it; publish a bounded diagnostic to the job log instead.
        print(json.dumps({**receipt, "status": "fail", "reason_code": "coverage-receipt-unwritable"}))
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
