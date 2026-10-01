"""ERG2 offline External Repository Governance validator (#581).

Single public entry path: ``validator.validate_erg_document`` (and the
``cli`` module). Consumes the #580 ERG contract — the shared standard
``01_Shared_Standards/github/external-repository-governance.md`` and the
Draft 2020-12 schemas in ``03_Templates/`` — rather than redefining it.

Bounded scope: deterministic, offline, credential-free, no-network
validation of consumer profiles and the central registry. Consumer
repository code is untrusted data and is never executed. Reports are
evidence only and authorize nothing.
"""

from .validator import validate_erg_document

__all__ = ["validate_erg_document"]
