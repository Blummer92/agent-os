"""
Unit Test Template

Use this template as a starting point for writing unit tests.
Each test should be independent, fast (< 100ms), and test a single behavior.

File location: tests/unit/test_<module_name>.py
"""
import pytest
from unittest.mock import Mock, patch


# ============================================================================
# EXAMPLE: Validator Unit Tests
# ============================================================================

class TestEmailValidator:
    """Test email validator function."""

    def test_valid_email_returns_true(self):
        """Test that valid email is accepted."""
        # Arrange
        from myapp.validators import validate_email
        email = "user@example.com"

        # Act
        result = validate_email(email)

        # Assert
        assert result is True

    def test_invalid_email_returns_false(self):
        """Test that invalid email is rejected."""
        # Arrange
        from myapp.validators import validate_email
        email = "not-an-email"

        # Act
        result = validate_email(email)

        # Assert
        assert result is False

    def test_empty_string_returns_false(self):
        """Test that empty string is rejected."""
        from myapp.validators import validate_email

        result = validate_email("")
        assert result is False

    def test_none_raises_value_error(self):
        """Test that None input raises ValueError."""
        from myapp.validators import validate_email

        with pytest.raises(ValueError, match="email required"):
            validate_email(None)

    @pytest.mark.parametrize("email,expected", [
        ("simple@example.com", True),
        ("user+tag@example.co.uk", True),
        ("invalid@", False),
        ("@example.com", False),
        ("user name@example.com", False),
    ])
    def test_various_email_formats(self, email, expected):
        """Test email validation with multiple formats."""
        from myapp.validators import validate_email

        result = validate_email(email)
        assert result is expected


# ============================================================================
# EXAMPLE: Function Unit Tests with Mocks
# ============================================================================

class TestDataProcessor:
    """Test data processor that depends on external service."""

    def test_process_valid_data(self, mocker):
        """Test successful data processing."""
        # Arrange
        from myapp.processor import process_data
        mock_api = mocker.patch("myapp.processor.external_api")
        mock_api.fetch.return_value = {"status": "ok"}
        test_data = {"id": 1, "value": 100}

        # Act
        result = process_data(test_data)

        # Assert
        assert result is not None
        mock_api.fetch.assert_called_once()

    def test_process_handles_api_error(self, mocker):
        """Test that processor handles API errors gracefully."""
        from myapp.processor import process_data
        mock_api = mocker.patch("myapp.processor.external_api")
        mock_api.fetch.side_effect = ConnectionError("API down")
        test_data = {"id": 1, "value": 100}

        # Act & Assert
        result = process_data(test_data)
        assert result["status"] == "error"
        assert "API" in result["message"]


# ============================================================================
# EXAMPLE: Class Unit Tests
# ============================================================================

class TestUserModel:
    """Test User model/class."""

    def test_user_creation(self):
        """Test creating a user instance."""
        from myapp.models import User

        user = User(name="John", email="john@example.com")

        assert user.name == "John"
        assert user.email == "john@example.com"

    def test_user_validation(self):
        """Test user validation."""
        from myapp.models import User

        user = User(name="John", email="john@example.com")
        assert user.is_valid()

    def test_user_to_dict(self):
        """Test converting user to dictionary."""
        from myapp.models import User

        user = User(name="John", email="john@example.com")
        data = user.to_dict()

        assert data["name"] == "John"
        assert data["email"] == "john@example.com"

    def test_user_equality(self):
        """Test user equality comparison."""
        from myapp.models import User

        user1 = User(name="John", email="john@example.com")
        user2 = User(name="John", email="john@example.com")

        assert user1 == user2

    def test_user_invalid_email_raises_error(self):
        """Test that invalid email raises error."""
        from myapp.models import User

        with pytest.raises(ValueError):
            User(name="John", email="invalid-email")


# ============================================================================
# EXAMPLE: Calculation Unit Tests
# ============================================================================

class TestCalculations:
    """Test calculation functions."""

    def test_add_positive_numbers(self):
        """Test addition of positive numbers."""
        from myapp.math import add

        result = add(2, 3)
        assert result == 5

    def test_add_negative_numbers(self):
        """Test addition with negative numbers."""
        from myapp.math import add

        result = add(-2, 3)
        assert result == 1

    def test_add_zero(self):
        """Test addition with zero."""
        from myapp.math import add

        assert add(5, 0) == 5
        assert add(0, 0) == 0

    @pytest.mark.parametrize("a,b,expected", [
        (1, 2, 3),
        (-1, 1, 0),
        (0, 0, 0),
        (100, 200, 300),
    ])
    def test_add_various_values(self, a, b, expected):
        """Test addition with various inputs."""
        from myapp.math import add

        result = add(a, b)
        assert result == expected


# ============================================================================
# EXAMPLE: String Processing Unit Tests
# ============================================================================

class TestStringProcessor:
    """Test string processing functions."""

    def test_format_name_capitalizes(self):
        """Test name formatting capitalizes correctly."""
        from myapp.string import format_name

        result = format_name("john doe")
        assert result == "John Doe"

    def test_format_name_handles_single_word(self):
        """Test name formatting with single word."""
        from myapp.string import format_name

        result = format_name("john")
        assert result == "John"

    def test_format_name_handles_multiple_spaces(self):
        """Test name formatting handles extra spaces."""
        from myapp.string import format_name

        result = format_name("john   doe")
        assert result == "John Doe"

    def test_sanitize_removes_special_chars(self):
        """Test sanitization removes special characters."""
        from myapp.string import sanitize

        result = sanitize("hello<script>alert()</script>")
        assert "<script>" not in result
        assert "hello" in result


# ============================================================================
# BEST PRACTICES CHECKLIST
# ============================================================================
"""
When writing unit tests, ensure:

- [ ] Test name describes what is being tested: test_<function>_<scenario>
- [ ] Each test is independent (no dependencies on other tests)
- [ ] Each test tests only ONE behavior
- [ ] Fixtures used for setup/teardown
- [ ] External dependencies are mocked
- [ ] Tests run quickly (< 100ms each)
- [ ] Assertions are clear and specific
- [ ] Edge cases are covered
- [ ] Error cases are tested
- [ ] No hardcoded test data (use fixtures)
- [ ] Uses parameterize for multiple similar tests
- [ ] Test docstring explains the scenario
"""
