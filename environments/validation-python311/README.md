# Python 3.11 pre-baked validation environment

Issue: #1332

This directory defines the first repository-local pre-baked Agent OS validation
environment. It is an optimization artifact, not a dependency-policy source of
truth.

## Identity contract

`scripts.agent_os_prebaked_environment` derives `prebaked-environment:<sha256>`
from:

- repository identity;
- the existing canonical `RequiredEnvironmentSpec.required_environment_id`;
- exact runtime version;
- exact package-manager version;
- existing approved source identity;
- SHA-256 of this build definition; and
- sorted SHA-256 identities of stable dependency input files.

A manifest/constraint, runtime, package-manager, approved-source, build-definition,
or canonical environment change therefore changes the image identity. Admission
fails closed unless repository identity and current `RequiredEnvironmentSpec`
binding match.

## Stable versus task-local dependencies

The first image installs only stable external validation dependencies from
`requirements-dev.txt` and `08_Tooling/workflow-scheduler/requirements.txt`.
Repository-local editable packages remain task/runtime-local. This preserves the
existing dependency-readiness preparation path and avoids baking repository source
or issue-specific dependencies into the global image.

## Excluded data

The image contract has no fields for credentials, secrets, authorization state,
repository source code, issue state, checkpoints, leases, or production data.
The Dockerfile copies only the two stable dependency manifests.

## Activation boundary

This issue does **not** authorize building or pushing this image, creating or
changing Artifact Registry, changing `cloudbuild.yaml` or triggers, IAM changes,
production promotion, or Codespaces/GCE runtime replacement. Those remain a
separate activation decision coordinated with #806 or a successor.

Until activation is separately authorized, `cloudbuild.yaml` remains unchanged
and continues installing dependencies at runtime.

## Validation

Focused offline test:

```bash
python -m pytest -q tests/test_prebaked_environment_identity.py
```

Repository aggregate validation remains the authoritative exact-head gate. No
numeric performance improvement is claimed before the #520 before/after
measurement is performed after an authorized live rollout.

## Rollback

Before activation, rollback is deletion/revert of this directory and
`scripts/agent_os_prebaked_environment`. After any separately authorized rollout,
rollback must restore the prior runtime image/install path through that rollout's
own governed change.
