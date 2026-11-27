import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import zlib
from collections import Counter
from decimal import localcontext
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from scripts.ci_perf import root_shard_replay as model

PATHS = ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]
AB = {
    ("tests.test_a", "test_x"): PATHS[0],
    ("tests.test_b", "test_x"): PATHS[1],
}


def _xml(cases: str, count: int, failures: int = 0) -> bytes:
    return (
        f'<testsuites><testsuite tests="{count}" errors="0" failures="{failures}">'
        f"{cases}</testsuite></testsuites>"
    ).encode()


def _case(module: str, seconds: str = "1", name: str = "test_x") -> str:
    return f'<testcase classname="tests.test_{module}" name="{name}" time="{seconds}"/>'


def _archive(path: Path, members) -> str:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, body in members:
            archive.writestr(name, body)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _commit(repo: Path) -> str:
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=QA",
        "-c",
        "user.email=qa@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def reference(tmp_path):
    repo = tmp_path / "repo with spaces"
    (repo / "tests").mkdir(parents=True)
    _git(repo, "init", "-q")
    for path in PATHS:
        (repo / path).write_text("def test_x(): pass\n")
    (repo / "tests/extra notes.txt").write_text("not Python")
    (repo / "not_root.py").write_text("not root")
    head = _commit(repo)
    archive = tmp_path / "evidence with spaces.zip"
    archive_hash = _archive(archive, [("root.xml", _xml(_case("a") + _case("b"), 2))])
    inventory = tmp_path / "case inventory.json"
    record = {
        "schema": model.SCHEMA,
        "repository": model.REPOSITORY,
        "source_head": head,
        "archive_sha256": archive_hash,
        "run_id": 123,
        "run_attempt": 1,
        "artifact_id": 456,
        "cases": [[*key, path] for key, path in AB.items()],
    }
    args = [
        "--archive",
        str(archive),
        "--archive-sha256",
        archive_hash,
        "--source-head",
        head,
        "--repo",
        str(repo),
        "--shards",
        "2",
        "--reference",
        str(inventory),
        "--reference-sha256",
        "",
    ]
    _update_inventory(inventory, record, args)
    return repo, head, archive, inventory, record, args


def _update_inventory(path, record, args):
    raw = json.dumps(record).encode()
    path.write_bytes(raw)
    args[-1] = hashlib.sha256(raw).hexdigest()


def test_balance_is_deterministic_and_keeps_whole_modules():
    raw = _xml(
        _case("a", "4") + _case("a", "1", "test_y") + _case("b", "3") + _case("c", "2"),
        4,
    )
    inventory = {
        **AB,
        ("tests.test_a", "test_y"): PATHS[0],
        ("tests.test_c", "test_x"): PATHS[2],
    }
    lanes = model.replay(raw, PATHS, 2, inventory)
    assert lanes == model.replay(raw, list(reversed(PATHS)), 2, inventory)
    assert [lane.files for lane in lanes] == [[PATHS[0]], PATHS[1:]]
    assert Counter(p for lane in lanes for p in lane.files) == Counter(PATHS)
    assert [lane.cases for lane in lanes] == [2, 2]
    assert [lane.testcase_seconds for lane in lanes] == ["5", "5"]


def test_classes_and_collection_skips_map_to_their_modules():
    class_case = _case("a.TestOuter.TestInner", "1", name="test_x[one.1]")
    skip = '<testcase classname="" name="tests.test_b" time="0"><skipped/></testcase>'
    expected = {
        ("tests.test_a.TestOuter.TestInner", "test_x[one.1]"): PATHS[0],
        ("", "tests.test_b"): PATHS[1],
    }
    lanes = model.replay(_xml(class_case + skip, 2), PATHS, 2, expected)
    assert [lane.files for lane in lanes] == [[PATHS[0]], [PATHS[1]]]
    assert [lane.cases for lane in lanes] == [1, 1]


@pytest.mark.parametrize(
    "raw, reason",
    [
        (_xml(_case("a") + _case("b"), 3), "junit-count-mismatch"),
        (_xml(_case("a") + _case("a"), 2), "duplicate-testcase-identity"),
        (_xml(_case("a") + _case("missing"), 2), "unmapped-testcase"),
        (_xml(_case("a") + _case("b", "NaN"), 2), "invalid-testcase-duration"),
        (_xml(_case("a") + _case("b"), 2, 1), "reference-root-failed"),
        (b"<!DOCTYPE testsuite>", "prohibited-xml-declaration"),
    ],
)
def test_unusable_inventory_is_rejected(raw, reason):
    with pytest.raises(model.Refusal, match=reason):
        model.replay(raw, PATHS, 2, AB)


def test_archive_requires_expected_digest(tmp_path):
    path = tmp_path / "evidence.zip"
    xml = _xml(_case("a") + _case("b"), 2)
    digest = _archive(path, [("root.xml", xml)])
    assert model.read_root(path, digest) == xml
    with pytest.raises(model.Refusal, match="evidence-digest-mismatch"):
        model.read_root(path, "0" * 64)


def test_cli_outputs_the_same_model_across_processes(reference):
    *_, args = reference
    cmd = [sys.executable, "-m", "scripts.ci_perf.root_shard_replay", *args]
    one = subprocess.check_output(cmd, env={**os.environ, "PYTHONHASHSEED": "1"})
    two = subprocess.check_output(cmd, env={**os.environ, "PYTHONHASHSEED": "2"})
    assert one == two
    payload = json.loads(one)
    assert payload == {
        "report_kind": "historical-testcase-duration-model-only",
        "source_head": args[args.index("--source-head") + 1],
        "archive_sha256": args[args.index("--archive-sha256") + 1],
        "shards": [
            {"files": [path], "cases": 1, "testcase_seconds": "1"} for path in PATHS[:2]
        ],
    }


def test_same_paths_on_another_commit_are_not_reference_binding(reference, capsys):
    repo, head, *_, args = reference
    (repo / PATHS[0]).write_text("def test_x(): assert True\n")
    new_head = _commit(repo)
    assert new_head != head
    assert model.tracked_test_paths(repo, head) == model.tracked_test_paths(
        repo, new_head
    )
    args[args.index("--source-head") + 1] = new_head
    assert model.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip().endswith("invalid-reference-binding")


def test_self_consistent_junit_is_not_independent_inventory(reference, capsys):
    _, _, _, inventory, record, args = reference
    record["cases"].append(["tests.test_c", "test_x", PATHS[2]])
    _update_inventory(inventory, record, args)
    assert model.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip().endswith("incomplete-reference-inventory")


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", "other"),
        ("repository", "other/repo"),
        ("source_head", "a" * 40),
        ("archive_sha256", "f" * 64),
        ("run_id", True),
        ("run_attempt", 0),
        ("artifact_id", "1"),
        ("cases", []),
        ("cases", [["tests.test_a", "test_x", "../bad.py"]]),
    ],
)
def test_reference_rejects_invalid_contract(reference, capsys, field, value):
    _, _, _, path, record, args = reference
    record[field] = value
    _update_inventory(path, record, args)
    assert model.main(args) == 2
    assert capsys.readouterr().out == ""


def test_reference_digest_wrong_or_missing(reference, capsys):
    *_, args = reference
    args[-1] = "0" * 64
    assert model.main(args) == 2
    assert capsys.readouterr().err.strip().endswith("evidence-digest-mismatch")
    assert model.main(args[:-4]) == 2
    assert capsys.readouterr().err.strip().endswith("invalid-arguments")


def test_git_commit_modes_and_nul_scope(reference):
    repo, head, *_ = reference
    assert model.tracked_test_paths(repo, head) == PATHS
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    with pytest.raises(model.Refusal, match="source-head-not-commit"):
        model.tracked_test_paths(repo, tree)
    assert model.tracked_test_paths(repo / "tests", head) == PATHS
    (repo / "tests/test space.py").write_text("pass\n")
    with_space = _commit(repo)
    assert "tests/test space.py" in model.tracked_test_paths(repo, with_space)
    (repo / "tests/test_link.py").symlink_to("test_a.py")
    with pytest.raises(model.Refusal, match="nonregular-test-path"):
        model.tracked_test_paths(repo, _commit(repo))


@pytest.mark.parametrize(
    "listing",
    [
        b"",
        b"bad record\0",
        b"100644 blob " + b"a" * 40 + b"\tother.py\0",
        b"100644 blob " + b"a" * 40 + b"\ttests/\xff.py\0",
        b"100644 blob " + b"a" * 40 + b"\ttests/test_a.py",
    ],
)
def test_git_listing_requires_a_canonical_nonempty_inventory(listing, monkeypatch):
    head = "a" * 40
    outputs = iter([b"a" * 40 + b"\n", b"commit\n", listing])
    monkeypatch.setattr(model, "_git", lambda *_: next(outputs))
    with pytest.raises(model.Refusal, match="invalid-git-inventory"):
        model.tracked_test_paths(Path("."), head)


@pytest.mark.parametrize(
    "error",
    [
        subprocess.TimeoutExpired("git", 15),
        subprocess.CalledProcessError(128, "git"),
        PermissionError("sensitive local path"),
    ],
)
def test_git_error_has_stable_reason(reference, monkeypatch, capsys, error):
    *_, args = reference

    def fail(*args, **kwargs):
        assert isinstance(args[0], list) and not kwargs.get("shell", False)
        raise error

    monkeypatch.setattr(model.subprocess, "run", fail)
    assert model.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "root shard timing replay refused: git-read-failed"


@pytest.mark.parametrize(
    "wrap",
    [
        lambda s: b"<unexpected>" + s + b"</unexpected>",
        lambda s: s.replace(b"<testsuites>", b'<testsuites failures="1">'),
        lambda s: s.replace(b"testsuite tests=", b'testsuite skipped="1" tests='),
        lambda s: s.replace(
            b"</testsuites>",
            b'<testcase name="outside"><failure/></testcase></testsuites>',
        ),
        lambda s: s.replace(
            b'time="1"/>', b'time="1"><result><error/></result></testcase>', 1
        ),
        lambda s: s.replace(b'time="1"/>', b'time="1"><failure/></testcase>', 1),
        lambda s: s.replace(b'time="1"/>', b'time="1"><error/></testcase>', 1),
        lambda s: s.replace(b'errors="0"', b'errors="1"'),
        lambda s: s.replace(b'errors="0"', b""),
        lambda s: s.replace(b'tests="2"', b'tests="1"'),
        lambda s: s.replace(b'tests="2"', b'tests="-2"'),
        lambda s: s.replace(b'tests="2"', b'tests="two"'),
        lambda s: s.replace(b'tests="2"', b""),
        lambda s: _xml("", 0),
    ],
)
def test_junit_rejects_bad_structure_outcomes_and_counts(wrap):
    xml = _xml(_case("a") + _case("b"), 2)
    with pytest.raises(model.Refusal):
        model.replay(wrap(xml), PATHS, 2, AB)


def test_classless_skips_require_exact_module_identity():
    bogus = "tests.test_b.unlisted"
    raw = _xml(
        _case("a") + f'<testcase name="{bogus}" time="0"><skipped/></testcase>', 2
    )
    inventory = {**AB, ("", bogus): PATHS[1]}
    with pytest.raises(model.Refusal, match="invalid-testcase-module"):
        model.replay(raw, PATHS, 2, inventory)


@pytest.mark.parametrize(
    "seconds",
    [
        "",
        "-1",
        "NaN",
        "Infinity",
        "-Infinity",
        "abc",
        "1e2",
        "1e1000000",
        "1e-1000030",
        "1.00000000000000000000000000001",
        "10000000",
        ".1",
        None,
    ],
)
def test_duration_invalid_or_out_of_bounds_refuses(seconds):
    b = (
        _case("b", seconds)
        if seconds is not None
        else _case("b").replace(' time="1"', "")
    )
    with pytest.raises(model.Refusal, match="invalid-testcase-duration"):
        model.replay(_xml(_case("a") + b, 2), PATHS, 2, AB)


def test_durations_sum_exactly_independent_of_context():
    raw = _xml(
        _case("a", "0.100000001")
        + _case("a", "0.200000002", "test_y")
        + _case("b", "9999999.999999999"),
        3,
    )
    inventory = {**AB, ("tests.test_a", "test_y"): PATHS[0]}
    with localcontext() as ctx:
        ctx.prec = 1
        lanes = model.replay(raw, PATHS, 2, inventory)
    assert lanes == model.replay(raw, PATHS, 2, inventory)
    assert [lane.testcase_seconds for lane in lanes] == [
        "9999999.999999999",
        "0.300000003",
    ]


@pytest.mark.parametrize("count", [0, 1, 9, -1, 2.0, True, "2"])
def test_shard_count_validated_at_pure_boundary(count):
    with pytest.raises(model.Refusal, match="invalid-shard-count"):
        model.replay(_xml(_case("a") + _case("b"), 2), PATHS, count, AB)


def test_shard_count_eight_and_insufficient_whole_modules():
    modules = "abcdefgh"
    inventory = {
        (f"tests.test_{key}", "test_x"): f"tests/test_{key}.py" for key in modules
    }
    paths = list(inventory.values())
    one = {("tests.test_a", "test_x"): paths[0], ("tests.test_a", "test_y"): paths[0]}
    lanes = model.replay(
        _xml("".join(_case(key, "0") for key in modules), 8), paths, 8, inventory
    )
    assert [lane.files for lane in lanes] == [[path] for path in paths]
    with pytest.raises(model.Refusal, match="insufficient-whole-modules"):
        model.replay(_xml(_case("a") + _case("a", name="test_y"), 2), paths, 2, one)


@pytest.mark.parametrize(
    "times, files",
    [
        (("0", "0", "0"), [[PATHS[0], PATHS[2]], [PATHS[1]]]),
        (("1", "1", "1"), [[PATHS[0], PATHS[2]], [PATHS[1]]]),
        (("999", "1", "1"), [[PATHS[0]], PATHS[1:]]),
    ],
)
def test_balancer_edge_cases(times, files):
    inventory = {**AB, ("tests.test_c", "test_x"): PATHS[2]}
    raw = _xml("".join(_case(key, time) for key, time in zip("abc", times)), 3)
    assert [lane.files for lane in model.replay(raw, PATHS, 2, inventory)] == files


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be", "utf-16", "utf-32-le"])
def test_xml_requires_canonical_utf8(encoding):
    raw = _xml(_case("a") + _case("b"), 2).decode()
    with pytest.raises(model.Refusal):
        model.replay(('<?xml version="1.0"?>' + raw).encode(encoding), PATHS, 2, AB)


@pytest.mark.parametrize(
    "change",
    [
        lambda raw: b'<?xml version="1.0" encoding="iso-8859-1"?>' + raw,
        lambda raw: raw + b"\0",
        lambda raw: raw + b"\xff",
        lambda raw: raw[:-5],
    ],
)
def test_xml_refuses_conflicting_declaration_or_bad_bytes(change):
    raw = _xml(_case("a") + _case("b"), 2)
    with pytest.raises(model.Refusal):
        model.replay(change(raw), PATHS, 2, AB)
    assert model.replay(b"\xef\xbb\xbf" + raw, PATHS, 2, AB)


@pytest.mark.parametrize(
    "paths",
    [
        ["other.xml"],
        ["nested/root.xml"],
        ["root.xml", "nested/root.xml"],
        ["root.xml/"],
        ["root.xml", "../unused.txt"],
    ],
)
def test_archive_member_layout(tmp_path, paths):
    path = tmp_path / "report.zip"
    digest = _archive(path, [(n, _xml(_case("a") + _case("b"), 2)) for n in paths])
    with pytest.raises(model.Refusal):
        model.read_root(path, digest)


def test_duplicate_root_archive_refuses(tmp_path):
    path = tmp_path / "report.zip"
    with pytest.warns(UserWarning):
        digest = _archive(path, [("root.xml", "first"), ("root.xml", "second")])
    with pytest.raises(model.Refusal, match="invalid-archive-member"):
        model.read_root(path, digest)


@pytest.mark.parametrize("mode", [stat.S_IFDIR, stat.S_IFLNK])
def test_root_zip_member_must_be_regular(tmp_path, mode):
    path = tmp_path / "report.zip"
    item = ZipInfo("root.xml")
    item.create_system = 3
    item.external_attr = (mode | 0o644) << 16
    digest = _archive(path, [(item, _xml(_case("a") + _case("b"), 2))])
    with pytest.raises(model.Refusal, match="invalid-root-member"):
        model.read_root(path, digest)


def test_archive_bounds_check_actual_bytes(reference, monkeypatch):
    _, _, path, _, record, _ = reference
    digest = record["archive_sha256"]
    cap = path.stat().st_size
    monkeypatch.setattr(model, "MAX_ARCHIVE", cap)
    raw = model.read_root(path, digest)
    monkeypatch.setattr(model, "MAX_ARCHIVE", cap - 1)
    with pytest.raises(model.Refusal, match="evidence-too-large"):
        model.read_root(path, digest)
    monkeypatch.setattr(model, "MAX_ARCHIVE", cap)
    monkeypatch.setattr(model, "MAX_XML", len(raw) - 1)
    with pytest.raises(model.Refusal, match="invalid-root-size"):
        model.read_root(path, digest)


def test_archive_refuses_actual_read_size_mismatch(reference, monkeypatch):
    _, _, path, _, record, _ = reference
    monkeypatch.setattr(ZipFile, "open", lambda *_, **__: io.BytesIO(b"short"))
    with pytest.raises(model.Refusal, match="invalid-root-size"):
        model.read_root(path, record["archive_sha256"])


@pytest.mark.parametrize(
    "error",
    [
        NotImplementedError("private"),
        RuntimeError("private"),
        EOFError("private"),
        zlib.error("private"),
    ],
)
def test_reader_exceptions_never_escape_cli(reference, capsys, monkeypatch, error):
    *_, args = reference

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(ZipFile, "open", fail)
    assert model.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "root shard timing replay refused: invalid-archive"


def test_input_and_argument_errors_do_not_echo_private_details(reference, capsys):
    *_, args = reference
    args[args.index("--archive") + 1] += "/private-sentinel"
    assert model.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip().endswith("evidence-read-failed")
    args[args.index("--shards") + 1] = "private-sentinel"
    assert model.main(args) == 2
    assert capsys.readouterr().err.strip().endswith("invalid-arguments")


def test_broken_output_is_a_refusal(reference, capsys, monkeypatch):
    *_, args = reference

    def fail(_payload):
        raise BrokenPipeError("sensitive-path")

    monkeypatch.setattr(model, "_write_output", fail)
    assert model.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert (
        captured.err.strip()
        == "root shard timing replay refused: input-or-output-unavailable"
    )


def test_real_pytest_junit_matches_independent_fixture_inventory(
    reference, tmp_path, capsys
):
    repo, _, archive, inventory, record, args = reference
    report = tmp_path / "root.xml"
    # The fixture declares known tests in three files. Separately verify that
    # pytest collects that inventory without using report rows as the reference.
    nodeids = [f"{path}::test_x" for path in PATHS]
    collect = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--collect-only",
            "-p",
            "no:cacheprovider",
            "tests",
        ],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    )
    assert [line for line in collect.stdout.splitlines() if "::" in line] == nodeids
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests",
            f"--junitxml={report}",
        ],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    )
    digest = _archive(archive, [("root.xml", report.read_bytes())])
    record["archive_sha256"] = digest
    record["cases"] = [
        [f"tests.test_{module}", "test_x", path] for module, path in zip("abc", PATHS)
    ]
    args[args.index("--archive-sha256") + 1] = digest
    _update_inventory(inventory, record, args)
    assert model.main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert sorted(path for lane in output["shards"] for path in lane["files"]) == PATHS
    assert sum(lane["cases"] for lane in output["shards"]) == 3


def test_real_closed_pipe_returns_two_without_shutdown_traceback(reference):
    *_, args = reference
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    with os.fdopen(write_fd, "wb", buffering=0) as sink:
        proc = subprocess.run(
            [sys.executable, "-m", "scripts.ci_perf.root_shard_replay", *args],
            stdout=sink,
            check=False,
            stderr=subprocess.PIPE,
            text=True,
        )
    assert proc.returncode == 2
    assert (
        proc.stderr.strip()
        == "root shard timing replay refused: input-or-output-unavailable"
    )


@pytest.mark.parametrize("contents", [b"", b"not zip", None])
def test_empty_malformed_and_truncated_archive(reference, contents):
    _, _, path, _, _, _ = reference
    raw = path.read_bytes()[:-5] if contents is None else contents
    path.write_bytes(raw)
    with pytest.raises(model.Refusal, match="invalid-archive"):
        model.read_root(path, hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize(
    "tracked", [[], [*PATHS, "tests/test_a.py"], [*PATHS, "outside.py"]]
)
def test_empty_duplicate_or_wrong_scope_inventory_refuses(tracked):
    with pytest.raises(model.Refusal):
        model.replay(_xml(_case("a") + _case("b"), 2), tracked, 2, AB)


def test_no_class_requires_skip_and_unnamed_cases_refuse():
    for bad in (
        '<testcase name="tests.test_b" time="1"/>',
        '<testcase classname="tests.test_b" time="1"/>',
    ):
        with pytest.raises(model.Refusal, match="unmapped-testcase"):
            model.replay(_xml(_case("a") + bad, 2), PATHS, 2, AB)
