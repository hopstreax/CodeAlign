"""Resolve plan references against repository GraphIndex and assemble evidence."""

import json
from dataclasses import asdict, dataclass, field

from codealign.analysis.graph_index import (
    CallerCalleeHit,
    GraphIndex,
    RelationshipHit,
    SymbolDefinition,
)
from codealign.analysis.plan_parser import ParsedPlan, PlanReference


@dataclass
class ResolvedReference:
    """An explicit plan reference resolved to repository ground truth."""

    reference: str
    kind: str  # "file", "class", "method", "function", "symbol"
    symbol: str
    file_path: str
    line: int | None
    symbols_in_file: list[SymbolDefinition] = field(default_factory=list)
    callers: list[CallerCalleeHit] = field(default_factory=list)
    callees: list[CallerCalleeHit] = field(default_factory=list)
    relationships: list[RelationshipHit] = field(default_factory=list)


@dataclass
class UnresolvedReference:
    """An explicit plan reference that could not be grounded in the codebase graph."""

    reference: str
    kind: str
    reason: str


@dataclass
class PlanAnalysisResult:
    """Outcome of resolving an implementation plan against codebase intelligence."""

    plan_file: str
    plan_title: str
    resolved: list[ResolvedReference] = field(default_factory=list)
    unresolved: list[UnresolvedReference] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert analysis result to dictionary suitable for JSON serialization."""
        return {
            "plan_file": self.plan_file,
            "plan_title": self.plan_title,
            "summary": {
                "total_references": len(self.resolved) + len(self.unresolved),
                "resolved_count": len(self.resolved),
                "unresolved_count": len(self.unresolved),
            },
            "resolved": [asdict(r) for r in self.resolved],
            "unresolved": [asdict(u) for u in self.unresolved],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize analysis result to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def format_terminal(self) -> str:
        """Format a clear, human-readable terminal report presenting evidence."""
        lines: list[str] = []
        lines.append("CodeAlign Plan Analysis")
        lines.append("========================")
        lines.append(f"Plan: {self.plan_file} ({self.plan_title})\n")

        if self.resolved:
            lines.append(f"RESOLVED REFERENCES ({len(self.resolved)})")
            lines.append("-" * 30)
            for r in self.resolved:
                lines.append(f"Plan reference:\n    {r.reference}")
                loc_str = f":{r.line}" if r.line is not None else ""
                lines.append(f"Resolved:\n    {r.file_path}{loc_str}")
                lines.append(f"Symbol:\n    {r.symbol} ({r.kind})")

                if r.symbols_in_file:
                    lines.append("Symbols in file:")
                    for s in r.symbols_in_file[:10]:
                        s_loc = f", line {s.line}" if s.line else ""
                        lines.append(f"    - {s.name} ({s.kind}{s_loc})")
                    if len(r.symbols_in_file) > 10:
                        lines.append(f"    ... and {len(r.symbols_in_file) - 10} more symbols")

                if r.callers:
                    lines.append("Callers:")
                    for c in r.callers:
                        c_loc = f":{c.line}" if c.line is not None else ""
                        lines.append(f"    - {c.file_path}{c_loc} ({c.symbol})")

                if r.callees:
                    lines.append("Callees:")
                    for c in r.callees:
                        c_loc = f":{c.line}" if c.line is not None else ""
                        lines.append(f"    - {c.file_path}{c_loc} ({c.symbol})")

                lines.append("")  # Blank spacer

        if self.unresolved:
            lines.append(f"UNRESOLVED REFERENCES ({len(self.unresolved)})")
            lines.append("-" * 30)
            for u in self.unresolved:
                lines.append(f"Plan reference:\n    {u.reference}")
                lines.append(f"Reason:\n    {u.reason}\n")

        return "\n".join(lines).strip()


def resolve_plan(plan: ParsedPlan, index: GraphIndex) -> PlanAnalysisResult:
    """Ground all references in the implementation plan against the codebase GraphIndex."""
    resolved: list[ResolvedReference] = []
    unresolved: list[UnresolvedReference] = []

    for ref in plan.references:
        _resolve_single_reference(ref, index, resolved, unresolved)

    return PlanAnalysisResult(
        plan_file=str(plan.path) if plan.path else "plan.md",
        plan_title=plan.title,
        resolved=resolved,
        unresolved=unresolved,
    )


def _resolve_single_reference(
    ref: PlanReference,
    index: GraphIndex,
    resolved: list[ResolvedReference],
    unresolved: list[UnresolvedReference],
) -> None:
    if ref.kind == "file":
        if index.file_exists(ref.target):
            symbols = index.get_symbols_in_file(ref.target)
            resolved.append(
                ResolvedReference(
                    reference=ref.raw,
                    kind="file",
                    symbol=ref.target,
                    file_path=ref.target,
                    line=1,
                    symbols_in_file=symbols,
                )
            )
        else:
            unresolved.append(
                UnresolvedReference(
                    reference=ref.raw,
                    kind="file",
                    reason=f"File '{ref.target}' not found in codebase graph",
                )
            )
        return

    if ref.kind == "method":
        parts = ref.target.split(".", 1)
        cls_name, method_name = parts[0], parts[1]
        matches = index.find_method(cls_name, method_name)

        if matches:
            for m in matches:
                callers = index.get_callers(m.id)
                callees = index.get_callees(m.id)
                relationships = index.get_relationships(m.id)
                resolved.append(
                    ResolvedReference(
                        reference=ref.raw,
                        kind="method",
                        symbol=m.name,
                        file_path=m.file_path,
                        line=m.line,
                        callers=callers,
                        callees=callees,
                        relationships=relationships,
                    )
                )
        else:
            # Check whether the class itself exists
            class_defs = index.find_symbol(cls_name)
            if not class_defs:
                unresolved.append(
                    UnresolvedReference(
                        reference=ref.raw,
                        kind="method",
                        reason=f"Class '{cls_name}' not found in codebase graph",
                    )
                )
            else:
                loc = (
                    f" at {class_defs[0].file_path}:{class_defs[0].line}"
                    if class_defs[0].line
                    else ""
                )
                reason_msg = (
                    f"Class '{cls_name}' found{loc}, "
                    f"but method '{method_name}' does not exist on it"
                )
                unresolved.append(
                    UnresolvedReference(
                        reference=ref.raw,
                        kind="method",
                        reason=reason_msg,
                    )
                )
        return

    # General symbol (class, function, identifier)
    matches = index.find_symbol(ref.target)
    if matches:
        for s in matches:
            callers = index.get_callers(s.id)
            callees = index.get_callees(s.id)
            relationships = index.get_relationships(s.id)
            resolved.append(
                ResolvedReference(
                    reference=ref.raw,
                    kind=s.kind,
                    symbol=s.name,
                    file_path=s.file_path,
                    line=s.line,
                    callers=callers,
                    callees=callees,
                    relationships=relationships,
                )
            )
    else:
        unresolved.append(
            UnresolvedReference(
                reference=ref.raw,
                kind="symbol",
                reason=f"Symbol '{ref.target}' not found in codebase graph",
            )
        )
