"""Command: codealign implement"""

import json
from enum import Enum
from pathlib import Path

import typer

from codealign.agent import GeminiAgent, GeminiExecutionError
from codealign.config import get_codealign_dir
from codealign.git.repository import GitError, NotAGitRepositoryError, get_git_repo_info
from codealign.models.baseline import ImplementationBaseline
from codealign.models.finding import FindingSeverity
from codealign.models.result import VerificationResult, VerificationStatus
from codealign.verify.verifier import verify_implementation


class OutputFormat(str, Enum):
    """Output format for implement command results."""

    TERMINAL = "terminal"
    JSON = "json"


def _format_verification_terminal(result: VerificationResult, bl: ImplementationBaseline) -> str:
    """Format verification outcome for human-readable terminal display."""
    lines: list[str] = []
    lines.append("CODEALIGN VERIFICATION\n")
    repo_desc = (
        f"{bl.repository.name} (branch: {bl.repository.branch}, "
        f"baseline commit: {bl.repository.commit})"
    )
    lines.append(f"Repository:\n  {repo_desc}\n")

    status_label = result.status.value.upper()
    lines.append(f"Result:\n  {status_label}\n")

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
    return "\n".join(lines).strip()


def implement_command(
    agent: str = typer.Option(
        "gemini",
        "--agent",
        "-a",
        help="Coding agent to invoke (currently supported: 'gemini').",
    ),
    baseline: Path | None = typer.Option(
        None,
        "--baseline",
        "-b",
        help="Path to baseline file (defaults to .codealign/baseline.json).",
    ),
    context: Path | None = typer.Option(
        None,
        "--context",
        "-c",
        help="Path to context file (defaults to .codealign/context.md).",
    ),
    approval_mode: str = typer.Option(
        "auto_edit",
        "--approval-mode",
        help="Gemini approval mode ('auto_edit', 'yolo', 'default', 'plan').",
    ),
    yolo: bool = typer.Option(
        False,
        "--yolo",
        help="Run Gemini in YOLO mode (auto-approve all actions).",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Gemini model to use.",
    ),
    format: OutputFormat = typer.Option(
        OutputFormat.TERMINAL,
        "--format",
        "-f",
        help="Output format: 'terminal' (human-readable) or 'json' (machine-readable).",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Treat warnings as verification failures.",
    ),
) -> None:
    """Hand off implementation baseline to Gemini CLI and verify resulting changes."""
    # 1. Confirm inside a Git repository
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

    # 2. Check supported agent
    if agent.lower() != "gemini":
        typer.secho(
            f"Error: Unsupported agent '{agent}'. Currently supported: 'gemini'.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    # 3. Locate baseline contract
    baseline_path = baseline if baseline is not None else (codealign_dir / "baseline.json")
    if not baseline_path.is_file():
        typer.secho(
            f"Error: Baseline contract not found at '{baseline_path}'.\n"
            "Run 'codealign baseline <plan.md>' first to generate the implementation baseline.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    # 4. Locate context file
    context_path = context if context is not None else (codealign_dir / "context.md")
    if not context_path.is_file():
        typer.secho(
            f"Error: Implementation context artifact not found at '{context_path}'.\n"
            "Run 'codealign context' first to generate the implementation context.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    # Load baseline
    try:
        bl = ImplementationBaseline.from_file(baseline_path)
    except Exception as exc:
        typer.secho(f"Error loading baseline file: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    # Load context markdown
    try:
        context_markdown = context_path.read_text(encoding="utf-8")
    except Exception as exc:
        typer.secho(f"Error loading context file: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    # 5. Confirm that Gemini CLI is available on PATH
    if not GeminiAgent.is_available():
        typer.secho(
            "Error: Gemini CLI ('gemini') not found on PATH.\n"
            "Please install and authenticate Gemini CLI before running 'codealign implement'.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    # 6. Invoke Gemini CLI
    if format == OutputFormat.TERMINAL:
        typer.echo(f"Invoking Gemini CLI to implement changes for '{bl.intent.title}'...")

    agent_runner = GeminiAgent()
    try:
        gemini_result = agent_runner.run(
            context_markdown=context_markdown,
            cwd=repo_info.root,
            approval_mode=approval_mode,
            yolo=yolo,
            model=model,
        )
    except GeminiExecutionError as exc:
        typer.secho(f"Error executing Gemini CLI: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    # Handle Gemini failure
    if not gemini_result.success:
        if format == OutputFormat.JSON:
            payload = {
                "agent": "gemini",
                "implementation": gemini_result.to_dict(),
                "verification": None,
            }
            typer.echo(json.dumps(payload, indent=2))
        else:
            lines = [
                "GEMINI IMPLEMENTATION",
                "=====================",
                "Agent: gemini",
                f"Status: FAILED (exit code {gemini_result.exit_code})",
            ]
            if gemini_result.stderr:
                lines.append(f"\nError Output:\n{gemini_result.stderr.strip()}")
            elif gemini_result.stdout:
                lines.append(f"\nOutput:\n{gemini_result.stdout.strip()}")
            typer.echo("\n".join(lines).strip())
        raise typer.Exit(code=1)

    # 7. Run CodeAlign verification
    if format == OutputFormat.TERMINAL:
        typer.echo("Gemini implementation completed. Running CodeAlign verification...\n")

    verification_result = verify_implementation(
        baseline=bl,
        repo_root=repo_info.root,
        repo_info=repo_info,
        strict=strict,
    )

    # 8. Report both results
    if format == OutputFormat.JSON:
        payload = {
            "agent": "gemini",
            "implementation": gemini_result.to_dict(),
            "verification": verification_result.to_dict(),
        }
        typer.echo(json.dumps(payload, indent=2))
    else:
        report_sections: list[str] = []

        # Gemini implementation section
        gemini_section = [
            "GEMINI IMPLEMENTATION",
            "=====================",
            "Agent: gemini",
            "Status: SUCCESS (exit code 0)",
        ]
        if gemini_result.stdout.strip():
            gemini_section.append(f"\nOutput:\n{gemini_result.stdout.strip()}")
        report_sections.append("\n".join(gemini_section))

        # Verification section
        verify_str = _format_verification_terminal(verification_result, bl)
        report_sections.append(verify_str)

        typer.echo("\n\n".join(report_sections))

    # Exit code based on verification outcome
    if verification_result.status == VerificationStatus.FAIL:
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)
