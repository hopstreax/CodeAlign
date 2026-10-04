"""Generate ImplementationBaseline contract from developer intent and repository evidence."""

import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from codealign.analysis.plan_parser import ParsedPlan
from codealign.analysis.resolver import PlanAnalysisResult
from codealign.git.repository import GitRepoInfo
from codealign.models.baseline import (
    BaselineEvidence,
    BaselineEvidenceItem,
    BaselineExpectations,
    BaselineIntent,
    BaselineRepositoryInfo,
    ExpectedFile,
    ExpectedRelationship,
    ExpectedSymbol,
    ExpectedTest,
    ImplementationBaseline,
)

TEST_PATH_PATTERNS = (
    r"^tests?/",
    r"/tests?/",
    r"test_",
    r"_test\.[a-zA-Z0-9]+$",
    r"\.test\.[a-zA-Z0-9]+$",
    r"\.spec\.[a-zA-Z0-9]+$",
)

CREATE_VERB_PATTERNS = (
    r"\bcreate\b",
    r"\bnew\s+file\b",
    r"\badd\s+(?:a\s+)?new\b",
    r"\badd\s+.*tests?\s+(?:in|to|for)\b",
    r"\bintroduce\b",
    r"\bscaffold\b",
    r"\bgenerate\b",
)

UPDATE_VERB_PATTERNS = (
    r"\bupdate\b",
    r"\bmodify\b",
    r"\bchange\b",
    r"\bedit\b",
    r"\brefactor\b",
    r"\btouch\b",
    r"\bfix\b",
)


def _is_test_file(path_str: str) -> bool:
    """Determine if a file path is a test file."""
    normalized = path_str.replace("\\", "/")
    return any(re.search(pat, normalized, re.IGNORECASE) for pat in TEST_PATH_PATTERNS)


def _detect_file_create_intent(file_path: str, plan: ParsedPlan) -> bool:
    """Determine whether the plan communicates an explicit intent to create a new file.

    Conservative rule:
    - If a line referencing the file explicitly contains creation verbs ('create', 'new file',
      'add a new file', etc.) -> returns True.
    - If it contains modification/update verbs ('update', 'modify', 'touch', 'edit', etc.)
      or lacks clear creation language -> returns False.
    """
    normalized_path = file_path.replace("\\", "/").lstrip("./")
    filename = Path(normalized_path).name

    matching_lines: list[str] = []
    for line in plan.raw_content.splitlines():
        norm_line = line.replace("\\", "/")
        if normalized_path in norm_line or filename in norm_line:
            matching_lines.append(line.strip().lower())

    if not matching_lines:
        return False

    for line in matching_lines:
        has_update = any(re.search(pat, line) for pat in UPDATE_VERB_PATTERNS)
        has_create = any(re.search(pat, line) for pat in CREATE_VERB_PATTERNS)

        if has_create and not has_update:
            return True
        if has_create and has_update:
            if re.search(r"\bcreate\b", line):
                return True

    return False


def generate_baseline(
    plan: ParsedPlan,
    analysis: PlanAnalysisResult,
    repo_info: GitRepoInfo | None = None,
    repo_root: Path | None = None,
) -> ImplementationBaseline:
    """Derive Implementation Baseline contract from plan intent and repository evidence.

    CRITICAL DISTINCTION:
    - Evidence: What was discovered in the repository (symbols, callers, callees, relationships).
    - Expectation: What must be true of the implementation based strictly on explicit developer
      intent. Callers and callees are NOT automatically turned into expected modifications.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Repository info (portable: no absolute local machine path)
    repo = BaselineRepositoryInfo(
        name=repo_info.root.name if repo_info else (repo_root.name if repo_root else ""),
        branch=repo_info.branch if repo_info else "",
        commit=repo_info.head_sha if repo_info else "",
    )

    # 2. Intent
    intent = BaselineIntent(
        plan_file=analysis.plan_file,
        title=plan.title or analysis.plan_title,
        goal=plan.goal,
        steps=plan.steps,
    )

    # 3. Evidence
    resolved_items: list[BaselineEvidenceItem] = []
    for r in analysis.resolved:
        symbols_in_file = [asdict(s) for s in r.symbols_in_file]
        symbols_in_file.sort(key=lambda s: (s.get("line") or 0, s.get("name", "")))

        callers = [asdict(c) for c in r.callers]
        callers.sort(
            key=lambda c: (c.get("file_path", ""), c.get("line") or 0, c.get("symbol", ""))
        )

        callees = [asdict(c) for c in r.callees]
        callees.sort(
            key=lambda c: (c.get("file_path", ""), c.get("line") or 0, c.get("symbol", ""))
        )

        relationships = [asdict(rel) for rel in r.relationships]
        relationships.sort(
            key=lambda rel: (
                rel.get("relation", ""),
                rel.get("source_symbol", ""),
                rel.get("target_symbol", ""),
            )
        )

        resolved_items.append(
            BaselineEvidenceItem(
                reference=r.reference,
                status="resolved",
                kind=r.kind,
                symbol=r.symbol,
                file_path=r.file_path,
                line=r.line,
                symbols_in_file=symbols_in_file,
                callers=callers,
                callees=callees,
                relationships=relationships,
            )
        )

    resolved_items.sort(key=lambda r: (r.file_path, r.line or 0, r.symbol))

    unresolved_items: list[BaselineEvidenceItem] = []
    for u in analysis.unresolved:
        unresolved_items.append(
            BaselineEvidenceItem(
                reference=u.reference,
                status="unresolved",
                kind=u.kind,
                reason=u.reason,
            )
        )

    unresolved_items.sort(key=lambda u: u.reference)

    evidence = BaselineEvidence(
        summary={
            "total_references": len(resolved_items) + len(unresolved_items),
            "resolved_count": len(resolved_items),
            "unresolved_count": len(unresolved_items),
        },
        resolved=resolved_items,
        unresolved=unresolved_items,
    )

    # 4. Expectations (derived strictly and conservatively)
    expected_files: list[ExpectedFile] = []
    seen_files: set[str] = set()

    def add_expected_file(path: str, action: str, status: str, reason: str) -> None:
        norm = path.replace("\\", "/").lstrip("./")
        if norm and norm not in seen_files:
            seen_files.add(norm)
            expected_files.append(
                ExpectedFile(path=norm, action=action, status=status, reason=reason)
            )

    # A. Files explicitly referenced in plan (resolved -> modify)
    for r in analysis.resolved:
        if r.kind == "file":
            add_expected_file(
                path=r.file_path,
                action="modify",
                status="resolved",
                reason="Explicitly referenced in plan",
            )

    # B. Files explicitly referenced in plan (unresolved in graph)
    # Conservative rule: Do NOT assume missing file means create!
    for u in analysis.unresolved:
        if u.kind == "file":
            if _detect_file_create_intent(u.reference, plan):
                add_expected_file(
                    path=u.reference,
                    action="create",
                    status="expected",
                    reason="Explicit creation intent in plan",
                )
            else:
                add_expected_file(
                    path=u.reference,
                    action="unresolved",
                    status="unresolved",
                    reason="File referenced by plan does not currently exist in repository",
                )

    # C. Files containing resolved symbols explicitly referenced in plan
    for r in analysis.resolved:
        if r.kind != "file" and r.file_path:
            add_expected_file(
                path=r.file_path,
                action="modify",
                status="resolved",
                reason=f"Defines target symbol '{r.symbol}' referenced in plan",
            )

    expected_files.sort(key=lambda f: f.path)

    # Expected symbols
    expected_symbols: list[ExpectedSymbol] = []
    for r in analysis.resolved:
        if r.kind != "file":
            expected_symbols.append(
                ExpectedSymbol(
                    name=r.symbol,
                    kind=r.kind,
                    file_path=r.file_path,
                    line=r.line,
                    status="existing",
                    reason=f"Explicitly referenced in plan as '{r.reference}'",
                )
            )

    for u in analysis.unresolved:
        if u.kind != "file":
            expected_symbols.append(
                ExpectedSymbol(
                    name=u.reference,
                    kind=u.kind,
                    status="unresolved",
                    reason=u.reason,
                )
            )

    expected_symbols.sort(key=lambda s: s.name)

    # Expected tests (only for non-unresolved test files)
    expected_tests: list[ExpectedTest] = []
    for f in expected_files:
        if f.status != "unresolved" and _is_test_file(f.path):
            expected_tests.append(
                ExpectedTest(
                    path=f.path,
                    reason=f"Explicit test file referenced in plan ({f.reason})",
                )
            )

    expected_tests.sort(key=lambda t: t.path)

    expected_relationships: list[ExpectedRelationship] = []

    expectations = BaselineExpectations(
        expected_files=expected_files,
        expected_symbols=expected_symbols,
        expected_tests=expected_tests,
        expected_relationships=expected_relationships,
    )

    return ImplementationBaseline(
        schema_version="0.1.0",
        generated_at=now_iso,
        repository=repo,
        intent=intent,
        evidence=evidence,
        expectations=expectations,
    )
