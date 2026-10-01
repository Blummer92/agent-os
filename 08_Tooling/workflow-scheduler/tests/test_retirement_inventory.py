from __future__ import annotations

import ast
import json
import shlex
from types import SimpleNamespace

from workflow_scheduler.governance import retirement_inventory as live


def completed(payload, returncode=0):
    return SimpleNamespace(returncode=returncode, stdout=json.dumps(payload), stderr="")


def instance():
    return {
        "status": "RUNNING",
        "machineType": "zones/us-central1-a/machineTypes/e2-standard-2",
        "disks": [
            {"source": "projects/p/zones/z/disks/boot", "boot": True, "autoDelete": True, "mode": "READ_WRITE"},
            {"source": "projects/p/zones/z/disks/data", "boot": False, "autoDelete": False, "mode": "READ_WRITE"},
        ],
        "networkInterfaces": [
            {
                "network": "projects/p/global/networks/default",
                "subnetwork": "projects/p/regions/r/subnetworks/default",
                "networkIP": "10.0.0.2",
                "accessConfigs": [{"natIP": "203.0.113.4"}],
            }
        ],
        "metadata": {"items": [{"key": "startup-script", "value": "SECRET"}]},
    }


def host_payload():
    return {
        "schema_version": "1.0",
        "status": "observed",
        "reason_codes": ["host-retirement-inventory-observed"],
        "browser_profiles": [{"kind": "google-chrome", "path": "/home/u/.config/google-chrome", "present": True, "backing_storage": {"status": "observed", "source": "/dev/sda1", "target": "/", "fstype": "ext4"}}],
        "repositories": [{"path": "/home/u/agent-os", "status": "observed", "branch": "main", "dirty_entry_count": 0, "unpushed_commit_count": 0}],
        "persistent_state": {"var_lib_agent_os_present": False},
        "services": {"running_service_count": 7, "timer_count": 2, "user_crontab_present": False},
        "containers": {"docker_volume_count": 0},
        "credential_presence": {"ssh_directory_present": True, "gcloud_adc_present": False},
        "credential_contents_emitted": False,
        "profile_contents_emitted": False,
        "repository_file_names_emitted": False,
        "side_effects_performed": False,
    }


def test_inventory_is_fixed_read_only_and_redacts_metadata_values():
    calls = []
    def run(argv, timeout=60):
        calls.append(tuple(argv))
        if argv[:4] == ("gcloud", "compute", "instances", "describe"):
            return completed(instance())
        if argv[:4] == ("gcloud", "compute", "snapshots", "list"):
            return completed([{"name": "snap", "sourceDisk": "projects/p/zones/z/disks/boot", "status": "READY"}])
        if argv[:4] == ("gcloud", "compute", "images", "list"):
            return completed([])
        raise AssertionError(argv)
    def host_run(command):
        assert command == live.HOST_RETIREMENT_INVENTORY_COMMAND
        return SimpleNamespace(returncode=0, stdout=f"{live._HOST_FRAME_START}\n{json.dumps(host_payload())}\n{live._HOST_FRAME_END}\n", stderr="")

    result = live.collect_retirement_inventory(run, host_run)

    assert result["status"] == "needs-decision"
    assert result["unobserved_evidence"] == {
        key: "UNKNOWN" for key in live.UNOBSERVED_EVIDENCE
    }
    assert "retirement-external-ip-allocation-unobserved" in result["reason_codes"]
    assert result["side_effects_performed"] is False
    assert result["external_write_performed"] is False
    assert result["cloud"]["metadata_keys"] == ["startup-script"]
    assert result["cloud"]["metadata_values_emitted"] is False
    assert "SECRET" not in json.dumps(result)
    assert result["cloud"]["disks"][1]["auto_delete"] is False
    assert result["host"]["credential_contents_emitted"] is False
    joined = " ".join(" ".join(call) for call in calls)
    for verb in (" start ", " stop ", " delete ", " create ", " add-iam-policy-binding "):
        assert verb not in f" {joined} "


def test_cloud_failure_is_explicit_unknown_not_guessed():
    def run(argv, timeout=60):
        return SimpleNamespace(returncode=1, stdout="", stderr="SECRET")
    def host_run(command):
        return SimpleNamespace(returncode=0, stdout=f"{live._HOST_FRAME_START}\n{json.dumps(host_payload())}\n{live._HOST_FRAME_END}", stderr="")

    result = live.collect_retirement_inventory(run, host_run)

    assert result["status"] == "needs-decision"
    assert result["cloud"] == {"status": "unknown"}
    assert result["host"]["status"] == "observed"
    assert "SECRET" not in json.dumps(result)


def test_host_contract_rejects_content_emission():
    payload = host_payload()
    payload["credential_contents_emitted"] = True

    def run(argv, timeout=60):
        if argv[:4] == ("gcloud", "compute", "instances", "describe"):
            return completed(instance())
        return completed([])
    def host_run(command):
        return SimpleNamespace(returncode=0, stdout=f"{live._HOST_FRAME_START}\n{json.dumps(payload)}\n{live._HOST_FRAME_END}", stderr="")

    result = live.collect_retirement_inventory(run, host_run)

    assert result["status"] == "needs-decision"
    assert result["host"] == {"status": "unknown"}
    assert "host-retirement-inventory-contract-violation" in result["reason_codes"]


def test_host_command_contains_no_credential_content_reads():
    command = live.HOST_RETIREMENT_INVENTORY_COMMAND
    assert "read_text" not in command
    assert "open(" not in command
    assert "cat " not in command
    assert "findmnt" in command
    assert "git" in command


def test_host_command_compiles_and_emits_a_valid_frame(capsys):
    argv = shlex.split(live.HOST_RETIREMENT_INVENTORY_COMMAND)
    assert argv[:2] == ["/usr/bin/python3", "-c"]
    assert len(argv) == 3
    source = argv[2]
    compile(source, "<retirement-host-script>", "exec")

    # Execute only the framing footer with synthetic metadata: no host reads.
    tree = ast.parse(source)
    footer = ast.Module(body=tree.body[-3:], type_ignores=[])
    payload = host_payload()
    exec(compile(footer, "<retirement-frame>", "exec"), {"json": json, "out": payload})

    stdout = capsys.readouterr().out
    assert stdout.splitlines() == [
        live._HOST_FRAME_START,
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        live._HOST_FRAME_END,
    ]
    assert live._extract_host_payload(stdout) == payload


def test_missing_disk_autodelete_is_unknown_instead_of_false():
    payload = instance()
    del payload["disks"][0]["autoDelete"]
    result = _collect_with_payloads(payload, host_payload())
    assert result["cloud"] == {"status": "unknown"}
    assert "retirement-disk-autodelete-unobserved" in result["reason_codes"]


def test_unreadable_host_metadata_has_explicit_reason_codes():
    payload = host_payload()
    payload["services"]["running_service_count"] = None
    payload["browser_profiles"][0]["backing_storage"] = {"status": "unknown"}
    payload["repositories"][0]["unpushed_commit_count"] = None
    result = _collect_with_payloads(instance(), payload)
    assert result["status"] == "needs-decision"
    assert "retirement-host-services-unobserved" in result["reason_codes"]
    assert "retirement-browser-storage-unobserved" in result["reason_codes"]
    assert "retirement-repository-state-unobserved" in result["reason_codes"]


def _collect_with_payloads(cloud, host):
    def run(argv, timeout=60):
        return completed(cloud if argv[2:4] == ("instances", "describe") else [])
    def host_run(command):
        assert command == live.HOST_RETIREMENT_INVENTORY_COMMAND
        return SimpleNamespace(returncode=0, stdout=f"{live._HOST_FRAME_START}\n{json.dumps(host)}\n{live._HOST_FRAME_END}", stderr="")
    return live.collect_retirement_inventory(run, host_run)
