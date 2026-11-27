import json
from collections import Counter
from hashlib import sha256

import pytest

from scripts.ci_perf import root_shadow as shadow


def report(ids):
    body = "".join(f'<testcase classname="tests.test_{i}" name="test_value"/>' for i in ids)
    return f'<testsuites><testsuite errors="0" failures="0" skipped="0" tests="{len(ids)}">{body}</testsuite></testsuites>'.encode()


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    binding = {"schema": shadow.SCHEMA, "head": "a" * 40, "run": "1", "attempt": "2"}
    paths = [[f"tests/test_{i}.py"] for i in range(4)]
    monkeypatch.setattr(shadow, "tracked_python", lambda: {p for lane in paths for p in lane})
    plan = tmp_path / "plan.json"
    shadow.write_json(plan, dict(binding, lanes=paths))
    runs = tmp_path / "runs"
    runs.mkdir()
    for label in ["0", "1", "2", "3", "serial"]:
        folder = runs / label
        folder.mkdir()
        raw = report(range(4) if label == "serial" else [int(label)])
        (folder / "root.xml").write_bytes(raw)
        shadow.write_json(folder / "receipt.json", dict(
            binding, lane=label, seconds=1.0, subtests=1 if label in ("serial", "0") else None,
            environment_sha256="b" * 64,
            plan_sha256=sha256(plan.read_bytes()).hexdigest(), junit_sha256=sha256(raw).hexdigest(),
        ))
    shadow.write_json(runs / "serial" / "completeness.json", {"verdict": "COMPLETE", "missing_count": 0, "executed_count": 4})
    return plan, runs, binding


def test_partition_is_deterministic_and_file_bound():
    files = [f"tests/test_{i}.py" for i in range(18)]
    lanes = shadow.partition(Counter(files))
    assert len(lanes) == 4
    assert lanes == shadow.partition(Counter(reversed(files)))
    assert sorted(file for lane in lanes for file in lane) == sorted(files)


def test_shadow_parity_passes(evidence):
    result = shadow.compare(*evidence)
    assert result["result"] == "root-parity-only"
    assert result["cases"] == 4


@pytest.mark.parametrize(("change", "code"), [
    ("missing", "wrong-lane-set"), ("extra", "wrong-lane-set"),
    ("head", "lane-binding-mismatch"), ("attempt", "lane-binding-mismatch"),
    ("subtests", "subtest-count-mismatch"), ("env", "lane-environment-mismatch"), ("tampered", "junit-digest-mismatch"),
    ("lane-file", "wrong-file-assignment"), ("completeness", "independent-completeness-mismatch"),
])
def test_non_parity_is_refused(evidence, change, code):
    plan, root, binding = evidence
    path = root / "0" / "receipt.json"
    receipt = json.loads(path.read_text())
    if change == "missing":
        (root / "0").rename(root.parent / "removed")
    elif change == "extra":
        (root / "4").mkdir()
    elif change == "env":
        receipt["environment_sha256"] = "c" * 64
        shadow.write_json(path, receipt)
    elif change in {"head", "attempt", "subtests"}:
        receipt[change] = 2 if change == "subtests" else "wrong"
        shadow.write_json(path, receipt)
    elif change in {"tampered", "lane-file"}:
        raw = report([1])
        (root / "0" / "root.xml").write_bytes(raw)
        if change == "lane-file":
            receipt["junit_sha256"] = sha256(raw).hexdigest()
            shadow.write_json(path, receipt)
    else:
        (root / "serial" / "completeness.json").write_text('{"verdict":"INCOMPLETE"}')
    with pytest.raises(shadow.Refusal, match=code):
        shadow.compare(plan, root, binding)


@pytest.mark.parametrize("payload", [
    b"<!DOCTYPE testsuites><testsuites/>",
    report([1, 1]),
    report([1]).replace(b'tests="1"', b'tests="0"'),
    report([1]).replace(b'failures="0"', b'failures="1"'),
])
def test_invalid_junit_does_not_produce_inventory(payload):
    with pytest.raises(shadow.Refusal):
        shadow.load_junit(payload)
