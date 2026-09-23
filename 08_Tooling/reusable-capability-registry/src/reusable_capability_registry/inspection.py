"""Bounded, offline, static evidence inspection for RC4 validation (#494 / #254).

Filesystem and Python ``ast`` inspection only. Never imports or executes an
inspected module; never scans the whole repository (`rglob("*.py")` is
prohibited); never accesses the network, environment, or credentials. Every
function returns an :class:`EvidenceOutcome`; ``code is None`` means the checked
property is satisfied (no finding), and the orchestrator counts it as evidence.
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .models import EvidenceConfidence, ValidationEvidence, ValidationSeverity

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Path classification (repository-relative POSIX).
_TEST_DIR = re.compile(r"(^|/)tests?(/|$)")
_TEST_FILE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$")
_EXCLUDED_DIR = re.compile(
    r"(^|/)(fixtures|snapshots|__snapshots__|golden|testdata|generated|dist|build|vendor|node_modules)(/|$)"
)
_INFORMATIONAL_DIR = re.compile(r"(^|/)(examples?|samples?|demos?|benchmarks?|migrations?)(/|$)")


@dataclass(frozen=True, slots=True)
class EvidenceOutcome:
    """Result of one inspection: ``code is None`` => verified (no finding)."""

    code: str | None
    confidence: EvidenceConfidence
    severity: ValidationSeverity
    evidence: tuple[ValidationEvidence, ...]
    manual_review_reason: str | None = None
    source_type: str | None = None  # counter label when verified


def _ok(source_type: str, evidence: tuple[ValidationEvidence, ...]) -> EvidenceOutcome:
    return EvidenceOutcome(None, EvidenceConfidence.VERIFIED, ValidationSeverity.PASS, evidence, None, source_type)


def _safe_evidence_path(value: str) -> str | None:
    """A registered value only becomes an evidence ``path`` when it is a valid POSIX relpath."""
    trimmed = value.strip()
    if not trimmed or trimmed.startswith("/") or "\\" in trimmed or re.match(r"^[A-Za-z]:", trimmed):
        return None
    return trimmed


# --- repository root & path lexical/filesystem inspection ------------------


def resolve_repository_root(repository_root: str | os.PathLike[str]) -> Path:
    root = Path(repository_root).resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"repository root is not a directory: {root}")
    return root


def _lexical_path_error(registered_path: str) -> str | None:
    """Return a ``path.*`` code for a lexically invalid registered path, else None."""
    if not registered_path or not registered_path.strip():
        return "path.invalid-format"
    if "\\" in registered_path:
        return "path.invalid-format"
    if registered_path.startswith("/"):
        return "path.invalid-format"
    if re.match(r"^[A-Za-z]:", registered_path):  # drive-qualified
        return "path.invalid-format"
    parts = registered_path.split("/")
    if any(part == ".." for part in parts):
        return "path.traversal"
    return None


def _normalize_relparts(registered_path: str) -> tuple[str, ...]:
    return tuple(part for part in registered_path.split("/") if part not in ("", "."))


def _exact_case_target(root: Path, parts: tuple[str, ...]) -> Path | None:
    """Walk components verifying exact on-disk spelling; return the path or None."""
    current = root
    for part in parts:
        try:
            entries = os.listdir(current)
        except OSError:
            return None
        if part not in entries:
            return None
        current = current / part
    return current


def inspect_canonical_path(root: Path, registered_path: str) -> EvidenceOutcome:
    registered = registered_path.strip()
    evidence = (ValidationEvidence(_safe_evidence_path(registered), None, None, "registered-path", f"registered path {registered!r}"),)

    lexical = _lexical_path_error(registered_path)
    if lexical is not None:
        conf = EvidenceConfidence.CONTRADICTED
        return EvidenceOutcome(lexical, conf, ValidationSeverity.FAIL, evidence)

    parts = _normalize_relparts(registered)
    candidate = root.joinpath(*parts)

    if candidate.is_symlink():
        target = candidate.resolve()
        if target == root or root in target.parents:
            return EvidenceOutcome(
                "path.symlink-inside",
                EvidenceConfidence.MANUAL_REVIEW,
                ValidationSeverity.MANUAL_REVIEW,
                evidence,
                "registered path is an in-repository symlink; resolve manually",
            )
        return EvidenceOutcome("path.symlink-outside", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, evidence)

    if not os.path.lexists(candidate):
        return EvidenceOutcome("path.missing", EvidenceConfidence.UNVERIFIED, ValidationSeverity.FAIL, evidence)

    # exists; enforce exact-case spelling and in-repository containment.
    exact = _exact_case_target(root, parts)
    if exact is None:
        return EvidenceOutcome("path.case-mismatch", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, evidence)
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        return EvidenceOutcome("path.outside-repository", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, evidence)

    canonical_spelling = "/".join(parts)
    if canonical_spelling != registered:
        return EvidenceOutcome(
            "path.noncanonical",
            EvidenceConfidence.PROBABLE,
            ValidationSeverity.WARN,
            evidence,
            None,
            "resolved-path",
        )
    return _ok("resolved-path", evidence)


# --- public interface parsing & module mapping -----------------------------


def parse_public_interface(interface: str) -> tuple[str, str] | None:
    """Return (module, symbol) or None when malformed."""
    text = interface.strip()
    if text.count(":") != 1:
        return None
    module, symbol = text.split(":")
    if not module or not symbol:
        return None
    if any(not _IDENTIFIER.match(part) for part in module.split(".")):
        return None
    return module, symbol


def map_module_to_canonical_paths(module: str, canonical_paths: tuple[str, ...]) -> list[str]:
    suffixes = (module.replace(".", "/") + ".py", module.replace(".", "/") + "/__init__.py")
    matches = []
    for path in canonical_paths:
        normalized = "/".join(_normalize_relparts(path.strip()))
        if normalized == suffixes[0] or normalized == suffixes[1] or any(
            normalized.endswith("/" + suffix) for suffix in suffixes
        ):
            matches.append(path.strip())
    return matches


def _read_source(root: Path, rel_path: str) -> str | None:
    try:
        return (root / rel_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


class _TopLevelBindings:
    """Static top-level binding facts for one module (no execution)."""

    def __init__(self, tree: ast.Module) -> None:
        self.unconditional: dict[str, str] = {}     # name -> kind
        self.conditional: set[str] = set()
        self.deleted: set[str] = set()
        self.aliases: dict[str, str] = {}           # name -> source name (simple alias)
        self.relative_import_source: dict[str, str] = {}  # name -> relative module
        self.all_list: set[str] | None = None
        self.has_getattr = False
        self.has_star_import = False
        for node in tree.body:
            self._visit_top(node)

    def _visit_top(self, node: ast.stmt) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.unconditional[node.name] = "definition"
            if node.name == "__getattr__":
                self.has_getattr = True
        elif isinstance(node, ast.ClassDef):
            self.unconditional[node.name] = "definition"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                self.unconditional[alias.asname or alias.name.split(".")[0]] = "import"
        elif isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                self.has_star_import = True
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                self.unconditional[local] = "import"
                if node.level and node.module:
                    self.relative_import_source[local] = node.module
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.id == "__all__":
                        self.all_list = _static_str_list(node.value)
                    else:
                        self.unconditional[target.id] = "assignment"
                        if isinstance(node.value, ast.Name):
                            self.aliases[target.id] = node.value.id
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.deleted.add(target.id)
        elif isinstance(node, (ast.If, ast.Try, ast.While, ast.For, ast.With)):
            for name in _conditionally_bound_names(node):
                self.conditional.add(name)


def _static_str_list(node: ast.AST) -> set[str] | None:
    if isinstance(node, (ast.List, ast.Tuple)):
        values = set()
        for element in node.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                values.add(element.value)
        return values
    return None


def _conditionally_bound_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                if alias.name == "*":
                    continue
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(child.name)
        elif isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _resolve_alias(name: str, bindings: _TopLevelBindings, seen: frozenset[str] = frozenset()) -> bool:
    """True when ``name`` resolves (acyclically) to a supported unconditional binding."""
    if name in seen:
        return False
    kind = bindings.unconditional.get(name)
    if kind in ("definition", "import"):
        return True
    if kind == "assignment" and name in bindings.aliases:
        return _resolve_alias(bindings.aliases[name], bindings, seen | {name})
    return False


def inspect_python_interface(root: Path, interface: str, canonical_paths: tuple[str, ...]) -> EvidenceOutcome:
    parsed = parse_public_interface(interface)
    base = (ValidationEvidence(None, None, interface.strip() or None, "public-interface", f"interface {interface.strip()!r}"),)
    if parsed is None:
        return EvidenceOutcome("interface.malformed", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, base)
    module, symbol = parsed
    if "." in symbol:
        return EvidenceOutcome(
            "interface.nested-symbol", EvidenceConfidence.MANUAL_REVIEW, ValidationSeverity.MANUAL_REVIEW, base,
            "dotted symbols require attribute resolution outside the bounded contract",
        )
    if not _IDENTIFIER.match(symbol):
        return EvidenceOutcome("interface.malformed", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, base)

    matches = map_module_to_canonical_paths(module, canonical_paths)
    if not matches:
        module_as_path = module.replace(".", "/")
        for path in canonical_paths:
            norm = "/".join(_normalize_relparts(path.strip()))
            last = norm.rsplit("/", 1)[-1]
            stem = norm.rsplit(".", 1)[0] if "." in last else norm
            if not norm.endswith(".py") and stem.endswith(module_as_path):
                return EvidenceOutcome(
                    "interface.non-python", EvidenceConfidence.MANUAL_REVIEW, ValidationSeverity.MANUAL_REVIEW, base,
                    "registered interface maps to a non-Python canonical path",
                )
        return EvidenceOutcome("interface.module-missing", EvidenceConfidence.UNVERIFIED, ValidationSeverity.FAIL, base)
    if len(matches) > 1:
        return EvidenceOutcome(
            "interface.module-ambiguous", EvidenceConfidence.MANUAL_REVIEW, ValidationSeverity.MANUAL_REVIEW, base,
            "more than one registered canonical path maps to this module",
        )
    rel_path = "/".join(_normalize_relparts(matches[0]))
    if not rel_path.endswith(".py"):
        return EvidenceOutcome(
            "interface.non-python", EvidenceConfidence.MANUAL_REVIEW, ValidationSeverity.MANUAL_REVIEW, base,
            "registered interface maps to a non-Python canonical path",
        )
    source = _read_source(root, rel_path)
    evidence = (ValidationEvidence(rel_path, None, symbol, "python-ast", f"symbol {symbol!r} in {rel_path}"),)
    if source is None:
        return EvidenceOutcome("interface.module-missing", EvidenceConfidence.UNVERIFIED, ValidationSeverity.FAIL, evidence)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return EvidenceOutcome("interface.syntax-error", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, evidence)

    bindings = _TopLevelBindings(tree)
    if symbol in bindings.unconditional and symbol not in bindings.deleted:
        # package __init__.py re-export: relative source must be a registered canonical path.
        if rel_path.endswith("/__init__.py") and symbol in bindings.relative_import_source:
            package_dir = rel_path[: -len("/__init__.py")]
            source_module = bindings.relative_import_source[symbol]
            source_rel = f"{package_dir}/{source_module.replace('.', '/')}.py"
            source_init = f"{package_dir}/{source_module.replace('.', '/')}/__init__.py"
            registered = {"/".join(_normalize_relparts(path.strip())) for path in canonical_paths}
            if source_rel not in registered and source_init not in registered:
                return EvidenceOutcome(
                    "interface.local-source-unregistered", EvidenceConfidence.MANUAL_REVIEW,
                    ValidationSeverity.MANUAL_REVIEW, evidence,
                    "re-export source module is not a registered canonical path",
                )
        if bindings.unconditional[symbol] == "assignment" and not _resolve_alias(symbol, bindings):
            return EvidenceOutcome(
                "interface.dynamic-export", EvidenceConfidence.MANUAL_REVIEW, ValidationSeverity.MANUAL_REVIEW, evidence,
                "assignment binding does not resolve to a supported static source",
            )
        return _ok("ast-binding", evidence)
    if symbol in bindings.deleted:
        return EvidenceOutcome(
            "interface.conflicting-binding", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, evidence,
        )
    if symbol in bindings.conditional:
        return EvidenceOutcome(
            "interface.conditional-binding", EvidenceConfidence.MANUAL_REVIEW, ValidationSeverity.MANUAL_REVIEW, evidence,
            "symbol is only bound in a conditional context",
        )
    if bindings.has_star_import or bindings.has_getattr:
        return EvidenceOutcome(
            "interface.dynamic-export", EvidenceConfidence.MANUAL_REVIEW, ValidationSeverity.MANUAL_REVIEW, evidence,
            "symbol may originate from a star import or dynamic __getattr__",
        )
    return EvidenceOutcome("interface.symbol-missing", EvidenceConfidence.UNVERIFIED, ValidationSeverity.FAIL, evidence)


# --- path classification ---------------------------------------------------


def classify_repository_path(rel_path: str) -> str:
    normalized = "/".join(_normalize_relparts(rel_path.strip()))
    if _TEST_DIR.search(normalized) or _TEST_FILE.search(normalized):
        return "test"
    if _EXCLUDED_DIR.search(normalized) or not normalized.endswith(".py"):
        return "excluded"
    if _INFORMATIONAL_DIR.search(normalized):
        return "informational"
    return "operational"


# --- consumer & test source analysis ---------------------------------------


class _ReferenceFacts:
    """Static import/reference facts for a consumer or test file."""

    def __init__(self, tree: ast.Module, modules: set[str], symbols: set[str]) -> None:
        self.modules = modules
        self.symbols = symbols
        self.registered_symbol_import = False   # imported a registered symbol (executable, non-typing)
        self.registered_module_import: set[str] = set()  # local names bound to registered modules
        self.symbol_local_names: set[str] = set()        # local names bound to registered symbols
        self.typing_only = False
        self.conditional = False
        self.dynamic = False
        self.has_assertion = False
        self.exercises_symbol = False
        self.skip_decorated = False
        self.local_helper_imports: set[str] = set()      # relative-imported local names
        self._collect(tree)

    def _collect(self, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_dynamic_import(node):
                self.dynamic = True
            if isinstance(node, ast.Assert):
                self.has_assertion = True
            if isinstance(node, ast.With) and _has_raises(node):
                self.has_assertion = True
        self._imports_and_refs(tree)

    def _imports_and_refs(self, tree: ast.Module) -> None:
        typing_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _has_skip_decorator(node):
                    self.skip_decorated = True
            if isinstance(node, ast.ImportFrom):
                # A registered symbol is referenced when its exact name is imported
                # from the registered module, a submodule of it, or a relative module
                # within the capability's own package.
                module_match = node.module is not None and _module_matches(node.module, self.modules)
                relative = bool(node.level)
                context = _import_context(tree, node)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    if alias.name in self.symbols and (module_match or relative):
                        if context == "typing":
                            self.typing_only = True
                            typing_names.add(alias.asname or alias.name)
                        elif context == "conditional":
                            self.conditional = True
                        else:
                            self.registered_symbol_import = True
                            self.symbol_local_names.add(alias.asname or alias.name)
                    elif relative:
                        self.local_helper_imports.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _module_matches(alias.name, self.modules):
                        self.registered_module_import.add(alias.asname or alias.name.split(".")[0])
        # references (Load) to imported registered symbols / qualified module access.
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id in self.symbol_local_names and node.id not in typing_names:
                    self.exercises_symbol = True
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                if isinstance(node.value, ast.Name) and node.value.id in self.registered_module_import:
                    self.exercises_symbol = True
                    self.registered_symbol_import = True


def _module_matches(module: str, registered: set[str]) -> bool:
    return any(module == reg or module.startswith(reg + ".") for reg in registered)


def _is_dynamic_import(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name) and func.id == "__import__":
        return True
    if isinstance(func, ast.Attribute) and func.attr in ("import_module", "load_module"):
        return True
    return False


def _has_raises(node: ast.With) -> bool:
    for item in node.items:
        call = item.context_expr
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "raises":
            return True
    return False


def _has_skip_decorator(node: ast.AST) -> bool:
    for decorator in getattr(node, "decorator_list", []):
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr in ("skip", "skipif", "xfail"):
            return True
    return False


def _import_context(tree: ast.Module, target: ast.ImportFrom) -> str:
    """Classify an import as 'typing', 'conditional', or 'module' by its enclosing block."""
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            if target in ast.walk(node):
                if _is_type_checking_test(node.test):
                    return "typing"
                return "conditional"
        if isinstance(node, ast.Try) and target in ast.walk(node):
            return "conditional"
    return "module"


def _is_type_checking_test(test: ast.AST) -> bool:
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
        return True
    return False


def _registered_names(interfaces: tuple[str, ...]) -> tuple[set[str], set[str]]:
    modules: set[str] = set()
    symbols: set[str] = set()
    for interface in interfaces:
        parsed = parse_public_interface(interface)
        if parsed is not None:
            module, symbol = parsed
            modules.add(module)
            if "." not in symbol:
                symbols.add(symbol)
    return modules, symbols


def _weak_text_present(source: str, symbols: set[str]) -> bool:
    return any(symbol in source for symbol in symbols)


def inspect_consumer(
    root: Path, consumer_path: str, interfaces: tuple[str, ...], canonical_paths: tuple[str, ...]
) -> EvidenceOutcome:
    rel = consumer_path.strip()
    evidence = (ValidationEvidence(_safe_evidence_path(rel), None, None, "consumer-path", f"listed consumer {rel!r}"),)
    lexical = _lexical_path_error(consumer_path)
    if lexical is not None:
        return EvidenceOutcome(lexical, EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, evidence)
    if not os.path.lexists(root.joinpath(*_normalize_relparts(rel))):
        return EvidenceOutcome("path.missing", EvidenceConfidence.UNVERIFIED, ValidationSeverity.FAIL, evidence)

    category = classify_repository_path(rel)
    if category == "test":
        return EvidenceOutcome(
            "consumer.path-not-operational", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, evidence,
            None, "test-only-consumer-evidence",
        )
    if category == "excluded":
        return EvidenceOutcome("consumer.path-not-operational", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, evidence)
    if category == "informational":
        return EvidenceOutcome(
            "consumer.path-not-operational", EvidenceConfidence.PROBABLE, ValidationSeverity.WARN, evidence,
            None, "informational-consumer-evidence",
        )

    source = _read_source(root, rel)
    if source is None:
        return EvidenceOutcome("path.missing", EvidenceConfidence.UNVERIFIED, ValidationSeverity.FAIL, evidence)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return EvidenceOutcome("consumer.syntax-error", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, evidence)

    modules, symbols = _registered_names(interfaces)
    facts = _ReferenceFacts(tree, modules, symbols)
    ok_evidence = (ValidationEvidence(rel, None, None, "operational-consumer-evidence", "operational-consumer evidence located"),)

    if facts.exercises_symbol and (facts.registered_symbol_import or facts.registered_module_import):
        return _ok("operational-consumer-evidence", ok_evidence)
    if facts.dynamic:
        return EvidenceOutcome(
            "consumer.dynamic-usage", EvidenceConfidence.MANUAL_REVIEW, ValidationSeverity.MANUAL_REVIEW, evidence,
            "registered interface may be reached only through dynamic import",
        )
    if facts.conditional:
        return EvidenceOutcome(
            "consumer.conditional-usage", EvidenceConfidence.MANUAL_REVIEW, ValidationSeverity.MANUAL_REVIEW, evidence,
            "registered interface is imported only under a runtime conditional",
        )
    if facts.registered_module_import and not facts.exercises_symbol:
        return EvidenceOutcome("consumer.package-import-only", EvidenceConfidence.PROBABLE, ValidationSeverity.WARN, evidence)
    if facts.typing_only:
        return EvidenceOutcome("consumer.typing-only", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, evidence)
    if _weak_text_present(source, symbols):
        return EvidenceOutcome("consumer.weak-text-only", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, evidence)
    return EvidenceOutcome("consumer.interface-missing", EvidenceConfidence.UNVERIFIED, ValidationSeverity.FAIL, evidence)


def inspect_test(root: Path, test_path: str, interfaces: tuple[str, ...]) -> EvidenceOutcome:
    rel = test_path.strip()
    evidence = (ValidationEvidence(_safe_evidence_path(rel), None, None, "test-path", f"listed test {rel!r}"),)
    lexical = _lexical_path_error(test_path)
    if lexical is not None:
        return EvidenceOutcome(lexical, EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, evidence)
    if not os.path.lexists(root.joinpath(*_normalize_relparts(rel))):
        return EvidenceOutcome("path.missing", EvidenceConfidence.UNVERIFIED, ValidationSeverity.FAIL, evidence)
    if classify_repository_path(rel) != "test":
        return EvidenceOutcome("test.path-not-test", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, evidence)

    source = _read_source(root, rel)
    if source is None:
        return EvidenceOutcome("path.missing", EvidenceConfidence.UNVERIFIED, ValidationSeverity.FAIL, evidence)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return EvidenceOutcome("test.syntax-error", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, evidence)

    modules, symbols = _registered_names(interfaces)
    facts = _ReferenceFacts(tree, modules, symbols)
    ok_evidence = (ValidationEvidence(rel, None, None, "test-interface-call", "test exercises a registered interface with an assertion"),)

    if facts.exercises_symbol and facts.has_assertion:
        return _ok("test-interface-call", ok_evidence)
    if facts.dynamic:
        return EvidenceOutcome(
            "test.dynamic-usage", EvidenceConfidence.MANUAL_REVIEW, ValidationSeverity.MANUAL_REVIEW, evidence,
            "test may reach the interface only through dynamic loading",
        )
    if facts.local_helper_imports and not facts.exercises_symbol:
        return EvidenceOutcome(
            "test.helper-boundary-unresolved", EvidenceConfidence.MANUAL_REVIEW, ValidationSeverity.MANUAL_REVIEW, evidence,
            "test reaches the interface only through an unresolved local helper",
        )
    if facts.registered_symbol_import or facts.registered_module_import:
        if facts.skip_decorated and not facts.has_assertion:
            return EvidenceOutcome("test.skipped-only", EvidenceConfidence.PROBABLE, ValidationSeverity.WARN, evidence)
        return EvidenceOutcome("test.import-only", EvidenceConfidence.PROBABLE, ValidationSeverity.WARN, evidence)
    if facts.skip_decorated:
        return EvidenceOutcome("test.skipped-only", EvidenceConfidence.PROBABLE, ValidationSeverity.WARN, evidence)
    if _weak_text_present(source, symbols):
        return EvidenceOutcome("test.weak-text-only", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, evidence)
    return EvidenceOutcome("test.unrelated", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL, evidence)
