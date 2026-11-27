"""Plan root shard experiments from historical JUnit; never select tests in CI."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

MAX_XML = 16 * 1024 * 1024
MAX_ARCHIVE = 32 * 1024 * 1024
SHA = re.compile(r"[a-f0-9]{40}")
DIGEST = re.compile(r"[a-f0-9]{64}")


@dataclass
class Lane:
    files: list[str] = field(default_factory=list)
    cases: int = 0
    testcase_seconds: Decimal = Decimal(0)


def tracked_test_paths(repo: Path, head: str) -> list[str]:
    if not SHA.fullmatch(head):
        raise ValueError("expected a full lowercase source commit SHA")
    result = subprocess.run(
        ["git", "ls-tree", "-rz", "--name-only", head, "--", "tests"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        timeout=15,
    )
    return [p for p in result.stdout.decode().split("\0") if p.endswith(".py")]


def read_root(archive: Path, expected_digest: str) -> bytes:
    if not DIGEST.fullmatch(expected_digest):
        raise ValueError("expected the provider SHA-256")
    with archive.open("rb") as stream:
        raw = stream.read(MAX_ARCHIVE + 1)
    if len(raw) > MAX_ARCHIVE or hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError("archive size or digest did not match")
    import io

    with ZipFile(io.BytesIO(raw)) as z:
        found = [item for item in z.infolist() if item.filename == "root.xml"]
        if len(found) != 1 or found[0].file_size > MAX_XML:
            raise ValueError("expected one bounded root.xml")
        return z.read(found[0])


def _root_cases(raw: bytes) -> list[ET.Element]:
    if len(raw) > MAX_XML or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("invalid or oversized root XML")
    root = ET.fromstring(raw.decode("utf-8"))
    suites = list(root.iter("testsuite"))
    if len(suites) != 1:
        raise ValueError("expected one root testsuite")
    suite = suites[0]
    cases = suite.findall("testcase")
    if not cases or len(cases) != int(suite.attrib["tests"]):
        raise ValueError("declared and itemized root counts differ")
    if any(int(suite.attrib[k]) for k in ("errors", "failures")):
        raise ValueError("reference root suite failed")
    return cases


def _case_file(
    case: ET.Element, paths: dict[str, str]
) -> tuple[tuple[str, str], str, Decimal]:
    classname, name = case.attrib.get("classname", ""), case.attrib.get("name", "")
    if not name or case.find("failure") is not None or case.find("error") is not None:
        raise ValueError("unsuccessful or unnamed testcase")
    if not classname and case.find("skipped") is None:
        raise ValueError("only collection skips may omit classname")
    module = classname or name
    while module and module not in paths:
        module = module.rpartition(".")[0]
    if not module:
        raise ValueError(f"testcase did not map to a tracked module: {classname}::{name}")
    elapsed = Decimal(case.attrib["time"])
    if not elapsed.is_finite() or elapsed < 0:
        raise ValueError("invalid testcase duration")
    return (classname, name), paths[module], elapsed


def replay(raw: bytes, tracked: list[str], count: int) -> list[Lane]:
    if not 2 <= count <= 8:
        raise ValueError("shard count must be 2–8")
    paths = {p[:-3].replace("/", "."): p for p in tracked}
    if len(paths) != len(tracked):
        raise ValueError("ambiguous tracked module paths")
    seen: set[tuple[str, str]] = set()
    cases: dict[str, int] = defaultdict(int)
    durations: dict[str, Decimal] = defaultdict(Decimal)
    for case in _root_cases(raw):
        identity, file, elapsed = _case_file(case, paths)
        if identity in seen:
            raise ValueError(f"duplicate testcase identity: {identity}")
        seen.add(identity)
        cases[file] += 1
        durations[file] += elapsed
    if len(cases) < count:
        raise ValueError("not enough whole modules for nonempty shards")
    lanes = [Lane() for _ in range(count)]
    for file in sorted(cases, key=lambda p: (-durations[p], p)):
        lane = min(lanes, key=lambda ln: (ln.testcase_seconds, len(ln.files)))
        lane.files.append(file)
        lane.cases += cases[file]
        lane.testcase_seconds += durations[file]
    return lanes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--repo", default=Path("."), type=Path)
    parser.add_argument("--shards", default=4, type=int)
    args = parser.parse_args(argv)
    try:
        paths = tracked_test_paths(args.repo, args.source_head)
        raw = read_root(args.archive, args.archive_sha256)
        lanes = replay(raw, paths, args.shards)
    except (
        BadZipFile,
        ET.ParseError,
        InvalidOperation,
        KeyError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as error:
        print(f"root shard timing replay refused: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "report_kind": "historical-testcase-duration-model-only",
                "source_head": args.source_head,
                "archive_sha256": args.archive_sha256,
                "shards": [
                    {
                        "files": lane.files,
                        "cases": lane.cases,
                        "testcase_seconds": str(lane.testcase_seconds),
                    }
                    for lane in lanes
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
