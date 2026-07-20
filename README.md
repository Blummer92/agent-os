# Agent OS

Agent OS is a modular knowledge base for engineering-agent standards, governance rules, reusable templates, registry maps, examples, and archive notes.

## Start Here

- `AGENTS.md` — execution entry point and global routing.
- `00_Governance/documentation-dependency-map.md` — documentation index and reading paths.

## Main Folders

- `00_Governance/`
- `01_Shared_Standards/`
- `02_Agent_Overlays/`
- `03_Templates/`
- `04_Registry/`
- `05_Examples/`
- `06_Archive/`
- `07_Agent_Tests/`

## Validation

Run the aggregate local validation command from the repository root:

```bash
./scripts/validate-all.sh
```

It runs `07_Agent_Tests/validate-repo-structure.sh` and discovered Python pytest suites. Exit code `0` means pass, `1` means validation failure, and `2` means the runner could not start.

### Cloud Build Validation

Cloud Build is an optional Linux execution surface for Agent OS validation. GitHub remains the canonical source of truth and pull requests remain the change-control surface. A successful build is evidence only; it does not authorize merge, readiness, labels, branch-protection, or external writes.

The repository-owned `cloudbuild.yaml` uses Python 3.11, installs declared test dependencies, and runs:

```bash
bash 07_Agent_Tests/validate-repo-structure.sh
./scripts/validate-all.sh
```

The configuration uses `CLOUD_LOGGING_ONLY`; review output in Google Cloud Build History. Record the build ID, exact tested SHA, failed step, overall result, and exit code. Never reuse evidence from one SHA for another branch head or synthetic pull-request merge.

A project operator may submit `cloudbuild.yaml` manually or use an approved project-side PR trigger such as `/gcbrun`. Trigger configuration, service-account identity, IAM bindings, and timeout settings live in the Google Cloud project, not this repository. Verify repository, ref, and SHA in the build details. Use only the project-approved service account and least-privilege permissions needed to fetch source and write logs; never document credentials or secrets here.

Classify failures before changing code:

- configuration: invalid YAML, builder image, or build options;
- dependency: installation or dependency resolution;
- validation: structural or pytest failure;
- repository/ref: wrong repository, branch, or SHA;
- permissions: source or logging access failure;
- timeout/platform: project timeout or Linux-specific behavior.

Cloud Build can be bypassed as a supplemental lane by not submitting it or by disabling the project-side trigger through the authorized Google Cloud owner. Do not delete `cloudbuild.yaml`, weaken validation, or change branch protection as a workaround. If unavailable, run the same commands in another approved Linux environment and record exact-SHA evidence.

Ownership: GitHub Service Agent owns repository configuration and documentation; QA / Test Agent owns validation evidence; Integration Manager supports cross-system routing; the authorized Google Cloud owner controls project triggers, service accounts, IAM, logs, and timeouts.

### GitHub Actions Validation

The `Agent OS Validation Gate` is the repository-visible compatibility and validation path. Cloud Build remains supplemental unless a separately approved governance or repository-settings decision makes a named status required.

The workflow does not commit, push, open pull requests, write to Google Drive, modify source-of-truth records, mutate labels, or change PR readiness. Issue-to-PR automation is not part of this validation workflow.

## Safe Change Workflow

Agent OS changes use:

```text
branch -> pull request -> validation -> merge -> main
```

1. Create a non-main branch.
2. Commit only related files.
3. Open a pull request into `main`.
4. Run and review validation for the exact SHA.
5. Merge only after evidence and review are complete.
