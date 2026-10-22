"""Report-only jscpd runner for #3688. Never authorizes code removal."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

SCOPE = ("scripts/agent_os_issue_acceptance", "08_Tooling/agent-os-execution-service/src")
VERSION = "4.0.5"
EXCLUDE = "**/build/**,**/dist/**,**/node_modules/**,**/__pycache__/**,**/.venv/**,**/tests/**,**/fixtures/**"


def scan(root: Path, output: Path, *, sha: str | None = None, command: str = "npx") -> dict:
    """Return evidence even when the scanner is missing or fails."""
    output.mkdir(parents=True, exist_ok=True)
    if sha is None:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
        sha = rev.stdout.strip() if rev.returncode == 0 else "unavailable"
    args = [command, "--yes", f"jscpd@{VERSION}", *SCOPE,
            "--min-lines", "8", "--min-tokens", "60", "--reporters", "json",
            "--output", str(output / "raw"), "--ignore", EXCLUDE, "--silent"]
    try:
        result = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=240, check=False)
        raw = output / "raw" / "jscpd-report.json"
        parsed = json.loads(raw.read_text(encoding="utf-8")) if raw.is_file() else None
        if result.returncode != 0 or not isinstance(parsed, dict):
            status = "scanner-error"
            clones = []
        else:
            status = "ok"
            clones = parsed.get("duplicates", [])
            if not isinstance(clones, list):
                status, clones = "scanner-error", []
    except (OSError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
        status, clones = "scanner-error", []
    evidence = {
        "schema": "agent-os-jscpd-advisory/1",
        "status": status,
        "head_sha": sha,
        "tool": "jscpd",
        "version": VERSION,
        "scope": list(SCOPE),
        "limitations": "Textual clone candidates only; never deletion or semantic equivalence evidence.",
        "candidate_count": len(clones),
        "candidates": clones[:100],
        "truncated": len(clones) > 100,
    }
    (output / "jscpd-advisory.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "jscpd-advisory.md").write_text(
        "# jscpd advisory\n\n"
        + f"- SHA: `{sha}`\n- Tool: jscpd {VERSION}\n- Status: {status}\n"
        + f"- Candidates: {len(clones)} (first 100 in JSON)\n\n"
        + "Findings require human review under #1729; no code deletion is authorized.\n",
        encoding="utf-8",
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("tmp/jscpd-advisory"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--sha")
    args = parser.parse_args()
    result = scan(args.root.resolve(), args.output.resolve(), sha=args.sha)
    print(json.dumps({k: v for k, v in result.items() if k != "candidates"}, sort_keys=True))
    # Advisory: findings and scanner errors never block other validation.
    return 0


if __name__ == "__main__":
    sys.exit(main())
