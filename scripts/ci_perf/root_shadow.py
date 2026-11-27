"""Observe-only root timings. No aggregate verdict or status publication."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from hashlib import sha256
from importlib import metadata
from pathlib import Path, PurePosixPath
from time import monotonic

LANES = 4
SCHEMA = "agent-os-root-shadow/1"
MAX_REPORT = 12 * 1024 * 1024
SELECTED_SLOW_FILES = {
    "tests/test_agent_os_ci_test_completeness.py": 54,
    "tests/agent_os_execution_interface/test_continuation_reachability.py": 28,
    "tests/test_validate_all_runner.py": 25,
    "tests/agent_os_remote_validation/test_issue_2826_continuation_acceptance.py": 19,
    "tests/agent_os_issue_acceptance/test_issue_acceptance_workflow.py": 18,
    "tests/test_build_chatgpt_checkout_package.py": 17,
    "tests/test_3255_candidate_size_limit.py": 16,
    "tests/test_agent_os_ci_nc09_port.py": 15,
}


class Refusal(ValueError):
    """An incomplete shadow experiment, not a merge verdict."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise Refusal(reason)


def tracked_python() -> set[str]:
    raw = subprocess.check_output(["git", "ls-files", "-z", "--", "tests/"], timeout=15)
    return {p for p in raw.decode().split("\0") if p.endswith(".py")}


def module_path(nodeid: str, tracked: set[str]) -> str:
    path = nodeid.split("::", 1)[0]
    bits = PurePosixPath(path).parts
    require(bool(bits) and bits[0] == "tests" and path in tracked, "untracked-collection")
    return path


class Capture:
    def __init__(self) -> None:
        self.items: list[str] = []
        self.skips: list[str] = []

    def pytest_collection_finish(self, session) -> None:
        self.items.extend(item.nodeid for item in session.items)

    def pytest_collectreport(self, report) -> None:
        if report.skipped:
            self.skips.append(report.nodeid)


def partition(paths: Counter[str]) -> list[list[str]]:
    require(len(paths) >= LANES, "insufficient-modules")
    lanes: list[list[str]] = [[] for _ in range(LANES)]
    loads = [0] * LANES

    def weight(p: str) -> int:
        return SELECTED_SLOW_FILES.get(p, 0) * 250 + paths[p] * 2 + 1

    for path in sorted(paths, key=lambda p: (-weight(p), p)):
        lane = min(range(LANES), key=lambda i: (loads[i], len(lanes[i]), i))
        lanes[lane].append(path)
        loads[lane] += weight(path)
    return [sorted(lane) for lane in lanes]


def identity() -> dict[str, str]:
    head = os.environ["SHADOW_HEAD"]
    run = os.environ["GITHUB_RUN_ID"]
    attempt = os.environ["GITHUB_RUN_ATTEMPT"]
    require(bool(re.fullmatch(r"[a-f0-9]{40}", head)), "head-invalid")
    require(all(re.fullmatch(r"[1-9][0-9]{0,19}", x) for x in (run, attempt)), "run-invalid")
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=15)
    require(actual.strip() == head, "checkout-mismatch")
    return {"schema": SCHEMA, "head": head, "run": run, "attempt": attempt}


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def read(path: Path) -> bytes:
    require(path.is_file() and 0 < path.stat().st_size <= MAX_REPORT, "report-missing-or-large")
    with path.open("rb") as fp:
        raw = fp.read(MAX_REPORT + 1)
    require(0 < len(raw) <= MAX_REPORT, "report-missing-or-large")
    return raw


def plan(output: Path, binding: dict[str, str]) -> None:
    import pytest

    tracked = tracked_python()
    capture = Capture()
    start = monotonic()
    code = pytest.main(["tests", "--collect-only", "-q", "-p", "no:cacheprovider"], plugins=[capture])
    require(code == 0 and bool(capture.items), "collection-failed")
    require(len(set(capture.items)) == len(capture.items), "duplicate-collected-id")
    paths = Counter(module_path(n, tracked) for n in capture.items + capture.skips)
    write_json(output, dict(binding, lanes=partition(paths), seconds=round(monotonic() - start, 3)))


def read_plan(path: Path, binding: dict[str, str]) -> list[list[str]]:
    payload = json.loads(read(path))
    require(all(payload.get(k) == v for k, v in binding.items()), "plan-binding-mismatch")
    lanes = payload["lanes"]
    require(type(lanes) is list and len(lanes) == LANES, "invalid-plan")
    tracked = tracked_python()
    combined: set[str] = set()
    for lane in lanes:
        require(type(lane) is list and bool(lane), "invalid-plan")
        for value in lane:
            require(type(value) is str and value not in combined, "invalid-plan")
            require(module_path(value, tracked) == value, "invalid-plan")
            combined.add(value)
    return lanes


def load_junit(raw: bytes) -> dict[tuple[str, str], tuple[str, str, str]]:
    require(b"\x00" not in raw and b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper(),
            "invalid-junit")
    suites = ET.fromstring(raw)
    require(suites.tag == "testsuites" and len(suites) == 1, "invalid-junit")
    suite = suites[0]
    require(suite.tag == "testsuite" and suite.get("errors") == suite.get("failures") == "0", "junit-not-clean")
    result = {}
    for row in suite.findall("testcase"):
        key = (row.get("classname", ""), row.attrib["name"])
        require(bool(key[1]) and key not in result, "duplicate-or-empty-id")
        require(row.find("error") is None and row.find("failure") is None, "junit-not-clean")
        skips = row.findall("skipped")
        require(len(skips) <= 1, "invalid-junit")
        result[key] = ("skip", skips[0].get("type", ""), skips[0].get("message", "")) if skips else ("pass", "", "")
    require(bool(result) and len(result) == int(suite.attrib["tests"]), "junit-count-mismatch")
    require(sum(v[0] == "skip" for v in result.values()) == int(suite.attrib["skipped"]), "junit-count-mismatch")
    return result


def environment_sha256() -> str:
    installed = sorted((d.metadata.get("Name", ""), d.version) for d in metadata.distributions())
    payload = (sys.version, installed)
    return sha256(json.dumps(payload).encode()).hexdigest()


def run_lane(label: str, plan_file: Path, output: Path, binding: dict[str, str]) -> None:
    from scripts.agent_os_ci_junit_subtest_receipt import parse_pytest_summary

    lanes = read_plan(plan_file, binding)
    paths = ["tests"] if label == "serial" else lanes[int(label)]
    output.mkdir()
    junit = output / "root.xml"
    log = output.parent / (label + ".pytest.log")
    cmd = [sys.executable, "-m", "pytest", *paths, f"--junitxml={junit}", "-p", "no:setuponly", "-p", "no:setupplan"]
    start = monotonic()
    with log.open("wb") as fp:
        cp = subprocess.run(cmd, stdout=fp, stderr=subprocess.STDOUT, timeout=1200, check=False)
    code = cp.returncode
    secs = round(monotonic() - start, 3)
    print(f"Shadow root {label}: pytest exit {code}; {secs} s", flush=True)
    require(code == 0, "pytest-failed")
    xml = read(junit)
    load_junit(xml)
    summary = parse_pytest_summary(read(log).decode("utf-8", "replace"))
    subtests = None if summary is None else summary["subtests_passed"]
    write_json(output / "receipt.json", dict(binding, lane=label, seconds=secs,
               plan_sha256=sha256(read(plan_file)).hexdigest(), junit_sha256=sha256(xml).hexdigest(),
               subtests=subtests, environment_sha256=environment_sha256()))


def compare(plan_file: Path, directory: Path, binding: dict[str, str]) -> dict:
    paths = read_plan(plan_file, binding)
    plan_digest = sha256(read(plan_file)).hexdigest()
    outcomes = {}
    receipts = {}
    labels = ["serial", *(str(n) for n in range(LANES))]
    require({p.name for p in directory.iterdir()} == set(labels), "wrong-lane-set")
    for label in labels:
        folder = directory / label
        receipt = json.loads(read(folder / "receipt.json"))
        require(all(receipt.get(k) == v for k, v in binding.items())
                and receipt.get("lane") == label and receipt.get("plan_sha256") == plan_digest, "lane-binding-mismatch")
        raw = read(folder / "root.xml")
        require(receipt.get("junit_sha256") == sha256(raw).hexdigest(), "junit-digest-mismatch")
        subtest_value = receipt["subtests"]
        require(subtest_value is None or (type(subtest_value) is int and subtest_value > 0), "invalid-subtest-count")
        require(bool(re.fullmatch(r"[a-f0-9]{64}", receipt["environment_sha256"])), "invalid-environment")
        duration = receipt.get("seconds")
        require(type(duration) in (float, int) and math.isfinite(duration)
                and duration >= 0, "invalid-duration")
        receipts[label] = receipt
        rows = load_junit(raw)
        if label != "serial":
            modules = {p.removesuffix(".py").replace("/", ".") for p in paths[int(label)]}
            for classname, name in rows:
                owner = classname or name
                if classname:
                    while owner and owner not in modules:
                        owner = owner.rpartition(".")[0]
                require(owner in modules, "wrong-file-assignment")
        outcomes[label] = rows
    require(len({r["environment_sha256"] for r in receipts.values()}) == 1, "lane-environment-mismatch")
    serial = outcomes.pop("serial")
    complete = json.loads(read(directory / "serial" / "completeness.json"))
    require(complete.get("verdict") == "COMPLETE" and complete.get("executed_count") == len(serial)
            and complete.get("missing_count") == 0, "independent-completeness-mismatch")
    groups = {}
    for lane in outcomes.values():
        require(not groups.keys() & lane.keys(), "overlapping-test-id")
        groups.update(lane)
    require(groups == serial, "outcome-parity-mismatch")
    subtests = sum(receipts[label]["subtests"] or 0 for label in outcomes)
    observed = receipts["serial"]["subtests"]
    require((observed or 0) == subtests, "subtest-count-mismatch")
    # When nobody observed a summary, report that limitation, not zero proof.
    return dict(binding, result="root-parity-only", cases=len(serial), passing_subtests=observed,
                serial_pytest_seconds=receipts["serial"]["seconds"],
                slowest_shard_pytest_seconds=max(receipts[k]["seconds"] for k in outcomes))


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("operation", choices=("plan", "run", "compare"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--lane", choices=("serial", "0", "1", "2", "3"))
    args = parser.parse_args()
    try:
        os.environ.pop("PYTEST_ADDOPTS", None)
        os.environ["PYTHONPATH"] = str(Path.cwd() / "src")
        binding = identity()
        if args.operation == "plan":
            plan(args.output, binding)
        elif args.operation == "run":
            require(args.plan is not None and args.lane is not None, "arguments-invalid")
            run_lane(args.lane, args.plan, args.output, binding)
        else:
            require(args.plan is not None, "arguments-invalid")
            print(json.dumps(compare(args.plan, args.output, binding), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, subprocess.SubprocessError, ET.ParseError) as exc:
        message = str(exc) if isinstance(exc, Refusal) else "shadow-evidence-unavailable"
        print(f"Root shadow refused: {message}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
