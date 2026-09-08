from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "01_Shared_Standards/global-engineering/expo-react-native-development.md"
INDEX = ROOT / "01_Shared_Standards/global-engineering/README.md"


def test_expo_react_native_standard_is_registered_and_extends_shared_standard():
    standard = STANDARD.read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")

    assert "expo-react-native-development.md" in index
    assert "extends `typescript-react-development.md`" in standard
    assert "preferred Agent OS mobile path" in standard


def test_expo_react_native_standard_covers_mobile_acceptance_contract():
    standard = STANDARD.read_text(encoding="utf-8")

    required_sections = (
        "## Expo project and workflow boundary",
        "## React Native components and styling",
        "## Platform-safe TypeScript and shared logic",
        "## Navigation and deep links",
        "## Safe area, keyboard, orientation, and screen size",
        "## Accessibility and touch targets",
        "## Permissions and least privilege",
        "## Device API boundary",
        "## Storage and secrets",
        "## Network, offline, and retry behavior",
        "## Required user-visible states",
        "## iOS and Android differences",
        "## Lifecycle and background behavior",
        "## Performance",
        "## Expo configuration and environment handling",
        "## Testing and device acceptance",
        "## Upgrade and dependency policy",
        "## React Native Web boundary",
    )
    for section in required_sections:
        assert section in standard

    assert "Permission denial, restricted status, unavailable hardware" in standard
    assert "Never blindly retry a non-idempotent external mutation" in standard
    assert "representative iOS and Android targets" in standard
    assert "production credentials" in standard
    assert "React Native Web is an option, not a mandate" in standard
    assert "Do not pursue 100% code sharing" in standard
    assert "native module or custom native implementation requires evidence" in standard
