# Test Environment Setup

## Quick Links

- **[local-development.md](local-development.md)** - Local machine setup
- **[docker-setup.md](docker-setup.md)** - Docker container setup
- **[ci-cd-setup.md](ci-cd-setup.md)** - GitHub Actions/CI setup
- **[databases.md](databases.md)** - Database configuration
- **[pre-commit-hooks.md](pre-commit-hooks.md)** - Pre-commit hook config
- **[setup-checklist.md](setup-checklist.md)** - Full environment checklist

## Overview

Test environments need to be:
- **Repeatable:** Same setup every time
- **Isolated:** Tests don't affect each other
- **Fast:** Complete in reasonable time
- **Documented:** Easy to set up

## Environment Types

| Environment | Purpose | Speed | Cost |
|---|---|---|---|
| Local Dev | Development & testing | Fast | Free |
| Docker | Consistent across machines | Medium | Minimal |
| CI/CD | Automated testing on commits | Slow | Minimal |

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements-dev.txt

# 2. Run tests locally
pytest tests/ -v

# 3. Check coverage
pytest --cov --cov-report=html

# 4. Open coverage report
open htmlcov/index.html
```
