"""Core implementation verification engine for CodeAlign."""

import re
from pathlib import Path

from codealign.git.repository import GitRepoInfo
from codealign.models.baseline import ExpectedSymbol, ImplementationBaseline
from codealign.models.finding import Finding, FindingCategory, FindingSeverity
from codealign.models.result import VerificationResult, VerificationStatus
from codealign.verify.git_diff import (
    BaseCommitNotFoundError,
    GitChangeSet,
    WorkingTreeSnapshot,
    get_git_changes,
)

TEST_PATH_PATTERNS = (
    r"^tests?/",
    r"/tests?/",
    r"test_",
    r"_test\.[a-zA-Z0-9]+$",
    r"\.test\.[a-zA-Z0-9]+$",
    r"\.spec\.[a-zA-Z0-9]+$",
)


def _normalize_path(p: str) -> str:
    """Normalize file path to forward slashes with no leading './'."""
    norm = p.strip().replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm.lstrip("/")


def _is_codealign_artifact(path: str) -> bool:
    """Check if path is inside .codealign/ workflow artifact directory."""
    norm = _normalize_path(path)
    parts = Path(norm).parts
    return (
        norm == ".codealign"
        or norm.startswith(".codealign/")
        or ".codealign" in parts
    )


def _is_plan_artifact(
    path: str, plan_file: str | None, repo_root: Path | None = None
) -> bool:
    """Check if path is the plan input file used to generate the baseline."""
    if not plan_file:
        return False
    norm_path = _normalize_path(path)
    norm_plan = _normalize_path(plan_file)
    if norm_path == norm_plan or norm_path.lower() == norm_plan.lower():
        return True
    if repo_root is not None:
        try:
            plan_p = Path(plan_file)
            if not plan_p.is_absolute():
                plan_p = repo_root / plan_p
            resolved_repo = repo_root.resolve()
            resolved_plan = plan_p.resolve()
            if resolved_plan.is_relative_to(resolved_repo):
                rel_plan = _normalize_path(str(resolved_plan.relative_to(resolved_repo)))
                if norm_path == rel_plan or norm_path.lower() == rel_plan.lower():
                    return True
        except (ValueError, RuntimeError):
            pass
    return False


def _is_python_runtime_artifact(path: str) -> bool:
    """Check if path is a Python runtime artifact (__pycache__ or *.pyc/*.pyo)."""
    norm = _normalize_path(path)
    parts = Path(norm).parts
    return norm.endswith(".pyc") or norm.endswith(".pyo") or "__pycache__" in parts


def _is_test_path(path: str) -> bool:
    """Check if a file path represents a test file."""
    norm = _normalize_path(path)
    return any(re.search(pat, norm, re.IGNORECASE) for pat in TEST_PATH_PATTERNS)


def _is_symbol_defined_in_content(content: str, ident: str) -> bool:
    """Check if symbol identifier appears to be defined in file content."""
    def_patterns = [
        # Python: def / async def / class
        rf"\bdef\s+{re.escape(ident)}\b",
        rf"\basync\s+def\s+{re.escape(ident)}\b",
        rf"\bclass\s+{re.escape(ident)}\b",
        # JS/TS: function / class / const / let / var
        rf"\bfunction\s+{re.escape(ident)}\b",
        rf"\bclass\s+{re.escape(ident)}\b",
        rf"\b(?:const|let|var)\s+{re.escape(ident)}\s*=",
        # TS/JS method: ident(...) { or ident(...) :
        rf"^\s*(?:(?:public|private|protected|static|readonly|async)\s+)*{re.escape(ident)}\s*\([^)]*\)\s*(?:\{{|:)",
        # Go: func ident / func (recv) ident
        rf"\bfunc\s+(?:\([^)]+\)\s+)?{re.escape(ident)}\b",
        # Rust: fn ident / struct ident / enum ident
        rf"\bfn\s+{re.escape(ident)}\b",
        rf"\bstruct\s+{re.escape(ident)}\b",
        rf"\benum\s+{re.escape(ident)}\b",
        # Generic assignment: ident = or ident: Type =
        rf"\b{re.escape(ident)}\s*=",
        rf"\b{re.escape(ident)}\s*:\s*[^=\n]+\s*=",
    ]
    for pat in def_patterns:
        if re.search(pat, content, re.MULTILINE):
            return True
    return False


def _find_created_symbol_in_repo(
    exp_sym: ExpectedSymbol,
    baseline: ImplementationBaseline,
    repo_root: Path,
) -> str | None:
    """Re-check current repository to determine if an unresolved symbol now exists.

    Returns:
        The normalized relative path of the file where the symbol was found, or None.
    """
    clean_name = exp_sym.name.replace("\\", "").rstrip("()") or exp_sym.name
    ident = clean_name.split(".")[-1].rstrip("()")
    if not ident:
        return None

    # 1. If symbol has an explicit file_path, check it first
    if exp_sym.file_path:
        sym_file = _normalize_path(exp_sym.file_path)
        target_path = repo_root / sym_file
        if target_path.is_file():
            content = target_path.read_text(encoding="utf-8", errors="ignore")
            if _is_symbol_defined_in_content(content, ident) or re.search(
                rf"\b{re.escape(ident)}\b", content
            ):
                return sym_file

    # 2. Collect candidate expected files from baseline
    expected_tests = {_normalize_path(t.path) for t in baseline.expectations.expected_tests}
    seen: set[str] = set()
    candidate_files: list[str] = []
    for ef in baseline.expectations.expected_files:
        if ef.action != "delete":
            norm = _normalize_path(ef.path)
            if norm and norm not in seen:
                seen.add(norm)
                candidate_files.append(norm)

    # Separate into implementation files and test files
    impl_files = [
        f for f in candidate_files
        if f not in expected_tests and not _is_test_path(f)
    ]
    test_files = [f for f in candidate_files if f not in impl_files]
    for t in baseline.expectations.expected_tests:
        tp = _normalize_path(t.path)
        if tp not in seen:
            seen.add(tp)
            test_files.append(tp)

    # Prioritize implementation files mentioned in intent steps or goal alongside the symbol
    prioritized_impl: list[str] = []
    other_impl: list[str] = []
    intent_texts = baseline.intent.steps + [baseline.intent.goal, baseline.intent.title]
    for f in impl_files:
        filename = Path(f).name
        mentioned = any(
            ident.lower() in text.lower()
            and (f.lower() in text.lower() or filename.lower() in text.lower())
            for text in intent_texts
        )
        if mentioned:
            prioritized_impl.append(f)
        else:
            other_impl.append(f)

    ordered_impl = prioritized_impl + other_impl

    # Pass 0: If class-qualified name, look for candidate where class also exists
    if "." in clean_name:
        class_name = clean_name.split(".")[0]
        for f in ordered_impl:
            target_path = repo_root / f
            if target_path.is_file():
                content = target_path.read_text(encoding="utf-8", errors="ignore")
                if class_name in content and _is_symbol_defined_in_content(content, ident):
                    return f

    # Pass 1: Look for explicit symbol definition in candidate implementation files
    for f in ordered_impl:
        target_path = repo_root / f
        if target_path.is_file():
            content = target_path.read_text(encoding="utf-8", errors="ignore")
            if _is_symbol_defined_in_content(content, ident):
                return f

    # Pass 2: Look for word boundary identifier presence in candidate implementation files
    for f in ordered_impl:
        target_path = repo_root / f
        if target_path.is_file():
            content = target_path.read_text(encoding="utf-8", errors="ignore")
            if re.search(rf"\b{re.escape(ident)}\b", content):
                return f

    # Pass 3: Look for symbol definition in candidate test files (if plan intended test helpers)
    for f in test_files:
        target_path = repo_root / f
        if target_path.is_file():
            content = target_path.read_text(encoding="utf-8", errors="ignore")
            if _is_symbol_defined_in_content(content, ident):
                return f

    return None


def _is_symbol_expected(
    sym_name: str,
    file_path: str,
    baseline: ImplementationBaseline,
) -> bool:
    """Check if an introduced symbol name is expected by the baseline contract."""
    sym_parts = sym_name.split(".")
    sym_ident = sym_parts[-1]

    for exp in baseline.expectations.expected_symbols:
        clean_exp = exp.name.replace("\\", "").rstrip("()")
        if not clean_exp:
            continue

        exp_parts = clean_exp.split(".")
        exp_ident = exp_parts[-1]

        # If expected symbol has an explicit containing file, ensure it matches
        if exp.file_path:
            norm_exp_file = _normalize_path(exp.file_path)
            if norm_exp_file and norm_exp_file != file_path:
                continue

        # Exact match (e.g. "Calculator.multiply" == "Calculator.multiply")
        if sym_name == clean_exp:
            return True

        # Identifier match (e.g. "Calculator.multiply" or "multiply" matching expected "multiply")
        if sym_ident == exp_ident:
            # If both are qualified, class must also match
            if len(sym_parts) == 2 and len(exp_parts) == 2:
                if sym_parts[0] == exp_parts[0]:
                    return True
            else:
                return True

    return False


def verify_implementation(
    baseline: ImplementationBaseline,
    repo_root: Path,
    repo_info: GitRepoInfo | None = None,
    strict: bool = False,
    changeset: GitChangeSet | None = None,
    pre_snapshot: WorkingTreeSnapshot | None = None,
    post_snapshot: WorkingTreeSnapshot | None = None,
) -> VerificationResult:
    """Verify actual repository changes against the ImplementationBaseline contract.

    Args:
        baseline: The canonical ImplementationBaseline contract.
        repo_root: Path to repository root directory.
        repo_info: Optional GitRepoInfo for active repository.
        strict: If True, treat any warnings as verification failure.
        changeset: Optional pre-computed GitChangeSet (e.g. from an implementation session).
        pre_snapshot: Optional pre-session working tree snapshot for symbol drift detection.
        post_snapshot: Optional post-session working tree snapshot for symbol drift detection.

    Returns:
        VerificationResult with deterministic status and structured findings.
    """
    findings: list[Finding] = []

    # 1. Repository Binding Verification
    if repo_info and baseline.repository.name:
        current_name = repo_info.root.name
        if baseline.repository.name.lower() != current_name.lower():
            findings.append(
                Finding(
                    category=FindingCategory.REPOSITORY_BINDING,
                    severity=FindingSeverity.ERROR,
                    message=(
                        f"Repository mismatch: baseline was generated for "
                        f"'{baseline.repository.name}', but current repository is '{current_name}'."
                    ),
                    expected=baseline.repository.name,
                    actual=current_name,
                    evidence="Baseline contract is bound to a different repository",
                )
            )

    # 2. Extract Git Changes relative to baseline commit
    if changeset is None:
        try:
            changeset = get_git_changes(repo_root, baseline.repository.commit)
        except BaseCommitNotFoundError as exc:
            findings.append(
                Finding(
                    category=FindingCategory.REPOSITORY_BINDING,
                    severity=FindingSeverity.ERROR,
                    message=str(exc),
                    expected=baseline.repository.commit,
                    actual="commit not found in git history",
                    evidence="Cannot compare working tree against missing baseline commit",
                )
            )
            return VerificationResult(
                status=VerificationStatus.FAIL,
                summary="Verification failed: baseline commit not found in repository history",
                findings=findings,
            )

    # 3. Expected Files Verification
    expected_file_paths: set[str] = set()
    for exp_file in baseline.expectations.expected_files:
        norm_path = _normalize_path(exp_file.path)
        expected_file_paths.add(norm_path)

        # Unresolved file expectations (preserve uncertainty)
        if exp_file.status == "unresolved" or exp_file.action == "unresolved":
            findings.append(
                Finding(
                    category=FindingCategory.UNRESOLVED_REFERENCE,
                    severity=FindingSeverity.WARN,
                    message=f"Baseline contains unresolved file reference: '{norm_path}'.",
                    file_path=norm_path,
                    expected="unresolved",
                    actual="unconfirmed in codebase graph",
                    evidence=exp_file.reason or "File referenced by plan was unconfirmed",
                )
            )
            continue

        # Expected Modify
        if exp_file.action == "modify":
            if norm_path in changeset.modified:
                findings.append(
                    Finding(
                        category=FindingCategory.MISSING_IMPLEMENTATION,
                        severity=FindingSeverity.PASS,
                        message=f"Expected file '{norm_path}' was modified.",
                        file_path=norm_path,
                        expected="modify",
                        actual="modified",
                        evidence="File modified relative to baseline commit",
                    )
                )
            elif norm_path in changeset.deleted:
                findings.append(
                    Finding(
                        category=FindingCategory.MISSING_IMPLEMENTATION,
                        severity=FindingSeverity.ERROR,
                        message=f"Expected file '{norm_path}' was deleted instead of modified.",
                        file_path=norm_path,
                        expected="modify",
                        actual="deleted",
                        evidence="File deleted in working tree",
                    )
                )
            else:
                findings.append(
                    Finding(
                        category=FindingCategory.MISSING_IMPLEMENTATION,
                        severity=FindingSeverity.ERROR,
                        message=f"Expected file '{norm_path}' was not modified.",
                        file_path=norm_path,
                        expected="modify",
                        actual="unchanged",
                        evidence=(
                            f"File '{norm_path}' has no modifications relative to "
                            f"baseline commit {baseline.repository.commit}"
                        ),
                    )
                )

        # Expected Create
        elif exp_file.action == "create":
            file_on_disk = (repo_root / norm_path).is_file()
            file_is_new = norm_path in changeset.added or norm_path in changeset.modified
            if file_on_disk and file_is_new:
                findings.append(
                    Finding(
                        category=FindingCategory.MISSING_IMPLEMENTATION,
                        severity=FindingSeverity.PASS,
                        message=f"Expected file '{norm_path}' was created.",
                        file_path=norm_path,
                        expected="create",
                        actual="created",
                        evidence="File exists on disk and is newly added relative to baseline",
                    )
                )
            else:
                findings.append(
                    Finding(
                        category=FindingCategory.MISSING_IMPLEMENTATION,
                        severity=FindingSeverity.ERROR,
                        message=f"Expected file '{norm_path}' was not created.",
                        file_path=norm_path,
                        expected="create",
                        actual="missing",
                        evidence=f"Expected new file was not found at '{norm_path}'",
                    )
                )

        # Expected Delete
        elif exp_file.action == "delete":
            file_on_disk = (repo_root / norm_path).exists()
            if norm_path in changeset.deleted or not file_on_disk:
                findings.append(
                    Finding(
                        category=FindingCategory.MISSING_IMPLEMENTATION,
                        severity=FindingSeverity.PASS,
                        message=f"Expected file '{norm_path}' was deleted.",
                        file_path=norm_path,
                        expected="delete",
                        actual="deleted",
                        evidence="File removed relative to baseline commit",
                    )
                )
            else:
                findings.append(
                    Finding(
                        category=FindingCategory.MISSING_IMPLEMENTATION,
                        severity=FindingSeverity.ERROR,
                        message=f"Expected file '{norm_path}' was not deleted.",
                        file_path=norm_path,
                        expected="delete",
                        actual="still exists",
                        evidence="File still exists in working tree",
                    )
                )

    # 4. Scope Drift Verification (Unexpected Changed Files)
    for changed_file in sorted(changeset.all_changed_files):
        if changed_file in expected_file_paths:
            continue
        if _is_codealign_artifact(changed_file):
            continue
        if _is_plan_artifact(changed_file, baseline.intent.plan_file, repo_root):
            continue
        if _is_python_runtime_artifact(changed_file):
            continue
        findings.append(
            Finding(
                category=FindingCategory.SCOPE_DRIFT,
                severity=FindingSeverity.WARN,
                message=f"Unexpected file changed: '{changed_file}'.",
                file_path=changed_file,
                expected="unchanged",
                actual="changed in working tree",
                evidence=f"File '{changed_file}' was changed but not declared in baseline",
            )
        )

    # 5. Expected Tests Verification
    for exp_test in baseline.expectations.expected_tests:
        test_path = _normalize_path(exp_test.path)
        test_changed = test_path in changeset.all_changed_files or (repo_root / test_path).is_file()
        if test_changed:
            findings.append(
                Finding(
                    category=FindingCategory.TEST_DRIFT,
                    severity=FindingSeverity.PASS,
                    message=f"Expected test file '{test_path}' verified (created/modified).",
                    file_path=test_path,
                    expected="test modified or created",
                    actual="changed",
                    evidence=exp_test.reason or "Test file implementation verified",
                )
            )
        else:
            findings.append(
                Finding(
                    category=FindingCategory.TEST_DRIFT,
                    severity=FindingSeverity.ERROR,
                    message=f"Expected test file '{test_path}' was not implemented or modified.",
                    file_path=test_path,
                    expected="test modified or created",
                    actual="no test changes detected",
                    evidence=exp_test.reason or "Plan required test coverage",
                )
            )

    # 6. Expected Symbols Verification
    for exp_sym in baseline.expectations.expected_symbols:
        if exp_sym.status in ("unresolved", "new"):
            found_file = _find_created_symbol_in_repo(
                exp_sym=exp_sym,
                baseline=baseline,
                repo_root=repo_root,
            )
            if found_file:
                clean_name = exp_sym.name.replace("\\", "").rstrip("()") or exp_sym.name
                ident = clean_name.split(".")[-1].rstrip("()")
                findings.append(
                    Finding(
                        category=FindingCategory.MISSING_IMPLEMENTATION,
                        severity=FindingSeverity.PASS,
                        message=f"Expected symbol '{clean_name}' created in '{found_file}'.",
                        symbol=clean_name,
                        file_path=found_file,
                        expected="created",
                        actual="created in file",
                        evidence=f"Symbol identifier '{ident}' present in '{found_file}'",
                    )
                )
            else:
                findings.append(
                    Finding(
                        category=FindingCategory.UNRESOLVED_REFERENCE,
                        severity=FindingSeverity.WARN,
                        message=f"Baseline contains unresolved symbol reference: '{exp_sym.name}'.",
                        symbol=exp_sym.name,
                        file_path=exp_sym.file_path or None,
                        expected="unresolved",
                        actual="unconfirmed in codebase graph",
                        evidence=exp_sym.reason or "Symbol was unconfirmed at baseline time",
                    )
                )
        elif exp_sym.status == "existing" and exp_sym.file_path:
            sym_file = _normalize_path(exp_sym.file_path)
            target_path = repo_root / sym_file
            if not target_path.is_file():
                findings.append(
                    Finding(
                        category=FindingCategory.MISSING_IMPLEMENTATION,
                        severity=FindingSeverity.ERROR,
                        message=(
                            f"Expected symbol '{exp_sym.name}' missing: "
                            f"containing file '{sym_file}' not found."
                        ),
                        symbol=exp_sym.name,
                        file_path=sym_file,
                        expected="symbol exists in file",
                        actual="file missing",
                        evidence=f"File '{sym_file}' does not exist on disk",
                    )
                )
            else:
                # Check symbol presence in file
                ident = exp_sym.name.split(".")[-1].rstrip("()")
                content = target_path.read_text(encoding="utf-8", errors="ignore")
                if ident in content:
                    findings.append(
                        Finding(
                            category=FindingCategory.MISSING_IMPLEMENTATION,
                            severity=FindingSeverity.PASS,
                            message=f"Expected symbol '{exp_sym.name}' confirmed in '{sym_file}'.",
                            symbol=exp_sym.name,
                            file_path=sym_file,
                            expected="symbol exists",
                            actual="confirmed in file",
                            evidence=f"Symbol identifier '{ident}' present in '{sym_file}'",
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            category=FindingCategory.MISSING_IMPLEMENTATION,
                            severity=FindingSeverity.WARN,
                            message=(
                                f"Expected symbol '{exp_sym.name}' appears to have been "
                                f"removed from '{sym_file}'."
                            ),
                            symbol=exp_sym.name,
                            file_path=sym_file,
                            expected=f"symbol '{exp_sym.name}' present in file",
                            actual="symbol identifier not found",
                            evidence=f"Identifier '{ident}' not found in '{sym_file}' content",
                        )
                    )

    # 7. Symbol-Level Drift Verification (Unexpected Defined Symbols)
    if pre_snapshot is not None and post_snapshot is not None:
        expected_impl_paths = {
            _normalize_path(f.path)
            for f in baseline.expectations.expected_files
            if f.action != "delete"
        }
        expected_test_paths = {
            _normalize_path(t.path)
            for t in baseline.expectations.expected_tests
        }

        for changed_file in sorted(changeset.all_changed_files):
            # Only evaluate expected implementation files
            if changed_file not in expected_impl_paths:
                continue
            # Exclude test files
            if _is_test_path(changed_file) or changed_file in expected_test_paths:
                continue
            # Exclude workflow and runtime artifacts
            if _is_codealign_artifact(changed_file):
                continue
            if _is_plan_artifact(changed_file, baseline.intent.plan_file, repo_root):
                continue
            if _is_python_runtime_artifact(changed_file):
                continue

            pre_syms = pre_snapshot.file_symbols.get(changed_file, set())
            post_syms = post_snapshot.file_symbols.get(changed_file, set())

            introduced_syms = post_syms - pre_syms
            for sym_name in sorted(introduced_syms):
                # Only public symbols are candidates: ignore symbols beginning with "_"
                parts = sym_name.split(".")
                if any(p.startswith("_") for p in parts):
                    continue

                # Remove/ignore symbols explicitly expected by baseline
                if _is_symbol_expected(sym_name, changed_file, baseline):
                    continue

                findings.append(
                    Finding(
                        category=FindingCategory.ABSTRACTION_DRIFT,
                        severity=FindingSeverity.WARN,
                        message=f"Unexpected symbol '{sym_name}' introduced in '{changed_file}'.",
                        file_path=changed_file,
                        symbol=sym_name,
                        expected="unmodified symbol set",
                        actual=f"new symbol '{sym_name}' defined",
                        evidence=(
                            f"Symbol '{sym_name}' was not present in pre-session file "
                            f"and was not expected by the baseline."
                        ),
                    )
                )

    # 8. Behavioral Drift Verification (Signature and Body Changes in Existing Callables)
    if pre_snapshot is not None and post_snapshot is not None:
        expected_impl_paths = {
            _normalize_path(f.path)
            for f in baseline.expectations.expected_files
            if f.action != "delete"
        }
        expected_test_paths = {
            _normalize_path(t.path)
            for t in baseline.expectations.expected_tests
        }

        for changed_file in sorted(changeset.all_changed_files):
            # Only evaluate expected implementation files
            if changed_file not in expected_impl_paths:
                continue
            # Exclude test files
            if _is_test_path(changed_file) or changed_file in expected_test_paths:
                continue
            # Exclude workflow and runtime artifacts
            if _is_codealign_artifact(changed_file):
                continue
            if _is_plan_artifact(changed_file, baseline.intent.plan_file, repo_root):
                continue
            if _is_python_runtime_artifact(changed_file):
                continue

            parse_errors = getattr(post_snapshot, "parse_errors", {})
            if changed_file in parse_errors:
                parse_err = parse_errors[changed_file]
                findings.append(
                    Finding(
                        category=FindingCategory.MISSING_IMPLEMENTATION,
                        severity=FindingSeverity.ERROR,
                        message=f"Syntax error in '{changed_file}': {parse_err}.",
                        file_path=changed_file,
                        expected="valid Python syntax",
                        actual="syntax error",
                        evidence=parse_err,
                    )
                )
                continue

            if not changed_file.endswith(".py"):
                continue

            pre_fps_map = getattr(pre_snapshot, "symbol_fingerprints", {})
            post_fps_map = getattr(post_snapshot, "symbol_fingerprints", {})
            pre_fps = pre_fps_map.get(changed_file, {})
            post_fps = post_fps_map.get(changed_file, {})

            common_syms = sorted(set(pre_fps.keys()) & set(post_fps.keys()))
            for sym_name in common_syms:
                pre_fp = pre_fps[sym_name]
                post_fp = post_fps[sym_name]

                if pre_fp.sig_hash != post_fp.sig_hash:
                    findings.append(
                        Finding(
                            category=FindingCategory.BEHAVIORAL_DRIFT,
                            severity=FindingSeverity.WARN,
                            message=(
                                f"Signature of function '{sym_name}' was modified "
                                f"in '{changed_file}'."
                            ),
                            file_path=changed_file,
                            symbol=sym_name,
                            expected="unmodified function signature",
                            actual="modified signature",
                            evidence=(
                                f"Callable '{sym_name}' (line {post_fp.line}) signature hash "
                                f"changed from {pre_fp.sig_hash[:8]} to {post_fp.sig_hash[:8]}"
                            ),
                        )
                    )
                elif pre_fp.body_hash != post_fp.body_hash:
                    findings.append(
                        Finding(
                            category=FindingCategory.BEHAVIORAL_DRIFT,
                            severity=FindingSeverity.WARN,
                            message=(
                                f"Implementation body of function '{sym_name}' was modified "
                                f"in '{changed_file}' (signature preserved)."
                            ),
                            file_path=changed_file,
                            symbol=sym_name,
                            expected="unmodified function body",
                            actual="modified body implementation",
                            evidence=(
                                f"Callable '{sym_name}' (line {post_fp.line}) body hash "
                                f"changed from {pre_fp.body_hash[:8]} to {post_fp.body_hash[:8]}"
                            ),
                        )
                    )

    # 9. Constraints Verification
    for constraint in baseline.constraints:
        findings.append(
            Finding(
                category=FindingCategory.CONSTRAINT_VIOLATION,
                severity=FindingSeverity.WARN,
                message=(
                    f"Constraint cannot be machine-verified deterministically in v0: "
                    f"'{constraint}'."
                ),
                expected="constraint respected",
                actual="manual review required",
                evidence="Natural-language constraint requires human or rule-based verification",
            )
        )

    # 10. Sort findings deterministically (by severity rank, then category, then file_path)
    severity_order = {
        FindingSeverity.ERROR: 0,
        FindingSeverity.WARN: 1,
        FindingSeverity.INFO: 2,
        FindingSeverity.PASS: 3,
    }
    findings.sort(
        key=lambda f: (
            severity_order.get(f.severity, 99),
            f.category.value,
            f.file_path or "",
            f.message,
        )
    )

    # 10. Compute Overall Status and Summary
    failures_count = sum(1 for f in findings if f.severity == FindingSeverity.ERROR)
    warnings_count = sum(1 for f in findings if f.severity == FindingSeverity.WARN)
    passes_count = sum(1 for f in findings if f.severity == FindingSeverity.PASS)

    if failures_count > 0:
        overall_status = VerificationStatus.FAIL
    elif warnings_count > 0:
        overall_status = VerificationStatus.FAIL if strict else VerificationStatus.WARN
    else:
        overall_status = VerificationStatus.PASS

    pass_noun = "pass" if passes_count == 1 else "passes"
    warn_noun = "warning" if warnings_count == 1 else "warnings"
    fail_noun = "failure" if failures_count == 1 else "failures"
    summary = (
        f"{passes_count} {pass_noun}, {warnings_count} {warn_noun}, {failures_count} {fail_noun}"
    )

    return VerificationResult(
        status=overall_status,
        summary=summary,
        findings=findings,
    )
