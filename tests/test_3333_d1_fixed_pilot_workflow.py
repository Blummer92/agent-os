"""D1 (#3333) workflow structure and exclusive-transfer harness tests.

Structure tests read the governed-invocation workflow the same way the
existing discovery-evidence tests do: raw text for step blocks (parsed
YAML truncates step names at " #", which is pre-existing behavior for
every "#3333" step name) and parsed YAML for conditions and flags.

The transfer harness executes the real transfer step script with a fake
``gh`` on PATH: ``codespace cp`` becomes a local copy and ``codespace
ssh`` runs the remote command locally, so the exclusive-transfer
sequence (fresh 0700 remote dir, 0600 staging, dual SHA-256 checks,
atomic link, inode equality) is exercised, not re-implemented. No live
Codespace, network, or credential is used. ``D1_WORKFLOW_PATH`` overrides
the workflow under test so the M1/M3 mutation controls can run the same
suite against a scratch mutant copy.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import yaml
import pytest

ROOT = Path(__file__).parents[1]
WORKFLOW = Path(os.environ.get("D1_WORKFLOW_PATH", str(ROOT / ".github/workflows/agent-os-governed-invocation.yml")))

PREFLIGHT = "Preflight fixed #3333 Codespaces connection"
TRANSFER = "Transfer fixed #3333 event exclusively"
RUN = "Run Gate 2 fixed #3333 pilot and return receipt"
GATE = "Enforce fixed #3333 pilot acceptance gate"
SUMMARY = "Publish bounded invocation summary"
CLEANUP = "Clean up fixed #3333 remote staging on gate pass"
UPLOAD = "Publish bounded ingress evidence"
FIXED = "Evaluate fixed #3333 Codespaces operation admission"
ROUTE = "Resolve Codespaces-first transport route"
DEV_GATE = "Enforce developer-validation result gate"

FAKE_GH = """#!/bin/bash
# Fake gh for the D1 transfer harness: only the subcommands the transfer
# step uses. cp becomes a local copy; ssh runs the remote command locally.
if [ "$1" = "codespace" ] && [ "$2" = "cp" ]; then
  src=""; dst=""
  shift 2
  while [ $# -gt 0 ]; do
    case "$1" in
      -c) shift 2 ;;
      remote:*) dst="${1#remote:}"; shift ;;
      *) src="$1"; shift ;;
    esac
  done
  if [ "${GH_FAULT:-}" = "symlink" ]; then
    ln -s "$src" "$dst"
  else
    cp "$src" "$dst"
  fi
  if [ "${GH_FAULT:-}" = "corrupt" ]; then
    printf 'X' >> "$dst"
  fi
  exit 0
fi
if [ "$1" = "codespace" ] && [ "$2" = "ssh" ]; then
  shift 5
  bash -c "$*"
  exit $?
fi
echo "fake gh: unsupported: $*" >&2
exit 99
"""


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _block(text: str, start: str, end: str) -> str:
    return text.split(f"- name: {start}", 1)[1].split(f"- name: {end}", 1)[0]


def _parsed_steps() -> list[dict]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return doc["jobs"]["ingress"]["steps"]


def _step_by_id(step_id: str) -> dict:
    for step in _parsed_steps():
        if step.get("id") == step_id:
            return step
    raise AssertionError(f"missing step id {step_id}")


def _run_script(text: str, start: str, end: str) -> str:
    block = _block(text, start, end)
    script = block.split("run: |", 1)[1]
    return textwrap.dedent(script).strip() + "\n"


def test_d1_steps_present_and_ordered() -> None:
    """Gate sits before summary; cleanup sits between summary and upload."""
    text = _text()
    order = [FIXED, PREFLIGHT, TRANSFER, RUN, GATE, SUMMARY, CLEANUP, DEV_GATE, UPLOAD]
    positions = [text.index(f"- name: {name}") for name in order]
    assert positions == sorted(positions)


def test_d1_gate_condition_and_no_continue_on_error() -> None:
    """The gate runs on always() for fixed envelopes and can never be skipped silently."""
    gate = _step_by_id("fixed_gate")
    condition = gate.get("if", "")
    assert "always()" in condition
    assert "is_codespace_implementation" in condition
    for step_id in ("fixed_preflight", "fixed_transfer", "fixed_run", "fixed_gate", "fixed_cleanup"):
        step = _step_by_id(step_id)
        assert step.get("continue-on-error") in (None, False), step_id


def test_d1_no_host_install_references() -> None:
    """The retired GCE host-install step is gone: no D1 condition or workflow
    text may reference it. (#3821 retired the step; the D1 conditions that
    carried `steps.host_install.outputs.requested != 'true'` were dead logic
    on an undefined step and are removed, not reintroduced.)"""
    text = _text()
    assert "host_install" not in text
    for step_id in ("fixed_preflight", "fixed_transfer", "fixed_run", "fixed_gate", "fixed_cleanup"):
        assert "host_install" not in (_step_by_id(step_id).get("if", "") or ""), step_id


def test_d1_step_condition_chaining() -> None:
    """Preflight gates transfer, transfer gates run, cleanup gates on gate pass."""
    assert "fixed_preflight.outputs.ready == 'true'" in _step_by_id("fixed_transfer").get("if", "")
    assert "fixed_transfer.outputs.transfer_ok == 'true'" in _step_by_id("fixed_run").get("if", "")
    assert "fixed_gate.outputs.decision == 'pass'" in _step_by_id("fixed_cleanup").get("if", "")


def test_d1_summary_precedence() -> None:
    """Fixed envelopes show diagnostic + gate, never 'Dispatch: None / None'."""
    text = _text()
    block = _block(text, SUMMARY, DEV_GATE)
    assert "codespace_implementation" in block
    assert "Fixed pilot acceptance gate" in block
    assert "Provider-less diagnostic only; not execution evidence." in block
    assert 'if not isinstance(result.get("codespace_implementation"), dict):' in block
    # Rebase pin: main's `control` summary block is preserved, and the
    # discovery/diagnostic/dev-validation chain still runs only when no
    # `control` dict is present (spelled as a negated if, because the D1
    # block sits between the control check and the chain).
    assert "Control status:" in block
    assert "if not isinstance(control, dict):" in block


def test_d1_event_confidentiality_and_no_expand() -> None:
    """The event stages privately, never under the uploaded ingress dir."""
    text = _text()
    transfer = _block(text, TRANSFER, RUN)
    assert "agent-os-gate2-private" in transfer
    assert "mkdir -m 0700" in transfer
    assert "0o600" in transfer
    assert "agent-os-ingress/gate2-event" not in transfer
    for step_id in ("fixed_preflight", "fixed_transfer", "fixed_run", "fixed_gate", "fixed_cleanup"):
        step = _step_by_id(step_id)
        assert "--expand" not in json.dumps(step)


def test_d1_no_shell_expansion_of_event_text() -> None:
    """Event text is read as bytes and copied as a file, never interpolated."""
    text = _text()
    transfer = _block(text, TRANSFER, RUN)
    assert transfer.count("GITHUB_EVENT_PATH") == 1
    assert 'os.environ["GITHUB_EVENT_PATH"]' in transfer
    assert "shell=True" not in transfer
    run = _block(text, RUN, GATE)
    assert "GITHUB_EVENT_PATH" not in run


def test_d1_preflight_checks_main_remote_head_identity_and_probe() -> None:
    """Preflight binds main head, remote HEAD, CODESPACE_NAME, and the probe."""
    text = _text()
    preflight = _block(text, PREFLIGHT, TRANSFER)
    assert "commits/main" in preflight
    assert "rev-parse HEAD" in preflight
    assert 'printf %s "$CODESPACE_NAME"' in preflight
    assert "--check-bindings" in preflight
    assert "shlex.quote" in preflight


def test_d1_no_checkout_mutation_and_no_invented_paths() -> None:
    """D1 never resets a checkout and never invents a host path (N4)."""
    text = _text()
    for start, end in ((PREFLIGHT, TRANSFER), (TRANSFER, RUN), (RUN, GATE), (CLEANUP, DEV_GATE)):
        block = _block(text, start, end)
        for forbidden in ("git reset", "git checkout", "git clean", "git pull", "agent-os-state"):
            assert forbidden not in block, (start, forbidden)
    preflight = _block(text, PREFLIGHT, TRANSFER)
    for var in (
        "vars.AGENT_OS_CHECKPOINT_STORE_ROOT",
        "vars.AGENT_OS_REPOSITORY_ROOT",
        "vars.AGENT_OS_WORKSPACE_PARENT",
        "vars.AGENT_OS_LEASE_DIRECTORY",
    ):
        assert var in preflight


def test_d1_original_diagnostic_unchanged_and_first() -> None:
    """The provider-less diagnostic step is untouched and still runs first."""
    text = _text()
    block = _block(text, FIXED, PREFLIGHT)
    assert "fixed_codespace_pilot" in block
    assert '--result-output "$RUNNER_TEMP/agent-os-ingress/result.json"' in block
    assert text.index(f"- name: {FIXED}") < text.index(f"- name: {PREFLIGHT}")


def test_d1_artifact_upload_unchanged_and_after_cleanup() -> None:
    """The seven-day artifact step still publishes the whole ingress dir, last."""
    steps = _parsed_steps()
    upload = next(step for step in steps if step.get("id") is None and step.get("uses", "").startswith("actions/upload-artifact@"))
    assert "agent-os-ingress/*.json" in str(upload.get("with", {}).get("path", ""))
    assert upload["with"]["retention-days"] == 7
    assert "always()" in upload.get("if", "")


def _run_transfer(
    tmp_path: Path,
    *,
    gh_fault: str | None = None,
    preplant_remote: bytes | None = None,
    remote_dir_override: str | None = None,
    event_body: bytes | None = None,
) -> dict:
    """Run the real transfer step script against a fake gh. Returns evidence."""
    runner_temp = tmp_path / "runner_temp"
    ingress = runner_temp / "agent-os-ingress"
    ingress.mkdir(parents=True)
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    gh = fakebin / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    # Actions runners provide `python`; this machine only has `python3`.
    (fakebin / "python").symlink_to(shutil.which("python3"))
    run_id = str(9000000000 + (os.getpid() % 100000))
    remote_dir = remote_dir_override or f"/tmp/agent-os-gate2-{run_id}-1"
    if event_body is None:
        event_body = b'{"action": "created", "comment": {"id": 1}}'
    event_path = tmp_path / "event.json"
    event_path.write_bytes(event_body)
    output_path = tmp_path / "github_output"
    output_path.write_text("")
    record = {
        "schema_version": "1.0",
        "run_id": int(run_id) if remote_dir_override is None else 1,
        "attempt": 1,
        "selected": "harness-codespace",
        "remote_dir": remote_dir,
        "ready": True,
        "reason_codes": [],
    }
    (ingress / "gate2-transfer.json").write_text(json.dumps(record), encoding="utf-8")
    remote_path = Path(remote_dir)
    if preplant_remote is not None:
        remote_path.mkdir(parents=True, exist_ok=True)
        (remote_path / "event.json").write_bytes(preplant_remote)
    script = _run_script(_text(), TRANSFER, RUN)
    script_path = tmp_path / "transfer_step.sh"
    script_path.write_text(script, encoding="utf-8")
    env = dict(os.environ)
    env.update(
        {
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_EVENT_PATH": str(event_path),
            "GITHUB_RUN_ID": run_id,
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_OUTPUT": str(output_path),
            "PATH": str(fakebin) + os.pathsep + env["PATH"],
            "GH_TOKEN": "dummy",
        }
    )
    if gh_fault is not None:
        env["GH_FAULT"] = gh_fault
    try:
        completed = subprocess.run(
            ["bash", str(script_path)], env=env, capture_output=True, text=True, timeout=120
        )
        assert completed.returncode == 0, completed.stderr[-2000:]
        record = json.loads((ingress / "gate2-transfer.json").read_text(encoding="utf-8"))
        private_dir = runner_temp / "agent-os-gate2-private"
        evidence: dict[str, object] = {
            "record": record,
            "outputs": output_path.read_text(encoding="utf-8"),
            "private_dir_exists": private_dir.exists(),
            "remote_dir": remote_dir,
        }
        if (remote_path / "event.json").exists():
            evidence["remote_event_bytes"] = (remote_path / "event.json").read_bytes()
            evidence["remote_event_mode"] = stat.S_IMODE((remote_path / "event.json").stat().st_mode)
        if (remote_path / "event.staging").exists():
            evidence["staging_mode"] = stat.S_IMODE((remote_path / "event.staging").stat().st_mode)
            if (remote_path / "event.json").exists():
                evidence["staging_inode"] = (remote_path / "event.staging").stat().st_ino
                evidence["final_inode"] = (remote_path / "event.json").stat().st_ino
        if (private_dir / "gate2-event.json").exists():
            evidence["private_mode"] = stat.S_IMODE((private_dir / "gate2-event.json").stat().st_mode)
        return evidence
    finally:
        shutil.rmtree(remote_path, ignore_errors=True)


def test_d1_transfer_happy_path(tmp_path) -> None:
    """N2/N7: exclusive transfer succeeds with dual hashes and inode equality."""
    event_body = b'{"action": "created", "comment": {"id": 1}}'
    evidence = _run_transfer(tmp_path, event_body=event_body)
    record = evidence["record"]
    assert record["transfer_ok"] is True
    assert record["event_sha256"] == hashlib.sha256(event_body).hexdigest()
    assert record["event_bytes"] == len(event_body)
    assert record["staging_sha256"] == record["event_sha256"]
    assert record["final_sha256"] == record["event_sha256"]
    assert record["inode_equal"] is True
    assert evidence["remote_event_bytes"] == event_body
    assert evidence["remote_event_mode"] == 0o600
    assert evidence["staging_mode"] == 0o600
    assert evidence["staging_inode"] == evidence["final_inode"]
    assert evidence["private_mode"] == 0o600
    assert "transfer_ok=true" in str(evidence["outputs"])


def test_d1_transfer_collision_is_blocked_and_preserved(tmp_path) -> None:
    """N2: a pre-existing remote event file is never overwritten."""
    original = b'{"action": "pre-existing"}'
    evidence = _run_transfer(tmp_path, preplant_remote=original)
    assert evidence["record"]["transfer_ok"] is False
    assert evidence["record"]["reason_codes"] == ["transfer-remote-dir-exists"]
    assert evidence["remote_event_bytes"] == original


def test_d1_transfer_symlink_is_blocked(tmp_path) -> None:
    """N2: a symlinked staging file fails the guard instead of being followed."""
    evidence = _run_transfer(tmp_path, gh_fault="symlink")
    assert evidence["record"]["transfer_ok"] is False
    assert evidence["record"]["reason_codes"] == ["transfer-staging-guard-failed"]


def test_d1_transfer_corrupt_bytes_are_blocked(tmp_path) -> None:
    """N2/N7: changed bytes fail the staging SHA check before linking."""
    evidence = _run_transfer(tmp_path, gh_fault="corrupt")
    assert evidence["record"]["transfer_ok"] is False
    assert evidence["record"]["reason_codes"] == ["transfer-staging-sha-mismatch"]


def test_d1_transfer_invalid_remote_dir_is_blocked(tmp_path) -> None:
    """N2: a non-numeric remote directory is rejected before any staging."""
    evidence = _run_transfer(tmp_path, remote_dir_override="/tmp/agent-os-gate2-abc-1")
    assert evidence["record"]["transfer_ok"] is False
    assert evidence["record"]["reason_codes"] == ["transfer-remote-dir-invalid"]
    assert evidence["private_dir_exists"] is False


def test_d1_transfer_shell_metacharacters_are_data(tmp_path) -> None:
    """N2: event text containing shell metacharacters is never interpreted."""
    pwn = tmp_path / "PWNED"
    event_body = (
        b'{"action": "created", "trap": "$(touch ' + str(pwn).encode() + b') `id`"}'
    )
    evidence = _run_transfer(tmp_path, event_body=event_body)
    assert evidence["record"]["transfer_ok"] is True
    assert not pwn.exists()
    assert evidence["remote_event_bytes"] == event_body

 
def test_d1_preflight_fixed_repository_root_guard() -> None:
    preflight = _block(_text(), PREFLIGHT, TRANSFER)
    assert 'bindings["AGENT_OS_REPOSITORY_ROOT"].rstrip("/") != "/workspaces/agent-os"' in preflight
    assert "preflight-repository-root-mismatch" in preflight


def test_d1_receipt_path_guard_is_canonical_before_copy() -> None:
    run = _block(_text(), RUN, GATE)
    assert 'store_root = Path(bindings["AGENT_OS_CHECKPOINT_STORE_ROOT"])' in run
    assert 'receipt_file.parent == receipts_dir' in run
    assert '".." not in receipt_file.parts' in run
    assert 'str(receipt_file) == receipt_path' in run
    assert run.index("receipt_path_canonical") < run.index('["gh", "codespace", "cp"')


@pytest.mark.parametrize(
    "root,path,allowed",
    [
        ("/store", "/store/invocations/receipts/fixed-head-probe-" + "a" * 64 + "-" + "b" * 40 + "-20261108T060000Z.json", True),
        ("/store/", "/store/invocations/receipts/fixed-head-probe-" + "a" * 64 + "-" + "b" * 40 + "-20261108T060000Z.json", True),
        ("/store", "/store/invocations/receipts/../../tmp/fixed-head-probe-" + "a" * 64 + "-" + "b" * 40 + "-20261108T060000Z.json", False),
        ("/store", "/store/invocations/receipts/./fixed-head-probe-" + "a" * 64 + "-" + "b" * 40 + "-20261108T060000Z.json", False),
        ("/store", "/store/invocations/receipts//fixed-head-probe-" + "a" * 64 + "-" + "b" * 40 + "-20261108T060000Z.json", False),
        ("/other", "/store/invocations/receipts/fixed-head-probe-" + "a" * 64 + "-" + "b" * 40 + "-20261108T060000Z.json", False),
    ],
)
def test_d1_receipt_path_lexical_policy(root: str, path: str, allowed: bool) -> None:
    # Mirror the literal/pathlib policy and keep this input table as a
    # regression oracle for trailing slash, traversal and duplicate separators.
    store_root = Path(root)
    file = Path(path)
    receipts_dir = store_root / "invocations" / "receipts"
    valid = (
        store_root.is_absolute()
        and ".." not in store_root.parts
        and file.is_absolute()
        and ".." not in file.parts
        and str(file) == path
        and file.parent == receipts_dir
    )
    assert valid is allowed
