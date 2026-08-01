"""Security guards for the generation layer.

Dependency-free on purpose: these run in CI whether or not the `genai` extra is
installed, because a committed credential must never depend on an optional
install to be caught.
"""
from __future__ import annotations

import re
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = sorted(PACKAGE_ROOT.rglob("*.py")) + sorted(PACKAGE_ROOT.rglob("*.md"))

# Google API keys start AIza; Notion integration tokens use these prefixes.
KEY_SHAPED = re.compile(r"AIza[0-9A-Za-z_\-]{30,}|\bsecret_[0-9A-Za-z]{40,}|\bntn_[0-9A-Za-z]{40,}")

GENERATION_MODULES = (
    PACKAGE_ROOT / "src" / "instructional_materials_coach" / "genai_client.py",
    PACKAGE_ROOT / "src" / "instructional_materials_coach" / "notion_ingest.py",
    PACKAGE_ROOT / "src" / "instructional_materials_coach" / "colab" / "bootstrap.py",
    PACKAGE_ROOT / "src" / "instructional_materials_coach" / "colab" / "run_lesson_build.py",
)


def _relevant_files():
    return [p for p in SOURCE_FILES if "__pycache__" not in p.parts]


def test_no_api_key_shaped_literal_is_committed():
    offenders = []
    for path in _relevant_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        # Skip this file's own detector pattern.
        if path.name == Path(__file__).name:
            continue
        if KEY_SHAPED.search(text):
            offenders.append(str(path.relative_to(PACKAGE_ROOT)))
    assert not offenders, f"credential-shaped literal committed in: {offenders}"


def test_secrets_are_never_printed_or_logged():
    """No generation module may print or log a resolved secret value."""
    for path in GENERATION_MODULES:
        source = path.read_text(encoding="utf-8")
        for banned in ("print(api_key", "print(resolved_key", "print(value", "log(api_key"):
            assert banned not in source, f"{path.name} echoes a secret via {banned!r}"


def test_missing_key_error_does_not_embed_the_key():
    """The missing-secret path must not interpolate a value into its message."""
    bootstrap = (
        PACKAGE_ROOT / "src" / "instructional_materials_coach" / "colab" / "bootstrap.py"
    ).read_text(encoding="utf-8")
    assert "{value}" not in bootstrap
    assert "MissingSecretError" in bootstrap


def test_colab_readme_never_shows_a_literal_key():
    readme = (
        PACKAGE_ROOT / "src" / "instructional_materials_coach" / "colab" / "README.md"
    ).read_text(encoding="utf-8")
    assert "userdata" in readme.lower() or "Secrets" in readme
    assert "AIza" not in readme


def test_no_committed_notebooks_or_binaries():
    """Colab support stays as importable modules; the repo keeps zero notebooks."""
    assert not list(PACKAGE_ROOT.rglob("*.ipynb"))
