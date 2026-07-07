# Python Integration Testing Standard

## Overview
Integration tests verify that multiple components work together correctly. They test workflows, data flows between components, and real or simulated external services. Integration tests are slower than unit tests but catch real-world interaction issues.

## Scope
- Component interactions (CLI → validator → database)
- Workflows across multiple modules
- Real or test databases, files, or services
- Error propagation across components
- Performance with real data

## Test Size Characteristics
- **Execution:** < 1 second per test
- **Setup:** Fixtures provide test databases or services
- **Assertions:** 2-5 assertions (verify complete workflow)
- **Dependencies:** Real or test doubles (not all mocked)

## Directory Organization

```
tests/
├── unit/                    # Isolated unit tests
│   ├── test_validators.py
│   └── test_cli.py
└── integration/             # Component interaction tests
    ├── conftest.py         # Integration fixtures
    ├── test_workflows.py    # End-to-end workflows
    ├── test_cli_to_db.py    # CLI → database
    ├── test_api_calls.py    # With mocked external APIs
    └── fixtures/
        ├── sample_files.py
        └── test_db.py
```

## Test Structure Template

```python
# tests/integration/test_workflows.py
class TestValidationWorkflow:
    """Test validation process from input to report."""
    
    def test_csv_validation_complete_workflow(self, tmp_path, test_db):
        """
        Test complete validation workflow:
        1. Load CSV file
        2. Validate each row
        3. Save results to database
        4. Generate report
        """
        # Arrange: Create test CSV
        input_file = tmp_path / "data.csv"
        input_file.write_text("name,email\nJohn,john@example.com\n")
        
        # Act: Run full workflow
        workflow = ValidationWorkflow(db=test_db)
        results = workflow.process_file(input_file)
        
        # Assert: Verify results at each stage
        assert results.rows_processed == 1
        assert results.rows_valid == 1
        assert results.rows_invalid == 0
        
        # Verify data was saved
        saved = test_db.get_validation_results()
        assert len(saved) == 1
        assert saved[0].email == "john@example.com"
```

## External Service Mocking

### Mock HTTP APIs
```python
def test_processor_with_mocked_api(mocker):
    """Test processor behavior with external API."""
    # Mock the requests library
    mock_response = mocker.MagicMock()
    mock_response.json.return_value = {
        "id": 123,
        "name": "Product",
        "price": 99.99,
    }
    mock_get = mocker.patch("requests.get")
    mock_get.return_value = mock_response
    
    # Call function that uses API
    product = get_product_details(123)
    
    # Verify API was called correctly
    mock_get.assert_called_once_with("https://api.example.com/products/123")
    assert product["price"] == 99.99
```

### Mock with Side Effects (Errors)
```python
def test_processor_handles_api_error(mocker):
    """Test processor handles API failures gracefully."""
    mock_get = mocker.patch("requests.get")
    mock_get.side_effect = requests.ConnectionError("API down")
    
    # Should handle error without crashing
    result = process_with_fallback(123)
    assert result["status"] == "fallback_used"
```

### Test Retries and Timeouts
```python
def test_processor_retries_on_timeout(mocker):
    """Test processor retries when API times out."""
    mock_get = mocker.patch("requests.get")
    
    # First call fails, second succeeds
    mock_get.side_effect = [
        requests.Timeout(),
        mocker.MagicMock(json=lambda: {"id": 1}),
    ]
    
    result = process_with_retry(1)
    
    # Verify retry happened
    assert mock_get.call_count == 2
    assert result["id"] == 1
```

## Database Testing

### Using Test Fixtures with Real Connections
```python
# tests/integration/conftest.py
@pytest.fixture
def test_db(tmp_path):
    """Create temporary test database."""
    db_path = tmp_path / "test.db"
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    
    yield db
    
    # Cleanup
    db.close()

@pytest.fixture
def populated_db(test_db):
    """Provide database with sample data."""
    test_db.users.insert({"id": 1, "name": "John", "email": "john@example.com"})
    test_db.users.insert({"id": 2, "name": "Jane", "email": "jane@example.com"})
    return test_db
```

### Testing Data Persistence
```python
def test_data_saved_and_retrieved(populated_db):
    """Test data persists and can be retrieved."""
    # Data was inserted in fixture
    user = populated_db.users.get(id=1)
    
    assert user.name == "John"
    assert user.email == "john@example.com"
```

### Testing Data Relationships
```python
def test_user_orders_relationship(test_db):
    """Test relationship between users and orders."""
    # Create user
    user = test_db.users.create(name="John")
    
    # Create orders
    order1 = test_db.orders.create(user_id=user.id, total=100.00)
    order2 = test_db.orders.create(user_id=user.id, total=200.00)
    
    # Verify relationship
    user_orders = test_db.orders.filter(user_id=user.id)
    assert len(user_orders) == 2
    assert sum(o.total for o in user_orders) == 300.00
```

### Database Cleanup & Rollback
```python
@pytest.fixture
def clean_db(test_db):
    """Rollback database after each test."""
    test_db.begin_transaction()
    yield test_db
    test_db.rollback()  # Clean slate for next test

def test_with_auto_cleanup(clean_db):
    """Database is automatically cleaned up."""
    clean_db.users.insert({"name": "Test User"})
    # Test runs...
    # Database is rolled back after test
```

## File System Testing

### Testing File Operations
```python
def test_report_generator_creates_file(tmp_path):
    """Test report generator creates output file."""
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    
    generator = ReportGenerator(output_dir=output_dir)
    generator.generate()
    
    # Verify file was created
    report_file = output_dir / "report.txt"
    assert report_file.exists()
    
    # Verify content
    content = report_file.read_text()
    assert "Summary" in content
```

### Testing File Formats
```python
def test_csv_export(tmp_path):
    """Test CSV export format and content."""
    csv_file = tmp_path / "export.csv"
    
    export_data([{"id": 1, "name": "John"}], csv_file)
    
    # Verify CSV structure
    lines = csv_file.read_text().strip().split("\n")
    assert lines[0] == "id,name"  # Header
    assert lines[1] == "1,John"   # Data
```

## CLI Testing

### Testing Command Line Interface
```python
from click.testing import CliRunner

def test_cli_validation_command(tmp_path):
    """Test CLI validate command."""
    runner = CliRunner()
    
    # Create test file
    input_file = tmp_path / "input.csv"
    input_file.write_text("email\ntest@example.com\n")
    
    # Run CLI command
    result = runner.invoke(cli.validate, [str(input_file)])
    
    # Verify exit code and output
    assert result.exit_code == 0
    assert "Valid" in result.output
```

### Testing CLI Error Handling
```python
def test_cli_handles_missing_file():
    """Test CLI error message for missing file."""
    runner = CliRunner()
    result = runner.invoke(cli.validate, ["nonexistent.csv"])
    
    assert result.exit_code != 0
    assert "not found" in result.output
```

## Async/Concurrent Testing

### Testing Async Functions
```python
@pytest.mark.asyncio
async def test_async_data_processing():
    """Test async data processing workflow."""
    data = [1, 2, 3, 4, 5]
    results = await process_async(data)
    
    assert len(results) == 5
    assert all(r > 0 for r in results)
```

### Testing Concurrent Operations
```python
@pytest.mark.asyncio
async def test_concurrent_requests(mocker):
    """Test multiple concurrent requests."""
    mock_get = mocker.patch("aiohttp.ClientSession.get")
    mock_get.return_value.json = mocker.AsyncMock(
        return_value={"id": 1}
    )
    
    results = await fetch_multiple([1, 2, 3])
    
    assert len(results) == 3
    assert mock_get.call_count == 3
```

## Performance Integration Testing

### Testing Performance Characteristics
```python
@pytest.mark.integration
def test_processor_handles_large_dataset_in_reasonable_time(benchmark):
    """Test processor doesn't degrade with larger datasets."""
    large_dataset = [{"id": i, "value": i * 2} for i in range(10000)]
    
    # Benchmark the operation
    result = benchmark(process_dataset, large_dataset)
    
    # Verify result is correct and performance is acceptable
    assert len(result) == 10000
    # pytest-benchmark will report on timing
```

### Memory Usage Testing
```python
def test_processor_memory_efficient(mocker):
    """Verify processor doesn't have memory leaks."""
    import tracemalloc
    
    tracemalloc.start()
    
    # Run operation
    result = process_large_file("large_file.csv")
    
    current, peak = tracemalloc.get_traced_memory()
    
    # Memory usage should stay reasonable
    assert peak < 500_000_000  # 500MB
    assert result.rows_processed > 0
```

## Error Scenario Testing

### Test Error Propagation
```python
def test_error_handling_across_components(mocker):
    """Test error is properly handled and reported."""
    # Mock validator to fail
    mocker.patch("validator.validate", side_effect=ValueError("Bad data"))
    
    # Error should propagate to report
    report = generate_report(invalid_data)
    
    assert report.success is False
    assert "Bad data" in report.error_message
```

### Test Graceful Degradation
```python
def test_processor_continues_on_partial_failure(test_db):
    """Test processor handles some failures gracefully."""
    # Mix of valid and invalid data
    data = [
        {"id": 1, "email": "valid@example.com"},      # Valid
        {"id": 2, "email": "invalid-email"},          # Invalid
        {"id": 3, "email": "another@example.com"},    # Valid
    ]
    
    result = process_batch(data)
    
    # Should process valid records despite invalid ones
    assert result.success_count == 2
    assert result.error_count == 1
    assert result.total == 3
```

## Marking and Running Integration Tests

### Mark Integration Tests
```python
# Use markers to separate unit and integration tests
@pytest.mark.integration
def test_database_workflow():
    pass

@pytest.mark.slow
def test_large_file_processing():
    pass
```

### Run Specific Test Categories
```bash
# Only unit tests (fast)
pytest -m "not integration"

# Only integration tests
pytest -m integration

# Skip slow tests
pytest -m "not slow"

# Everything
pytest
```

## Configuration

### pytest.ini for Integration Tests
```ini
[pytest]
testpaths = tests
markers =
    integration: marks tests as integration tests
    slow: marks tests as slow running
    asyncio: marks tests as async
```

## Best Practices

- [ ] Each integration test tests one workflow/scenario
- [ ] Fixtures provide clean test environment (DB, files, etc.)
- [ ] External APIs are mocked unless testing API integration
- [ ] Tests cleanup after themselves (temp files, DB records)
- [ ] Error paths are tested (not just happy path)
- [ ] Performance is acceptable (< 1 second per test)
- [ ] Async operations use @pytest.mark.asyncio
- [ ] No test interdependencies
- [ ] Real databases use fixtures with teardown
- [ ] Randomness is seeded for reproducibility

## Version
0.1.0

## Changelog
- 0.1.0: Initial integration testing standard