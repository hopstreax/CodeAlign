"""Tests for CodeAlign CLI application."""

import pytest
from typer.testing import CliRunner

from codealign.cli import app

runner = CliRunner()


def test_cli_help() -> None:
    """Verify codealign --help displays description and all top-level commands."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "CodeAlign: Keep implementations aligned with developer intent." in result.stdout

    expected_commands = [
        "init",
        "analyze",
        "baseline",
        "verify",
        "status",
        "context",
        "explain",
    ]
    for cmd in expected_commands:
        assert cmd in result.stdout


def test_cli_version() -> None:
    """Verify codealign --version shows the current package version."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "CodeAlign version" in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        "init",
        "analyze",
        "baseline",
        "verify",
        "status",
        "context",
        "explain",
    ],
)
def test_subcommand_help(command: str) -> None:
    """Verify each subcommand displays its own help message."""
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0
    assert f"Usage: codealign {command}" in result.stdout or f"{command} [OPTIONS]" in result.stdout


def test_subcommand_placeholders() -> None:
    """Verify subcommands run without unhandled errors as initial placeholders."""
    result_init = runner.invoke(app, ["init"])
    assert result_init.exit_code == 0
    assert "CodeAlign init" in result_init.stdout

    result_analyze = runner.invoke(app, ["analyze"])
    assert result_analyze.exit_code == 0
    assert "CodeAlign analyze" in result_analyze.stdout

    result_baseline = runner.invoke(app, ["baseline"])
    assert result_baseline.exit_code == 0
    assert "CodeAlign baseline" in result_baseline.stdout

    result_verify_term = runner.invoke(app, ["verify"])
    assert result_verify_term.exit_code == 0
    assert "CodeAlign verify" in result_verify_term.stdout

    result_verify_json = runner.invoke(app, ["verify", "--format", "json"])
    assert result_verify_json.exit_code == 0
    assert '"status":' in result_verify_json.stdout

    result_status = runner.invoke(app, ["status"])
    assert result_status.exit_code == 0
    assert "CodeAlign status" in result_status.stdout

    result_context_json = runner.invoke(app, ["context", "--format", "json"])
    assert result_context_json.exit_code == 0
    assert '"baseline":' in result_context_json.stdout

    result_explain = runner.invoke(app, ["explain"])
    assert result_explain.exit_code == 0
    assert "CodeAlign explain" in result_explain.stdout
