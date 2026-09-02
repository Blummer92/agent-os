from __future__ import annotations

import builtins

import workflow_scheduler.governance.eia_paddleocr_runtime_qualification as eia


def test_missing_runtime_fails_closed_without_install_or_download(monkeypatch) -> None:
    real_import = eia.importlib.import_module

    def fake_import(name: str):
        if name in {"paddle", "paddleocr", "paddlex"}:
            raise ModuleNotFoundError(name)
        return real_import(name)

    monkeypatch.setattr(eia.importlib, "import_module", fake_import)
    result = eia.qualify_runtime()
    assert result.status == "blocked"
    assert result.reason_codes == (
        "runtime-dependency-missing:paddle",
        "runtime-dependency-missing:paddleocr",
        "runtime-dependency-missing:paddlex",
    )
    assert result.network_used is False
    assert result.installation_performed is False
    assert result.model_download_performed is False
    assert result.external_write_performed is False
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.production_authorized is False
    assert result.classroom_data_authorized is False


def test_entrypoint_exposes_no_caller_command_surface() -> None:
    assert eia.QUALIFICATION_ID == "eia-paddleocr-runtime-qualification"
    assert eia.main.__code__.co_argcount == 0
    assert "subprocess" not in eia.__dict__
    assert "requests" not in eia.__dict__
    assert "urllib" not in eia.__dict__
