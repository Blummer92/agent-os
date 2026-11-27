"""Check pinned Black on tracked Intake sources; never publish GitHub status.

Dirty checkout inputs are reported as checkout-inputs-unverified. A receipt
keeps attempt for compatibility and also exposes run_attempt. Files is empty
unless Black reports findings; diff_lines counts diff body lines before preview
truncation (including hunk headers but excluding file headers).
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

VERSION = "26.10.0"
PACKAGE = "08_Tooling/visual-asset-intake"
SCOPE = f"{PACKAGE}/src/visual_asset_intake"
CONFIG = f"{PACKAGE}/pyproject.toml"
GIT_TIMEOUT = 10
TIMEOUT = 60
MAX_OUTPUT = 256 * 1024
PREVIEW_LINES = 24
SCHEMA = "agent-os-ci-black/1"
INTERRUPT_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
BLACK_FLAGS = (
    "-I",
    "-m",
    "black",
    "--required-version",
    VERSION,
    "--check",
    "--diff",
    "--no-color",
    "--no-cache",
    "--workers",
    "1",
    "--config",
    CONFIG,
    "--",
)


class CheckError(Exception):
    """A reportable scanner error; never include raw subprocess diagnostics."""


def verify_head(head: str, run_id: str, attempt: str) -> None:
    if (
        not isinstance(head, str)
        or not re.fullmatch(r"[0-9a-f]{40}", head)
        or any(
            not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value)
            for value in (run_id, attempt)
        )
    ):
        raise CheckError("invalid-checkout")
    try:
        observed = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], timeout=GIT_TIMEOUT
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CheckError("invalid-checkout") from exc
    if observed.strip() != head.encode():
        raise CheckError("invalid-checkout")


def verify_clean(head: str) -> None:
    try:
        subprocess.run(
            ["git", "diff", "--quiet", "--no-ext-diff", head, "--", SCOPE, CONFIG],
            timeout=GIT_TIMEOUT,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CheckError("checkout-inputs-unverified") from exc


def collect_sources(head: str) -> list[str]:
    try:
        tracked = (
            subprocess.check_output(
                [
                    "git",
                    "ls-tree",
                    "-r",
                    "-z",
                    "--name-only",
                    head,
                    "--",
                    SCOPE,
                    CONFIG,
                ],
                timeout=GIT_TIMEOUT,
            )
            .decode()
            .split("\0")
        )
        sources = sorted(path for path in tracked if path.endswith(".py"))
        valid = (
            CONFIG in tracked
            and sources
            and len(sources) == len(set(sources))
            and all(
                not any(char in path for char in "\t\n\r")
                and (path == CONFIG or path.startswith(f"{SCOPE}/"))
                and Path(path).is_file()
                and Path(path).resolve() == Path(path).absolute()
                for path in [CONFIG, *sources]
            )
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise CheckError("scope-missing-or-invalid") from exc
    if not valid:
        raise CheckError("scope-missing-or-invalid")
    return sources


def verify_version() -> str:
    # Distribution metadata is enough; do not execute an unverified formatter.
    try:
        return importlib.metadata.version("black")
    except importlib.metadata.PackageNotFoundError as exc:
        raise CheckError("dependency-missing") from exc


def run_file(source: str, timeout: float, limit: int) -> tuple[int, bytes]:
    command = [sys.executable, *BLACK_FLAGS, source]
    env = {key: value for key, value in os.environ.items() if key != "BLACK_CACHE_DIR"}
    try:
        with tempfile.TemporaryFile() as stream:
            status = subprocess.run(
                command,
                stdout=stream,
                stderr=subprocess.STDOUT,
                env=env,
                timeout=timeout,
                check=False,
            ).returncode
            stream.seek(0)
            output = stream.read(limit + 1)
    except KeyboardInterrupt as exc:
        raise CheckError("scanner-incomplete-scope") from exc
    except subprocess.TimeoutExpired as exc:
        raise CheckError("scanner-timeout") from exc
    except OSError as exc:
        raise CheckError("scanner-launch-failed") from exc
    if status < 0 or status in {128 + s for s in (*INTERRUPT_SIGNALS, signal.SIGKILL)}:
        raise CheckError("scanner-incomplete-scope")
    if len(output) > limit:
        raise CheckError("scanner-output-too-large")
    return status, output


def run_black(sources: list[str]) -> dict[str, list[str]]:
    # A multi-file --diff starts Black's multiprocessing manager even with
    # --workers 1. Sequential single-file invocations need no local socket.
    deadline = time.monotonic() + TIMEOUT
    remaining = MAX_OUTPUT
    findings: dict[str, list[str]] = {}
    for source in sources:
        timeout = deadline - time.monotonic()
        if timeout <= 0:
            raise CheckError("scanner-timeout")
        status, output = run_file(source, timeout, remaining)
        remaining -= len(output)
        findings.update(parse_output(status, output, source))
    return findings


def diff_sections(output: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    active = None
    pending = None
    for line in output.split("\n"):
        if line.startswith("--- ") and "\t" in line:
            pending = line[4:].partition("\t")[0]
            active = None
        elif line.startswith("+++ ") and "\t" in line:
            path = line[4:].partition("\t")[0]
            if path != pending or path in sections:
                raise CheckError("scanner-incomplete-scope")
            sections[path] = []
            active = path
            pending = None
        elif active is not None:
            if line.startswith((" ", "+", "-", "@@ ", "\\ No newline")):
                sections[active].append(line)
            else:
                active = None
    if pending is not None:
        raise CheckError("scanner-incomplete-scope")
    return sections


def summarize_findings(sections: dict[str, list[str]]) -> dict[str, object]:
    paths = sorted(sections)
    total = sum(len(sections[path]) for path in paths)
    fix = "Fix: " + shlex.join(["python", "-I", "-m", "black", *paths])
    summaries = [f"would reformat {path}" for path in paths]
    footer = [f"Total diff_lines: {total}", fix]
    # Reserve one truncation marker per file before distributing preview bytes.
    marker = "... [truncated {} lines]"
    reserved = sum(len(line.encode()) + 1 for line in [*summaries, *footer])
    reserved += sum(len(marker.format(len(sections[path]))) + 1 for path in paths)
    if reserved > MAX_OUTPUT:
        raise CheckError("scanner-output-too-large")
    remaining = MAX_OUTPUT - reserved
    rendered = []
    files = []
    for path, summary in zip(paths, summaries):
        lines = sections[path]
        rendered.append(summary)
        kept = 0
        for line in lines[:PREVIEW_LINES]:
            size = len(line.encode()) + 1
            if size > remaining:
                break
            remaining -= size
            rendered.append(line)
            kept += 1
        if kept != len(lines):
            rendered.append(marker.format(len(lines) - kept))
        files.append({"path": path, "would_reformat": True, "diff_lines": len(lines)})
    return {
        "status": "findings",
        "reason_code": "black-formatting-changes",
        "files": files,
        "diff_lines": total,
        "diagnostics": "\n".join([*rendered, *footer]) + "\n",
    }


def parse_output(status: int, output: bytes, source: str) -> dict[str, list[str]]:
    text = output.decode("utf-8", errors="replace")
    unchanged = re.findall(r"(?m)^([0-9]+) files? would be left unchanged\.?$", text)
    if status == 0:
        lines = [line for line in text.splitlines() if line.strip()]
        if lines not in (
            ["1 file would be left unchanged."],
            ["All done! ✨ 🍰 ✨", "1 file would be left unchanged."],
        ):
            raise CheckError("scanner-incomplete-scope")
        return {}
    if status != 1 or "would reformat " not in text:
        raise CheckError("scanner-exit-unexpected")
    markers = re.findall(r"(?m)^would reformat (.+)$", text)
    sections = diff_sections(text)
    if (
        markers != [source]
        or list(sections) != [source]
        or unchanged
        or re.findall(r"(?m)^([0-9]+) files? would be reformatted\.$", text) != ["1"]
        or not sections[source]
        or not sections[source][0].startswith("@@ ")
    ):
        raise CheckError("scanner-incomplete-scope")
    return sections


def receipt_template(head: str, run_id: str, attempt: str) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "head_sha": head,
        "run_id": run_id,
        "attempt": attempt,
        "run_attempt": attempt,
        "version": None,
        "sources": [],
        "files": [],
        "diff_lines": 0,
        "status": "scanner-error",
        "reason_code": "invalid-checkout",
        "diagnostics": "",
    }


def check(head: str, run_id: str, attempt: str) -> tuple[int, dict[str, object]]:
    receipt = receipt_template(head, run_id, attempt)
    try:
        verify_head(head, run_id, attempt)
        verify_clean(head)
        sources = collect_sources(head)
        receipt["sources"] = sources
        receipt["version"] = verify_version()
        if receipt["version"] != VERSION:
            raise CheckError("dependency-version-mismatch")
        findings = run_black(sources)
        if findings:
            return 1, dict(receipt, **summarize_findings(findings))
        return 0, dict(receipt, status="clean", reason_code=None)
    except CheckError as exc:
        return 2, dict(receipt, reason_code=str(exc))
    except KeyboardInterrupt:
        return 2, dict(receipt, reason_code="scanner-incomplete-scope")


def interrupt(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


def verify_clean_receipt(output: Path, head: str, run_id: str, attempt: str) -> int:
    try:
        verify_head(head, run_id, attempt)
        verify_clean(head)
        sources = collect_sources(head)
        with output.open("rb") as stream:
            raw = stream.read(MAX_OUTPUT + 1)
        if len(raw) > MAX_OUTPUT:
            raise CheckError("scanner-output-too-large")
        received = json.loads(raw)
        expected = dict(
            receipt_template(head, run_id, attempt),
            status="clean",
            reason_code=None,
            version=VERSION,
            sources=sources,
        )
        if not isinstance(received, dict) or any(
            key not in received
            or type(received[key]) is not type(value)
            or received[key] != value
            for key, value in expected.items()
        ):
            raise CheckError("receipt-mismatch")
    except (CheckError, OSError, ValueError, KeyboardInterrupt):
        print("Black formatting: clean receipt invalid", file=sys.stderr)
        return 2
    return 0


def evidence_identity() -> tuple[str, str, str]:
    return (
        os.environ.get("CI_JUNIT_HEAD_SHA", ""),
        os.environ.get("CI_JUNIT_RUN_ID", ""),
        os.environ.get("CI_JUNIT_RUN_ATTEMPT", ""),
    )


def main() -> int:
    if sys.argv[1:2] == ["--verify-clean"] and len(sys.argv) == 3:
        return verify_clean_receipt(Path(sys.argv[2]), *evidence_identity())
    if len(sys.argv) != 2:
        return 2
    output = Path(sys.argv[1])
    handlers = {sig: signal.signal(sig, interrupt) for sig in INTERRUPT_SIGNALS}
    try:
        status, receipt = check(*evidence_identity())
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(receipt["diagnostics"], end="")
    print(f"Black formatting: {receipt['status']} ({receipt['reason_code'] or 'ok'})")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
