# Branch coverage pilot: local replay

Run from a clean checkout with the same validation dependencies as Actions:

```bash
bash scripts/ci-local.sh
```

Use this wrapper to reproduce the pilot locally; `validate-all.sh` alone is
the underlying suite runner, not the coverage gate. The wrapper ignores
inherited JUnit and coverage output paths, prints its private output locations
and retains evidence. Local receipts are explicitly labeled `origin: local`;
their numeric run identifier is not a GitHub Actions run.

Actions calls the same wrapper with `--hosted`; it keeps the existing terminal
publisher. Both paths execute the aggregate once, require exact source paths
and valid reports, and retain the original validation failure. Only pilot
manifests contain the extra command and hash fields. Changing coverage scope
uses `scripts/ci-coverage-suites.tsv`. The 80% floor is on the combined line
and branch opportunities, not a repo-wide coverage claim.

The checkout cleanliness checks and post-suite fingerprints detect workspace
drift and changes after the capture point. They are not a security sandbox:
pytest and coverage instrumentation run as the same operating-system user.
Do not treat these receipts as trustworthy attestations against hostile test
code. An independently protected evidence producer is needed for that claim.

Treat the floor as a pilot until real pytest-cov artifacts and hosted healthy,
below-floor, and missing-report controls have been reviewed.
