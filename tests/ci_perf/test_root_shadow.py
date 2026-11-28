import json
from collections import Counter
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

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
            binding, lane=label, seconds=12.0 if label == "serial" else (3.0, 1.0, 5.0, 2.0)[int(label)], subtests=1 if label in ("serial", "0") else None,
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
    assert result["passing_subtests"] == 1
    assert result["serial_pytest_seconds"] == 12.0
    assert result["slowest_shard_pytest_seconds"] == 5.0


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


def test_partition_obeys_weight_and_least_load(monkeypatch):
    files = [f"tests/test_{i}.py" for i in range(9)]
    monkeypatch.setattr(shadow, "SELECTED_SLOW_FILES", {files[8]: 1})
    assert shadow.partition(Counter({p: i for i, p in enumerate(files)}))[0] == [files[8]]
    monkeypatch.setattr(shadow, "SELECTED_SLOW_FILES", {})
    counts = Counter(dict(zip(files, (1, 1, 1, 1, 1, 3, 4, 4))))
    assert shadow.partition(counts) == [[files[i] for i in lane] for lane in
                                        ([4, 6], [7], [3, 5], [0, 1, 2])]


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("SHADOW_HEAD", "", "head-invalid"),
    ("SHADOW_HEAD", "a" * 39, "head-invalid"),
    ("SHADOW_HEAD", "z" * 40, "head-invalid"),
    ("GITHUB_RUN_ID", "0", "run-invalid"),
    ("GITHUB_RUN_ID", "text", "run-invalid"),
    ("GITHUB_RUN_ATTEMPT", "0", "run-invalid"),
    ("GITHUB_RUN_ATTEMPT", "text", "run-invalid"),
    ("actual", "b" * 40, "checkout-mismatch"),
])
def test_identity_refuses_invalid_inputs(monkeypatch, field, value, reason):
    for name, good in {"SHADOW_HEAD": "a" * 40, "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "2"}.items():
        monkeypatch.setenv(name, value if field == name else good)
    monkeypatch.setattr(shadow.subprocess, "check_output", lambda *args, **kw:
                        (value if field == "actual" else shadow.os.environ["SHADOW_HEAD"]) + "\n")
    with pytest.raises(shadow.Refusal, match=reason):
        shadow.identity()


def test_plan_rejects_duplicate_collection(tmp_path, monkeypatch):
    paths = [f"tests/test_{i}.py" for i in range(4)]
    ids = [f"{p}::test_value" for p in paths]
    monkeypatch.setattr(shadow, "tracked_python", lambda: set(paths))

    def collect(args, *, plugins):
        assert "--collect-only" in args
        plugins[0].pytest_collection_finish(SimpleNamespace(
            items=[SimpleNamespace(nodeid=n) for n in [*ids, ids[0]]],
        ))
        return 0

    monkeypatch.setattr(pytest, "main", collect)
    output = tmp_path / "plan.json"
    with pytest.raises(shadow.Refusal, match="duplicate-collected-id"):
        shadow.plan(output, {})
    assert not output.exists()


@pytest.mark.parametrize(("name", "tracked"), [
    ("tests/untracked.py::test_value", set()),
    ("elsewhere/test_a.py::test_value", {"elsewhere/test_a.py"}),
])
def test_collection_keeps_only_tracked_root_modules(name, tracked):
    with pytest.raises(shadow.Refusal, match="untracked-collection"):
        shadow.module_path(name, tracked)


@pytest.mark.parametrize(("payload", "reason"), [
    (b"<!DOCTYPE testsuites>" + report([1]), "invalid-junit"),
    (b"<!-- <!ENTITY marker -->" + report([1]), "invalid-junit"),
    (report([1]).replace(b'errors="0"', b'errors="1"'), "junit-not-clean"),
    (report([1, 1]), "duplicate-or-empty-id"),
    (report([1]).replace(b'tests="1"', b'tests="2"'), "junit-count-mismatch"),
    (report([1]).replace(b'skipped="0"', b'skipped="1"'), "junit-count-mismatch"),
    (report([1]).replace(b'"/>', b'"><skipped/><skipped/></testcase>').replace(
        b'skipped="0"', b'skipped="1"'), "invalid-junit"),
    (report([1]).replace(b'"/>', b'"><failure/></testcase>'), "junit-not-clean"),
    (report([1]).replace(b'"/>', b'"><error/></testcase>'), "junit-not-clean"),
    (report([]), "junit-count-mismatch"),
])
def test_parser_checks_exact_invalidity(payload, reason):
    with pytest.raises(shadow.Refusal, match=reason):
        shadow.load_junit(payload)


def test_junit_identity_includes_classname():
    assert set(shadow.load_junit(report([0, 1]))) == {
        ("tests.test_0", "test_value"), ("tests.test_1", "test_value"),
    }


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("plan_sha256", "d" * 64, "lane-binding-mismatch"),
    ("subtests", 0, "invalid-subtest-count"),
    ("subtests", -1, "invalid-subtest-count"),
    ("subtests", 1.0, "invalid-subtest-count"),
    ("subtests", "1", "invalid-subtest-count"),
    ("subtests", True, "invalid-subtest-count"),
    ("seconds", -1, "invalid-duration"),
    ("seconds", float("nan"), "invalid-duration"),
    ("seconds", "1", "invalid-duration"),
    ("environment_sha256", "short", "invalid-environment"),
])
def test_invalid_receipt_fields(evidence, field, value, reason):
    plan, root, binding = evidence
    path = root / "0" / "receipt.json"
    receipt = json.loads(path.read_text())
    shadow.write_json(path, dict(receipt, **{field: value}))
    with pytest.raises(shadow.Refusal, match=reason):
        shadow.compare(plan, root, binding)


@pytest.mark.parametrize(("replacement", "reason"), [
    (b' name="other_test"', "outcome-parity-mismatch"),
    (b' name="test_value"', "wrong-file-assignment"),
    (b' classname="tests.unknown" name="test_value"', "wrong-file-assignment"),
    (b' classname="tests.test_1" name="test_value"', "wrong-file-assignment"),
    (b' classname="tests.test_0" name="test_value"/>', "outcome-parity-mismatch"),
])
def test_comparator_checks_rehashed_outcomes(evidence, replacement, reason):
    plan, root, binding = evidence
    base = report([0])
    key = b' classname="tests.test_0" name="test_value"'
    if replacement.endswith(b'/>'):
        raw = base.replace(key + b'/>', key + b'><skipped/></testcase>').replace(b'skipped="0"', b'skipped="1"')
    elif replacement == b' name="other_test"':
        raw = base.replace(b' name="test_value"', replacement)
    else:
        raw = base.replace(key, replacement)
    path = root / "0" / "receipt.json"
    receipt = json.loads(path.read_text())
    (path.parent / "root.xml").write_bytes(raw)
    shadow.write_json(path, dict(receipt, junit_sha256=sha256(raw).hexdigest()))
    with pytest.raises(shadow.Refusal, match=reason):
        shadow.compare(plan, root, binding)


def test_duplicate_across_nested_module_owners_refused(evidence, monkeypatch):
    plan, root, binding = evidence
    payload = json.loads(plan.read_text())
    payload["lanes"][1] = ["tests/test_0/test_nested.py"]
    monkeypatch.setattr(shadow, "tracked_python", lambda: {p for lane in payload["lanes"] for p in lane})
    shadow.write_json(plan, payload)
    for folder in root.iterdir():
        receipt = json.loads((folder / "receipt.json").read_text())
        raw = (folder / "root.xml").read_bytes().replace(b'tests.test_1', b'tests.test_0')
        if folder.name in {"0", "1", "serial"}:
            raw = raw.replace(b'tests.test_0"', b'tests.test_0.test_nested"')
        if folder.name == "serial":
            raw = raw.replace(b'name="test_value"/>', b'name="test_other"/>', 1)
        (folder / "root.xml").write_bytes(raw)
        shadow.write_json(folder / "receipt.json", dict(
            receipt, plan_sha256=sha256(plan.read_bytes()).hexdigest(),
            junit_sha256=sha256(raw).hexdigest(),
        ))
    with pytest.raises(shadow.Refusal, match="overlapping-test-id"):
        shadow.compare(plan, root, binding)


@pytest.mark.parametrize(("field", "value"), [("verdict", "INCOMPLETE"), ("executed_count", 3), ("missing_count", 1)])
def test_completeness_requires_verdict_and_counts(evidence, field, value):
    plan, root, binding = evidence
    path = root / "serial" / "completeness.json"
    shadow.write_json(path, dict(json.loads(path.read_text()), **{field: value}))
    with pytest.raises(shadow.Refusal, match="independent-completeness-mismatch"):
        shadow.compare(plan, root, binding)


def test_shadow_workflow_guard_contract():
    workflow = (Path(__file__).resolve().parents[2] /
                ".github/workflows/agent-os-root-shadow.yml").read_text()
    inventory, root_and_parity = workflow.split("\n  root:\n")
    root, parity = root_and_parity.split("\n  parity:\n")
    for job in (inventory, root, parity):
        assert job.count("ref: ${{ env.SHADOW_HEAD }}") == 1
        assert job.count("persist-credentials: false") == 1
    for producer in (inventory, root):
        assert producer.count("if-no-files-found: error") == 1
        assert producer.count("retention-days: 7") == 1
    assert "fail-fast: false" in root
    assert "if: matrix.lane == 'serial'" in root
    assert "--receipt \"$RUNNER_TEMP/root-shadow/completeness.json\"" in root
    assert 'test "$ROOT_RESULT" = success' in parity
    assert 'test -z "$(find "$RUNNER_TEMP/downloads" -mindepth 1 -print -quit)"' in parity
    assert "pip install" not in parity
