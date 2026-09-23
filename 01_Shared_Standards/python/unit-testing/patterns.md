# Unit Test Patterns (AAA)

## Arrange-Act-Assert Pattern

Every unit test follows three steps:

### Arrange: Set up test conditions

```python
def test_calculate_discount():
    """Test discount calculation."""
    # ARRANGE - Set up inputs
    price = 100
    discount_rate = 0.10
```

### Act: Execute the code being tested

```python
    # ACT - Execute function
    discounted_price = calculate_discount(price, discount_rate)
```

### Assert: Verify the result

```python
    # ASSERT - Verify result
    expected = 90
    assert discounted_price == expected
```

## Complete Example

```python
class TestPriceCalculation:
    """Test price calculations."""
    
    def test_apply_discount(self):
        """Discount reduces price correctly."""
        # ARRANGE
        original_price = 100
        discount = 0.20
        
        # ACT
        result = apply_discount(original_price, discount)
        
        # ASSERT
        assert result == 80
    
    def test_invalid_discount_raises_error(self):
        """Invalid discount raises ValueError."""
        # ARRANGE
        price = 100
        invalid_discount = -0.10
        
        # ACT & ASSERT
        with pytest.raises(ValueError):
            apply_discount(price, invalid_discount)
```

## Golden Rules

1. **One assertion per test** (or related assertions)
2. **Clear test names** that describe what's being tested
3. **Minimize setup code** (use fixtures for reuse)
4. **Test behavior, not implementation**
5. **Avoid test interdependencies**
