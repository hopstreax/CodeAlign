"""Command: codealign verify"""

from enum import Enum
from pathlib import Path

import typer

from codealign.config import get_codealign_dir
from codealign.git.repository import GitError, NotAGitRepositoryError, get_git_repo_info
from codealign.models.baseline import ImplementationBaseline
from codealign.models.finding import FindingSeverity
from codealign.models.result import VerificationStatus
from codealign.verify.verifier import verify_implementation


class OutputFormat(str, Enum):
    """Output format for verification results."""

    TERMINAL = "terminal"
    JSON = "json"


def verify_command(
    baseline: Path | None = typer.Option(
        None,
        "--baseline",
        "-b",
        help="Path to baseline file (defaults to .codealign/baseline.json).",
    ),
    format: OutputFormat = typer.Option(
        OutputFormat.TERMINAL,
        "--format",
        "-f",
        help="Output format: 'terminal' (human-readable) or 'json' (machine/agent-readable).",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Treat warnings as verification failures.",
    ),
) -> None:
    """Verify actual code changes against the implementation baseline and repository state."""
    # 1. Locate repository root and .codealign state
    try:
        repo_info = get_git_repo_info()
    except (NotAGitRepositoryError, GitError) as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    codealign_dir = get_codealign_dir(repo_info.root)
    if not codealign_dir.is_dir():
        typer.secho(
            f"Error: CodeAlign is not initialized in '{repo_info.root}'.\n"
            "Run 'codealign init' first to initialize CodeAlign.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    # 2. Locate baseline file
    baseline_path = baseline if baseline is not None else (codealign_dir / "baseline.json")
    if not baseline_path.is_file():
        typer.secho(
            f"Error: Baseline contract not found at '{baseline_path}'.\n"
            "Run 'codealign baseline <plan.md>' first to generate the implementation baseline.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    # 3. Load baseline contract
    try:
        bl = ImplementationBaseline.from_file(baseline_path)
    except Exception as exc:
        typer.secho(f"Error loading baseline file: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    # 4. Execute verification
    result = verify_implementation(
        baseline=bl,
        repo_root=repo_info.root,
        repo_info=repo_info,
        strict=strict,
    )

    # 5. Output handling
    if format == OutputFormat.JSON:
        typer.echo(result.to_json())
    else:
        lines: list[str] = []
        lines.append("CODEALIGN VERIFICATION\n")
        repo_desc = (
            f"{bl.repository.name} (branch: {bl.repository.branch}, "
            f"baseline commit: {bl.repository.commit})"
        )
        lines.append(f"Repository:\n  {repo_desc}\n")

        status_label = result.status.value.upper()
        lines.append(f"Result:\n  {status_label}\n")

        # Group findings: failures, warnings, passes
        errors = [f for f in result.findings if f.severity == FindingSeverity.ERROR]
        warnings = [f for f in result.findings if f.severity == FindingSeverity.WARN]
        passes = [f for f in result.findings if f.severity == FindingSeverity.PASS]

        if passes:
            lines.append("PASS:")
            for p in passes:
                lines.append(f"  [OK] {p.message}")
            lines.append("")

        if warnings:
            lines.append("WARN:")
            for w in warnings:
                lines.append(f"  [!] {w.message}")
            lines.append("")

        if errors:
            lines.append("FAIL:")
            for e in errors:
                lines.append(f"  [X] {e.message}")
            lines.append("")

        lines.append(f"Summary:\n  {result.summary}")
        typer.echo("\n".join(lines).strip())

    # 6. Exit code
    if result.status == VerificationStatus.FAIL:
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)
