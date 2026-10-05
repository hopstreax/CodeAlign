"""Command: codealign context"""

from pathlib import Path

import typer

from codealign.config import get_codealign_dir
from codealign.git.repository import GitError, NotAGitRepositoryError, get_git_repo_info
from codealign.handoff import BaselineNotFoundError, prepare_agent_handoff


def context_command(
    baseline: Path | None = typer.Option(
        None,
        "--baseline",
        "-b",
        help="Path to baseline file (defaults to .codealign/baseline.json).",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Target file path for context artifact (defaults to .codealign/context.md).",
    ),
    stdout: bool = typer.Option(
        False,
        "--stdout",
        help="Print the generated context Markdown directly to standard output.",
    ),
) -> None:
    """Export implementation baseline as concise, agent-consumable Markdown context."""
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

    # 2. Prepare handoff payload using canonical handoff contract
    try:
        handoff = prepare_agent_handoff(repo_info.root, baseline_path=baseline)
    except BaselineNotFoundError as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except Exception as exc:
        typer.secho(f"Error loading baseline file: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    bl = handoff.baseline
    context_md = handoff.context_markdown

    # 5. Determine target output path and write artifact
    target_output = output if output is not None else (codealign_dir / "context.md")
    try:
        target_output.parent.mkdir(parents=True, exist_ok=True)
        target_output.write_text(context_md, encoding="utf-8")
    except Exception as exc:
        typer.secho(f"Error writing context artifact: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    # 6. Output handling
    if stdout:
        typer.echo(context_md, nl=False)
    else:
        try:
            rel_output = target_output.relative_to(repo_info.root).as_posix()
        except ValueError:
            rel_output = str(target_output)

        lines: list[str] = []
        lines.append("CONTEXT GENERATED\n")
        lines.append(f"Plan:\n  {bl.intent.title}\n")
        repo_desc = (
            f"{bl.repository.name} (branch: {bl.repository.branch}, commit: {bl.repository.commit})"
        )
        lines.append(f"Repository:\n  {repo_desc}\n")
        lines.append("Expected files:")
        if bl.expectations.expected_files:
            for f in bl.expectations.expected_files:
                if f.status == "unresolved":
                    lines.append(f"  {f.path} (unresolved)")
                else:
                    lines.append(f"  {f.path}")
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append(f"Output:\n  {rel_output}")
        typer.echo("\n".join(lines).strip())
