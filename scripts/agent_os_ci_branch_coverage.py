"""Validate the aggregate's bounded branch-coverage reports and emit a receipt."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path

PACKAGES = {
    "workflow-scheduler": "workflow_scheduler",
    "reusable-capability-registry": "reusable_capability_registry",
    "visual-asset-intake": "visual_asset_intake",
}
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


def _source_files(root, suite, package):
    project = root / "08_Tooling" / suite
    return {
        path.relative_to(project).as_posix()
        for path in (project / "src" / package).rglob("*.py")
        if path.is_file()
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
            return {"status": "fail", "reason_code": "coverage-report-file-set-mismatch"}
        files = [_counts(item["summary"]) for item in raw.values()]
        if tuple(map(sum, zip(*files))) != totals:
            raise ValueError
    except FileNotFoundError:
        return {"status": "fail", "reason_code": "coverage-report-missing"}
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return {"status": "fail", "reason_code": "coverage-report-invalid"}

    covered, total = lines + branches, statements + branch_total
    result = {
        "status": "pass", "covered": covered, "total": total,
        "tool_version": version, "source_files": len(expected_files),
        "report_sha256": hashlib.sha256(data).hexdigest(),
    }
    if covered * 100 < FLOOR * total:
        result.update(status="fail", reason_code="coverage-below-floor")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--validation-exit", type=int, required=True, choices=range(256), metavar="0..255")
    args = parser.parse_args()
    head = os.environ.get("CI_JUNIT_HEAD_SHA", "")
    run = os.environ.get("CI_JUNIT_RUN_ID", "")
    attempt = os.environ.get("CI_JUNIT_RUN_ATTEMPT", "")
    bound = bool(re.fullmatch(r"[a-f0-9]{40}", head) and all(
        re.fullmatch(r"[1-9][0-9]{0,19}", value) for value in (run, attempt)
    ))
    reports = {
        f"{name}.json": _measure(
            args.directory / f"{name}.json", _source_files(Path.cwd(), name, package)
        )
        for name, package in PACKAGES.items()
    }
    passed = bound and args.validation_exit == 0 and all(report["status"] == "pass" for report in reports.values())
    receipt = {
        "schema": "agent-os-ci-branch-coverage/1", "status": "pass" if passed else "fail",
        "head_sha": head if bound else None, "run_id": int(run) if bound else None,
        "attempt": int(attempt) if bound else None, "floor": FLOOR, "reports": reports,
        "validation_exit": args.validation_exit,
    }
    if not bound:
        receipt["reason_code"] = "coverage-run-binding-invalid"
    elif args.validation_exit:
        receipt["reason_code"] = "coverage-validation-failed"
    args.directory.mkdir(parents=True, exist_ok=True)
    (args.directory / "coverage-receipt.json").write_text(
        json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
