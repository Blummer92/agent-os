# CKR PR-3: offline metadata staging

This is a standalone, standard-library Python review tool for synthetic metadata.
It is not imported by the lesson selector or wired into any workflow. It does not
read gold labels, fetch evidence, verify owner/custodian identity, construct
trusted observations, run evaluation arms, or grant activation.

- v2 checks distinct holdout incident families against the cohort minimum.
- It requires distinct claimed reviewer roles, owner-bound rubric/recipe digest
  fields, and a custodian attestation that the registry and reviewed revisions
  are at or before cutoff. Claims and hashes are not source authentication.
- Unknown intake keys, invalid JSON, and inconsistent counts fail closed.
- The shipped rubric is proposed, the intake is blank, and the protocol remains
  blocked. A synthetic pass is metadata-only.

From this directory, run:

```sh
python3 -m unittest -v
python3 -I audit_intake.py draft-intake.json --rubric draft-rubric.json
```

The first command runs 26 synthetic tests. The blank audit is expected to
print `BLOCKED` and exit 2. For replays use `--as-of` with an explicit UTC time
no later than the current clock. Use v2-shaped input; v1 intentionally blocks.

The governing record is #4054. This staging review does not authorize
collection, scoring, unsealing, a protocol freeze, or a production change.
