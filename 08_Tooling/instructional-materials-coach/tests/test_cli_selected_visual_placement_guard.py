"""CLI guard: selected visuals with no plannable placement bindings must refuse the build.

Nov 3 mutation FCLI2. Kept in its own file (helpers are reused from ``test_cli.py`` by path)
so it does not share a file with other active visual PRs.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("_cli_guard_helpers", Path(__file__).with_name("test_cli.py"))
_helpers = importlib.util.module_from_spec(spec)
sys.modules["_cli_guard_helpers"] = _helpers
spec.loader.exec_module(_helpers)
_visual_build_args = _helpers._visual_build_args


def test_main_selected_visuals_without_planned_placements_refuse_the_build(monkeypatch, tmp_path, capsys):
    """Nov 3 mutation FCLI2: selected visuals must never be silently dropped.

    The governed plan selected asset-1, but no placement binding can be planned
    from it. Admission later derives its required visuals from the planned
    bindings, so building here would yield a materials build with no required
    visuals to verify. The CLI must refuse before any connected write.
    """
    from instructional_materials_coach import cli
    monkeypatch.setenv("ALLOW_WRITE", "true")
    with (
        patch("instructional_materials_coach.cli.get_credentials", return_value="creds"),
        patch("instructional_materials_coach.cli.build_drive_service", return_value="drive"),
        patch("instructional_materials_coach.cli.build_slides_service", return_value="slides"),
        patch("instructional_materials_coach.cli.build_docs_service", return_value="docs"),
        patch("instructional_materials_coach.cli._require_visual_placement_support"),
        patch("instructional_materials_coach.cli.get_file_metadata",
              return_value={"id": "file-1", "trashed": False, "sha256Checksum": "c" * 64}),
        patch("instructional_materials_coach.cli.plan_visual_placement_bindings", return_value=()),
        patch("instructional_materials_coach.cli.build_live_materials") as live,
    ):
        exit_code = cli.main(_visual_build_args(tmp_path))
    assert exit_code == 1
    live.assert_not_called()
    err = capsys.readouterr().err
    assert "no placement bindings could be planned" in err
    assert "selected_asset_ids=asset-1" in err
