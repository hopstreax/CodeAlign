"""Analysis package for plan parsing, graph indexing, and evidence resolution."""

from codealign.analysis.graph_index import (
    CallerCalleeHit,
    GraphIndex,
    RelationshipHit,
    SymbolDefinition,
)
from codealign.analysis.plan_parser import (
    ParsedPlan,
    PlanReference,
    parse_plan_file,
    parse_plan_text,
)
from codealign.analysis.resolver import (
    PlanAnalysisResult,
    ResolvedReference,
    UnresolvedReference,
    resolve_plan,
)

__all__ = [
    "CallerCalleeHit",
    "GraphIndex",
    "ParsedPlan",
    "PlanAnalysisResult",
    "PlanReference",
    "RelationshipHit",
    "ResolvedReference",
    "SymbolDefinition",
    "UnresolvedReference",
    "parse_plan_file",
    "parse_plan_text",
    "resolve_plan",
]
