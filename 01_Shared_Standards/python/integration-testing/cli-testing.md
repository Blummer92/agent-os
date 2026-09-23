# CLI Command Testing

## Testing Click Commands

### With Click Test Runner

```python
from click.testing import CliRunner
import pytest

from myapp.cli import main_cli

@pytest.fixture
def cli_runner():
    """Create Click CLI test runner."""
    return CliRunner()

@pytest.mark.integration
def test_user_create_command(cli_runner, test_db):
    """Test 'user create' CLI command."""
    # ACT - Execute CLI command
    result = cli_runner.invoke(main_cli, [
        'user', 'create',
        '--name', 'John Doe',
        '--email', 'john@example.com'
    ])
    
    # ASSERT - Check exit code
    assert result.exit_code == 0
    assert 'User created' in result.output
    
    # Verify database change
    user = test_db.query(User).filter_by(email='john@example.com').first()
    assert user.name == 'John Doe'
```

## Test Command Output

```python
def test_list_users_command(cli_runner, populated_db):
    """Test 'user list' command output."""
    result = cli_runner.invoke(main_cli, ['user', 'list'])
    
    assert result.exit_code == 0
    assert 'alice@example.com' in result.output
    assert 'bob@example.com' in result.output
```

## Test Error Handling

```python
def test_invalid_command_shows_help(cli_runner):
    """Test invalid command shows error."""
    result = cli_runner.invoke(main_cli, ['invalid'])
    
    assert result.exit_code != 0
    assert 'No such command' in result.output

def test_missing_required_argument(cli_runner):
    """Test missing required argument."""
    result = cli_runner.invoke(main_cli, ['user', 'create'])
    
    assert result.exit_code != 0
    assert 'Missing option' in result.output or 'Error' in result.output
```

## Test with File Input/Output

```python
def test_import_users_command(cli_runner, test_db, tmp_path):
    """Test importing users from file."""
    # SETUP - Create input file
    input_file = tmp_path / 'users.csv'
    input_file.write_text('name,email\nJohn,john@example.com\n')
    
    # ACT - Run import command
    result = cli_runner.invoke(main_cli, [
        'user', 'import',
        '--file', str(input_file)
    ])
    
    # ASSERT
    assert result.exit_code == 0
    user = test_db.query(User).filter_by(email='john@example.com').first()
    assert user.name == 'John'
```

## Test Interactive Prompts

Pass stdin input as a list of lines to `cli_runner.invoke()` for prompts
(e.g. `['Jane\n', 'jane@example.com\n']` for name then email prompts).
