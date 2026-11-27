"""Check pinned Black on tracked Intake sources; never publish GitHub status."""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

VERSION = "26.10.0"
PACKAGE = "08_Tooling/visual-asset-intake"
SCOPE = f"{PACKAGE}/src/visual_asset_intake"
CONFIG = f"{PACKAGE}/pyproject.toml"
MAX_OUTPUT = 256 * 1024


def check(head: str, run_id: str, attempt: str) -> tuple[int, dict]:
    receipt = {
        "schema": "agent-os-ci-black/1",
        "head_sha": head,
        "run_id": run_id,
        "attempt": attempt,
        "version": None,
        "sources": [],
        "status": "scanner-error",
        "reason_code": "invalid-checkout",
        "diagnostics": "",
    }
    if not re.fullmatch(r"[0-9a-f]{40}", head) or any(
        not re.fullmatch(r"[1-9][0-9]*", value) for value in (run_id, attempt)
    ):
        return 2, receipt
    try:
        actual = subprocess.check_output(["git", "rev-parse", "HEAD"], timeout=10).decode().strip()
        if actual != head:
            return 2, receipt
        paths = [SCOPE, CONFIG]
        subprocess.run(
            ["git", "diff", "--quiet", "--no-ext-diff", head, "--", *paths],
            timeout=10,
            check=True,
        )
        tracked = subprocess.check_output(
            ["git", "ls-tree", "-r", "-z", "--name-only", head, "--", *paths],
            timeout=10,
        ).decode().split("\0")
        sources = sorted(path for path in tracked if path.endswith(".py"))
        if CONFIG not in tracked or not sources or any(
            not Path(path).is_file() or Path(path).resolve() != Path(path).absolute()
            for path in [CONFIG, *sources]
        ):
            return 2, dict(receipt, reason_code="scope-missing-or-invalid")
    except subprocess.CalledProcessError:
        return 2, dict(receipt, reason_code="checkout-inputs-unverified")
    except (OSError, ValueError, subprocess.SubprocessError):
        return 2, receipt
    receipt["sources"] = sources
    try:
        version = importlib.metadata.version("black")
    except importlib.metadata.PackageNotFoundError:
        return 2, dict(receipt, reason_code="dependency-missing")
    receipt["version"] = version
    if version != VERSION:
        return 2, dict(receipt, reason_code="dependency-version-mismatch")

    command = [
        sys.executable, "-I", "-m", "black", "--required-version", VERSION,
        "--check", "--no-cache", "--workers", "1", "--config", CONFIG, "--", *sources,
    ]
    env = {key: value for key, value in os.environ.items() if key != "BLACK_CACHE_DIR"}
    try:
        with tempfile.TemporaryFile() as stream:
            status = subprocess.run(
                command, stdout=stream, stderr=subprocess.STDOUT, env=env,
                timeout=60, check=False,
            ).returncode
            stream.seek(0)
            output = stream.read(MAX_OUTPUT + 1)
    except subprocess.TimeoutExpired:
        return 2, dict(receipt, reason_code="scanner-timeout")
    except OSError:
        return 2, dict(receipt, reason_code="scanner-launch-failed")
    if len(output) > MAX_OUTPUT:
        return 2, dict(receipt, reason_code="scanner-output-too-large")
    if status == 0:
        counts = re.findall(rb"(?m)^([0-9]+) files? would be left unchanged\.$", output)
        if counts != [str(len(sources)).encode()]:
            return 2, dict(receipt, reason_code="scanner-incomplete-scope")
        return 0, dict(receipt, status="clean", reason_code=None)
    if status == 1 and b"would reformat " in output:
        return 1, dict(
            receipt, status="findings", reason_code="black-formatting-changes",
            diagnostics=output.decode("utf-8", errors="replace"),
        )
    return 2, dict(receipt, reason_code="scanner-exit-unexpected")


def main() -> int:
    output = Path(sys.argv[1])
    status, receipt = check(
        os.environ.get("CI_JUNIT_HEAD_SHA", ""),
        os.environ.get("CI_JUNIT_RUN_ID", ""),
        os.environ.get("CI_JUNIT_RUN_ATTEMPT", ""),
    )
    with output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(receipt["diagnostics"], end="")
    print(f"Black formatting: {receipt['status']} ({receipt['reason_code'] or 'ok'})")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
