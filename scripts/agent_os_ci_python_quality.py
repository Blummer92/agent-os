"""Run bounded Python quality checks without granting aggregate or deletion authority."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCOPE = "08_Tooling/visual-asset-intake/src/visual_asset_intake"
CONFIG = "scripts/ci-python-quality.toml"
REQUIREMENTS = "scripts/ci-python-quality-requirements.txt"
CHECKS = {
    "black": (1, ("--check", "--no-cache")),
    "mypy": (1, ("--no-incremental", "--cache-dir", os.devnull)),
    "vulture": (3, ()),
}
MAX_LOG_BYTES = 262_144


def run_check(tool: str, expected_version: str, sources: list[str]) -> dict:
    result = {
        "expected_version": expected_version,
        "version": None,
        "exit_code": None,
        "status": "scanner-error",
        "reason_code": "dependency-missing",
        "diagnostics": "",
    }
    try:
        result["version"] = importlib.metadata.version(tool)
    except importlib.metadata.PackageNotFoundError:
        return result
    if result["version"] != expected_version:
        return dict(result, reason_code="dependency-version-mismatch")

    findings_exit, args = CHECKS[tool]
    config_flag = "--config-file" if tool == "mypy" else "--config"
    command = [sys.executable, "-I", "-m", tool, *args, config_flag, CONFIG, *sources]
    cfg_overrides = {"BLACK_CACHE_DIR", "MYPY_CACHE_DIR", "MYPYPATH"}
    env = {key: value for key, value in os.environ.items() if key not in cfg_overrides}
    try:
        with tempfile.TemporaryFile() as log:
            ran = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=60, check=False)
            log.seek(0)
            diagnostics = log.read(MAX_LOG_BYTES + 1)
    except subprocess.TimeoutExpired:
        return dict(result, reason_code="scanner-timeout")
    except OSError:
        return dict(result, reason_code="scanner-launch-failed")

    result["exit_code"] = ran.returncode
    if len(diagnostics) > MAX_LOG_BYTES:
        return dict(result, reason_code="scanner-output-too-large")
    result["diagnostics"] = diagnostics.decode("utf-8", errors="replace")
    if ran.returncode == 0:
        return dict(result, status="clean", reason_code=None)
    findings_marker = {"black": "would reformat ", "mypy": ": error: ", "vulture": "% confidence)"}
    if ran.returncode == findings_exit and findings_marker[tool] in result["diagnostics"]:
        return dict(result, status="findings", reason_code=None)
    return dict(result, reason_code="scanner-exit-unexpected")


def build_report(head: str, run_id: int, attempt: int) -> dict:
    report = {
        "schema": "agent-os-ci-python-quality/1",
        "head_sha": head,
        "run_id": run_id,
        "attempt": attempt,
        "scope": SCOPE,
        "status": "scanner-error",
        "reason_code": "invalid-checkout",
        "sources": [],
        "tools": {},
    }
    try:
        observed = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=10).strip()
        if observed != head:
            return report
        inputs = [SCOPE, CONFIG, REQUIREMENTS]
        diff = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", *inputs], check=False, timeout=10
        )
        raw = subprocess.check_output(["git", "ls-files", "-z", "--", *inputs], timeout=10)
        tracked = set(raw.decode("utf-8").split("\0"))
        if not {CONFIG, REQUIREMENTS} <= tracked:
            return dict(report, reason_code="tool-config-invalid")
        sources = sorted(path for path in tracked if path.endswith(".py"))
        if not sources or any(
            not Path(path).is_file() or Path(path).resolve() != Path(path).absolute()
            for path in sources
        ):
            return dict(report, reason_code="scope-missing-or-invalid")
        if diff.returncode:
            return dict(report, reason_code="checkout-inputs-changed")
        report["sources"] = sources
    except (OSError, ValueError, subprocess.SubprocessError):
        return report
    try:
        lines = Path(REQUIREMENTS).read_text(encoding="utf-8").splitlines()
        pairs = [line.split("==") for line in lines if line]
        pins = dict(pairs)
        if len(pins) != len(pairs) or not Path(CONFIG).is_file() or any(
            not pins.get(tool) for tool in CHECKS
        ):
            raise ValueError("missing or duplicate scanner pins or config")
    except (OSError, ValueError):
        return dict(report, reason_code="tool-config-invalid")
    report["tools"] = {tool: run_check(tool, pins[tool], sources) for tool in CHECKS}
    statuses = {item["status"] for item in report["tools"].values()}
    if "scanner-error" in statuses:
        return dict(report, reason_code="scanner-error")
    return dict(report, status="findings" if "findings" in statuses else "clean", reason_code=None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--head", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.head) or min(args.run_id, args.attempt) <= 0:
        parser.error("head, run ID, and attempt must be valid")
    args.output.mkdir(parents=True, exist_ok=True)
    report = build_report(args.head, args.run_id, args.attempt)
    with (args.output / "python-quality.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    for tool, result in report["tools"].items():
        print(f"{tool}: {result['status']}")
    print(f"Python quality: {report['status']}")
    return int(report["status"] == "scanner-error")


if __name__ == "__main__":
    raise SystemExit(main())
