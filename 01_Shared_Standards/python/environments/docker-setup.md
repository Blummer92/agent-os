# Docker Test Environment

## Dockerfile

Create `Dockerfile` in project root:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

# Copy project
COPY . .

# Default command: run tests
CMD ["pytest", "-v"]
```

## Docker Compose (with Database)

Create `docker-compose.test.yml`:

```yaml
version: '3.8'

services:
  app:
    build: .
    volumes:
      - .:/app
    depends_on:
      - postgres
      - redis

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_PASSWORD: testpass
      POSTGRES_DB: testdb
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

## Build and Run

```bash
# Build Docker image
docker build -t myapp-tests .

# Run tests in container
docker run myapp-tests

# Run specific test
docker run myapp-tests pytest tests/unit -v

# With volume mounting for live development
docker run -v $(pwd):/app myapp-tests
```

## Docker Compose Commands

```bash
# Start services
docker-compose -f docker-compose.test.yml up -d

# Run tests
docker-compose -f docker-compose.test.yml run app pytest

# View logs
docker-compose -f docker-compose.test.yml logs -f app

# Stop services
docker-compose -f docker-compose.test.yml down
```

## Environment Variables

Create `.env.test`:

```env
DATABASE_URL=postgresql://postgres:testpass@postgres:5432/testdb
REDIS_URL=redis://redis:6379/0
DEBUG=true
```

Reference in tests via `os.getenv()` after `load_dotenv('.env.test')`.
