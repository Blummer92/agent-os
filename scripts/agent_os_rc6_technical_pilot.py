#!/usr/bin/env python3
"""Run the frozen, read-only RC6 T01-T24 technical pilot."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.agent_os_rc6_pilot_support import (
    AUTH_EVIDENCE, EXPECTED_IDS, FROZEN_SHA, PilotContractError, evidence,
    load_api, load_package, validate_package, verify_baseline,
)

load_frozen_package = load_package
validate_frozen_package = validate_package
_load_interfaces = load_api
verify_frozen_baseline = verify_baseline

DEFAULT_FIXTURE = Path("tests/fixtures/rc6_technical_pilot/frozen_package.json")
DEFAULT_OUTPUT = Path("artifacts/rc6-technical-pilot")


@dataclass(frozen=True)
class PilotRun:
    payload: dict[str, Any]
    json_text: str
    markdown_text: str
    exit_code: int


def _provenance(results: list[Any], report: Any, api: Any) -> str:
    valid = [item for item in results if isinstance(item, api.DiscoveryResult)]
    if not valid:
        return "absent" if not results else "not-interpreted"
    if not isinstance(report, api.ValidationReport):
        return "not-interpreted"
    values = {item.provenance for item in valid}
    if len(values) != 1:
        return "mismatch"
    discovery, validation = next(iter(values)), report.provenance
    if discovery is None or validation is None:
        return "missing"
    if discovery != validation:
        return "mismatch"
    return "matched" if discovery.is_supported else "unsupported"


def _summarize(case: dict[str, Any], base: Any, results: list[Any], report: Any, attached: Any, rendered: str, api: Any) -> dict[str, Any]:
    valid = [item for item in results if isinstance(item, api.DiscoveryResult)]
    candidates = [{
        "capability_id": item.capability.capability_id,
        "confidence": item.confidence.value,
        "evidence_basis": list(item.evidence_basis),
    } for item in valid]
    ids = {item.capability.capability_id for item in valid}
    if isinstance(report, api.ValidationReport):
        findings = [item for item in report.findings if item.capability_id in ids]
        rank = {"pass": 0, "warn": 1, "manual-review": 2, "fail": 3}
        severity = max((item.severity.value for item in findings), key=rank.get, default="pass")
        codes = sorted(item.code for item in findings)
    else:
        severity, codes = "invalid", []
    info = list(attached.report.informational_checks)
    statuses, names = [item.status.value for item in info], [item.name for item in info]
    lines = [line for item in info for line in item.evidence]
    positive = any(item.status.value in {"pass", "warn"} and item.name.startswith("reuse candidate") for item in info)
    if not info:
        disposition = "identity-no-informational-section"
    elif names == ["reuse-evidence-error"]:
        disposition = "reuse-evidence-error"
    elif case["scenario"] == "future_validation_code" and any("future.surface-check" in line for line in lines):
        disposition = "unknown-evidence-preserved"
    elif positive and any("remaining_risk=behavioral-contract-not-evaluated" in line for line in lines):
        disposition = "positive-with-explicit-residual-risk"
    elif any(status in {"manual-review", "fail"} for status in statuses):
        disposition = "positive-guidance-suppressed"
    elif "warn" in statuses:
        disposition = "qualified-positive"
    else:
        disposition = "positive-informational"
    return {
        "case_id": case["case_id"], "rc3_results": candidates,
        "rc3_warnings": sorted({warning for item in valid for warning in item.warnings}),
        "rc3_manual_review_reasons": sorted({reason for item in valid for reason in item.manual_review_reasons}),
        "rc4_severity": severity, "rc4_finding_codes": codes,
        "provenance_interpretation": _provenance(results, report, api),
        "rc5_informational_statuses": statuses, "rc5_check_names": names,
        "rc5_evidence": lines, "rc5_evidence_disposition": disposition,
        "base_readiness_before": base.outcome.value, "base_readiness_after": attached.outcome.value,
        "implementation_authorization": "not-authorized",
        "repository_write_authorization": "not-authorized", "merge_authorization": "not-authorized",
        "automatic_selection": False, "positive_guidance": positive, "rendered_report": rendered,
    }


def _compare(case: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    expected, failures = case["expected"], []
    fields = (
        "rc3_results", "rc3_warnings", "rc3_manual_review_reasons", "rc4_severity",
        "rc4_finding_codes", "provenance_interpretation", "rc5_informational_statuses",
        "rc5_evidence_disposition", "base_readiness_before", "base_readiness_after",
        "implementation_authorization", "repository_write_authorization",
        "merge_authorization", "automatic_selection",
    )
    for field in fields:
        if actual[field] != expected[field]:
            failures.append(f"{field}: expected {expected[field]!r}, got {actual[field]!r}")
    for value in expected.get("required_rc5_evidence", []):
        if not any(value in line for line in actual["rc5_evidence"]):
            failures.append(f"required RC5 evidence missing: {value}")
    for value in expected.get("required_check_names", []):
        if value not in actual["rc5_check_names"]:
            failures.append(f"required RC5 check missing: {value}")
    if actual["base_readiness_before"] != actual["base_readiness_after"]:
        failures.append("RC5 changed base readiness")
    if actual["rc5_check_names"] and "reuse-evidence-error" not in actual["rc5_check_names"] and AUTH_EVIDENCE not in actual["rc5_evidence"]:
        failures.append("authorization-boundary evidence missing")
    return failures


def _once(case: dict[str, Any], root: Path, api: Any) -> tuple[dict[str, Any], str]:
    base, results, report, attached, resources = evidence(case, root, api)
    rendered = api.render_report(attached.report)
    summary = _summarize(case, base, results, report, attached, rendered, api)
    for resource in resources:
        resource.cleanup()
    return summary, rendered


def _thresholds(package: dict[str, Any], actuals: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id, source = {item["case_id"]: item for item in actuals}, package["thresholds"]
    unsafe = source["false_positive"]["cases"]
    clean = source["false_negative"]["denominator"]
    all_values = list(by_id.values())
    metrics = {
        "false_positive": [sum(by_id[c]["positive_guidance"] for c in unsafe), len(unsafe), 0],
        "false_negative": [sum(not by_id[c]["positive_guidance"] for c in clean), len(clean), 0],
        "unexpected_manual_review": [sum("manual-review" in by_id[c]["rc5_informational_statuses"] for c in clean), len(clean), 0],
        "false_implementation_authorization": [sum(x["implementation_authorization"] != "not-authorized" for x in all_values), 24, 0],
        "false_repository_write_authorization": [sum(x["repository_write_authorization"] != "not-authorized" for x in all_values), 24, 0],
        "false_merge_authorization": [sum(x["merge_authorization"] != "not-authorized" for x in all_values), 24, 0],
        "silent_automatic_selection": [int(by_id["T05"]["automatic_selection"]), 1, 0],
        "contradicted_evidence_positive": [int(by_id["T12"]["positive_guidance"]), 1, 0],
        "missing_active_path_positive": [int(by_id["T15"]["positive_guidance"]), 1, 0],
    }
    output = {name: {"numerator": a, "denominator": b, "limit": limit, "passed": a <= limit} for name, (a, b, limit) in metrics.items()}
    deterministic = sum(item["deterministic"] for item in all_values)
    output["deterministic_repeated_output"] = {"numerator": deterministic, "denominator": 24, "required": 24, "passed": deterministic == 24}
    reviewed = int(any("consumer_exemption=" in line for line in by_id["T13"]["rc5_evidence"]))
    output["active_exemptions_reviewed"] = {"numerator": reviewed, "denominator": 1, "required_percent": 100, "percent": 100 * reviewed, "passed": reviewed == 1}
    return output


def _markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# RC6 Technical Pilot", "", f"- Tested SHA: `{payload['tested_sha']}`",
        f"- Package: `{payload['package_version']}`",
        f"- Cases: {summary['passed_cases']}/{summary['total_cases']} passed",
        f"- Deterministic: {summary['deterministic_cases']}/{summary['total_cases']}",
        f"- Overall result: **{summary['result'].upper()}**", "", "## Thresholds", "",
        "| Metric | Result | Observed | Required |", "|---|---:|---:|---:|",
    ]
    for name, metric in payload["thresholds"].items():
        required = f"<= {metric['limit']}" if "limit" in metric else (f"= {metric['required']}" if "required" in metric else f"= {metric['required_percent']}%")
        lines.append(f"| `{name}` | {'pass' if metric['passed'] else 'fail'} | {metric['numerator']}/{metric['denominator']} | {required} |")
    lines += ["", "## Cases", "", "| Case | Result | RC3 | RC4 | RC5 | Readiness |", "|---|---:|---|---|---|---|"]
    for item in payload["cases"]:
        actual = item["actual"]
        rc3 = ", ".join(value["capability_id"] for value in actual["rc3_results"]) or "none"
        rc5 = ", ".join(actual["rc5_informational_statuses"]) or "none"
        ready = f"{actual['base_readiness_before']} -> {actual['base_readiness_after']}"
        lines.append(f"| {item['case_id']} | {'pass' if item['passed'] else 'fail'} | {rc3} | {actual['rc4_severity']} | {rc5} | {ready} |")
        lines += [f"\n- **{item['case_id']} failure:** {failure}" for failure in item["failures"]]
    lines += ["", "## Authorization Boundary", "", "This report is evidence only. It does not authorize implementation, repository writes, readiness changes, or merge.", ""]
    return "\n".join(lines)


def run_pilot(fixture: str | Path, repository_root: str | Path, tested_sha: str, verify_head: bool = True) -> PilotRun:
    package = load_package(fixture)
    if tested_sha != FROZEN_SHA:
        raise PilotContractError(f"tested SHA must be {FROZEN_SHA}")
    root, api = Path(repository_root).resolve(), load_api(Path(repository_root).resolve())
    verify_baseline(root, package, tested_sha, api, verify_head)
    cases = []
    for case in package["cases"]:
        first, render_1 = _once(case, root, api)
        second, render_2 = _once(case, root, api)
        deterministic = first == second and render_1.encode() == render_2.encode()
        failures = _compare(case, first)
        if not deterministic:
            failures.append("repeated output is not byte-identical")
        actual = {key: value for key, value in first.items() if key != "rendered_report"}
        actual.update({
            "deterministic": deterministic,
            "repeat_output_digest_1": hashlib.sha256(render_1.encode()).hexdigest(),
            "repeat_output_digest_2": hashlib.sha256(render_2.encode()).hexdigest(),
        })
        cases.append({"case_id": case["case_id"], "title": case["title"], "passed": not failures, "failures": failures, "actual": actual})
    thresholds = _thresholds(package, [case["actual"] for case in cases])
    passed, deterministic = sum(case["passed"] for case in cases), sum(case["actual"]["deterministic"] for case in cases)
    ok = passed == 24 and deterministic == 24 and all(item["passed"] for item in thresholds.values())
    payload = {
        "report_version": "1.0", "package_version": package["package_version"], "tested_sha": tested_sha,
        "summary": {"result": "pass" if ok else "fail", "total_cases": 24, "passed_cases": passed, "failed_cases": 24 - passed, "deterministic_cases": deterministic, "thresholds_passed": all(item["passed"] for item in thresholds.values())},
        "thresholds": thresholds, "cases": cases,
        "authorization": {"implementation": "not-authorized", "repository_writes": "not-authorized", "merge": "not-authorized"},
    }
    return PilotRun(payload, json.dumps(payload, sort_keys=True, indent=2) + "\n", _markdown(payload), 0 if ok else 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--tested-sha", required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        run = run_pilot(args.fixture, args.repository_root, args.tested_sha)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "rc6-technical-pilot.json").write_text(run.json_text, encoding="utf-8")
        (args.output_dir / "rc6-technical-pilot.md").write_text(run.markdown_text, encoding="utf-8")
        print(run.markdown_text, end="")
        return run.exit_code
    except PilotContractError as exc:
        print(f"RC6 technical pilot contract error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"RC6 technical pilot execution error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
