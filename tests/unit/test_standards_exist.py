"""
Unit tests for Agent OS testing standards.

Tests verify that:
- All required standards exist
- Standards have required sections
- Standards are properly formatted
- Standards follow the governance framework
"""
import pytest


@pytest.mark.unit
class TestTestingStandardExists:
    """Test Python Testing Standard."""

    def test_testing_standard_file_exists(self, testing_standard):
        """Test that Python Testing Standard file exists."""
        assert testing_standard.exists()
        assert testing_standard.name == "testing-standard.md"
        assert testing_standard.suffix == ".md"

    def test_testing_standard_is_readable(self, testing_standard):
        """Test that standard file is readable."""
        content = testing_standard.read_text()
        assert len(content) > 0
        assert "Testing Standard" in content

    def test_testing_standard_has_version(self, testing_standard):
        """Test that standard specifies version."""
        content = testing_standard.read_text()
        assert "Version" in content
        assert "0.2.0" in content or "0.1.0" in content

    def test_testing_standard_has_coverage_requirement(self, testing_standard):
        """Test that standard defines coverage requirements."""
        content = testing_standard.read_text()
        assert "coverage" in content.lower()
        assert "80" in content  # 80% minimum

    def test_testing_standard_has_framework_section(self, testing_standard):
        """Test that standard specifies testing framework."""
        content = testing_standard.read_text()
        assert "pytest" in content.lower()

    def test_testing_standard_has_examples(self, testing_standard):
        """Test that standard includes code examples."""
        content = testing_standard.read_text()
        assert "```python" in content or "```" in content


@pytest.mark.unit
class TestUnitTestingStandardExists:
    """Test Unit Testing Standard."""

    def test_unit_testing_standard_file_exists(self, unit_testing_standard):
        """Test that Unit Testing Standard file exists."""
        assert unit_testing_standard.exists()
        assert unit_testing_standard.name == "unit-testing-standard.md"

    def test_unit_testing_standard_has_content(self, unit_testing_standard):
        """Test that unit testing standard has substantial content."""
        content = unit_testing_standard.read_text()
        assert len(content) > 1000  # Should be comprehensive
        assert "Unit Testing" in content

    def test_unit_testing_standard_has_naming_patterns(self, unit_testing_standard):
        """Test that standard defines test naming patterns."""
        content = unit_testing_standard.read_text()
        assert "test_" in content or "naming" in content.lower()

    def test_unit_testing_standard_has_fixture_guidance(self, unit_testing_standard):
        """Test that standard covers fixtures."""
        content = unit_testing_standard.read_text()
        assert "fixture" in content.lower()

    def test_unit_testing_standard_has_mocking_patterns(self, unit_testing_standard):
        """Test that standard covers mocking."""
        content = unit_testing_standard.read_text()
        assert "mock" in content.lower()


@pytest.mark.unit
class TestIntegrationTestingStandardExists:
    """Test Integration Testing Standard."""

    def test_integration_testing_standard_file_exists(self, integration_testing_standard):
        """Test that Integration Testing Standard file exists."""
        assert integration_testing_standard.exists()
        assert integration_testing_standard.name == "integration-testing-standard.md"

    def test_integration_testing_standard_has_content(self, integration_testing_standard):
        """Test that integration testing standard has substantial content."""
        content = integration_testing_standard.read_text()
        assert len(content) > 1000
        assert "Integration Testing" in content or "integration" in content.lower()

    def test_integration_testing_standard_covers_workflows(self, integration_testing_standard):
        """Test that standard covers workflow testing."""
        content = integration_testing_standard.read_text()
        assert "workflow" in content.lower() or "component" in content.lower()

    def test_integration_testing_standard_covers_databases(self, integration_testing_standard):
        """Test that standard covers database testing."""
        content = integration_testing_standard.read_text()
        assert "database" in content.lower() or "db" in content.lower()

    def test_integration_testing_standard_covers_apis(self, integration_testing_standard):
        """Test that standard covers API testing."""
        content = integration_testing_standard.read_text()
        assert "api" in content.lower() or "http" in content.lower()


@pytest.mark.unit
class TestTestEnvironmentSetupExists:
    """Test Environment Setup Guide."""

    def test_environment_setup_file_exists(self, test_environment_setup):
        """Test that Test Environment Setup file exists."""
        assert test_environment_setup.exists()
        assert test_environment_setup.name == "test-environment-setup.md"

    def test_environment_setup_has_content(self, test_environment_setup):
        """Test that environment setup guide has substantial content."""
        content = test_environment_setup.read_text()
        assert len(content) > 1000
        assert "environment" in content.lower() or "setup" in content.lower()

    def test_environment_setup_covers_local_dev(self, test_environment_setup):
        """Test that guide covers local development setup."""
        content = test_environment_setup.read_text()
        assert "local" in content.lower() or "development" in content.lower()

    def test_environment_setup_covers_docker(self, test_environment_setup):
        """Test that guide covers Docker setup."""
        content = test_environment_setup.read_text()
        assert "docker" in content.lower()

    def test_environment_setup_covers_ci_cd(self, test_environment_setup):
        """Test that guide covers CI/CD setup."""
        content = test_environment_setup.read_text()
        assert "ci" in content.lower() or "github" in content.lower()


@pytest.mark.unit
class TestPyTestConfiguration:
    """Test pytest configuration."""

    def test_pytest_ini_exists(self, repo_root):
        """Test that pytest.ini exists."""
        pytest_ini = repo_root / "pytest.ini"
        assert pytest_ini.exists()

    def test_pytest_ini_has_testpaths(self, repo_root):
        """Test that pytest.ini specifies test paths."""
        pytest_ini = repo_root / "pytest.ini"
        content = pytest_ini.read_text()
        assert "testpaths" in content
        assert "tests" in content

    def test_pytest_ini_has_markers(self, repo_root):
        """Test that pytest.ini defines markers."""
        pytest_ini = repo_root / "pytest.ini"
        content = pytest_ini.read_text()
        assert "markers" in content
        assert "unit" in content or "integration" in content

    def test_conftest_exists(self, repo_root):
        """Test that tests/conftest.py exists."""
        conftest = repo_root / "tests" / "conftest.py"
        assert conftest.exists()

    def test_conftest_has_fixtures(self, repo_root):
        """Test that conftest.py defines fixtures."""
        conftest = repo_root / "tests" / "conftest.py"
        content = conftest.read_text()
        assert "@pytest.fixture" in content


@pytest.mark.unit
class TestTestDirectoryStructure:
    """Test test directory structure."""

    def test_tests_directory_exists(self, repo_root):
        """Test that tests directory exists."""
        tests_dir = repo_root / "tests"
        assert tests_dir.exists()
        assert tests_dir.is_dir()

    def test_unit_tests_directory_exists(self, repo_root):
        """Test that tests/unit directory exists."""
        unit_dir = repo_root / "tests" / "unit"
        assert unit_dir.exists()
        assert unit_dir.is_dir()

    def test_integration_tests_directory_exists(self, repo_root):
        """Test that tests/integration directory exists."""
        integration_dir = repo_root / "tests" / "integration"
        assert integration_dir.exists()
        assert integration_dir.is_dir()

    def test_fixtures_directory_exists(self, repo_root):
        """Test that tests/fixtures directory exists."""
        fixtures_dir = repo_root / "tests" / "fixtures"
        assert fixtures_dir.exists()
        assert fixtures_dir.is_dir()

    def test_tests_has_init_files(self, repo_root):
        """Test that __init__.py files exist for test packages."""
        init_files = list((repo_root / "tests").rglob("__init__.py"))
        assert len(init_files) > 0


@pytest.mark.unit
class TestRequirementsFiles:
    """Test development requirements."""

    def test_requirements_dev_exists(self, repo_root):
        """Test that requirements-dev.txt exists."""
        req_dev = repo_root / "requirements-dev.txt"
        assert req_dev.exists()

    def test_requirements_dev_has_pytest(self, repo_root):
        """Test that requirements-dev.txt includes pytest."""
        req_dev = repo_root / "requirements-dev.txt"
        content = req_dev.read_text()
        assert "pytest" in content.lower()

    def test_requirements_dev_has_coverage(self, repo_root):
        """Test that requirements-dev.txt includes coverage tools."""
        req_dev = repo_root / "requirements-dev.txt"
        content = req_dev.read_text()
        assert "pytest-cov" in content.lower() or "coverage" in content.lower()

    def test_requirements_dev_has_mock(self, repo_root):
        """Test that requirements-dev.txt includes mocking tools."""
        req_dev = repo_root / "requirements-dev.txt"
        content = req_dev.read_text()
        assert "pytest-mock" in content.lower() or "mock" in content.lower()


@pytest.mark.unit
class TestStandardsCompleteness:
    """Test that all standards are present and complete."""

    def test_all_required_standards_exist(self, standard_files):
        """Test that all required standards exist."""
        standard_names = {f.name for f in standard_files}

        required = {
            "testing-standard.md",
            "unit-testing-standard.md",
            "integration-testing-standard.md",
            "test-environment-setup.md",
        }

        assert required.issubset(standard_names), \
            f"Missing standards: {required - standard_names}"

    def test_all_standards_have_version(self, standard_files):
        """Test that all standards specify a version."""
        for standard in standard_files:
            content = standard.read_text()
            assert "Version" in content or "version" in content.lower(), \
                f"{standard.name} is missing version"

    def test_all_standards_are_substantial(self, python_standards_dir):
        """Test that all standards have substantial content."""
        min_length = 5000  # Minimum 5000 characters for actual standards

        # Only check the main testing standards, not placeholder files
        required_standards = {
            "testing-standard.md",
            "unit-testing-standard.md",
            "integration-testing-standard.md",
            "test-environment-setup.md",
        }

        for std_name in required_standards:
            standard = python_standards_dir / std_name
            if standard.exists():
                content = standard.read_text()
                assert len(content) > min_length, \
                    f"{standard.name} is too short ({len(content)} chars < {min_length})"

    def test_standards_are_linked_in_docs(self, repo_root):
        """Test that standards are referenced in documentation."""
        # This is a simple check - standards should be mentioned in README
        readme = repo_root / "README.md"
        if readme.exists():
            content = readme.read_text()
            # At least one standard should be mentioned
            has_reference = (
                "Testing" in content or
                "Standard" in content or
                "Governance" in content
            )
            assert has_reference, "README should reference standards"
