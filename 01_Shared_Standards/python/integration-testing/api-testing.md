# API Testing

## Testing HTTP Endpoints

### With Flask Test Client

```python
import pytest
from flask import create_app

@pytest.fixture
def app():
    """Create test Flask app."""
    app = create_app('testing')
    return app

@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()

@pytest.mark.integration
def test_get_user_endpoint(client, test_db):
    """Test GET /users/<id> endpoint."""
    # SETUP - Create user in database
    user = User(name='John', email='john@example.com')
    test_db.add(user)
    test_db.commit()
    
    # ACT - Call endpoint
    response = client.get(f'/users/{user.id}')
    
    # ASSERT - Verify response
    assert response.status_code == 200
    data = response.get_json()
    assert data['name'] == 'John'
    assert data['email'] == 'john@example.com'
```

### With FastAPI TestClient

```python
from fastapi.testclient import TestClient
from main import app

@pytest.fixture
def client():
    return TestClient(app)

@pytest.mark.integration
def test_create_user_endpoint(client):
    """Test POST /users endpoint."""
    payload = {'name': 'Jane', 'email': 'jane@example.com'}
    
    response = client.post('/users', json=payload)
    
    assert response.status_code == 201
    data = response.json()
    assert data['id'] is not None
```

## Test Response Status Codes

```python
def test_api_status_codes(client):
    """Test various HTTP status codes."""
    # 200 OK
    response = client.get('/users')
    assert response.status_code == 200
    
    # 404 Not Found
    response = client.get('/users/nonexistent')
    assert response.status_code == 404
    
    # 400 Bad Request
    response = client.post('/users', json={})  # Missing required fields
    assert response.status_code == 400
```

## Test Response Content

```python
def test_json_response_structure(client):
    """Test response JSON structure."""
    response = client.get('/users/1')
    data = response.get_json()
    
    # Verify structure
    assert 'id' in data
    assert 'name' in data
    assert 'email' in data
    assert isinstance(data['id'], int)
```

## Mock External APIs

Use `mocker.patch(...)` on the external call before hitting the endpoint,
then assert the mock was called -- see `../frameworks/mocking-setup.md`.
