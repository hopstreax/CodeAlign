"""Lightweight query and read index over Graphify graph.json."""

import json
from dataclasses import dataclass
from pathlib import Path


def _parse_line(loc: str | None) -> int | None:
    """Parse line integer from Graphify source_location (e.g. 'L42' -> 42)."""
    if not loc:
        return None
    loc_str = str(loc).strip()
    if loc_str.startswith("L") and loc_str[1:].isdigit():
        return int(loc_str[1:])
    if loc_str.isdigit():
        return int(loc_str)
    return None


def _normalize_name(name: str) -> str:
    """Normalize a symbol name for lookup (lowercase, stripped parens)."""
    name = name.strip()
    if name.endswith("()"):
        name = name[:-2]
    return name.lower()


def _normalize_path(path: str) -> str:
    """Normalize file path to forward slashes with no leading './'."""
    p = path.replace("\\", "/").strip()
    if p.startswith("./"):
        p = p[2:]
    return p


@dataclass(frozen=True)
class SymbolDefinition:
    """A symbol defined in the codebase."""

    id: str
    name: str
    file_path: str
    line: int | None
    kind: str  # "class", "function", "method", "file"
    raw_label: str


@dataclass(frozen=True)
class CallerCalleeHit:
    """A call relationship connected to a symbol."""

    symbol: str
    file_path: str
    line: int | None
    relation: str  # "calls" or "indirect_call"


@dataclass(frozen=True)
class RelationshipHit:
    """A general graph relationship connected to a symbol."""

    relation: str
    source_symbol: str
    source_file: str
    source_line: int | None
    target_symbol: str
    target_file: str
    target_line: int | None
    direction: str  # "incoming" or "outgoing"


class GraphIndex:
    """In-memory index over Graphify graph.json data.

    Answers direct lookup questions:
    1. Symbols in a file
    2. Where a symbol or method is defined
    3. Callers and callees of a symbol
    4. General relationships connected to a symbol
    """

    def __init__(
        self,
        nodes: list[dict],
        edges: list[dict],
    ) -> None:
        self._nodes_by_id: dict[str, dict] = {}
        self._nodes_by_file: dict[str, list[dict]] = {}
        self._symbols_by_name: dict[str, list[dict]] = {}
        self._classes_by_name: dict[str, list[dict]] = {}
        self._methods_by_class_id: dict[str, list[dict]] = {}
        self._edges_by_source: dict[str, list[dict]] = {}
        self._edges_by_target: dict[str, list[dict]] = {}
        self._known_files: set[str] = set()

        self._build_index(nodes, edges)

    @classmethod
    def from_file(cls, path: Path) -> "GraphIndex":
        """Load and index a graph.json file from disk."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        nodes = data.get("nodes", [])
        edges = data.get("links") if "links" in data else data.get("edges", [])
        return cls(nodes, edges)

    @classmethod
    def from_dict(cls, data: dict) -> "GraphIndex":
        """Build an index from a graph dictionary."""
        nodes = data.get("nodes", [])
        edges = data.get("links") if "links" in data else data.get("edges", [])
        return cls(nodes, edges)

    def _determine_kind(self, node: dict) -> str:
        label = node.get("label", "")
        if node.get("source_location") == "L1" and (
            any(label.endswith(ext) for ext in (".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs"))
            or node.get("type") == "package"
            or node.get("id", "").startswith("file_")
        ):
            return "file"
        if node.get("_callable_class") or node.get("node_kind") == "class":
            return "class"
        if label.startswith(".") or (
            label.endswith("()")
            and any(
                e.get("relation") == "method" and e.get("target") == node.get("id")
                for e in self._edges_by_target.get(node.get("id", ""), [])
            )
        ):
            return "method"
        if node.get("_callable") or label.endswith("()"):
            return "function"
        return "symbol"

    def _build_index(self, nodes: list[dict], edges: list[dict]) -> None:
        for node in nodes:
            nid = node.get("id")
            if not nid:
                continue
            self._nodes_by_id[nid] = node

            source_file = node.get("source_file")
            if source_file:
                norm_f = _normalize_path(source_file)
                self._known_files.add(norm_f)
                self._nodes_by_file.setdefault(norm_f, []).append(node)

            # Index by normalized name (excluding rationale/doc nodes)
            if node.get("file_type") == "code":
                label = node.get("label", "")
                norm_label = _normalize_name(label.lstrip("."))
                if norm_label:
                    self._symbols_by_name.setdefault(norm_label, []).append(node)

                # Track classes
                if node.get("_callable_class") or node.get("node_kind") == "class":
                    self._classes_by_name.setdefault(norm_label, []).append(node)

        # Index edges
        for edge in edges:
            src = edge.get("source")
            tgt = edge.get("target")
            if src:
                self._edges_by_source.setdefault(src, []).append(edge)
            if tgt:
                self._edges_by_target.setdefault(tgt, []).append(edge)

            # Map methods to classes
            if edge.get("relation") in ("method", "contains") and src and tgt:
                src_node = self._nodes_by_id.get(src, {})
                if src_node.get("_callable_class") or src_node.get("node_kind") == "class":
                    tgt_node = self._nodes_by_id.get(tgt)
                    if tgt_node:
                        self._methods_by_class_id.setdefault(src, []).append(tgt_node)

    def file_exists(self, file_path: str) -> bool:
        """Check whether a file exists in the repository graph."""
        norm = _normalize_path(file_path)
        return norm in self._known_files

    def get_symbols_in_file(self, file_path: str) -> list[SymbolDefinition]:
        """Return all code symbols defined inside the specified file."""
        norm = _normalize_path(file_path)
        nodes = self._nodes_by_file.get(norm, [])
        symbols: list[SymbolDefinition] = []

        for n in nodes:
            if n.get("file_type") != "code":
                continue
            kind = self._determine_kind(n)
            if kind == "file":
                continue

            symbols.append(
                SymbolDefinition(
                    id=n["id"],
                    name=n.get("label", "").lstrip(".").rstrip("()"),
                    file_path=norm,
                    line=_parse_line(n.get("source_location")),
                    kind=kind,
                    raw_label=n.get("label", ""),
                )
            )

        symbols.sort(key=lambda s: (s.line or 0, s.name))
        return symbols

    def find_symbol(self, name: str) -> list[SymbolDefinition]:
        """Resolve a symbol name to its definitions."""
        clean = name.strip()
        if "." in clean and not clean.startswith("."):
            parts = clean.split(".", 1)
            return self.find_method(parts[0], parts[1])

        norm = _normalize_name(clean)
        nodes = self._symbols_by_name.get(norm, [])
        defs: list[SymbolDefinition] = []
        for n in nodes:
            defs.append(
                SymbolDefinition(
                    id=n["id"],
                    name=n.get("label", "").rstrip("()"),
                    file_path=_normalize_path(n.get("source_file", "")),
                    line=_parse_line(n.get("source_location")),
                    kind=self._determine_kind(n),
                    raw_label=n.get("label", ""),
                )
            )
        return defs

    def find_method(self, class_name: str, method_name: str) -> list[SymbolDefinition]:
        """Resolve a Class.method reference to its method definitions."""
        norm_class = _normalize_name(class_name)
        norm_method = _normalize_name(method_name)
        classes = self._classes_by_name.get(norm_class, [])

        defs: list[SymbolDefinition] = []
        for c in classes:
            cid = c.get("id", "")
            methods = self._methods_by_class_id.get(cid, [])
            for m in methods:
                m_label = _normalize_name(m.get("label", "").lstrip("."))
                if m_label == norm_method:
                    method_str = m.get("label", "").lstrip(".").rstrip("()")
                    clean_name = f"{c.get('label', class_name)}.{method_str}"
                    defs.append(
                        SymbolDefinition(
                            id=m["id"],
                            name=clean_name,
                            file_path=_normalize_path(m.get("source_file", "")),
                            line=_parse_line(m.get("source_location")),
                            kind="method",
                            raw_label=m.get("label", ""),
                        )
                    )
        return defs

    def get_callers(self, node_id: str) -> list[CallerCalleeHit]:
        """Return callers connecting into this symbol."""
        incoming = self._edges_by_target.get(node_id, [])
        callers: list[CallerCalleeHit] = []
        for e in incoming:
            if e.get("relation") in ("calls", "indirect_call"):
                src_node = self._nodes_by_id.get(e.get("source", ""), {})
                src_label = src_node.get("label", "").rstrip("()")
                callers.append(
                    CallerCalleeHit(
                        symbol=src_label or e.get("source", ""),
                        file_path=_normalize_path(
                            e.get("source_file") or src_node.get("source_file", "")
                        ),
                        line=_parse_line(
                            e.get("source_location") or src_node.get("source_location")
                        ),
                        relation=e.get("relation", "calls"),
                    )
                )
        callers.sort(key=lambda c: (c.file_path, c.line or 0))
        return callers

    def get_callees(self, node_id: str) -> list[CallerCalleeHit]:
        """Return callees called by this symbol."""
        outgoing = self._edges_by_source.get(node_id, [])
        callees: list[CallerCalleeHit] = []
        for e in outgoing:
            if e.get("relation") in ("calls", "indirect_call"):
                tgt_node = self._nodes_by_id.get(e.get("target", ""), {})
                tgt_label = tgt_node.get("label", "").rstrip("()")
                callees.append(
                    CallerCalleeHit(
                        symbol=tgt_label or e.get("target", ""),
                        file_path=_normalize_path(
                            e.get("source_file") or tgt_node.get("source_file", "")
                        ),
                        line=_parse_line(
                            e.get("source_location") or tgt_node.get("source_location")
                        ),
                        relation=e.get("relation", "calls"),
                    )
                )
        callees.sort(key=lambda c: (c.file_path, c.line or 0))
        return callees

    def get_relationships(self, node_id: str) -> list[RelationshipHit]:
        """Return all incoming and outgoing relationships connected to this symbol."""
        hits: list[RelationshipHit] = []

        for e in self._edges_by_target.get(node_id, []):
            rel = e.get("relation", "")
            src_node = self._nodes_by_id.get(e.get("source", ""), {})
            tgt_node = self._nodes_by_id.get(node_id, {})
            hits.append(
                RelationshipHit(
                    relation=rel,
                    source_symbol=src_node.get("label", "").rstrip("()"),
                    source_file=_normalize_path(
                        e.get("source_file") or src_node.get("source_file", "")
                    ),
                    source_line=_parse_line(
                        e.get("source_location") or src_node.get("source_location")
                    ),
                    target_symbol=tgt_node.get("label", "").rstrip("()"),
                    target_file=_normalize_path(tgt_node.get("source_file", "")),
                    target_line=_parse_line(tgt_node.get("source_location")),
                    direction="incoming",
                )
            )

        for e in self._edges_by_source.get(node_id, []):
            rel = e.get("relation", "")
            src_node = self._nodes_by_id.get(node_id, {})
            tgt_node = self._nodes_by_id.get(e.get("target", ""), {})
            hits.append(
                RelationshipHit(
                    relation=rel,
                    source_symbol=src_node.get("label", "").rstrip("()"),
                    source_file=_normalize_path(src_node.get("source_file", "")),
                    source_line=_parse_line(src_node.get("source_location")),
                    target_symbol=tgt_node.get("label", "").rstrip("()"),
                    target_file=_normalize_path(
                        e.get("source_file") or tgt_node.get("source_file", "")
                    ),
                    target_line=_parse_line(
                        e.get("source_location") or tgt_node.get("source_location")
                    ),
                    direction="outgoing",
                )
            )

        return hits
