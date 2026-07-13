# Error and Exception Testing

## Test Error Propagation

```python
import pytest

@pytest.mark.integration
def test_error_propagates_through_layers(self, test_db):
    """Test error propagates from data layer to API."""
    # Invalid data that triggers database error
    with pytest.raises(IntegrityError):
        user = User(id=1, name='First')
        test_db.add(user)
        test_db.commit()
        
        # Try to add duplicate
        user2 = User(id=1, name='Duplicate')
        test_db.add(user2)
        test_db.commit()
```

## Test Error Handling at Each Layer

```python
def test_database_error_handling(self, test_db):
    """Test database errors are handled correctly."""
    try:
        # Cause database error
        test_db.query(User).delete()
        test_db.commit()
        test_db.execute('SELECT * FROM nonexistent_table')
    except OperationalError as e:
        assert 'no such table' in str(e).lower()

def test_validation_error_handling(self):
    """Test validation errors are caught."""
    with pytest.raises(ValidationError) as exc_info:
        validate_email('not-an-email')
    
    assert 'invalid email' in str(exc_info.value).lower()
```

## Test API Error Responses

```python
@pytest.mark.integration
def test_api_returns_error_on_validation_failure(client):
    """Test API returns proper error response."""
    response = client.post('/users', json={
        'name': '',  # Invalid: empty name
        'email': 'test@example.com'
    })
    
    assert response.status_code == 400
    data = response.get_json()
    assert data['error'] == 'Validation error'
    assert 'name' in data['details']
```

## Test Graceful Degradation

```python
def test_handle_missing_external_service(client, mocker):
    """Test graceful failure when external service is down."""
    # Mock service to raise error
    mocker.patch('email_service.send', side_effect=Exception('Service down'))
    
    response = client.post('/users', json={
        'name': 'John',
        'email': 'john@example.com'
    })
    
    # Should still succeed, but without email
    assert response.status_code == 201
    data = response.get_json()
    assert data['id'] is not None
    assert data.get('email_sent') is False
```

## Test Timeout Handling

Mock a slow operation (e.g. `time.sleep`) and assert a `TimeoutError` is
raised when the call exceeds a short configured `timeout`.

## Test Recovery from Errors

Simulate a function that fails N times then succeeds (raise on early
calls, return normally after), then assert your retry wrapper reaches
the success path within its configured `max_attempts`.
