# Code Coverage Standards

## Quick Links

- **[requirements.md](requirements.md)** - Coverage target percentages
- **[measurement.md](measurement.md)** - How to measure coverage
- **[reporting.md](reporting.md)** - Coverage reports and CI/CD

## Overview

Code coverage measures what percentage of code is executed by tests.

## Targets

- **Overall:** 80% minimum
- **Critical modules:** 90% (validators, safety-critical)
- **Data models:** 85%

## Key Principle

Coverage is necessary but not sufficient. High coverage ≠ good tests.

Focus on:
- Testing behavior, not coverage percentage
- Testing error paths, not just happy paths
- Testing edge cases
- Meaningful assertions
