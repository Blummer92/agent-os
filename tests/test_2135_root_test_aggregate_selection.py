from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "scripts/agent_os_remote_validation/validation_profiles.yml"


def test_every_root_test_change_selects_aggregate_validation():
    config = yaml.safe_load(PROFILES.read_text(encoding="utf-8"))
    prefixes = tuple(config["aggregate_prefixes"])
    examples = (
        "tests/test_new_regression.py",
        "tests/agent_os_candidate_packet/test_new_regression.py",
        "tests/agent_os_issue_acceptance/test_new_regression.py",
    )
    for path in examples:
        assert any(path.startswith(prefix) for prefix in prefixes), path
