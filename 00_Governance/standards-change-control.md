# Standards Change Control

- Every standards change gets a `CHANGELOG` entry.
- Every module has a version.
- Repository releases and module versions are versioned independently.
- Repository releases may include packaging, registry, routing, documentation, or infrastructure updates without changing module versions.
- A module version changes only when that module's standards or contract changes.
- Agent overlays reference module versions.
- Breaking changes require human approval.
- Superseded documents move to archive.
- Bugs that change policy update the relevant standard.
- Repeated agent failures create governance review items.
- New agents inherit existing modules before new instructions are created.
