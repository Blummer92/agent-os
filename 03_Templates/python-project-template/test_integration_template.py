"""
Integration Test Template

Use this template for testing multiple components working together.
Integration tests are slower than unit tests but catch real-world issues.

File location: tests/integration/test_<workflow_name>.py
Mark with: @pytest.mark.integration
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock


# ============================================================================
# EXAMPLE: Complete Workflow Integration Test
# ============================================================================

@pytest.mark.integration
class TestValidationWorkflow:
    """Test complete validation workflow from file input to output."""

    def test_csv_validation_complete_workflow(self, temp_dir, test_db_connection):
        """
        Test complete validation workflow:
        1. Load CSV file
        2. Parse rows
        3. Validate each row
        4. Save valid results to database
        5. Generate report
        """
        # Arrange
        from myapp.workflow import ValidationWorkflow

        input_file = temp_dir / "input.csv"
        input_file.write_text("name,email\nJohn,john@example.com\nJane,jane@example.com\n")
        output_file = temp_dir / "report.txt"

        workflow = ValidationWorkflow(db=test_db_connection)

        # Act
        results = workflow.process_file(input_file, output_file)

        # Assert: Verify workflow completed successfully
        assert results.success is True
        assert results.rows_processed == 2
        assert results.rows_valid == 2
        assert results.rows_invalid == 0

        # Assert: Verify output file was created
        assert output_file.exists()
        content = output_file.read_text()
        assert "Summary" in content
        assert "2 rows processed" in content

    def test_workflow_handles_invalid_rows(self, temp_dir, test_db_connection):
        """Test workflow processes mix of valid and invalid data."""
        from myapp.workflow import ValidationWorkflow

        # Arrange
        input_file = temp_dir / "mixed.csv"
        input_file.write_text(
            "name,email\n"
            "John,john@example.com\n"      # Valid
            "Jane,invalid-email\n"          # Invalid
            "Bob,bob@example.com\n"         # Valid
        )

        workflow = ValidationWorkflow(db=test_db_connection)

        # Act
        results = workflow.process_file(input_file)

        # Assert
        assert results.rows_processed == 3
        assert results.rows_valid == 2
        assert results.rows_invalid == 1
        assert results.success is False  # Some rows failed


# ============================================================================
# EXAMPLE: CLI Integration Test
# ============================================================================

@pytest.mark.integration
class TestCLIWorkflow:
    """Test command-line interface workflows."""

    def test_validate_command_with_file(self, temp_dir):
        """Test CLI validate command with CSV file."""
        from click.testing import CliRunner
        from myapp.cli import main

        # Arrange
        input_file = temp_dir / "data.csv"
        input_file.write_text("email\ntest@example.com\nvalid@example.com\n")

        runner = CliRunner()

        # Act
        result = runner.invoke(main, ['validate', str(input_file)])

        # Assert
        assert result.exit_code == 0
        assert "Valid" in result.output
        assert "2" in result.output  # 2 records processed

    def test_validate_command_missing_file_error(self):
        """Test CLI error handling for missing file."""
        from click.testing import CliRunner
        from myapp.cli import main

        runner = CliRunner()

        # Act
        result = runner.invoke(main, ['validate', 'nonexistent.csv'])

        # Assert
        assert result.exit_code != 0
        assert "not found" in result.output.lower() or "error" in result.output.lower()

    def test_validate_command_with_options(self, temp_dir):
        """Test CLI validate command with options."""
        from click.testing import CliRunner
        from myapp.cli import main

        # Arrange
        input_file = temp_dir / "data.csv"
        input_file.write_text("email\ntest@example.com\n")
        output_file = temp_dir / "report.txt"

        runner = CliRunner()

        # Act
        result = runner.invoke(main, [
            'validate',
            str(input_file),
            '--output', str(output_file),
            '--strict'
        ])

        # Assert
        assert result.exit_code == 0
        assert output_file.exists()


# ============================================================================
# EXAMPLE: Database Integration Test
# ============================================================================

@pytest.mark.integration
class TestDatabaseWorkflow:
    """Test workflows involving database operations."""

    def test_save_and_retrieve_user(self, test_db_connection):
        """Test saving and retrieving user from database."""
        # Arrange
        from myapp.models import User
        from myapp.database import UserRepository

        repo = UserRepository(test_db_connection)
        user = User(name="John Doe", email="john@example.com")

        # Act
        user_id = repo.save(user)
        retrieved_user = repo.get(user_id)

        # Assert
        assert retrieved_user.name == "John Doe"
        assert retrieved_user.email == "john@example.com"

    def test_user_relationships(self, test_db_connection):
        """Test user and orders relationship."""
        from myapp.models import User, Order
        from myapp.database import UserRepository, OrderRepository

        user_repo = UserRepository(test_db_connection)
        order_repo = OrderRepository(test_db_connection)

        # Arrange & Act
        user_id = user_repo.save(User(name="John", email="john@example.com"))
        order1 = Order(user_id=user_id, total=100.00)
        order2 = Order(user_id=user_id, total=200.00)
        order_repo.save(order1)
        order_repo.save(order2)

        # Assert
        user_orders = order_repo.find_by_user(user_id)
        assert len(user_orders) == 2
        assert sum(o.total for o in user_orders) == 300.00


# ============================================================================
# EXAMPLE: API Integration Test with Mocking
# ============================================================================

@pytest.mark.integration
class TestAPIIntegration:
    """Test integration with external APIs."""

    def test_processor_with_mocked_api(self, mocker):
        """Test processor with mocked external API."""
        from myapp.processor import fetch_and_process

        # Arrange
        mock_api = mocker.patch("requests.get")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 1,
            "name": "Product",
            "price": 99.99,
        }
        mock_api.return_value = mock_response

        # Act
        result = fetch_and_process(1)

        # Assert
        assert result["name"] == "Product"
        assert result["price"] == 99.99
        mock_api.assert_called_once_with("https://api.example.com/products/1")

    def test_processor_handles_api_timeout(self, mocker):
        """Test processor handles API timeouts."""
        from myapp.processor import fetch_and_process
        import requests

        # Arrange
        mock_api = mocker.patch("requests.get")
        mock_api.side_effect = requests.Timeout("Connection timeout")

        # Act
        result = fetch_and_process(1)

        # Assert
        assert result["status"] == "timeout"
        assert result["error"] is not None

    def test_processor_retries_on_error(self, mocker):
        """Test processor retries on API error."""
        from myapp.processor import fetch_and_process_with_retry

        # Arrange
        mock_api = mocker.patch("requests.get")
        mock_api.side_effect = [
            Exception("First call fails"),
            MagicMock(json=lambda: {"id": 1, "status": "ok"}),
        ]

        # Act
        result = fetch_and_process_with_retry(1)

        # Assert
        assert result["status"] == "ok"
        assert mock_api.call_count == 2  # First failed, second succeeded


# ============================================================================
# EXAMPLE: File Processing Integration Test
# ============================================================================

@pytest.mark.integration
class TestFileProcessing:
    """Test file processing workflows."""

    def test_import_csv_to_database(self, temp_dir, test_db_connection):
        """Test importing CSV file data to database."""
        from myapp.importer import import_csv

        # Arrange
        csv_file = temp_dir / "users.csv"
        csv_file.write_text(
            "id,name,email\n"
            "1,Alice,alice@example.com\n"
            "2,Bob,bob@example.com\n"
        )

        # Act
        count = import_csv(csv_file, test_db_connection)

        # Assert
        assert count == 2

    def test_export_database_to_csv(self, temp_dir, test_db_connection):
        """Test exporting database data to CSV."""
        from myapp.exporter import export_to_csv

        # Arrange: Populate database
        test_db_connection.insert("users", {"name": "Alice", "email": "alice@example.com"})
        test_db_connection.insert("users", {"name": "Bob", "email": "bob@example.com"})

        output_file = temp_dir / "export.csv"

        # Act
        export_to_csv("users", output_file, test_db_connection)

        # Assert
        assert output_file.exists()
        content = output_file.read_text()
        assert "Alice" in content
        assert "Bob" in content


# ============================================================================
# EXAMPLE: Error Scenario Integration Test
# ============================================================================

@pytest.mark.integration
class TestErrorScenarios:
    """Test integration test error handling."""

    def test_workflow_with_corrupted_data(self, temp_dir, test_db_connection):
        """Test workflow handles corrupted input gracefully."""
        from myapp.workflow import ValidationWorkflow

        # Arrange
        input_file = temp_dir / "corrupted.csv"
        input_file.write_text("name,email\n" + "A" * 10000 + "\n")  # Invalid data

        workflow = ValidationWorkflow(db=test_db_connection)

        # Act & Assert
        result = workflow.process_file(input_file)
        assert result.success is False
        assert result.error_message is not None

    def test_workflow_with_database_error(self, temp_dir, mocker):
        """Test workflow handles database errors."""
        from myapp.workflow import ValidationWorkflow

        # Arrange
        input_file = temp_dir / "data.csv"
        input_file.write_text("name,email\nJohn,john@example.com\n")

        mock_db = MagicMock()
        mock_db.insert.side_effect = Exception("Database connection lost")

        workflow = ValidationWorkflow(db=mock_db)

        # Act & Assert
        with pytest.raises(Exception, match="Database"):
            workflow.process_file(input_file)


# ============================================================================
# BEST PRACTICES CHECKLIST
# ============================================================================
"""
When writing integration tests, ensure:

- [ ] Marked with @pytest.mark.integration
- [ ] Tests one complete workflow or feature
- [ ] Uses real database/file system (or reliable test doubles)
- [ ] External APIs are mocked appropriately
- [ ] Test data setup is in fixtures
- [ ] Database cleanup in fixture teardown
- [ ] Handles error scenarios
- [ ] Verifies end-to-end behavior
- [ ] Tests actual interactions between components
- [ ] Not testing implementation details
- [ ] Run in CI/CD pipeline
- [ ] No hardcoded paths or credentials
"""
