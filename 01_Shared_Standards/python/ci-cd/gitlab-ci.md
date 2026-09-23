# GitLab CI

Create `.gitlab-ci.yml`:

```yaml
stages:
  - test
  - coverage

test:
  stage: test
  image: python:3.11
  services:
    - postgres:15-alpine
    - redis:7-alpine
  before_script:
    - pip install -r requirements.txt
    - pip install -r requirements-dev.txt
  script:
    - pytest --cov=src --cov-report=term-missing --cov-report=html
  coverage: '/(?i)total.*? (100(?:\.0+)?\%|[1-9]?\d(?:\.\d+)?\%)$/'
  artifacts:
    when: always
    paths:
      - htmlcov/
    reports:
      junit: junit.xml
  variables:
    POSTGRES_DB: test_db
    POSTGRES_USER: test_user
    POSTGRES_PASSWORD: test_password
```

See `github-actions.md` for the GitHub Actions equivalent.
