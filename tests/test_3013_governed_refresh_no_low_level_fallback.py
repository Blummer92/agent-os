"""Regression contract for #3013 governed PR-refresh safety."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "02_Agent_Overlays/github-service-agent.md"


def test_3013_refresh_never_uses_stale_tree_git_object_fallback() -> None:
    text = " ".join(OVERLAY.read_text(encoding="utf-8").split())
    for phrase in (
        "use only the existing governed branch-refresh path",
        "never authorizes composing a merge commit from the stale PR tree",
        "moving the branch ref through ad-hoc Git-object operations",
        "compare the resulting tree/scope against current `main`",
        "`behind_by=0` or topological currentness alone is not proof",
    ):
        assert phrase in text
