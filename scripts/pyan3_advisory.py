"""Report-only Pyan3 call-graph runner for #3689. Never authorizes code removal.

Static call-graph evidence only: a node with no incoming static edge is a
*potentially disconnected* candidate, never proven runtime-unreachable code.
Tests, entrypoints, dynamic/plugin/MCP registration and callers outside the
bounded scope are not visible to this analysis.
"""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import json
from pathlib import Path
import subprocess
import sys

SCOPE = ("scripts/agent_os_issue_acceptance", "08_Tooling/agent-os-execution-service/src")
VERSION = "2.9.0"
STRUCTURAL = {"module", "class", "function", "method", "classmethod"}
MAX_CANDIDATES = 100
MAX_UNRESOLVED = 100
MAX_CYCLES = 50
MAX_NODES = 5000
MAX_EDGES = 10000
LIMITATIONS = (
    "Approximate static call graph (Pyan3). Dynamic imports/calls, attribute "
    "dispatch, decorators-as-registration, entrypoints and callers outside the "
    "bounded scope are incompletely visible; an unreferenced static node is "
    "not proof of runtime unreachability and never alone authorizes deletion."
)


def _node_id(node) -> str:
    if node.namespace:
        return f"{node.namespace}.{node.name}"
    return str(node.name)


def _kind(node) -> str:
    return str(node.flavor).rsplit(".", 1)[-1].lower()


def _is_test_file(path: str) -> bool:
    parts = Path(path).parts
    name = Path(path).name
    return "tests" in parts or "test" in parts or name.startswith("test_") or name.endswith("_test.py")


def _make_visitor(files: list[str], root: Path):
    """Build the pinned Pyan3 visitor; raises on missing/mismatched tool."""
    from importlib.metadata import version

    found = version("pyan3")
    if found != VERSION:
        raise RuntimeError(f"pyan3 version mismatch: pinned {VERSION}, found {found}")
    from pyan.analyzer import CallGraphVisitor

    return CallGraphVisitor(files, root=str(root))


def _normalize(visitor, root: Path) -> tuple[list[dict], list[dict], list[dict], int]:
    """Reduce Pyan3's noisy graph to defined structural nodes and their edges."""
    nodes: dict[str, dict] = {}
    raw: dict[str, object] = {}
    for group in visitor.nodes.values():
        for node in group:
            if _kind(node) not in STRUCTURAL or not node.defined or node.name == "^^^argument^^^":
                continue
            nid = _node_id(node)
            raw[nid] = node
            filename = getattr(node, "filename", None) or ""
            try:
                filename = str(Path(filename).relative_to(root))
            except (ValueError, TypeError):
                filename = str(filename)
            ast_node = getattr(node, "ast_node", None)
            nodes[nid] = {
                "id": nid,
                "kind": _kind(node),
                "file": filename,
                "line": getattr(ast_node, "lineno", None),
                "decorated": bool(getattr(ast_node, "decorator_list", None)),
            }
    edges: set[tuple[str, str]] = set()
    unresolved: set[tuple[str, str]] = set()
    for source, targets in visitor.uses_edges.items():
        if _kind(source) not in STRUCTURAL or not source.defined:
            continue
        sid = _node_id(source)
        if sid not in nodes:
            continue
        for target in targets:
            tid = _node_id(target)
            if tid in nodes and tid != sid:
                edges.add((sid, tid))
            elif target.name != "^^^argument^^^" and (
                _kind(target) not in STRUCTURAL or not target.defined
            ):
                unresolved.add((sid, tid))
    # Pyan3 nondeterministically (hash order) also emits a bare, unnamespaced
    # unresolved duplicate of a call it resolved to a qualified node from the
    # same caller. Drop those duplicates so reports are deterministic; a bare
    # name with no resolved counterpart from that caller stays unresolved.
    resolved_leaves: dict[str, set[str]] = defaultdict(set)
    for a, b in edges:
        resolved_leaves[a].add(b.rsplit(".", 1)[-1])
    unresolved = {
        (a, t) for a, t in unresolved if "." in t or t not in resolved_leaves.get(a, set())
    }
    defines = sum(len(t) for t in visitor.defines_edges.values())
    node_list = [nodes[k] for k in sorted(nodes)]
    edge_list = [{"from": a, "to": b, "type": "uses"} for a, b in sorted(edges)]
    unresolved_list = [{"from": a, "target": b} for a, b in sorted(unresolved)]
    return node_list, edge_list, unresolved_list, defines


def _strongly_connected(graph: dict[str, set[str]]) -> list[list[str]]:
    """Iterative Tarjan SCC; returns components of size > 1 plus self-loops."""
    index_counter = [0]
    stack: list[str] = []
    lowlink: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: defaultdict[str, bool] = defaultdict(bool)
    result: list[list[str]] = []
    for start in sorted(graph):
        if start in index:
            continue
        work = [(start, iter(sorted(graph.get(start, ()))))]
        index[start] = lowlink[start] = index_counter[0]
        index_counter[0] += 1
        stack.append(start)
        on_stack[start] = True
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in index:
                    index[nxt] = lowlink[nxt] = index_counter[0]
                    index_counter[0] += 1
                    stack.append(nxt)
                    on_stack[nxt] = True
                    work.append((nxt, iter(sorted(graph.get(nxt, ())))))
                    advanced = True
                    break
                if on_stack[nxt]:
                    lowlink[node] = min(lowlink[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])
            if lowlink[node] == index[node]:
                comp = []
                while True:
                    member = stack.pop()
                    on_stack[member] = False
                    comp.append(member)
                    if member == node:
                        break
                if len(comp) > 1:
                    result.append(sorted(comp))
                elif node in graph.get(node, ()):
                    result.append([node])
    return sorted(result)


def _import_cycles(root: Path, files: list[Path]) -> list[list[str]]:
    """Module import cycles among in-scope files, from AST imports only."""
    def module_name(path: Path) -> str:
        rel = path.relative_to(root).with_suffix("")
        parts = list(rel.parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    names = {module_name(f): f for f in files}
    by_suffix: dict[str, str] = {}
    for name in names:
        parts = name.split(".")
        for i in range(len(parts)):
            by_suffix.setdefault(".".join(parts[i:]), name)
    graph: dict[str, set[str]] = {name: set() for name in names}
    for name, path in names.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        package = name.rsplit(".", 1)[0] if path.name != "__init__.py" and "." in name else name
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split(".")[: len(package.split(".")) - node.level + 1] if package else []
                    targets = [".".join(base + ([node.module] if node.module else []))]
                elif node.module:
                    targets = [node.module]
            for target in targets:
                hit = target if target in names else by_suffix.get(target)
                if hit and hit != name:
                    graph[name].add(hit)
                elif hit == name and isinstance(node, ast.Import):
                    graph[name].add(name)
    return _strongly_connected(graph)[:MAX_CYCLES]


def _classify(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict], int]:
    """Split unreferenced nodes into candidates vs test-only-referenced.

    A node is a candidate only when no analyzed caller references it, it is
    production code, and it is not a module, dunder, `main`, or decorated
    (decorated nodes may be plugin/registry entrypoints).
    """
    by_id = {n["id"]: n for n in nodes}
    incoming: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        incoming[edge["to"]].add(edge["from"])
    candidates: list[dict] = []
    test_only: list[dict] = []
    decorated_excluded = 0
    for nid in sorted(by_id):
        node = by_id[nid]
        if node["kind"] == "module" or _is_test_file(node["file"]):
            continue
        callers = incoming.get(nid, set())
        if callers:
            if all(_is_test_file(by_id[c]["file"]) for c in callers if c in by_id):
                test_only.append({"id": nid, "file": node["file"], "line": node["line"],
                                  "callers": sorted(callers)})
            continue
        name = nid.rsplit(".", 1)[-1]
        if (name.startswith("__") and name.endswith("__")) or name == "main":
            continue
        if node["decorated"]:
            decorated_excluded += 1
            continue
        candidates.append({"id": nid, "kind": node["kind"], "file": node["file"], "line": node["line"]})
    return candidates, test_only, decorated_excluded


def scan(root: Path, output: Path, *, sha: str | None = None, scope: tuple[str, ...] = SCOPE) -> dict:
    """Return evidence even when the scanner is missing or fails."""
    output.mkdir(parents=True, exist_ok=True)
    if sha is None:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
        sha = rev.stdout.strip() if rev.returncode == 0 else "unavailable"
    files = sorted(
        p for rel in scope for p in (root / rel).rglob("*.py") if "__pycache__" not in p.parts
    ) if all((root / rel).exists() for rel in scope) else []
    parse_failures: list[str] = []
    parseable: list[Path] = []
    for path in files:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            parseable.append(path)
        except (OSError, SyntaxError, ValueError):
            parse_failures.append(str(path.relative_to(root)))
    status, detail = "ok", None
    nodes: list[dict] = []
    edges: list[dict] = []
    unresolved: list[dict] = []
    defines_count = 0
    import_cycles: list[list[str]] = []
    call_cycles: list[list[str]] = []
    candidates: list[dict] = []
    test_only: list[dict] = []
    decorated_excluded = 0
    if not files:
        status, detail = "scanner-error", "scope not found or empty"
    else:
        try:
            visitor = _make_visitor([str(p) for p in parseable], root)
            nodes, edges, unresolved, defines_count = _normalize(visitor, root)
            import_cycles = _import_cycles(root, parseable)
            call_graph: dict[str, set[str]] = defaultdict(set)
            for edge in edges:
                call_graph[edge["from"]].add(edge["to"])
            call_cycles = _strongly_connected(call_graph)[:MAX_CYCLES]
            candidates, test_only, decorated_excluded = _classify(nodes, edges)
        except Exception as exc:  # scanner failure is evidence, never fatal
            status, detail = "scanner-error", f"{type(exc).__name__}: {exc}"
            nodes, edges, unresolved = [], [], []
    evidence = {
        "schema": "agent-os-pyan3-advisory/1",
        "status": status,
        "detail": detail,
        "head_sha": sha,
        "tool": "pyan3",
        "version": VERSION,
        "scope": list(scope),
        "limitations": LIMITATIONS,
        "file_count": len(files),
        "parse_failures": parse_failures,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "defines_edge_count": defines_count,
        "unresolved_count": len(unresolved),
        "unresolved": unresolved[:MAX_UNRESOLVED],
        "unresolved_truncated": len(unresolved) > MAX_UNRESOLVED,
        "import_cycles": import_cycles,
        "call_cycles": call_cycles,
        "candidate_count": len(candidates),
        "candidates": candidates[:MAX_CANDIDATES],
        "candidates_truncated": len(candidates) > MAX_CANDIDATES,
        "test_only_count": len(test_only),
        "test_only_referenced": test_only[:MAX_CANDIDATES],
        "decorated_excluded_count": decorated_excluded,
    }
    (output / "raw").mkdir(exist_ok=True)
    (output / "raw" / "pyan3-graph.json").write_text(
        json.dumps({"nodes": nodes[:MAX_NODES], "edges": edges[:MAX_EDGES],
                    "nodes_truncated": len(nodes) > MAX_NODES,
                    "edges_truncated": len(edges) > MAX_EDGES}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    (output / "pyan3-advisory.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Pyan3 advisory", "",
        f"- SHA: `{sha}`", f"- Tool: pyan3 {VERSION}", f"- Status: {status}",
        f"- Files: {len(files)}; nodes: {len(nodes)}; resolved edges: {len(edges)}; "
        f"unresolved edges: {len(unresolved)}",
        f"- Import cycles: {len(import_cycles)}; call cycles: {len(call_cycles)}",
        f"- Potentially disconnected candidates: {len(candidates)} (first {MAX_CANDIDATES} in JSON); "
        f"test-only referenced: {len(test_only)}; decorated excluded: {decorated_excluded}",
        "", "## Import cycles",
        *(["- " + " <-> ".join(c) for c in import_cycles] or ["- none detected"]),
        "", "## Potentially disconnected candidates",
        *([f"- `{c['id']}` ({c['file']}:{c['line']})" for c in candidates[:MAX_CANDIDATES]] or ["- none"]),
        "", LIMITATIONS, "",
        "Findings require human review under #1729 Wire-or-Retire; a candidate is "
        "not proven unreachable and no code deletion is authorized.", "",
    ]
    (output / "pyan3-advisory.md").write_text("\n".join(lines), encoding="utf-8")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("tmp/pyan3-advisory"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--sha")
    args = parser.parse_args()
    result = scan(args.root.resolve(), args.output.resolve(), sha=args.sha)
    print(json.dumps({k: v for k, v in result.items() if k not in ("candidates", "unresolved")}, sort_keys=True))
    # Advisory: findings and scanner errors never block other validation.
    return 0


if __name__ == "__main__":
    sys.exit(main())
