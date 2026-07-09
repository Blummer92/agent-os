# Docstring Requirements

## Function/Class Docstrings

```python
def validator_function(data):
    """
    Validate input data against schema.

    Args:
        data: Dictionary to validate

    Returns:
        ValidationResult: Object with status and errors

    Raises:
        ValueError: If data is None
    """
```

## Test Docstrings

State the scenario and the expected outcome, not just what's being called:

```python
def test_validator_with_empty_dict():
    """
    Test validator behavior with empty dictionary input.

    Expected: Returns invalid status with 'missing required fields' error.
    """
```
