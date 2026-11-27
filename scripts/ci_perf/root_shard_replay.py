"""Model historical root testcase timings; never select tests in CI."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryFile
from xml.parsers import expat
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo

MAX_XML = 16 * 1024 * 1024
MAX_ARCHIVE = 32 * 1024 * 1024
MAX_INVENTORY = 16 * 1024 * 1024
MAX_GIT = 16 * 1024 * 1024
MAX_ZIP_ENTRIES = 4096
GIT_TIMEOUT = 15
TICKS_PER_SECOND = 10**9
SHA = re.compile(r"[a-f0-9]{40}")
DIGEST = re.compile(r"[a-f0-9]{64}")
UINT = re.compile(r"(?:0|[1-9][0-9]{0,8})")
PROVIDER_ID = re.compile(r"[1-9][0-9]{0,19}")
PROVIDER_KEYS = ("run_id", "run_attempt", "artifact_id")
DURATION = re.compile(r"([0-9]{1,7})(?:\.([0-9]{1,9}))?")
XML_DECLARATION = re.compile(r"\A<\?xml[ \t\r\n].*?\?>", re.DOTALL)
XML_ENCODING = re.compile(r"""\bencoding\s*=\s*(['"])([^'"]+)\1""")
SCHEMA = "agent-os-root-timing-reference/1"
REPOSITORY = "Blummer92/agent-os"
Identity = tuple[str, str]
Inventory = dict[Identity, str]
ProviderIdentity = tuple[int, int, int]


class Refusal(ValueError):
    """Internal error with a fixed, non-sensitive reason code."""


@dataclass
class Lane:
    files: list[str] = field(default_factory=list)
    cases: int = 0
    ticks: int = 0

    @property
    def testcase_seconds(self) -> str:
        whole, fraction = divmod(self.ticks, TICKS_PER_SECOND)
        return str(whole) if not fraction else f"{whole}.{fraction:09d}".rstrip("0")


def _path_parts(path: str) -> list[str]:
    parts = path.split("/")
    if (
        not path
        or any(part in {"", ".", ".."} for part in parts)
        or any(unicodedata.category(c) == "Cc" or c in "\\:" for c in path)
    ):
        raise Refusal("unsafe-path")
    return parts


def _test_path(path: str) -> None:
    parts = _path_parts(path)
    if len(parts) < 2 or parts[0] != "tests" or not parts[-1].endswith(".py"):
        raise Refusal("invalid-test-path")


def _git(repo: Path, *args: str) -> bytes:
    # Do not let inherited Git context redirect this read to another object store.
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )
    try:
        with TemporaryFile() as stdout:
            subprocess.run(
                ["git", *args],
                cwd=repo,
                env=env,
                stdout=stdout,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=GIT_TIMEOUT,
            )
            stdout.seek(0)
            result = stdout.read(MAX_GIT + 1)
    except (OSError, subprocess.SubprocessError):
        raise Refusal("git-read-failed") from None
    if len(result) > MAX_GIT:
        raise Refusal("git-output-too-large")
    return result


def tracked_test_paths(repo: Path, head: str) -> list[str]:
    if not SHA.fullmatch(head):
        raise Refusal("invalid-source-head")
    if (
        _git(repo, "rev-parse", "--verify", head + "^{object}")
        != head.encode("ascii") + b"\n"
        or _git(repo, "cat-file", "-t", head) != b"commit\n"
    ):
        raise Refusal("source-head-not-commit")
    raw = _git(repo, "ls-tree", "-rz", "--full-tree", head, "--", "tests")
    if not raw or not raw.endswith(b"\0"):
        raise Refusal("invalid-git-inventory")
    paths = []
    try:
        for line in raw[:-1].decode("utf-8").split("\0"):
            metadata, path = line.split("\t", 1)
            mode, kind, object_id = metadata.split(" ")
            if not SHA.fullmatch(object_id) or not path.startswith("tests/"):
                raise Refusal("invalid-git-inventory")
            if path.endswith(".py"):
                _test_path(path)
                if mode not in {"100644", "100755"} or kind != "blob":
                    raise Refusal("nonregular-test-path")
                paths.append(path)
    except (UnicodeError, ValueError) as error:
        if isinstance(error, Refusal):
            raise
        raise Refusal("invalid-git-inventory") from None
    if not paths or len(set(paths)) != len(paths):
        raise Refusal("invalid-git-inventory")
    return paths


def _read_verified(path: Path, digest: str, limit: int) -> bytes:
    if not DIGEST.fullmatch(digest):
        raise Refusal("invalid-digest")
    # A FIFO or device is not a supported evidence input; do not block on open.
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK"):
        raise Refusal("unsupported-filesystem-platform")
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    try:
        with os.fdopen(os.open(path, flags), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise Refusal("nonregular-evidence-file")
            if info.st_size > limit:
                raise Refusal("evidence-too-large")
            raw = stream.read(limit + 1)
    except OSError:
        raise Refusal("evidence-read-failed") from None
    if len(raw) > limit:
        raise Refusal("evidence-too-large")
    if hashlib.sha256(raw).hexdigest() != digest:
        raise Refusal("evidence-digest-mismatch")
    return raw


def _root_member(z: ZipFile) -> ZipInfo:
    entries = z.infolist()
    if len(entries) > MAX_ZIP_ENTRIES:
        raise Refusal("too-many-archive-members")
    seen = set()
    found = None
    for item in entries:
        name = item.filename
        parts = _path_parts(name.removesuffix("/"))
        if item.orig_filename != name or name in seen:
            raise Refusal("invalid-archive-member")
        seen.add(name)
        if parts[-1] != "root.xml":
            continue
        kind = stat.S_IFMT(item.external_attr >> 16) if item.create_system == 3 else 0
        if (
            name != "root.xml"
            or kind not in (0, stat.S_IFREG)
            or item.external_attr & 0x10
        ):
            raise Refusal("invalid-root-member")
        found = item
    if found is None:
        raise Refusal("missing-root-member")
    if found.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
        raise Refusal("unsupported-root-compression")
    if not 0 < found.file_size <= MAX_XML:
        raise Refusal("invalid-root-size")
    return found


def read_root(archive: Path, expected_digest: str) -> bytes:
    raw = _read_verified(archive, expected_digest, MAX_ARCHIVE)
    try:
        with ZipFile(io.BytesIO(raw)) as z:
            root = _root_member(z)
            with z.open(root) as stream:
                xml = stream.read(MAX_XML + 1)
            if len(xml) != root.file_size or len(xml) > MAX_XML:
                raise Refusal("invalid-root-size")
            return xml
    except (
        BadZipFile,
        EOFError,
        NotImplementedError,
        OSError,
        RuntimeError,
        zlib.error,
    ):
        raise Refusal("invalid-archive") from None


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refusal("duplicate-reference-field")
        result[key] = value
    return result


def read_inventory(
    path: Path, digest: str, head: str, archive_digest: str, provider: ProviderIdentity
) -> Inventory:
    raw = _read_verified(path, digest, MAX_INVENTORY)
    try:
        record = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise Refusal("invalid-reference-json") from None
    if not isinstance(record, dict) or record.keys() != {
        "schema",
        "repository",
        "source_head",
        "archive_sha256",
        "run_id",
        "run_attempt",
        "artifact_id",
        "cases",
    }:
        raise Refusal("invalid-reference-shape")
    if (
        record["schema"] != SCHEMA
        or record["repository"] != REPOSITORY
        or record["source_head"] != head
        or record["archive_sha256"] != archive_digest
        or tuple(record[k] for k in PROVIDER_KEYS) != provider
        or any(
            type(record[k]) is not int or not 0 < record[k] < 10**20
            for k in PROVIDER_KEYS
        )
    ):
        raise Refusal("invalid-reference-binding")
    rows = record["cases"]
    if not isinstance(rows, list) or not rows:
        raise Refusal("empty-reference-inventory")
    inventory = {}
    for row in rows:
        if (
            not isinstance(row, list)
            or len(row) != 3
            or any(type(v) is not str for v in row)
        ):
            raise Refusal("invalid-reference-row")
        classname, name, module_path = row
        _test_path(module_path)
        identity = (classname, name)
        if not name or identity in inventory:
            raise Refusal("invalid-reference-identity")
        inventory[identity] = module_path
    return inventory


def _reject_xml_declaration(*_args: object) -> None:
    raise Refusal("prohibited-xml-declaration")


def _require_safe_xml(text: str) -> None:
    # Apply the policy to parser events, not to strings printed in test logs.
    parser = expat.ParserCreate("UTF-8")
    parser.StartDoctypeDeclHandler = _reject_xml_declaration
    parser.EntityDeclHandler = _reject_xml_declaration
    parser.ExternalEntityRefHandler = _reject_xml_declaration
    parser.Parse(text.encode("utf-8"), True)


def _xml_root(raw: bytes) -> ET.Element:
    if not raw or len(raw) > MAX_XML:
        raise Refusal("invalid-root-size")
    try:
        text = raw.decode("utf-8-sig")
        if "\0" in text:
            raise Refusal("invalid-xml-encoding")
        declaration = XML_DECLARATION.match(text)
        if declaration:
            encoding = XML_ENCODING.search(declaration[0])
            if encoding and encoding[2].lower() != "utf-8":
                raise Refusal("invalid-xml-encoding")
        _require_safe_xml(text)
        return ET.fromstring(text)
    except (UnicodeError, ET.ParseError, expat.ExpatError):
        raise Refusal("invalid-root-xml") from None


def _count(node: ET.Element, key: str) -> int:
    raw = node.get(key, "")
    if not UINT.fullmatch(raw):
        raise Refusal("invalid-junit-count")
    return int(raw)


def _metadata(node: ET.Element) -> None:
    if node.tag == "properties":
        if any(child.tag != "property" or len(child) for child in node):
            raise Refusal("invalid-junit-structure")
    elif node.tag not in {"system-out", "system-err"} or len(node):
        raise Refusal("invalid-junit-structure")


def _case_skipped(case: ET.Element) -> bool:
    skipped = False
    for child in case:
        if child.tag in {"failure", "error"}:
            raise Refusal("reference-testcase-failed")
        if child.tag == "skipped":
            if skipped or len(child):
                raise Refusal("invalid-junit-structure")
            skipped = True
        else:
            _metadata(child)
    return skipped


def _root_cases(raw: bytes) -> list[tuple[ET.Element, bool]]:
    root = _xml_root(raw)
    if root.tag == "testsuite":
        suite = root
    elif root.tag == "testsuites" and len(root) == 1 and root[0].tag == "testsuite":
        suite = root[0]
    else:
        raise Refusal("invalid-junit-structure")
    for key in ("errors", "failures"):
        if _count(suite, key) or (
            root is not suite and key in root.attrib and _count(root, key)
        ):
            raise Refusal("reference-root-failed")
    cases = []
    for node in suite:
        if node.tag == "testcase":
            cases.append((node, _case_skipped(node)))
        else:
            _metadata(node)
    if not cases:
        raise Refusal("empty-root-suite")
    for key, expected in (
        ("tests", len(cases)),
        ("skipped", sum(skip for _, skip in cases)),
    ):
        for container in (root,) if root is suite else (root, suite):
            required = key == "tests" and container is suite
            if (required or key in container.attrib) and _count(
                container, key
            ) != expected:
                raise Refusal("junit-count-mismatch")
    return cases


def _case_file(
    case: ET.Element,
    skipped: bool,
    inventory: Inventory,
    modules: dict[str, str],
) -> tuple[Identity, str, int]:
    classname, name = case.get("classname", ""), case.get("name", "")
    identity = (classname, name)
    if not name or identity not in inventory:
        raise Refusal("unmapped-testcase")
    path = inventory[identity]
    supplied_path = case.get("file")
    if supplied_path is not None and supplied_path != path:
        raise Refusal("testcase-file-mismatch")
    module = modules.get(path)
    if (
        not module
        or (not classname and (not skipped or name != module))
        or (
            classname and classname != module and not classname.startswith(module + ".")
        )
    ):
        raise Refusal("invalid-testcase-module")
    elapsed = DURATION.fullmatch(case.get("time", ""))
    if not elapsed:
        raise Refusal("invalid-testcase-duration")
    whole, fraction = elapsed.groups()
    ticks = int(whole) * TICKS_PER_SECOND + int((fraction or "").ljust(9, "0"))
    return identity, path, ticks


def replay(
    raw: bytes, tracked: list[str], count: int, inventory: Inventory
) -> list[Lane]:
    if type(count) is not int or not 2 <= count <= 8:
        raise Refusal("invalid-shard-count")
    modules = {}
    for path in tracked:
        _test_path(path)
        modules[path] = path[:-3].replace("/", ".")
    if not modules or len(set(modules.values())) != len(tracked):
        raise Refusal("ambiguous-or-empty-git-inventory")
    if not inventory or not set(inventory.values()) <= modules.keys():
        raise Refusal("invalid-reference-inventory")
    seen: set[Identity] = set()
    cases: dict[str, int] = defaultdict(int)
    durations: dict[str, int] = defaultdict(int)
    for case, skipped in _root_cases(raw):
        identity, path, ticks = _case_file(case, skipped, inventory, modules)
        if identity in seen:
            raise Refusal("duplicate-testcase-identity")
        seen.add(identity)
        cases[path] += 1
        durations[path] += ticks
    if seen != inventory.keys():
        raise Refusal("incomplete-reference-inventory")
    if len(cases) < count:
        raise Refusal("insufficient-whole-modules")
    lanes = [Lane() for _ in range(count)]
    for path in sorted(cases, key=lambda p: (-durations[p], p)):
        lane = min(lanes, key=lambda value: (value.ticks, len(value.files)))
        lane.files.append(path)
        lane.cases += cases[path]
        lane.ticks += durations[path]
    return lanes


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise Refusal("invalid-arguments")


def _write_all(sink, data: str | memoryview) -> None:
    while data:
        written = sink.write(data)
        if type(written) is not int or not 0 < written <= len(data):
            raise OSError("stream made no write progress")
        data = data[written:]


def _write_stream(stream, text: str) -> None:
    if stream is None:
        raise OSError("stream unavailable")
    # Native streams use an unbuffered duplicate, so a closed pipe cannot
    # leave data for the interpreter to retry on shutdown.
    if stream is sys.__stdout__ or stream is sys.__stderr__:
        with os.fdopen(os.dup(stream.fileno()), "wb", buffering=0) as sink:
            _write_all(sink, memoryview(text.encode("ascii")))
    else:
        _write_all(stream, text)
        stream.flush()


def _write_output(text: str) -> None:
    _write_stream(sys.stdout, text)


def _provider_id(value: str) -> int:
    if not PROVIDER_ID.fullmatch(value):
        raise Refusal("invalid-provider-identity")
    return int(value)


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(prog="root-shard-replay", description=__doc__, allow_abbrev=False)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--reference-sha256", required=True)
    for key in PROVIDER_KEYS:
        parser.add_argument("--" + key.replace("_", "-"), required=True)
    parser.add_argument("--repo", default=Path("."), type=Path)
    parser.add_argument("--shards", default=4, type=int)
    try:
        args = parser.parse_args(argv)
        if not SHA.fullmatch(args.source_head):
            raise Refusal("invalid-source-head")
        if not DIGEST.fullmatch(args.archive_sha256):
            raise Refusal("invalid-digest")
        inventory = read_inventory(
            args.reference,
            args.reference_sha256,
            args.source_head,
            args.archive_sha256,
            (
                _provider_id(args.run_id),
                _provider_id(args.run_attempt),
                _provider_id(args.artifact_id),
            ),
        )
        paths = tracked_test_paths(args.repo, args.source_head)
        raw = read_root(args.archive, args.archive_sha256)
        lanes = replay(raw, paths, args.shards, inventory)
        payload = {
            "report_kind": "historical-testcase-duration-model-only",
            "source_head": args.source_head,
            "archive_sha256": args.archive_sha256,
            "shards": [
                {
                    "files": lane.files,
                    "cases": lane.cases,
                    "testcase_seconds": lane.testcase_seconds,
                }
                for lane in lanes
            ],
        }
        _write_output(json.dumps(payload, indent=2) + "\n")
    except (Refusal, ValueError, OSError, KeyboardInterrupt) as error:
        reason = (
            str(error) if isinstance(error, Refusal) else "input-or-output-unavailable"
        )
        try:
            _write_stream(sys.stderr, f"root shard timing replay refused: {reason}\n")
        except (OSError, ValueError):
            pass
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
