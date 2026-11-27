from collections import Counter
from decimal import Decimal
import hashlib
from zipfile import ZipFile

import pytest

from scripts.ci_perf.root_shard_replay import read_root, replay


PATHS = ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]


def _xml(cases: str, count: int, failures: int = 0) -> bytes:
    return (
        f'<testsuites><testsuite tests="{count}" errors="0" failures="{failures}">'
        f"{cases}</testsuite></testsuites>"
    ).encode()


def _case(module: str, seconds: str = "1", name: str = "test_x") -> str:
    return f'<testcase classname="tests.test_{module}" name="{name}" time="{seconds}"/>'


def test_balance_is_deterministic_and_keeps_whole_modules():
    raw = _xml(_case("a", "4") + _case("a", "1", "test_y") + _case("b", "3") + _case("c", "2"), 4)
    lanes = replay(raw, PATHS, 2)
    assert lanes == replay(raw, list(reversed(PATHS)), 2)
    assert Counter(p for lane in lanes for p in lane.files) == Counter(PATHS)
    assert [lane.cases for lane in lanes] == [2, 2]
    assert [lane.testcase_seconds for lane in lanes] == [Decimal(5), Decimal(5)]


def test_classes_and_collection_skips_map_to_their_modules():
    class_case = _case("a.TestCases", "1")
    skip = '<testcase classname="" name="tests.test_b" time="0"><skipped/></testcase>'
    lanes = replay(_xml(class_case + skip, 2), PATHS, 2)
    assert [lane.files for lane in lanes] == [["tests/test_a.py"], ["tests/test_b.py"]]
    assert [lane.cases for lane in lanes] == [1, 1]


@pytest.mark.parametrize(
    "raw, reason",
    [
        (_xml(_case("a") + _case("b"), 3), "counts differ"),
        (_xml(_case("a") + _case("a"), 2), "duplicate testcase"),
        (_xml(_case("a") + _case("missing"), 2), "tracked module"),
        (_xml(_case("a") + _case("b", "NaN"), 2), "invalid testcase duration"),
        (_xml(_case("a") + _case("b"), 2, 1), "suite failed"),
        (b"<!DOCTYPE testsuite>", "invalid or oversized"),
    ],
)
def test_unusable_inventory_is_rejected(raw, reason):
    with pytest.raises(ValueError, match=reason):
        replay(raw, PATHS, 2)


def test_archive_requires_expected_digest(tmp_path):
    path = tmp_path / "evidence.zip"
    xml = _xml(_case("a") + _case("b"), 2)
    with ZipFile(path, "w") as archive:
        archive.writestr("root.xml", xml)
    assert read_root(path, hashlib.sha256(path.read_bytes()).hexdigest()) == xml
    with pytest.raises(ValueError, match="digest did not match"):
        read_root(path, "0" * 64)
