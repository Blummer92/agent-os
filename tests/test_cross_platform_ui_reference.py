from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "05_Examples/ui-cross-platform-reference"


def read(path: str) -> str:
    return (FIXTURE / path).read_text(encoding="utf-8")


def test_reference_fixture_contains_shared_web_mobile_and_acceptance_surfaces():
    required = (
        "README.md",
        "package.json",
        "index.html",
        "shared/task.ts",
        "web/TaskPanel.tsx",
        "web/task-panel.css",
        "web/main.tsx",
        "mobile/TaskScreen.tsx",
        "tests/shared.test.ts",
        "tests/web.test.tsx",
        "tests/web.e2e.ts",
        "tests/mobile.test.tsx",
        "playwright.config.ts",
    )
    for path in required:
        assert (FIXTURE / path).is_file(), path


def test_shared_logic_is_platform_free_and_models_deterministic_states():
    shared = read("shared/task.ts")
    for state in ('"loading"', '"empty"', '"success"', '"error"'):
        assert state in shared
    assert "TaskRepository" in shared
    assert "react-native" not in shared.lower()
    assert "document." not in shared
    assert "window." not in shared


def test_web_fixture_preserves_semantic_and_keyboard_specific_behavior():
    html = read("index.html")
    web = read("web/TaskPanel.tsx")
    css = read("web/task-panel.css")
    e2e = read("tests/web.e2e.ts")
    assert '<main id="root"><p>Loading Agent OS UI reference' in html
    assert "<h1>Agent OS UI Reference</h1>" in html
    assert "<form" in web and 'role="dialog"' in web
    assert 'aria-modal="true"' in web and 'e.key === "Escape"' in web
    assert ":focus-visible" in css and "@media" in css
    assert 'press("Enter")' in e2e and 'keyboard.press("Escape")' in e2e
    assert "toBeFocused" in e2e


def test_mobile_fixture_uses_native_accessibility_layout_and_mocked_capability_seam():
    mobile = read("mobile/TaskScreen.tsx")
    mobile_test = read("tests/mobile.test.tsx")
    assert 'from "react-native"' in mobile
    assert "SafeAreaView" in mobile and "useWindowDimensions" in mobile
    assert "width >= 768" in mobile and "minHeight: 44" in mobile
    assert "requestPhotoAccess" in mobile
    assert 'mockResolvedValue("denied")' in mobile_test
    assert "production" not in mobile_test.lower()


def test_docs_explain_why_domain_logic_is_shared_but_rendering_is_not():
    docs = read("README.md")
    assert "## What is shared" in docs
    assert "## What stays web-specific" in docs
    assert "## What stays native-specific" in docs
    assert "## Why rendering is not shared" in docs
    assert "not a production application" in docs
    assert "Do not supply production credentials" in docs
