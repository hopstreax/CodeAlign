"""Command: codealign status"""

from pathlib import Path

import typer

from codealign.config import get_codealign_dir
from codealign.git.repository import GitError, NotAGitRepositoryError, get_git_repo_info
from codealign.models.baseline import ImplementationBaseline
from codealign.models.finding import FindingCategory, FindingSeverity
from codealign.verify.git_diff import BaseCommitNotFoundError, get_git_changes
from codealign.verify.verifier import verify_implementation


def status_command(
    baseline: Path | None = typer.Option(
        None,
        "--baseline",
        "-b",
        help="Path to baseline file (defaults to .codealign/baseline.json).",
    ),
) -> None:
    """Show current status of the implementation baseline and verification findings."""
    # 1. Discover Git repository
    try:
        repo_info = get_git_repo_info()
    except NotAGitRepositoryError:
        typer.secho(
            "Error: Current directory is not inside a Git repository.\n"
            "CodeAlign requires a Git repository.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    except GitError as exc:
        typer.secho(f"Git error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    # 2. Check CodeAlign initialization
    codealign_dir = get_codealign_dir(repo_info.root)
    if not codealign_dir.is_dir():
        typer.secho(
            f"Error: CodeAlign is not initialized in '{repo_info.root}'.\n"
            "Run 'codealign init' first to initialize CodeAlign.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    # 3. Locate baseline file
    baseline_path = baseline if baseline is not None else (codealign_dir / "baseline.json")
    if not baseline_path.is_file():
        typer.secho(
            f"Error: Baseline contract not found at '{baseline_path}'.\n"
            "Run 'codealign baseline <plan.md>' first to generate the implementation baseline.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    # 4. Load baseline contract
    try:
        bl = ImplementationBaseline.from_file(baseline_path)
    except Exception as exc:
        typer.secho(
            f"Error loading baseline file at '{baseline_path}':\n  {exc}\n"
            "Verify that the file contains valid JSON matching the CodeAlign baseline schema.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    # 5. Extract Git changes relative to baseline commit
    try:
        changeset = get_git_changes(repo_info.root, bl.repository.commit)
    except BaseCommitNotFoundError as exc:
        typer.secho(
            f"Error: {exc}\n"
            "The baseline commit is not present in the current Git history "
            "(it may have been rebased or squashed).\n"
            "Check your branch history or create a new baseline with "
            "'codealign baseline <plan.md>'.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    except GitError as exc:
        typer.secho(f"Git error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    # 6. Execute fresh verification against current working tree
    verification_result = verify_implementation(
        baseline=bl,
        repo_root=repo_info.root,
        repo_info=repo_info,
        changeset=changeset,
    )

    # 7. Format status report
    lines: list[str] = []
    lines.append("CODEALIGN STATUS")
    lines.append("================")

    # Repository section
    lines.append("\nRepository:")
    lines.append(f"  Name:          {repo_info.root.name}")
    branch_note = ""
    if bl.repository.branch and repo_info.branch != bl.repository.branch:
        branch_note = f" (baseline branch: {bl.repository.branch})"
    lines.append(f"  Branch:        {repo_info.branch}{branch_note}")
    commit_note = ""
    if bl.repository.commit and repo_info.head_sha != bl.repository.commit:
        commit_note = f" (baseline commit: {bl.repository.commit[:7]})"
    lines.append(f"  HEAD:          {repo_info.head_sha[:7]}{commit_note}")
    wt_status = "dirty (uncommitted changes present)" if repo_info.is_dirty else "clean"
    lines.append(f"  Working tree:  {wt_status}")

    # Active Baseline section
    lines.append("\nActive Baseline:")
    plan_info = bl.intent.title or "Untitled"
    if bl.intent.plan_file:
        plan_info += f" ({bl.intent.plan_file})"
    lines.append(f"  Plan:          {plan_info}")
    lines.append(f"  Created:       {bl.generated_at} (schema: {bl.schema_version})")
    lines.append(
        f"  Evidence:      {len(bl.evidence.resolved)} resolved, "
        f"{len(bl.evidence.unresolved)} unresolved"
    )
    lines.append(
        f"  Expectations:  {len(bl.expectations.expected_files)} files, "
        f"{len(bl.expectations.expected_tests)} tests, "
        f"{len(bl.expectations.expected_symbols)} symbols, "
        f"{len(bl.constraints)} constraints"
    )

    # Changes Since Baseline section
    lines.append("\nChanges Since Baseline:")
    lines.append(
        f"  Files:         {len(changeset.modified)} modified, "
        f"{len(changeset.added)} added, "
        f"{len(changeset.deleted)} deleted, "
        f"{len(changeset.renamed)} renamed"
    )

    scope_drift_findings = [
        f for f in verification_result.findings if f.category == FindingCategory.SCOPE_DRIFT
    ]
    if scope_drift_findings:
        lines.append(f"  Scope drift:   {len(scope_drift_findings)} unexpected file(s)")
        for sf in scope_drift_findings:
            if sf.file_path:
                lines.append(f"    [!] {sf.file_path}")
    else:
        lines.append("  Scope drift:   clean (0 unexpected files)")

    # Fresh Verification section
    lines.append("\nFresh Verification (Current Working Tree):")
    status_label = verification_result.status.value.upper()
    lines.append(f"  Status:        {status_label}")
    lines.append(
        f"  Findings:      {len(verification_result.passes)} passed, "
        f"{len(verification_result.warnings)} warnings, "
        f"{len(verification_result.failures)} failures"
    )
    if verification_result.summary:
        lines.append(f"  Summary:       {verification_result.summary}")

    errors = [f for f in verification_result.findings if f.severity == FindingSeverity.ERROR]
    warnings = [f for f in verification_result.findings if f.severity == FindingSeverity.WARN]

    if errors:
        lines.append("\n  Failures:")
        for e in errors:
            lines.append(f"    [X] {e.message}")

    if warnings:
        lines.append("\n  Warnings:")
        for w in warnings:
            lines.append(f"    [!] {w.message}")

    # Note regarding session vs standalone
    lines.append(
        "\nNote: Standalone status reflects fresh verification of the current working tree against "
        "the baseline commit.\nIt does not have the pre/post session snapshots available during "
        "'codealign implement'."
    )

    typer.echo("\n".join(lines).strip())
    raise typer.Exit(code=0)
