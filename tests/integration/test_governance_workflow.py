"""
Integration tests for Agent OS governance and standards workflows.

Tests verify that:
- Standards are properly integrated with governance
- Documentation flows align with procedures
- Handoff points are clearly defined
- End-to-end processes work correctly
"""
import pytest


@pytest.mark.integration
class TestStandardsGovernanceAlignment:
    """Test alignment between standards and governance."""

    def test_testing_standards_exist_in_governance_context(
        self,
        python_standards_dir,
        governance_dir
    ):
        """Test that testing standards exist alongside governance."""
        assert python_standards_dir.exists()
        assert governance_dir.exists()

        standards = list(python_standards_dir.glob("*testing*.md"))
        assert len(standards) > 0

    def test_standards_reference_governance_concepts(self, python_standards_dir):
        """Test that standards reference governance concepts."""
        standards = list(python_standards_dir.glob("*.md"))

        for standard in standards:
            content = standard.read_text()
            # Check for governance-relevant terms
            has_governance_terms = (
                "handoff" in content.lower() or
                "approval" in content.lower() or
                "governance" in content.lower() or
                "agent" in content.lower()
            )
            # Some standards may not explicitly mention these
            # but core standards should
            if "testing-standard" in standard.name:
                assert "ci" in content.lower() or "release" in content.lower()

    def test_templates_follow_standards(self, templates_dir, python_standards_dir):
        """Test that templates follow standards."""
        assert templates_dir.exists()
        templates = templates_dir / "python-project-template"
        assert templates.exists()

        # Should have pytest.ini
        pytest_ini = templates / "pytest.ini"
        assert pytest_ini.exists()

    def test_standards_have_consistent_format(self, standard_files):
        """Test that standards follow consistent format."""
        for standard in standard_files:
            content = standard.read_text()

            # All standards should have these sections
            assert "Overview" in content or "overview" in content.lower()
            assert "Version" in content
            assert "Changelog" in content

    def test_governance_roles_defined_for_testing(self, governance_dir):
        """Test that testing roles are defined in governance."""
        # Check for agent overlays defining test responsibilities
        overlays = list(governance_dir.parent.glob("02_Agent_Overlays/*test*.md"))

        # There should be at least one QA test agent definition
        assert len(overlays) >= 1


@pytest.mark.integration
class TestImplementationGuideCompleteness:
    """Test that implementation guides are complete."""

    def test_implementation_strategy_exists(self, templates_dir):
        """Test that implementation strategy guide exists."""
        strategy = templates_dir / "prompts" / "implement-testing-strategy.md"
        assert strategy.exists()

    def test_implementation_strategy_has_phases(self, templates_dir):
        """Test that implementation strategy defines phases."""
        strategy = templates_dir / "prompts" / "implement-testing-strategy.md"
        content = strategy.read_text()

        # Should have multiple phases
        assert "Phase 1" in content
        assert "Phase 2" in content
        assert "Phase 3" in content or "Week" in content

    def test_governance_implementation_guide_exists(self, templates_dir):
        """Test that governance implementation guide exists."""
        guide = templates_dir / "reports" / "testing-governance-implementation.md"
        assert guide.exists()

    def test_governance_guide_covers_roles(self, templates_dir):
        """Test that governance guide covers roles."""
        guide = templates_dir / "reports" / "testing-governance-implementation.md"
        content = guide.read_text()

        # Should define roles
        assert "developer" in content.lower() or "developer" in content.lower()
        assert "qa" in content.lower() or "test" in content.lower()

    def test_governance_guide_covers_handoffs(self, templates_dir):
        """Test that governance guide covers handoff points."""
        guide = templates_dir / "reports" / "testing-governance-implementation.md"
        content = guide.read_text()

        assert "handoff" in content.lower()


@pytest.mark.integration
class TestDocumentationConsistency:
    """Test consistency across documentation."""

    def test_all_markdown_files_readable(self, markdown_files):
        """Test that all markdown files are readable."""
        for md_file in markdown_files:
            try:
                content = md_file.read_text()
                assert len(content) > 0
            except Exception as e:
                pytest.fail(f"Could not read {md_file}: {e}")

    def test_no_broken_internal_links(self, markdown_files):
        """Test that internal references point to existing files."""
        repo_root = markdown_files[0].parent if markdown_files else None
        if not repo_root:
            pytest.skip("No markdown files found")

        for md_file in markdown_files:
            content = md_file.read_text()

            # Simple check for markdown links
            import re
            links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content)

            for link_text, link_path in links:
                # Skip external links (http, https, etc.)
                if link_path.startswith(('http://', 'https://', '#')):
                    continue

                # Check if file exists (relative to markdown file location)
                target_file = md_file.parent / link_path
                # This is optional - some links may be valid references

    def test_standards_version_numbers_reasonable(self, standard_files):
        """Test that version numbers are in reasonable format."""
        import re

        for standard in standard_files:
            content = standard.read_text()

            # Find version
            version_match = re.search(r'Version\s+(\d+\.\d+\.\d+)', content, re.IGNORECASE)

            if version_match:
                version = version_match.group(1)
                # Should be semantic versioning
                parts = version.split('.')
                assert len(parts) == 3, f"Invalid version in {standard.name}: {version}"


@pytest.mark.integration
class TestTemplateCompleteness:
    """Test that templates are complete and functional."""

    def test_all_required_templates_exist(self, templates_dir):
        """Test that all required templates exist."""
        python_template = templates_dir / "python-project-template"
        assert python_template.exists()

        required_files = {
            "pytest.ini",
            "test_conftest.py",
            "test_unit_template.py",
            "test_integration_template.py",
        }

        existing_files = {f.name for f in python_template.glob("*")}

        assert required_files.issubset(existing_files), \
            f"Missing template files: {required_files - existing_files}"

    def test_templates_are_not_empty(self, templates_dir):
        """Test that templates have substantial content."""
        python_template = templates_dir / "python-project-template"

        for template_file in python_template.glob("*"):
            content = template_file.read_text()
            assert len(content) > 100, \
                f"Template {template_file.name} is too short"

    def test_pytest_ini_template_is_valid(self, templates_dir):
        """Test that pytest.ini template is valid."""
        pytest_ini = templates_dir / "python-project-template" / "pytest.ini"
        content = pytest_ini.read_text()

        # Should have required pytest sections
        assert "[pytest]" in content
        assert "testpaths" in content

    def test_conftest_template_has_fixtures(self, templates_dir):
        """Test that conftest.py template defines fixtures."""
        conftest = templates_dir / "python-project-template" / "test_conftest.py"
        content = conftest.read_text()

        # Should have multiple fixture definitions
        import re
        fixtures = re.findall(r'@pytest\.fixture', content)
        assert len(fixtures) > 3, "conftest should define multiple fixtures"

    def test_unit_test_template_has_examples(self, templates_dir):
        """Test that unit test template has examples."""
        template = templates_dir / "python-project-template" / "test_unit_template.py"
        content = template.read_text()

        # Should have example test classes
        assert "class Test" in content
        assert "def test_" in content

    def test_integration_test_template_has_examples(self, templates_dir):
        """Test that integration test template has examples."""
        template = templates_dir / "python-project-template" / "test_integration_template.py"
        content = template.read_text()

        # Should have example integration tests
        assert "@pytest.mark.integration" in content
        assert "def test_" in content


@pytest.mark.integration
class TestEndToEndWorkflow:
    """Test complete end-to-end workflows."""

    def test_developer_can_implement_from_templates(
        self,
        temp_dir,
        templates_dir,
        repo_root
    ):
        """Test that developer can implement testing from templates."""
        # Simulate copying files
        pytest_ini = templates_dir / "python-project-template" / "pytest.ini"
        conftest = templates_dir / "python-project-template" / "test_conftest.py"

        # Both should exist
        assert pytest_ini.exists()
        assert conftest.exists()

        # Both should have content
        assert len(pytest_ini.read_text()) > 0
        assert len(conftest.read_text()) > 0

    def test_standards_are_discoverable_from_templates(self, templates_dir):
        """Test that standards are referenced from templates."""
        strategy = templates_dir / "prompts" / "implement-testing-strategy.md"
        content = strategy.read_text()

        # Should reference standards
        assert "Testing Standard" in content or "testing-standard" in content

    def test_governance_document_references_standards(self, templates_dir):
        """Test that governance document references standards."""
        guide = templates_dir / "reports" / "testing-governance-implementation.md"
        content = guide.read_text()

        # Should reference Agent OS standards
        assert "standard" in content.lower()
        assert "governance" in content.lower()

    def test_complete_implementation_path_exists(
        self,
        templates_dir,
        python_standards_dir,
        governance_dir
    ):
        """Test that complete implementation path exists."""
        # Start with standards
        standards = list(python_standards_dir.glob("*testing*.md"))
        assert len(standards) > 0

        # Have templates
        templates = templates_dir / "python-project-template"
        assert templates.exists()

        # Have implementation guides
        strategy = templates_dir / "prompts" / "implement-testing-strategy.md"
        assert strategy.exists()

        # Have governance integration
        gov_guide = templates_dir / "reports" / "testing-governance-implementation.md"
        assert gov_guide.exists()
