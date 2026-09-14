"""Keep locally distributed packages resolvable against the developer loop.

Third-party version constraints are declared in two independent places:

* ``requirements-dev.txt`` -- what the developer loop and CI actually install;
* each locally distributed package's ``pyproject.toml`` -- what ``pip`` must
  satisfy when the packaging tests build a wheelhouse and install it with
  ``--no-index``.

Dependabot is configured for directory ``/`` only, so it updates the first file
and never the second. When the two drift apart the offline wheel installation
fails with an opaque pip resolution error far away from the edit that caused it
(this is exactly how ``mcp>=2.2.0`` broke ``agent-os-execution-service``, which
still declared ``mcp<2.2``).

These tests make the drift itself the failure, named at the constraint that
caused it, instead of leaving it to surface as a wheelhouse install error.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

_UPPER_OPERATORS = frozenset({"<", "<=", "==", "===", "~="})

ROOT = Path(__file__).resolve().parents[1]
DEV_REQUIREMENTS = ROOT / "requirements-dev.txt"

# Directories that hold example or vendored project metadata rather than a
# distribution this repository builds and installs.
EXCLUDED_PARTS = frozenset({".venv", "venv", "build", "dist", "06_Archive", "03_Templates"})


def _distribution_pyprojects() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in sorted(ROOT.rglob("pyproject.toml")):
        if EXCLUDED_PARTS & set(path.relative_to(ROOT).parts):
            continue
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        name = data.get("project", {}).get("name")
        if name:
            found[canonicalize_name(name)] = path
    return found


def _declared_requirements(path: Path) -> dict[str, Requirement]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    entries = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        entries.extend(extra)
    return {canonicalize_name(r.name): r for r in map(Requirement, entries)}


def _dev_requirements() -> dict[str, Requirement]:
    requirements: dict[str, Requirement] = {}
    for raw in DEV_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        # ``-e ./path`` entries are the local editable distributions; their
        # versions come from the pyproject files scanned separately below.
        if not line or line.startswith("-"):
            continue
        requirements[canonicalize_name(Requirement(line).name)] = Requirement(line)
    return requirements


def _probe_versions(*specifiers: SpecifierSet) -> set[Version]:
    """Every version worth testing for membership of a combined specifier.

    A specifier set built from ``>=``/``<``/``==`` style clauses changes truth
    value only at the versions it names, so the named bounds plus a point just
    above each of them are enough to decide satisfiability without a resolver
    or any network access.
    """
    probes: set[Version] = set()
    for specifier in specifiers:
        for clause in specifier:
            try:
                bound = Version(clause.version.rstrip(".*"))
            except InvalidVersion:
                continue
            probes.add(bound)
            probes.add(Version(f"{bound}.post1"))
    return probes


def _is_satisfiable(first: SpecifierSet, second: SpecifierSet) -> bool:
    """Whether any single version can satisfy both declarations at once."""
    combined = first & second
    if not any(clause.operator in _UPPER_OPERATORS for clause in combined):
        # Nothing caps the range, so a new enough release always satisfies it.
        return True
    return any(
        combined.contains(candidate, prereleases=True)
        for candidate in _probe_versions(first, second)
    )


def test_local_distributions_stay_resolvable_against_the_developer_loop() -> None:
    """A package constraint and the developer loop pin must share a version.

    A package asking for a *newer* floor than requirements-dev.txt is fine --
    pip installs the newest release satisfying both. The failure is an empty
    intersection, which is what an unnoticed upper bound produces.
    """
    dev = _dev_requirements()
    violations: list[str] = []

    for dist_name, path in _distribution_pyprojects().items():
        for req_name, requirement in _declared_requirements(path).items():
            pinned = dev.get(req_name)
            if pinned is None:
                continue
            if not _is_satisfiable(pinned.specifier, requirement.specifier):
                violations.append(
                    f"{path.relative_to(ROOT)} declares {req_name}"
                    f"{requirement.specifier}, which shares no version with "
                    f"requirements-dev.txt ({req_name}{pinned.specifier}). Update "
                    f"{dist_name}'s constraint in the same change."
                )

    assert not violations, "Dependency constraint drift:\n- " + "\n- ".join(violations)


def test_local_distribution_versions_satisfy_sibling_constraints() -> None:
    """Packages in this repository are installed from the checkout, not an index."""
    pyprojects = _distribution_pyprojects()
    versions = {
        name: Version(tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"])
        for name, path in pyprojects.items()
        if "version" in tomllib.loads(path.read_text(encoding="utf-8")).get("project", {})
    }
    violations: list[str] = []

    for dist_name, path in pyprojects.items():
        for req_name, requirement in _declared_requirements(path).items():
            local = versions.get(req_name)
            if local is None:
                continue
            if not requirement.specifier.contains(local, prereleases=True):
                violations.append(
                    f"{path.relative_to(ROOT)} declares {req_name}"
                    f"{requirement.specifier}, but this repository distributes "
                    f"{req_name} {local}"
                )

    assert not violations, "Local distribution drift:\n- " + "\n- ".join(violations)


def test_dependabot_directory_scope_is_the_reason_this_guard_exists() -> None:
    """Pin the assumption this guard rests on so a config change revisits it.

    If Dependabot is ever configured to watch the nested package directories
    directly, the drift it causes changes shape and these tests should be
    re-derived rather than silently kept.
    """
    config = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    pip_directories = [
        line.split(":", 1)[1].strip().strip('"')
        for line in config.splitlines()
        if line.strip().startswith("directory:")
    ]
    assert pip_directories, "dependabot.yml declares no update directories"
    assert set(pip_directories) == {"/"}, (
        "Dependabot now watches directories other than the repository root: "
        f"{sorted(set(pip_directories))}. Re-derive the constraint-drift guard."
    )


def test_guard_rejects_the_conflict_that_caused_this_failure() -> None:
    """The exact #2293 shape: dev loop moved to mcp 2.2, the package kept <2.2."""
    assert not _is_satisfiable(SpecifierSet(">=2.2.0,<2.3"), SpecifierSet(">=2.1.1,<2.2"))
    assert _is_satisfiable(SpecifierSet(">=2.2.0,<2.3"), SpecifierSet(">=2.2.0,<2.3"))


def test_guard_rejects_the_next_major_bump_of_each_capped_dependency() -> None:
    """The same drift is latent wherever a package caps a shared dependency."""
    # PyYAML is capped at <7 by workflow-scheduler and reusable-capability-registry.
    assert not _is_satisfiable(SpecifierSet(">=7.0"), SpecifierSet(">=6.0,<7"))
    # PyGithub is capped at <3 by agent-os-execution-service.
    assert not _is_satisfiable(SpecifierSet("==3.0.0"), SpecifierSet(">=2.9.1,<3"))


def test_guard_accepts_the_non_conflicts_it_must_not_flag() -> None:
    """Boundary cases that look like drift but resolve perfectly well."""
    # A package may require a newer floor than the developer loop's minimum.
    assert _is_satisfiable(SpecifierSet(">=7.0.0"), SpecifierSet(">=8"))
    # An exact dev pin inside the package's supported range.
    assert _is_satisfiable(SpecifierSet("==2.10.0"), SpecifierSet(">=2.9.1,<3"))
    # A dev floor strictly below the package cap.
    assert _is_satisfiable(SpecifierSet(">=6.0.3"), SpecifierSet(">=6.0,<7"))
    # An unconstrained dev requirement never conflicts.
    assert _is_satisfiable(SpecifierSet(""), SpecifierSet(">=6.0,<7"))
    # Exactly-at-the-cap is excluded; one release below it is not.
    assert not _is_satisfiable(SpecifierSet("==7.0"), SpecifierSet("<7"))
    assert _is_satisfiable(SpecifierSet("==6.9"), SpecifierSet("<7"))
