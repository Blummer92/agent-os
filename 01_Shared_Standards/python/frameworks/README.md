# Testing Frameworks

This directory contains configuration and setup for Python testing frameworks.

## Quick Links

- **[pytest-setup.md](pytest-setup.md)** - pytest framework configuration
- **[mocking-setup.md](mocking-setup.md)** - Mocking strategies and tools
- **[fixtures-patterns.md](fixtures-patterns.md)** - pytest fixture patterns
- **[async-testing.md](async-testing.md)** - Async/await test patterns

## Overview

All Python projects use:
- **Framework:** pytest (7.0+)
- **Fixtures:** pytest fixtures for setup/teardown
- **Mocking:** unittest.mock or pytest-mock
- **Async:** pytest-asyncio for async code

## Installation

```bash
pip install pytest>=7.0.0 pytest-cov>=4.0.0 pytest-mock>=3.10.0 pytest-asyncio>=0.21.0
```
