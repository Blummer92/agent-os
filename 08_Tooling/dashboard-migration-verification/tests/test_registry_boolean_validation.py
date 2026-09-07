from pathlib import Path
import importlib.util
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "snapshot_notion.py"
spec = importlib.util.spec_from_file_location("snapshot_notion_boolean_validation", SCRIPT_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def _write_config(tmp_path: Path, *, retirement="MISSING", approval="MISSING") -> Path:
    lines = ["dashboards:", "  sample:", "    name: Sample"]
    if retirement != "MISSING":
        lines.append(f"    retirement_allowed: {retirement}")
    if approval != "MISSING":
        lines.append(f"    human_approval_required: {approval}")
    path = tmp_path / "dashboards.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_missing_authorization_booleans_keep_safe_defaults(tmp_path: Path) -> None:
    entry = module.load_dashboard_registry(_write_config(tmp_path))["sample"]
    assert entry.retirement_allowed is False
    assert entry.human_approval_required is True


def test_exact_yaml_booleans_are_preserved(tmp_path: Path) -> None:
    entry = module.load_dashboard_registry(
        _write_config(tmp_path, retirement="true", approval="false")
    )["sample"]
    assert entry.retirement_allowed is True
    assert entry.human_approval_required is False


@pytest.mark.parametrize("value", ['"false"', "0", "null", "[]", "{}"])
@pytest.mark.parametrize("field", ["retirement", "approval"])
def test_malformed_authorization_booleans_fail_closed(tmp_path: Path, field: str, value: str) -> None:
    kwargs = {field: value}
    with pytest.raises(ValueError, match="must be a boolean"):
        module.load_dashboard_registry(_write_config(tmp_path, **kwargs))
