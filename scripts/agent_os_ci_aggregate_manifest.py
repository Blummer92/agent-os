"""Validate the manifest/member contract of a successful aggregate bundle.

JUnit parsing and subtest corroboration remain with their existing owners.
The producer and trusted collector share this inventory/receipt check.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path

HEADER = "suite_name\tjunit_file\tjunit_exists\tstatus\texit_code\tclassification"
COMPLETENESS_PREFIX = "test selection completeness: "
COMPLETENESS_SCHEMA = "agent-os-ci-test-completeness/1"
_FILE = re.compile(r"[A-Za-z0-9_.-]+\Z", re.ASCII)


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("aggregate-receipt-duplicate-field")
        result[key] = value
    return result


def validate_aggregate_manifest(files: Mapping[str, bytes]) -> dict[str, int]:
    """Require every successful full suite and its COMPLETE receipt.

    ``files`` contains safe regular archive members, or a producer directory
    snapshot. The caller owns XML validity and provider provenance checks.
    """
    try:
        manifest = files["manifest.tsv"].decode("utf-8")
    except (KeyError, UnicodeError, AttributeError) as exc:
        raise ValueError("aggregate-manifest-missing-or-invalid") from exc
    if not manifest.endswith("\n") or "\r" in manifest:
        raise ValueError("aggregate-manifest-framing")
    lines = manifest.splitlines()
    if not lines or lines[0] != HEADER or len(lines) < 2:
        raise ValueError("aggregate-manifest-header-or-empty")
    suites: dict[str, str] = {}
    receipts: dict[str, str] = {}
    names: set[str] = set()
    members: set[str] = set()
    xml_members: set[str] = set()
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) != 6:
            raise ValueError("aggregate-manifest-row-fields")
        name, member, exists, status, code, classification = fields
        if not name.strip() or name != name.strip() or name in names:
            raise ValueError("aggregate-manifest-suite-identity")
        if not _FILE.fullmatch(member) or member in (".", "..") or member in members:
            raise ValueError("aggregate-manifest-artifact-identity")
        names.add(name)
        members.add(member)
        if exists != "yes" or status != "PASS" or code != "0":
            raise ValueError("aggregate-manifest-not-successful")
        if member not in files or not files[member]:
            raise ValueError("aggregate-manifest-member-missing")
        if name.startswith(COMPLETENESS_PREFIX):
            suite = name[len(COMPLETENESS_PREFIX):]
            if not suite or classification != "COMPLETE" or not member.endswith(".json"):
                raise ValueError("aggregate-manifest-completeness-row")
            try:
                receipt = json.loads(files[member], object_pairs_hook=_json_object)
            except (ValueError, UnicodeError, TypeError) as exc:
                raise ValueError("aggregate-receipt-invalid") from exc
            if (
                type(receipt) is not dict
                or receipt.get("schema") != COMPLETENESS_SCHEMA
                or receipt.get("suite_name") != suite
                or receipt.get("verdict") != "COMPLETE"
                or receipt.get("error") is not None
            ):
                raise ValueError("aggregate-receipt-not-complete")
            outcome = receipt.get("outcome")
            if (
                type(receipt.get("expected_count")) is not int
                or receipt["expected_count"] < 1
                or type(receipt.get("executed_count")) is not int
                or receipt["executed_count"] < receipt["expected_count"]
                or type(receipt.get("missing_count")) is not int
                or receipt["missing_count"] != 0
                or any(receipt.get(key) != [] for key in (
                    "missing", "skipped_mandatory", "skip_allowlist_stale",
                    "reference_only", "reference_noconftest_only"))
                or any(type(receipt.get(key)) is not int or receipt[key] != 0
                       for key in ("reference_returncode", "reference_noconftest_returncode"))
                or type(outcome) is not dict
                or any(type(outcome.get(key)) is not int or outcome[key] != 0
                       for key in ("failures", "errors"))
                or outcome.get("failed_nodes") != []
            ):
                raise ValueError("aggregate-receipt-proof-incomplete")
            receipts[suite] = member
        else:
            if name.startswith("focused: ") or classification != "EXECUTED_PASS" or not member.endswith(".xml"):
                raise ValueError("aggregate-manifest-suite-row")
            suites[name] = member
            xml_members.add(member)
    if "root" not in suites or set(suites) != set(receipts):
        raise ValueError("aggregate-manifest-suite-receipt-mismatch")
    if xml_members != {name for name in files if name.lower().endswith(".xml")}:
        raise ValueError("aggregate-manifest-xml-inventory-mismatch")
    return {"suites": len(suites), "completeness_receipts": len(receipts)}


def validate_directory(directory: Path) -> dict[str, int]:
    """Read a flat producer bundle, refusing symlink/directory substitutions."""
    files: dict[str, bytes] = {}
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file():
            raise ValueError("aggregate-evidence-not-regular-file")
        files[path.name] = path.read_bytes()
    return validate_aggregate_manifest(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    try:
        result = validate_directory(args.directory)
    except (OSError, ValueError) as exc:
        print(f"Aggregate evidence rejected: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"classification": "COMPLETE", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
