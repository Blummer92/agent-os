from __future__ import annotations

import pytest

from scripts.agent_os_ci_junit_diff import diff_junit


def _xml(nodes: list[tuple[str, str]]) -> bytes:
    cases = "".join(f'<testcase classname="{c}" name="{n}"/>' for c, n in nodes)
    return (
        f'<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="{len(nodes)}" '
        f'failures="0" errors="0" skipped="0">{cases}</testsuite></testsuites>'
    ).encode()


def test_mapped_replacement_is_machine_verified() -> None:
    out = diff_junit(
        _xml([("m", "old"), ("m", "kept")]),
        _xml([("m", "new"), ("m", "kept")]),
        {"m::old": ["m::new"]},
    )
    assert out["removed"] == ["m::old"]
    assert out["mapped_removed_ids"] == ["m::old"]
    assert out["unmapped_removed_ids"] == []
    assert out["verdict"] == "COMPLETE_WITH_MAPPING"


def test_unmapped_removed_is_incomplete() -> None:
    out = diff_junit(_xml([("m", "old"), ("m", "kept")]), _xml([("m", "kept")]))
    assert out["unmapped_removed_ids"] == ["m::old"]
    assert out["verdict"] == "INCOMPLETE"


def test_phantom_replacement_does_not_map() -> None:
    out = diff_junit(
        _xml([("m", "old")]),
        _xml([("m", "other")]),
        {"m::old": ["m::phantom"]},
    )
    assert out["mapped_removed_ids"] == []
    assert out["unmapped_removed_ids"] == ["m::old"]
    assert out["verdict"] == "INCOMPLETE"


def test_duplicate_nodes_and_count_mismatch_are_rejected() -> None:
    with pytest.raises(ValueError):
        diff_junit(_xml([("m", "t"), ("m", "t")]), _xml([("m", "t")]))
    bad = b'<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="2" failures="0" errors="0" skipped="0"><testcase classname="m" name="t"/></testsuite></testsuites>'
    with pytest.raises(ValueError):
        diff_junit(bad, _xml([("m", "t")]))
