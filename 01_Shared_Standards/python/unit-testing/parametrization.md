# Parameterized Tests

## Why Parametrize?

Avoid repeating test logic for similar cases:

```python
# Without parametrization (repetitive)
def test_validate_short_name(self):
    assert validate_name('A')

def test_validate_long_name(self):
    assert validate_name('Alexander')

def test_validate_name_with_space(self):
    assert validate_name('John Doe')
```

## With @pytest.mark.parametrize

```python
import pytest

@pytest.mark.parametrize('name,is_valid', [
    ('A', True),
    ('Alexander', True),
    ('John Doe', True),
    ('', False),
    ('123', False),
])
def test_validate_name(name, is_valid):
    """Test various name formats."""
    assert validate_name(name) == is_valid
```

## Multiple Parameters

```python
@pytest.mark.parametrize('price,discount,expected', [
    (100, 0.10, 90),
    (50, 0.20, 40),
    (0, 0.50, 0),
])
def test_apply_discount(price, discount, expected):
    result = apply_discount(price, discount)
    assert result == expected
```

## Multiple Parametrize Decorators

```python
@pytest.mark.parametrize('input_value', [1, 2, 3])
@pytest.mark.parametrize('multiplier', [2, 3])
def test_multiply(input_value, multiplier):
    """Tests all combinations (6 tests total)."""
    result = input_value * multiplier
    assert result > 0
```

## With Fixtures

```python
@pytest.mark.parametrize('email', [
    'valid@example.com',
    'user+tag@domain.co.uk',
])
def test_validate_email_formats(email, smtp_server):
    """Test different formats with fixture."""
    assert validate_email(email, smtp_server)
```

## Dynamic Parameters

```python
import pytest

test_cases = [
    ('admin', True),
    ('user', False),
    ('guest', False),
]

@pytest.mark.parametrize('role,is_admin', test_cases)
def test_user_roles(role, is_admin):
    user = create_user(role=role)
    assert user.is_admin == is_admin
```
