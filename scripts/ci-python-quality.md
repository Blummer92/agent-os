# Python quality CI pilot

This report-only job scans tracked Visual Asset Intake Python source files.
Black checks formatting without rewriting files; mypy uses strict mode; Vulture
reports candidates at 90% confidence and above. No findings authorize deletion.
The job is not an input to the authoritative aggregate. It runs on main pushes
and on same-repository PRs authored and triggered by the repository owner. It
does not run on fork PRs. No changes to CodeQL, Ruff, the existing advisories,
JUnit verification, or the artifact collector are part of this patch.

Use Python 3.11 from a fresh venv and a committed, trusted checkout:

```bash
python3.11 -m venv /tmp/agent-os-quality-venv
/tmp/agent-os-quality-venv/bin/python -m pip install --only-binary=:all: -r scripts/ci-python-quality-requirements.txt
/tmp/agent-os-quality-venv/bin/python -m scripts.agent_os_ci_python_quality \
  --head "$(git rev-parse HEAD)" --run-id 1 --attempt 1 \
  --output "$(mktemp -d)"
```

Local run/attempt values are stand-ins, not hosted evidence. Hosted CI publishes
`python-quality-advisory-<attempt>` containing `python-quality.json`. Inspect
the same provider run, head and attempt; download by artifact ID and match the
provider digest before reading the report. This is manual GitHub Actions
readback; the independent collector does not consume this stream yet.
An analysis with findings remains report-only. A scanner error or missing
artifact fails the advisory job without turning the required aggregate red.
An interrupted job may have no artifact and is not a clean scan.

Before promoting the pilot, validate two hosted runs on the same candidate and
read back both archives. On separate never-merge controls, prove the three
scanners emit their own findings and that scanner crash, missing archive, and
mismatched head/attempt aren't accepted as clean. Compare Ruff against Flake8
and isort before adding duplicate checks. CodeQL scan scope and publishing,
Pyan3/jscpd reporting improvements, and scheduled mutation testing are follow-up
work, not outcomes of this patch. Roll back this job by reverting the patch;
no existing required job depends on it.
