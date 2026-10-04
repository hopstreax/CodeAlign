# Contributing to CodeAlign

Thank you for your interest in contributing to **CodeAlign**!

CodeAlign is an open-source developer tool designed to keep software implementations aligned with developer intent.

## Development Principles

When contributing to CodeAlign, please keep our core engineering principles in mind:

1. **Understand architecture before writing code.**
2. **Keep the MVP small.** Prefer a small working vertical slice over speculative abstractions.
3. **Deterministic verification first.** Prefer deterministic repository analysis and graph-backed verification over vague AI judgments. Evidence is always more important than arbitrary scores.
4. **Graphify provider isolation.** Keep code intelligence behind clean provider abstractions (`CodeIntelligenceProvider`).
5. **CodeAlign is not an AI coding agent.** CodeAlign defines intent, expected impact, constraints, and verification; coding agents or humans implement the changes.
6. **Developer agency.** The developer remains responsible for implementation plans and engineering decisions.

## Setting Up Your Development Environment

### Prerequisites

- Python 3.12 or newer
- Git

### Setup Steps

1. Clone the repository:
   ```bash
   git clone https://github.com/your-org/CodeAlign.git
   cd CodeAlign
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   # On Windows (PowerShell):
   .\.venv\Scripts\Activate.ps1
   # On Linux/macOS:
   source .venv/bin/activate
   ```

3. Install CodeAlign in editable mode with development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

4. Verify your installation:
   ```bash
   codealign --help
   pytest
   ```

## Development Workflow

- Run tests: `pytest`
- Format and lint code: `ruff check src tests` and `ruff format src tests`

## Pull Request Guidelines

- Ensure all existing tests pass and add unit tests for new functionality.
- Keep PRs focused on a single change or feature.
- Follow PEP 8 and modern Python practices (type annotations, clear docstrings).
