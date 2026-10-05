"""Core implementation verification engine for CodeAlign."""

from pathlib import Path

from codealign.git.repository import GitRepoInfo
from codealign.models.baseline import ImplementationBaseline
from codealign.models.finding import Finding, FindingCategory, FindingSeverity
from codealign.models.result import VerificationResult, VerificationStatus
from codealign.verify.git_diff import BaseCommitNotFoundError, GitChangeSet, get_git_changes


def _normalize_path(p: str) -> str:
    """Normalize file path to forward slashes."""
    return p.strip().replace("\\", "/").lstrip("./")


def verify_implementation(
    baseline: ImplementationBaseline,
    repo_root: Path,
    repo_info: GitRepoInfo | None = None,
    strict: bool = False,
) -> VerificationResult:
    """Verify actual repository changes against the ImplementationBaseline contract.

    Args:
        baseline: The canonical ImplementationBaseline contract.
        repo_root: Path to repository root directory.
        repo_info: Optional GitRepoInfo for active repository.
        strict: If True, treat any warnings as verification failure.

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
    changeset: GitChangeSet
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
        if changed_file not in expected_file_paths:
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
        if exp_sym.status == "unresolved":
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

    # 7. Constraints Verification
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

    # 8. Sort findings deterministically (by severity rank, then category, then file_path)
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

    # 9. Compute Overall Status and Summary
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
