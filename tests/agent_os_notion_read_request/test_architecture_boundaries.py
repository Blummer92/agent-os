"""Architecture-boundary proofs for the #2283 read path.

The locked architecture forbids a second curriculum source of truth, a second
Notion client, a second context engine, a second asset registry, a second
scheduler, a GCE dependency for routine reads, any native/direct ChatGPT Notion
connector branch, and any unauthorized Drive or classroom-artifact write.
"""
from __future__ import annotations
import ast
import json
from pathlib import Path
import pytest
from scripts.agent_os_notion_read_request import CREDENTIAL_ENV_VAR, DISPATCH_COMPLETED, REQUEST_CLASSES, RESULT_KIND, load_catalog
from scripts.agent_os_notion_read_request import runner as runner_module
from .notion_read_support import ACTOR, GENERATED_AT, REPOSITORY, RecordingExecutor, transport

PACKAGE = Path(__file__).resolve().parents[2] / "scripts" / "agent_os_notion_read_request"
ROUTER = Path(__file__).resolve().parents[2] / "src" / "navigation_registry" / "connectors" / "curriculum_execution_surface_router.py"
MODULES = sorted(PACKAGE.glob("*.py"))
FORBIDDEN_IMPORT_ROOTS = frozenset({"requests","httpx","urllib","urllib3","http","socket","ssl","aiohttp","notion_client","notion","googleapiclient","google","boto3","subprocess","sched","celery","redis","sqlite3","apscheduler"})


def imported_roots(module: Path) -> set[str]:
    tree = ast.parse(module.read_text(encoding="utf-8")); roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module: roots.add(node.module.split(".")[0])
    return roots


def test_modules_exist() -> None:
    assert {module.name for module in MODULES} >= {"admission.py","catalog.py","execution.py","models.py","projection.py","runner.py"}


@pytest.mark.parametrize("module", MODULES, ids=lambda path: path.name)
def test_no_second_client_transport_or_scheduler_is_introduced(module: Path) -> None:
    forbidden = imported_roots(module) & FORBIDDEN_IMPORT_ROOTS
    assert not forbidden, f"{module.name} imports a forbidden root: {sorted(forbidden)}"


@pytest.mark.parametrize("module", MODULES, ids=lambda path: path.name)
def test_no_gce_or_workflow_scheduler_dependency(module: Path) -> None:
    source = module.read_text(encoding="utf-8").lower()
    for marker in ("gcloud","workload_identity","compute.instances","iap"): assert marker not in source, f"{module.name} references {marker}"
    assert "import workflow_scheduler" not in source; assert "from workflow_scheduler" not in source


@pytest.mark.parametrize("module", MODULES, ids=lambda path: path.name)
def test_no_drive_or_classroom_artifact_write_is_introduced(module: Path) -> None:
    source = module.read_text(encoding="utf-8").lower()
    for marker in ("drive.files","slides.presentations","documents.create","classroom.courses","classroom_v1","www.googleapis.com"): assert marker not in source, f"{module.name} references {marker}"


def test_router_does_not_gain_drive_or_classroom_write_authority() -> None:
    source = ROUTER.read_text(encoding="utf-8").lower()
    for marker in ("drive.files.create","drive.files.update","drive.files.delete","permissions.create","slides.presentations.create","slides.presentations.batchupdate","documents.create","documents.batchupdate","classroom.courses.create","classroom.courses.patch","classroom.courses.delete"):
        assert marker not in source, f"router introduces external write surface: {marker}"


def test_reuses_existing_capabilities_instead_of_reimplementing_them() -> None:
    admission=(PACKAGE/"admission.py").read_text(encoding="utf-8"); execution=(PACKAGE/"execution.py").read_text(encoding="utf-8")
    assert "build_curriculum_read_plan" in admission
    assert "retrieve_curriculum_evidence" in execution
    assert "build_scheduler_fallback_read_executor" in execution
    assert "resolve_current_curriculum_state" in execution
    assert "def build_curriculum_read_plan" not in admission + execution
    assert "def orchestrate_curriculum_evidence" not in execution
    assert "def assemble_current_curriculum_evidence" not in execution


def test_native_direct_connector_routing_is_absent() -> None:
    source=ROUTER.read_text(encoding="utf-8")
    for removed in ("NATIVE_ROUTE","native_notion_connector_available","native_execute_read","select_curriculum_read_executor"): assert removed not in source


def test_single_credential_vocabulary_is_reused() -> None:
    assert CREDENTIAL_ENV_VAR == "NOTION_TOKEN"; assert load_catalog().credential_env_var == "NOTION_TOKEN"
    for module in MODULES:
        source=module.read_text(encoding="utf-8")
        for competing in ("NOTION_API_KEY","NOTION_SECRET","NOTION_READONLY_TOKEN_2","AGENT_OS_NOTION_TOKEN"): assert competing not in source


def test_no_module_reads_the_credential_from_the_environment() -> None:
    for module in MODULES:
        source=module.read_text(encoding="utf-8"); assert "os.environ" not in source; assert "getenv" not in source


def test_result_is_not_a_durable_curriculum_store(verified_catalog) -> None:
    evidence=runner_module.run_notion_read_request(transport(),expected_repository=REPOSITORY,expected_actor=ACTOR,generated_at=GENERATED_AT,catalog=verified_catalog,scheduler_task_executor_factory=RecordingExecutor().factory)
    provenance=evidence["result"]["provenance"]
    assert provenance["curriculum_source_of_truth"] == "notion-working-curriculum"
    assert provenance["governance_source_of_truth"] == "github-agent-os"
    assert provenance["evidence_class"] == "request-scoped-projection"
    assert provenance["authoritative_curriculum_record"] is False
    assert provenance["durable_curriculum_store"] is False


def test_shipped_catalog_preserves_verified_sources_and_fail_closed_unit_bindings(shipped_catalog) -> None:
    for source in shipped_catalog.sources:
        assert source.verification_state == "verified-current"
        assert source.data_source_id is not None
        assert source.dispatchable is True

    by_key = {unit.canonical_unit_key: unit for unit in shipped_catalog.canonical_units}
    photography = by_key["photography-foundations"]
    assert photography.verification_state == "verified-current"
    assert photography.provider_page_id is not None
    assert photography.dispatchable is True

    candy = by_key["candy-branding"]
    assert candy.verification_state == "unverified"
    assert candy.provider_page_id is None
    assert candy.dispatchable is False


def test_shipped_catalog_contains_only_authorized_verified_identities() -> None:
    raw=(PACKAGE/"notion_read_catalog.json").read_text(encoding="utf-8")
    for verified in ("da5cba48-50fd-4377-9790-8df8f6f2c7dd","c5b202aa-83d1-4cc4-9992-f98af648e461","3907ac78-3131-8129-8c73-cd9f6b8e8a7d"):
        assert verified in raw
    assert "f7f22d33-e1ef-4932-b294-cbe39b24a39a" not in raw
    assert "notion.so" not in raw; assert "https://" not in raw


def test_shipped_catalog_first_path_is_minimal(shipped_catalog) -> None:
    assert {source.logical_source for source in shipped_catalog.sources} == {"canonical-unit","visual-asset-library"}
    assert {record.request_class for record in shipped_catalog.requests} <= set(REQUEST_CLASSES)
    request_issues = {record.request_id: record.issue_number for record in shipped_catalog.requests}
    assert request_issues["photography-foundations-canonical-unit"] == 2283
    assert request_issues["photography-foundations-visual-assets"] == 2283
    assert request_issues["candy-branding-canonical-unit"] == 2816
    assert request_issues["candy-branding-visual-assets"] == 2816


def test_cli_writes_one_bounded_json_artifact(tmp_path, capsys) -> None:
    transport_path=tmp_path/"transport.json"; transport_path.write_text(json.dumps(transport()),encoding="utf-8")
    output_path=tmp_path/"evidence"/"result.json"
    exit_code=runner_module.main(["--transport",str(transport_path),"--repository",REPOSITORY,"--allowed-actor",ACTOR,"--generated-at",GENERATED_AT,"--output",str(output_path)])
    assert exit_code == 0
    written=json.loads(output_path.read_text(encoding="utf-8"))
    assert written["dispatch_status"] == "not-activated"
    assert written["dispatch_reason"] == "live-read-executor-not-configured"
    assert written["result"] is None; assert written["gce_invoked"] is False
    printed=capsys.readouterr().out; assert "ntn_" not in printed; assert "Authorization" not in printed


def test_cli_refuses_an_oversized_transport_file(tmp_path) -> None:
    transport_path=tmp_path/"transport.json"; transport_path.write_text("x"*(runner_module.MAX_TRANSPORT_BYTES+1),encoding="utf-8")
    with pytest.raises(Exception,match="exceeds byte bound"): runner_module._read_transport(transport_path)


def test_completed_result_is_json_serializable_for_artifact_surface(verified_catalog) -> None:
    evidence=runner_module.run_notion_read_request(transport(),expected_repository=REPOSITORY,expected_actor=ACTOR,generated_at=GENERATED_AT,catalog=verified_catalog,scheduler_task_executor_factory=RecordingExecutor().factory)
    assert evidence["dispatch_status"] == DISPATCH_COMPLETED
    serialized=json.dumps(evidence,sort_keys=True)
    assert json.loads(serialized)["result"]["result_kind"] == RESULT_KIND
    assert len(serialized) < 64*1024
