"""Finite argv grammar for the existing #3333 transport, not an executor.

Only admitted repository inspection, local worktree preparation and focused
pytest commands are recognized. These are trusted repository operations, not a
sandbox for hostile repository code. Caller-owned lane/path/currentness checks
and qualified environment evidence remain required.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

MAX_ARGV_PARTS = 64
MAX_ARG_CHARS = 4096
MAX_ARGV_CHARS = 16384
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:+^~-]{0,255}$", re.ASCII)
_COUNT = re.compile(r"^--max-count=([1-9][0-9]{0,2}|1000)$", re.ASCII)
_MAXFAIL = re.compile(r"^--maxfail=([1-9][0-9]?|100)$", re.ASCII)
_STATUS = frozenset({"--short", "--branch", "--porcelain", "--porcelain=v1",
                     "--untracked-files=no", "--untracked-files=normal",
                     "--untracked-files=all"})
_READ_FLAGS = {
    "diff": frozenset({"--stat", "--name-only", "--name-status", "--check",
                       "--cached", "--staged", "--no-ext-diff", "--no-textconv",
                       "--no-color"}),
    "show": frozenset({"--stat", "--name-only", "--name-status", "--oneline",
                       "--no-ext-diff", "--no-textconv", "--no-color"}),
    "log": frozenset({"--oneline", "--no-decorate", "--no-color"}),
    "ls-files": frozenset({"--cached", "--modified", "--others",
                           "--exclude-standard", "--stage"}),
    "rev-parse": frozenset({"--verify", "--short", "--show-toplevel"}),
}
_PYTEST_FLAGS = frozenset({"-q", "-v", "-vv", "-x", "--disable-warnings",
                           "--strict-markers", "--collect-only", "--tb=short",
                           "--tb=long", "--tb=no", "--no-header", "--no-summary"})
_RG_FLAGS = frozenset({"-n", "-l", "-i", "-F", "-E", "--files",
                       "--files-with-matches", "--fixed-strings", "--ignore-case",
                       "--line-number", "--no-heading", "--count", "--color=never"})
_RG_VALUES = frozenset({"-e", "--regexp", "-g", "--glob", "--iglob", "-t", "--type"})


def valid_argv_data(argv: object) -> bool:
    """Bound every token before selection, discovery or transport."""
    return (
        type(argv) is tuple and 0 < len(argv) <= MAX_ARGV_PARTS
        and all(type(p) is str and 0 < len(p) <= MAX_ARG_CHARS
                and not any(ord(c) < 32 or ord(c) == 127 for c in p) for p in argv)
        and sum(map(len, argv)) <= MAX_ARGV_CHARS
    )


def _path(value: str, *, absolute: bool = False) -> bool:
    return (not value.startswith("-") and "://" not in value
            and ".." not in PurePosixPath(value).parts
            and (absolute or not PurePosixPath(value).is_absolute()))


def _ref(value: str) -> bool:
    return _REF.fullmatch(value) is not None and ".." not in value


def _git(args: tuple[str, ...]) -> bool:
    if not args:
        return False
    command, rest = args[0], args[1:]
    if command == "status":
        flags = _STATUS
    elif command in _READ_FLAGS:
        flags = _READ_FLAGS[command]
    elif command == "worktree":
        if rest in (("list",), ("list", "--porcelain")):
            return True
        if not rest or rest[0] != "add":
            return False
        operands = rest[1:]
        if operands and operands[0] == "--detach":
            operands = operands[1:]
        elif len(operands) >= 2 and operands[0] == "-b":
            branch = operands[1]
            if not _ref(branch) or branch in {"main", "master"} or ":" in branch:
                return False
            operands = operands[2:]
        return (len(operands) in (1, 2) and _path(operands[0], absolute=True)
                and (len(operands) == 1 or _ref(operands[1])))
    else:
        # No global git options/config/aliases, helpers, publication or cleanup.
        return False
    paths = False
    for value in rest:
        if value == "--":
            paths = True
        elif paths:
            if not _path(value):
                return False
        elif value in flags or (command == "log" and _COUNT.fullmatch(value)):
            continue
        elif command in {"diff", "show", "log", "rev-parse"} and _ref(value):
            continue
        else:
            return False
    return True


def _pytest(args: tuple[str, ...]) -> bool:
    index = 0
    while index < len(args):
        value = args[index]
        if value in _PYTEST_FLAGS or _MAXFAIL.fullmatch(value):
            index += 1
            continue
        if value in {"-k", "-m"}:
            if index + 1 >= len(args):
                return False
            index += 2
            continue
        path = value.split("::", 1)[0]
        parts = PurePosixPath(path).parts
        in_tests = (path == "tests" or path.startswith("tests/")
                    or (len(parts) >= 3 and parts[0] == "08_Tooling" and parts[2] == "tests"))
        if not in_tests or not _path(path):
            # No -p/plugin, --override-ini, arbitrary modules/scripts or paths.
            return False
        index += 1
    return True


def _rg(args: tuple[str, ...]) -> bool:
    index, has_pattern, literal = 0, False, False
    files = "--files" in args
    while index < len(args):
        value = args[index]
        if not literal and value == "--":
            literal = True
        elif not literal and value in _RG_FLAGS:
            pass
        elif not literal and value in _RG_VALUES:
            if index + 1 >= len(args):
                return False
            index += 1
            has_pattern = has_pattern or value in {"-e", "--regexp"}
        elif not literal and value.startswith("-"):
            # In particular --pre/--pre-glob never become executable helpers.
            return False
        elif not files and not has_pattern:
            has_pattern = True
        elif not _path(value):
            return False
        index += 1
    return files or has_pattern


def admitted_repository_argv(argv: tuple[str, ...]) -> bool:
    """Fail closed for every executable/action family not listed here."""
    if not valid_argv_data(argv):
        return False
    head, rest = argv[0], argv[1:]
    if head == "git":
        return _git(rest)
    if head == "pytest":
        return _pytest(rest)
    if head in {"python", "python3"} and rest[:2] == ("-m", "pytest"):
        return _pytest(rest[2:])
    if head == "rg":
        return _rg(rest)
    return False
