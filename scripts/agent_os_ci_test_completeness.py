"""Test-selection completeness check for the canonical validation runner.

Root cause it repairs (PR #3816, run 42395721554): the authoritative
aggregate accepted a candidate whose ``pytest.ini`` carried
``--deselect=tests/agent_os_issue_acceptance/test_report.py`` while the
severed-helper regression that file detects was still present. The runner
(``scripts/validate-all.sh``) treated pytest exit 0 plus a present JUnit
file as ``EXECUTED_PASS`` and never asked whether the executed set was the
collected set, so the aggregate job, the aggregate gate, and the
``agent-os/authoritative-aggregate`` status all went green on a candidate
whose regression tests never ran. The same fault without the deselect
(PR #3815) failed with four test failures, which proves the omission --
not the test suite -- was the difference.

How this check works, per pytest suite:

1. Collect the test inventory twice, in the suite directory, with the
   environment the real suite run uses: once with the candidate's own
   configuration (the "actual" set), and once with only test-selection
   options removed from the effective ``addopts`` (the "reference" set).
   Selection options removed from the reference are ``--deselect``,
   ``-k``, ``-m``, ``--ignore``, ``--ignore-glob``, and ``-o`` /
   ``--override-ini`` overrides (an ``-o`` override inside ``addopts``
   could otherwise narrow discovery, e.g. ``python_files``), including
   those flags bundled inside a short-option cluster (``-qk``). The
   reference additionally resets the ini-level test-discovery options
   ``python_files``, ``python_classes``, ``python_functions``,
   ``norecursedirs``, and ``testpaths`` to pytest's defaults, except
   for the explicitly allowlisted exclusions in
   ``_DISCOVERY_ALLOWLIST``. Every other option -- verbosity,
   ``--continue-on-collection-errors``, reporting -- is preserved
   verbatim, so both collections tolerate the same collection errors.
   Both collections run with ``-v`` appended so they print node ids
   (flat or tree format) rather than per-file counts, which lets the
   comparison pair tests whose parameter values are regenerated on
   every collection (see below) in every suite, not only in suites
   whose ``addopts`` already contains ``-v``. ``PYTEST_ADDOPTS`` is
   scrubbed from both collections' environment (and unset by
   ``validate-all.sh`` before any suite runs), because the environment
   variable applies to both collections identically and would
   otherwise be an invisible narrowing.
2. Compare the two node sets. Any test in the reference set but missing
   from the actual set is an unexpected omission and the suite verdict
   is ``INCOMPLETE``. Tests in the actual set but missing from the
   reference set are an ``ERROR`` (fail closed: the comparison itself
   cannot be trusted).

What this deliberately does NOT do:

* It is not a global test-count floor. Legitimate additions, removals,
  and renames of tests change both sets identically, because the
  reference is collected from the candidate tree itself, not from a
  frozen baseline. Skipped and xfailed tests are collected by both
  runs and remain valid.
* It does not police ``conftest.py`` collection hooks
  (``pytest_collection_modifyitems``, ``pytest_ignore_collect``): those
  run identically in both collections, so a hook that deselects is
  invisible here. That is a code change, visible in review, in the
  same trust class as any other in-repo runner change; this check
  covers the configuration surface the proven bypass used.
* It does not police ``-c`` / ``--rootdir`` inside ``addopts``: pytest
  ignores both there (verified: a ``-c`` pointing at a narrowing ini
  file and a ``--rootdir`` pointing elsewhere leave the collection
  unchanged), so they cannot narrow either run.
* It does not apply to focused runs (``validate-all.sh --focused``,
  the bounded plan executor). Focused runs select tests explicitly and
  by design; their receipts already record selected-vs-executed. This
  check guards full-suite runs only, which is the authoritative path.

A config-level exclusion (``--deselect``, ``-k``, ``-m``,
``--ignore`` in ``addopts``, or a narrowing ini discovery option) is
therefore no longer a silent way to narrow the authoritative run,
except for the allowlisted exclusions recorded in
``_DISCOVERY_ALLOWLIST`` and for ``conftest.py`` hooks (above). Tests
that must not run in a given environment belong behind a skip marker
in code: they are collected, reported as skipped, and pass this check.

Exit codes: 0 ``COMPLETE``, 1 ``INCOMPLETE``, 2 ``ERROR`` (the
comparison could not be established; fail closed).
"""
from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

SCHEMA = "agent-os-ci-test-completeness/1"

# pytest's inifile search order within each directory, walking upward.
_INI_CANDIDATES = ("pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg")

# Tokens that narrow the selected set. A following argument is consumed
# for the bare forms; the ``=`` forms carry their argument inline.
_SELECTION_WITH_ARG = ("--deselect", "-k", "-m", "--ignore", "--ignore-glob")
_SELECTION_EQUALS = ("--deselect=", "--ignore=", "--ignore-glob=", "-k=", "-m=")
_OVERRIDE_WITH_ARG = ("-o", "--override-ini")
_OVERRIDE_EQUALS = ("--override-ini=",)

# Short flags that take an argument (pytest). Inside a bundled cluster
# the rest of the token, or the next token, is that flag's argument.
# ``k`` and ``m`` are selection flags; ``o`` is an ini override; the
# rest are preserved with their argument.
_SHORT_ARG_FLAGS = frozenset("kmop rWcn".replace(" ", ""))
_SHORT_SELECTION_FLAGS = frozenset("km")

# pytest's default test-discovery settings. The reference collection
# resets any candidate discovery setting to these (plus the allowlist
# below), so a one-line ``pytest.ini`` change cannot silently narrow
# the suite the way ``--deselect`` did in PR #3816.
_DISCOVERY_DEFAULTS: dict[str, list[str]] = {
    "python_files": ["test_*.py", "*_test.py"],
    "python_classes": ["Test*"],
    "python_functions": ["test_*"],
    "norecursedirs": [".*", "build", "dist", "CVS", "_darcs", "{arch}", "*.egg"],
    "testpaths": [],
}

# Legitimate discovery exclusions the reference keeps on top of the
# pytest default, keyed by (suite name, option). Each entry is an
# exclusion the repo relies on and that must not read as a narrowing:
# 08_Tooling/reusable-capability-registry keeps its validation
# fixtures (intentional example/test files) and its ``__pycache__``
# directories out of its own suite. Anything else a candidate adds
# to a discovery option is reset in the reference run and therefore
# detected as an omission.
_DISCOVERY_ALLOWLIST: dict[tuple[str, str], list[str]] = {
    ("08_Tooling/reusable-capability-registry", "norecursedirs"): [
        "fixtures",
        "__pycache__",
    ],
}

_MISSING_CAP = 100


def _pytest_ini_options(path: Path) -> dict:
    """The ``[tool.pytest.ini_options]`` table of a ``pyproject.toml``.

    Returns ``{}`` when the file has no such table, or when the
    ``[tool]`` / ``[tool.pytest]`` chain is not a table at all (a
    malformed file must never crash the check; it fails closed as
    "no pytest options here" and the caller decides the verdict).
    """
    import tomllib

    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    tool = payload.get("tool")
    if not isinstance(tool, dict):
        return {}
    section = tool.get("pytest")
    if not isinstance(section, dict):
        return {}
    options = section.get("ini_options")
    return options if isinstance(options, dict) else {}


def _pytest_options(config_path: Path | None) -> dict[str, str | list[str]]:
    """Raw pytest options from a config file (keys lowercased)."""
    if config_path is None:
        return {}
    name = config_path.name
    if name in ("pytest.ini", "tox.ini"):
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(config_path, encoding="utf-8")
        if not parser.has_section("pytest"):
            return {}
        return {key: parser.get("pytest", key) for key in parser.options("pytest")}
    if name == "setup.cfg":
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(config_path, encoding="utf-8")
        if not parser.has_section("tool:pytest"):
            return {}
        return {
            key: parser.get("tool:pytest", key) for key in parser.options("tool:pytest")
        }
    if name == "pyproject.toml":
        return {
            str(key).lower(): value for key, value in _pytest_ini_options(config_path).items()
        }
    return {}


def _as_str_list(value: str | list[str]) -> list[str]:
    """Normalize a pytest option value (string or list) to a list."""
    if isinstance(value, str):
        return value.split()
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise ValueError("pytest option value must be a string or a list of strings")


def _counts_as_pytest_config(path: Path) -> bool:
    """Whether ``path`` actually defines pytest options.

    Mirrors pytest: a ``pyproject.toml`` only counts when it has a
    ``[tool.pytest.ini_options]`` table, a ``tox.ini`` only with a
    ``[pytest]`` section, and a ``setup.cfg`` only with a
    ``[tool:pytest]`` section. A bare file of those kinds does not
    anchor the search -- pytest keeps walking upward. A ``pytest.ini``
    anchors by existence. A structurally surprising file (for example
    ``[tool] pytest = "not-a-table"``) never raises here; it simply
    does not count, and the search keeps walking. A genuinely
    unreadable or unparseable file (bad TOML, bad ini syntax) raises,
    so the caller fails closed as ERROR instead of silently reading a
    different config.
    """
    if path.name == "pytest.ini":
        return True
    try:
        if path.name == "pyproject.toml":
            return bool(_pytest_ini_options(path))
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(path, encoding="utf-8")
        section = "pytest" if path.name == "tox.ini" else "tool:pytest"
        return parser.has_section(section)
    except (AttributeError, TypeError):
        return False


def find_pytest_config(suite_dir: Path) -> Path | None:
    """Return the pytest inifile that governs ``suite_dir``.

    Mirrors pytest's upward search: from the suite directory toward the
    filesystem root, the first directory containing a file that actually
    defines pytest options wins, checked in the order ``pytest.ini``,
    ``pyproject.toml``, ``tox.ini``, ``setup.cfg`` within the directory.
    """
    current = suite_dir.resolve()
    while True:
        for name in _INI_CANDIDATES:
            candidate = current / name
            if candidate.is_file() and _counts_as_pytest_config(candidate):
                return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def read_addopts(config_path: Path | None) -> str:
    """Return the effective ``addopts`` string from a pytest config file."""
    options = _pytest_options(config_path)
    addopts = options.get("addopts", "")
    if isinstance(addopts, str):
        return addopts
    if isinstance(addopts, list) and all(isinstance(item, str) for item in addopts):
        return " ".join(addopts)
    raise ValueError("pyproject addopts must be a string or a list of strings")


def read_discovery_options(config_path: Path | None) -> dict[str, list[str]]:
    """The candidate's ini-level test-discovery settings.

    Only the keys this check resets in the reference run are returned,
    and only when the config actually sets them; an unset key means
    pytest's default applies. A value that is neither a string nor a
    list of strings is a malformed config and raises ``ValueError``.
    """
    options = _pytest_options(config_path)
    found: dict[str, list[str]] = {}
    for key in _DISCOVERY_DEFAULTS:
        if key in options:
            found[key] = _as_str_list(options[key])
    return found


def reference_discovery_overrides(
    config_path: Path | None, suite_name: str
) -> tuple[list[str], dict]:
    """``-o`` overrides resetting discovery options to pytest defaults.

    Returns ``(overrides, detail)``: the ``key=value`` strings to pass
    to the reference collection, and a per-key record of the candidate
    value, the reference value, and any allowlisted additions, for the
    receipt. A key needs no override when the candidate leaves it at
    the default (or unset, which is the default) and the allowlist
    adds nothing to it. Note the reference value is the pytest default
    plus allowlisted exclusions -- never the candidate's own list, so
    a candidate that adds a new exclusion to a discovery option is
    still detected as an omission.
    """
    candidate = read_discovery_options(config_path)
    overrides: list[str] = []
    detail: dict[str, dict] = {}
    for key, default in _DISCOVERY_DEFAULTS.items():
        allowed = [
            value
            for value in _DISCOVERY_ALLOWLIST.get((suite_name, key), [])
            if value not in default
        ]
        reference = [*default, *allowed]
        detail[key] = {
            "candidate": candidate.get(key, default),
            "reference": reference,
            "allowlisted": allowed,
        }
        candidate_value = candidate.get(key)
        if candidate_value is None:
            needs_override = reference != default
        else:
            needs_override = candidate_value != reference
        if needs_override:
            overrides.append(f"{key}={' '.join(reference)}")
    return overrides, detail


def _filter_short_cluster(
    token: str, next_token: str | None
) -> tuple[list[str], bool]:
    """Filter one bundled short-option token (``-qk``, ``-vkfoo``).

    Walks the characters after ``-`` with pytest's short-flag table:
    a flag that takes an argument consumes the rest of the token, or
    the next token when the rest is empty. Selection flags (``-k``,
    ``-m``) and ``-o`` overrides are dropped with their argument;
    every other flag is kept with its argument. Returns
    ``(kept_tokens, consumed_next)``: the tokens that survive (the
    rebuilt cluster, plus the next token when it is the argument of a
    kept flag) and whether the next token was consumed.
    """
    chars = token[1:]
    kept_chars: list[str] = []
    index = 0
    while index < len(chars):
        char = chars[index]
        if char in _SHORT_SELECTION_FLAGS or char == "o":
            # Drop the flag and its argument (the rest of the token,
            # or the next token when the rest is empty).
            if index + 1 < len(chars):
                break
            kept = ["-" + "".join(kept_chars)] if kept_chars else []
            return kept, True
        if char in _SHORT_ARG_FLAGS:
            # Kept flag with an argument: attached (rest of token) or
            # separate (the next token).
            if index + 1 < len(chars):
                kept_chars.extend(chars[index:])
                break
            kept_chars.append(char)
            kept = ["-" + "".join(kept_chars)] if kept_chars else []
            if next_token is not None:
                kept.append(next_token)
            return kept, True
        kept_chars.append(char)
        index += 1
    kept = ["-" + "".join(kept_chars)] if kept_chars else []
    return kept, False


def filter_selection_options(addopts: str) -> str:
    """Return ``addopts`` with test-selection options removed.

    Everything else is preserved verbatim (including verbosity and
    ``--continue-on-collection-errors``) so the reference collection
    behaves identically to the actual collection except for selection.
    Short flags are parsed as clusters: a selection flag consumes the
    remainder of its cluster as its argument (``-qk 'not x'`` drops
    the ``-k`` and the expression; ``-vkfoo`` drops ``kfoo``), so a
    bundled flag cannot smuggle a selection past the filter.
    """
    try:
        tokens = shlex.split(addopts)
    except ValueError as exc:
        raise ValueError(f"addopts cannot be parsed: {exc}") from exc
    kept: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _SELECTION_WITH_ARG or token in _OVERRIDE_WITH_ARG:
            index += 2  # drop the option and its argument
            continue
        if token.startswith(_SELECTION_EQUALS) or token.startswith(_OVERRIDE_EQUALS):
            index += 1  # argument is inline after '='
            continue
        if (
            token.startswith("-")
            and not token.startswith("--")
            and len(token) > 2
        ):
            # Bundled short-option cluster, e.g. ``-qk`` or ``-vkfoo``.
            next_token = tokens[index + 1] if index + 1 < len(tokens) else None
            cluster_kept, consumed_next = _filter_short_cluster(token, next_token)
            kept.extend(cluster_kept)
            index += 2 if consumed_next else 1
            continue
        kept.append(token)
        index += 1
    return shlex.join(kept)


_NODEID_RE = re.compile(r"^(.+\.py)::(.+)$")
_FILE_COUNT_RE = re.compile(r"^(.+\.py): (\d+)$")
# The tree-format tags. The name capture is greedy up to the line's
# final ``>`` because a parametrized name can itself contain ``>``
# (for example ``test_x[<lambda>0]``); a ``[^>]+`` capture would
# truncate it and the reconstructed node id would never match the
# flat one. ``unittest`` cases appear as ``<UnitTestCase>`` /
# ``<TestCaseFunction>`` and are treated exactly like classes and
# functions: a missing class segment would misbuild every one of
# their node ids.
_TREE_FUNCTION_RE = re.compile(r"^(\s*)<(?:Function|TestCaseFunction) (.+)>\s*$")
_TREE_MODULE_RE = re.compile(r"^(\s*)<Module (.+)>\s*$")
_TREE_CLASS_RE = re.compile(r"^(\s*)<(?:Class|UnitTestCase) (.+)>\s*$")
_TREE_DIR_RE = re.compile(r"^(\s*)<(?:Dir|Package) (.+)>\s*$")
_SUMMARY_RE = re.compile(r"(\d+) tests? collected")
_ITEMS_RE = re.compile(r"collected (\d+) items?\b")
_ERROR_FILE_RE = re.compile(r"^ERROR (\S+\.py)\s*$")
_ERROR_COLLECTING_RE = re.compile(r"ERROR collecting (\S+\.py)")


def parse_collection_output(text: str, root_name: str | None = None) -> dict:
    """Parse ``pytest --collect-only`` stdout into an inventory.

    Handles the three formats pytest emits depending on verbosity:
    one node id per line (``-q``), the indented collection tree
    (default verbosity or ``-v``), and one ``file: count`` line per
    file (``-qq``). ``root_name`` is the collection root directory's
    own name, as printed by the tree format's top ``<Dir>`` entry; it
    is not part of the node ids, which are relative to that root.
    """
    nodes: set[str] = set()
    file_counts: dict[str, int] = {}
    error_files: set[str] = set()
    collected: int | None = None
    # Stack of (indent, kind, name) for the tree format. ``kind`` is
    # "dir", "module", or "class"; the module entry holds the full
    # relative path of the test module being listed.
    stack: list[tuple[int, str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _SUMMARY_RE.search(line)
        if match:
            collected = int(match.group(1))
        items_match = _ITEMS_RE.search(line)
        if items_match:
            # The verbose/tree "collecting ... collected N items" line
            # is the only count the tree format prints.
            collected = int(items_match.group(1))
        if "no tests collected" in line:
            collected = 0
        error_match = _ERROR_FILE_RE.match(line)
        if error_match:
            error_files.add(error_match.group(1))
            continue
        collecting_match = _ERROR_COLLECTING_RE.search(line)
        if collecting_match:
            error_files.add(collecting_match.group(1))
            continue
        if line.startswith(("SKIPPED", "ERROR", "===")):
            continue
        count_match = _FILE_COUNT_RE.match(line)
        if count_match and "::" not in line:
            file_counts[count_match.group(1)] = int(count_match.group(2))
            continue
        node_match = _NODEID_RE.match(line)
        if node_match and not line.startswith("<"):
            # The ``<`` guard keeps a tree-format line from matching
            # as a node id: a parametrized name can itself contain a
            # ``.py::`` fragment (for example a param value of
            # ``"pytest tests/test_x.py::test_waived_case"``), and the
            # raw ``<Function ...>`` line would otherwise be stored
            # verbatim as a bogus node id instead of being parsed as
            # a tree entry below.
            nodes.add(line)
            continue
        tree_match = _TREE_FUNCTION_RE.match(raw_line)
        if tree_match:
            indent = len(tree_match.group(1))
            func_name = tree_match.group(2)
            while stack and stack[-1][0] >= indent:
                stack.pop()
            module_path = ""
            class_names: list[str] = []
            for _, kind, name in stack:
                if kind == "module":
                    module_path = name
                elif kind == "class":
                    class_names.append(name)
            if module_path:
                nodes.add("::".join([module_path, *class_names, func_name]))
            continue
        for pattern, kind in (
            (_TREE_DIR_RE, "dir"),
            (_TREE_MODULE_RE, "module"),
            (_TREE_CLASS_RE, "class"),
        ):
            tree_match = pattern.match(raw_line)
            if tree_match:
                indent = len(tree_match.group(1))
                name = tree_match.group(2)
                while stack and stack[-1][0] >= indent:
                    stack.pop()
                if kind == "dir":
                    stack.append((indent, kind, name))
                elif kind == "module":
                    prefix = "/".join(
                        item_name
                        for _, item_kind, item_name in stack
                        if item_kind == "dir" and item_name != root_name
                    )
                    full = f"{prefix}/{name}" if prefix else name
                    stack.append((indent, kind, full))
                else:
                    stack.append((indent, kind, name))
                break
    if nodes:
        form = "nodeids"
    elif file_counts:
        form = "counts"
    else:
        form = "unknown"
    return {
        "nodes": nodes,
        "file_counts": file_counts,
        "error_files": sorted(error_files),
        "collected": collected,
        "format": form,
    }


def run_collection(
    python_bin: str,
    suite_dir: Path,
    *,
    filtered_addopts: str | None,
    timeout: int,
    extra_overrides: list[str] | None = None,
    root_name: str | None = None,
) -> dict:
    """Collect one inventory; ``filtered_addopts=None`` is the actual run.

    ``extra_overrides`` are additional ``-o key=value`` overrides for
    the reference run only (the discovery resets). Both runs append
    ``-v`` so the collection prints node ids (flat or tree format)
    rather than per-file counts: only node ids can pair regenerated
    parameter values, and a ``-qq`` in a candidate's ``addopts``
    would otherwise silently degrade the comparison to counts.
    ``PYTEST_ADDOPTS`` is scrubbed from the child environment: it
    applies to both collections identically and would otherwise be an
    invisible narrowing.
    """
    argv = [
        python_bin,
        "-m",
        "pytest",
        "tests",
        "--collect-only",
        "-v",
        "-p",
        "no:cacheprovider",
        "--continue-on-collection-errors",
    ]
    if filtered_addopts is not None:
        argv += ["-o", f"addopts={filtered_addopts}"]
    for override in extra_overrides or []:
        argv += ["-o", override]
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    try:
        proc = subprocess.run(
            argv,
            cwd=suite_dir,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": argv,
            "returncode": None,
            "stdout": "",
            "stderr": f"collection timed out after {timeout}s: {exc}",
            "inventory": parse_collection_output("", root_name=root_name or suite_dir.name),
            "timed_out": True,
        }
    except OSError as exc:
        # The pytest executable itself could not start (missing binary,
        # missing module): no inventory at all, fail closed as ERROR.
        return {
            "argv": argv,
            "returncode": None,
            "stdout": "",
            "stderr": f"collection could not start: {exc}",
            "inventory": parse_collection_output("", root_name=root_name or suite_dir.name),
            "timed_out": False,
        }
    return {
        "argv": argv,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "inventory": parse_collection_output(proc.stdout, root_name=root_name or suite_dir.name),
        "timed_out": False,
    }


def _base_node(nodeid: str) -> str:
    """The node id without its ``[...]`` parametrization.

    A few tests parametrize over values generated at import time (for
    example ``secrets.token_urlsafe`` in
    ``tests/teacher_os_web/test_teacher_os_api.py``), so the same test
    legitimately carries a different parameter suffix on every
    collection. Pairing by base distinguishes that regeneration from a
    genuine omission.
    """
    return nodeid.split("[", 1)[0]


def _pair_regenerated(
    missing: list[str], extra: list[str]
) -> tuple[list[str], list[str], list[str]]:
    """Pair missing/extra nodes that share a base node id.

    Returns ``(unpaired_missing, unpaired_extra, regenerated_bases)``.
    A missing node paired with an extra node on the same base is the
    same test collected with a regenerated parameter value, not an
    omission; an unpaired missing node is a real omission.
    """
    missing_by_base: dict[str, list[str]] = {}
    for node in missing:
        missing_by_base.setdefault(_base_node(node), []).append(node)
    extra_by_base: dict[str, list[str]] = {}
    for node in extra:
        extra_by_base.setdefault(_base_node(node), []).append(node)
    unpaired_missing: list[str] = []
    unpaired_extra: list[str] = []
    regenerated_bases: list[str] = []
    for base in sorted(set(missing_by_base) | set(extra_by_base)):
        gone = missing_by_base.get(base, [])
        new = extra_by_base.get(base, [])
        paired = min(len(gone), len(new))
        if paired:
            regenerated_bases.append(base)
        unpaired_missing.extend(gone[paired:])
        unpaired_extra.extend(new[paired:])
    return sorted(unpaired_missing), sorted(unpaired_extra), regenerated_bases


def _as_counts(inventory: dict) -> dict:
    """Normalize an inventory to per-file counts.

    A counts-format inventory already carries them; a node-format one
    derives them by counting nodes per file. Used when the two runs
    print in different formats (different verbosity), so the comparison
    still works instead of mistaking an empty count map for an omission.
    """
    counts = dict(inventory["file_counts"])
    if not counts:
        for node in inventory["nodes"]:
            path = node.split("::", 1)[0]
            counts[path] = counts.get(path, 0) + 1
    return {"file_counts": counts}


def check_suite(
    python_bin: str,
    suite_dir: Path,
    suite_name: str,
    *,
    timeout: int = 300,
) -> dict:
    """Compare actual vs unfiltered collection for one suite."""
    config_path: Path | None = None
    try:
        config_path = find_pytest_config(suite_dir)
        addopts = read_addopts(config_path)
        filtered = filter_selection_options(addopts)
        discovery_overrides, discovery_detail = reference_discovery_overrides(
            config_path, suite_name
        )
    except (ValueError, AttributeError, TypeError, OSError, configparser.Error) as exc:
        return _receipt(
            suite_name=suite_name,
            suite_dir=suite_dir,
            verdict="ERROR",
            config_path=config_path,
            error=f"cannot establish the reference collection: {exc}",
        )
    # The tree format's top <Dir> is the pytest rootdir: the governing
    # config file's directory when one exists, else the suite directory.
    root_name = (
        config_path.parent.name if config_path is not None else suite_dir.name
    )
    actual = run_collection(
        python_bin, suite_dir, filtered_addopts=None, timeout=timeout,
        root_name=root_name,
    )
    reference = run_collection(
        python_bin, suite_dir, filtered_addopts=filtered, timeout=timeout,
        extra_overrides=discovery_overrides, root_name=root_name,
    )
    base = _receipt(
        suite_name=suite_name,
        suite_dir=suite_dir,
        verdict="COMPLETE",
        config_path=config_path,
        addopts=addopts,
        filtered_addopts=filtered,
        discovery=discovery_detail,
        actual=actual,
        reference=reference,
    )
    if actual["timed_out"] or reference["timed_out"]:
        base["verdict"] = "ERROR"
        base["error"] = "a collection run timed out; completeness cannot be established"
        return base
    actual_inv = actual["inventory"]
    reference_inv = reference["inventory"]
    if (
        actual_inv["collected"] is None
        and reference_inv["collected"] is None
        and not actual_inv["nodes"]
        and not reference_inv["nodes"]
        and not actual_inv["file_counts"]
        and not reference_inv["file_counts"]
    ):
        base["verdict"] = "ERROR"
        detail = (
            "neither collection run reported a test inventory; "
            "collection failed before any test was listed"
        )
        stderr_tail = (actual.get("stderr", "") or reference.get("stderr", ""))[-500:]
        if stderr_tail.strip():
            detail += f"; collection stderr: {stderr_tail.strip()}"
        base["error"] = detail
        return base
    if actual_inv["format"] == "counts" or reference_inv["format"] == "counts":
        return _compare_counts(base, _as_counts(actual_inv), _as_counts(reference_inv))
    # An empty inventory is only evidence of a narrowing when the
    # collection itself ran cleanly (pytest exit 0, or 5 for "no tests
    # collected"). Any other outcome means the collection failed and
    # the comparison cannot be established.
    if (
        not actual_inv["nodes"]
        and reference_inv["nodes"]
        and actual.get("returncode") not in (0, 5)
    ):
        base["verdict"] = "ERROR"
        detail = "the candidate collection produced no test inventory"
        stderr_tail = (actual.get("stderr", ""))[-500:]
        if stderr_tail.strip():
            detail += f"; collection stderr: {stderr_tail.strip()}"
        base["error"] = detail
        return base
    if (
        not reference_inv["nodes"]
        and actual_inv["nodes"]
        and reference.get("returncode") not in (0, 5)
    ):
        base["verdict"] = "ERROR"
        base["error"] = "the unfiltered reference collection produced no test inventory"
        return base
    missing = sorted(reference_inv["nodes"] - actual_inv["nodes"])
    extra = sorted(actual_inv["nodes"] - reference_inv["nodes"])
    unpaired_missing, unpaired_extra, regenerated_bases = _pair_regenerated(missing, extra)
    base["actual_count"] = len(actual_inv["nodes"])
    base["reference_count"] = len(reference_inv["nodes"])
    base["missing"] = unpaired_missing[:_MISSING_CAP]
    base["missing_count"] = len(unpaired_missing)
    base["extra"] = unpaired_extra[:_MISSING_CAP]
    base["extra_count"] = len(unpaired_extra)
    base["regenerated_param_count"] = len(missing) - len(unpaired_missing)
    base["regenerated_param_bases"] = regenerated_bases[:_MISSING_CAP]
    if unpaired_missing:
        base["verdict"] = "INCOMPLETE"
        base["error"] = (
            f"{len(unpaired_missing)} test(s) in the unfiltered collection were not "
            "selected by the candidate configuration; test selection is "
            "narrowed by addopts or an ini discovery option"
        )
    elif unpaired_extra:
        base["verdict"] = "ERROR"
        base["error"] = (
            f"{len(unpaired_extra)} test(s) were collected by the candidate "
            "configuration but not by the unfiltered reference; the "
            "comparison cannot be trusted"
        )
    return base


def _compare_counts(base: dict, actual_inv: dict, reference_inv: dict) -> dict:
    actual_counts = actual_inv["file_counts"]
    reference_counts = reference_inv["file_counts"]
    missing_files = {
        path: {"reference": reference_counts[path], "actual": actual_counts.get(path, 0)}
        for path in reference_counts
        if actual_counts.get(path, 0) < reference_counts[path]
    }
    extra_files = {
        path: {"reference": reference_counts.get(path, 0), "actual": count}
        for path, count in actual_counts.items()
        if count > reference_counts.get(path, 0)
    }
    base["actual_count"] = sum(actual_counts.values())
    base["reference_count"] = sum(reference_counts.values())
    base["missing_files"] = missing_files
    base["missing_count"] = sum(
        item["reference"] - item["actual"] for item in missing_files.values()
    )
    base["extra_files"] = extra_files
    base["extra_count"] = sum(
        item["actual"] - item["reference"] for item in extra_files.values()
    )
    if missing_files:
        base["verdict"] = "INCOMPLETE"
        base["error"] = (
            f"{len(missing_files)} test file(s) collected fewer tests "
            "under the candidate configuration than unfiltered; test "
            "selection is narrowed by addopts or an ini discovery option"
        )
    elif extra_files:
        base["verdict"] = "ERROR"
        base["error"] = (
            "the candidate configuration collected more tests per file "
            "than the unfiltered reference; the comparison cannot be trusted"
        )
    return base


def _receipt(
    *,
    suite_name: str,
    suite_dir: Path,
    verdict: str,
    config_path: Path | None,
    error: str | None = None,
    addopts: str | None = None,
    filtered_addopts: str | None = None,
    discovery: dict | None = None,
    actual: dict | None = None,
    reference: dict | None = None,
) -> dict:
    receipt: dict = {
        "schema": SCHEMA,
        "suite_name": suite_name,
        "suite_dir": str(suite_dir),
        "verdict": verdict,
        "config_path": str(config_path) if config_path is not None else None,
        "addopts": addopts,
        "filtered_addopts": filtered_addopts,
        "discovery": discovery,
        "actual_count": None,
        "reference_count": None,
        "missing": [],
        "missing_count": 0,
        "extra": [],
        "extra_count": 0,
        "regenerated_param_count": 0,
        "regenerated_param_bases": [],
        "error": error,
    }
    if actual is not None:
        receipt["actual_count"] = actual["inventory"]["collected"]
        receipt["actual_returncode"] = actual["returncode"]
        receipt["actual_command"] = " ".join(actual["argv"])
        receipt["actual_error_files"] = actual["inventory"]["error_files"]
        receipt["actual_format"] = actual["inventory"]["format"]
    if reference is not None:
        receipt["reference_count"] = reference["inventory"]["collected"]
        receipt["reference_returncode"] = reference["returncode"]
        receipt["reference_command"] = " ".join(reference["argv"])
        receipt["reference_error_files"] = reference["inventory"]["error_files"]
        receipt["reference_format"] = reference["inventory"]["format"]
    return receipt


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", required=True, type=Path)
    parser.add_argument("--suite-name", required=True)
    parser.add_argument("--python-bin", default="python3")
    parser.add_argument("--receipt", type=Path, default=None)
    parser.add_argument("--timeout", type=int, default=300)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = check_suite(
        args.python_bin, args.suite_dir, args.suite_name, timeout=args.timeout
    )
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.receipt is not None:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(text, encoding="utf-8")
    print(text, end="")
    return {"COMPLETE": 0, "INCOMPLETE": 1, "ERROR": 2}[result["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
