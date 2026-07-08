# Assertions and Error Testing

## Basic Assertions

```python
assert x == expected        # Equality
assert x is not None        # Identity
assert x in [1, 2, 3]       # Membership
assert isinstance(x, str)   # Type check
assert x > 0                # Comparison
```

## Better: pytest Assertions

```python
from pytest import approx

# Numbers with tolerance
assert result == approx(3.14, rel=1e-2)

# Strings
assert message.startswith('Error:')
assert 'warning' in message.lower()

# Collections
assert result == {'key': 'value'}
assert len(items) == 3
```

## Testing Exceptions

```python
import pytest

def test_invalid_input_raises_error(self):
    """Test that function raises correct exception."""
    with pytest.raises(ValueError) as exc_info:
        my_function(invalid_input)
    
    # Check exception message
    assert 'Expected integer' in str(exc_info.value)
```

## Testing Multiple Conditions

```python
def test_user_creation(self):
    """Test user object has correct attributes."""
    user = create_user('John', 'john@example.com')
    
    # Related assertions - grouped together
    assert user.name == 'John'
    assert user.email == 'john@example.com'
    assert user.is_active is True
```

## Clear Assertion Messages

```python
# Good: Message explains what failed
assert user.age >= 18, f"User {user.id} must be 18+ years old"

# Better: pytest shows detailed diff automatically
assert user == expected_user
```

## What NOT to Assert

❌ Don't assert on mocks unnecessarily
❌ Don't assert internal implementation details
❌ Don't assert on random data (seed randomness)
❌ Don't assert multiple unrelated things

## Pattern: Assertions with Values

```python
result = expensive_function()

# Verify behavior, not just existence
assert result is not None        # ✓ Meaningful
assert result is not []          # ✗ Redundant
assert len(result) > 0           # ✓ Better
```
