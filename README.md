# CodeAlign

> **Keep implementations aligned with developer intent.**

CodeAlign is a standalone, open-source developer CLI that analyzes an implementation plan against your real codebase, generates an **Implementation Baseline**, and later verifies whether the actual implementation matches that baseline.

---

## The Problem

AI-assisted coding agents and human developers alike frequently introduce:
- **Scope drift:** Modifying unrelated files or creating unintended abstractions.
- **Architectural drift:** Violating architectural patterns, introducing forbidden dependencies, or ignoring existing conventions.
- **Missing implementation:** Skipping test coverage, error handling, or key requirements from the initial plan.
- **Premature / misaligned code:** Producing hallucinations or poorly grounded changes that look correct on the surface but drift from the codebase structure.

Existing tools often rely on subjective "AI-slop" detection or post-hoc heuristics. CodeAlign instead grounds verification in **concrete repository code intelligence, explicit developer intent, and Git diffs**.

---

## The Core Workflow

```text
Implementation Plan
        ↓
CodeAlign Baseline Analysis
        ↓
Implementation Baseline  ─── (Handoff Context) ───►  Coding Agent / Developer
                                                             ↓
                                                       Implementation
                                                             ↓
                                                    Git Changes / Diff
                                                             ↓
                                                     CodeAlign Verify
                                                             ↓
                                                   PASS / WARN / FAIL
                                                    (with Evidence)
```

1. **Intent & Analysis:** You provide an implementation plan. CodeAlign analyzes the target codebase using code intelligence (symbols, dependencies, callers, callees).
2. **Implementation Baseline:** CodeAlign creates a structured baseline (`.codealign/baseline.json`) defining expected files, expected symbols, relationships, constraints, and verification criteria.
3. **Agent Handoff:** The baseline serves as the **handoff contract and context** for coding agents (e.g., Claude Code, Cursor, Codex, OpenCode) to start implementation with clear boundaries.
4. **Deterministic Verification:** After changes are made, `codealign verify` inspects the Git changes against the baseline and codebase graph, producing deterministic, evidence-backed findings.

---

## Relationship with Graphify

CodeAlign uses [Graphify](https://github.com/...) as its initial code-intelligence engine for deep static code analysis (symbol resolution, call graphs, import graphs, and dependency tracking). 

- **Graphify** provides the code intelligence: repository structure, symbols, callers, callees, and dependencies.
- **CodeAlign** owns developer intent, the implementation baseline contract, expected impact, change verification, and agent feedback.
- CodeAlign accesses code intelligence through an abstract `CodeIntelligenceProvider` interface, allowing pluggable engines in the future without coupling the application to specific analyzer internals.

---

## What CodeAlign Is NOT

- **Not an AI coding agent:** CodeAlign does not write your application code. The coding agent or human engineer implements the solution.
- **Not an AI-slop detector:** CodeAlign provides deterministic verification grounded in code graphs and developer intent, not subjective LLM scoring.
- **Not an automatic planner:** The developer remains in control of engineering decisions and implementation plans.

---

## Status & Roadmap

> [!NOTE]
> CodeAlign is currently in active pre-alpha development (bootstrap phase).

| Command | Description | Status |
| :--- | :--- | :--- |
| `codealign init` | Initialize `.codealign/` state and extract code intelligence | **Available** |
| `codealign analyze` | Resolve plan references against repository code intelligence | **Available** |
| `codealign baseline` | Generate the Implementation Baseline contract (`baseline.json`) | **Available** |
| `codealign context` | Export agent-consumable Markdown implementation context (`context.md`) | **Available** |
| `codealign verify` | Verify Git changes against the baseline and code graph | Planned |
| `codealign status` | View baseline and verification status | Planned |
| `codealign explain` | Explain findings and provide evidence-backed guidance | Planned |

---

## Installation & Quickstart

### Prerequisites

- Python 3.12+
- Git
- [Graphify](https://github.com/Graphify-Labs/graphify) (`pip install graphifyy`)

### Installation

```bash
# Clone the repository
git clone https://github.com/hopstreax/CodeAlign.git
cd CodeAlign

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Or on Windows: .\.venv\Scripts\Activate.ps1

# Install in editable mode
pip install -e ".[dev]"
```

### Basic CLI Workflow

The core alignment workflow progresses in three deliberate stages:

```text
codealign analyze <plan.md>   →  Resolve plan references against repository evidence
codealign baseline <plan.md>  →  Produce canonical implementation contract (.codealign/baseline.json)
codealign context             →  Export concise, agent-consumable context (.codealign/context.md)
```

- **`baseline` is the canonical implementation contract:** It locks plan intent, repository identity (branch, commit), resolved/unresolved repository evidence, and explicit expectations into a machine-readable, deterministic schema.
- **`context` packages that baseline for an implementation agent:** It transforms the baseline into concise, structured Markdown (`.codealign/context.md` or stdout) containing the intent, expected files, symbols, tests, evidence (callers, callees, relationships), and constraints.
- **`context` does NOT perform new analysis:** It does not rerun Graphify, does not query LLMs, does not re-analyze the repository, and does not invent implementation steps or make engineering decisions.
- **The coding agent remains responsible for implementation:** The context provides grounded boundaries, leaving actual coding and design execution to the agent.

```bash
codealign --help

# 1. Initialize CodeAlign and extract code intelligence
codealign init

# 2. Analyze an implementation plan against the codebase
codealign analyze plan.md

# 3. Output structured evidence in JSON
codealign analyze plan.md --format json

# 4. Generate the canonical Implementation Baseline contract (.codealign/baseline.json)
codealign baseline plan.md

# 5. Output baseline contract in JSON
codealign baseline plan.md --format json

# 6. Export agent-consumable implementation context (.codealign/context.md)
codealign context

# 7. Print implementation context directly to stdout (for piping into agent prompts)
codealign context --stdout
```

---

## License

This project is licensed under the [MIT License](LICENSE).
