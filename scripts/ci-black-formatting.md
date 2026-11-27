# Required Black formatting check

Black runs in check mode on the tracked Python source of Visual Asset Intake,
using its checked-in config and the exact pin in `requirements-dev.txt`.
Install the development requirements, then run `bash scripts/ci-local.sh` from
a clean checkout for the same wrapper used by the existing aggregate job.

The wrapper saves `black-format-receipt.json` in the existing JUnit artifact
directory, without creating a synthetic JUnit test. A formatting difference
fails the same aggregate job even when tests and coverage passed. A missing
receipt, version mismatch, wrong checkout, scanner crash, timeout, incomplete
scan, or oversize output also prevents success. Repo tests and coverage retain
their separate results. If validation already failed, Black does not run and
cannot cause a green aggregate.

This is a one-tool change. It adds no job, status publisher, required-check
name, branch-protection rule, claims of deletion authority, or change to
the separate advisory scanners. Roll back the implementation commit if this
bounded gate needs to be removed.
