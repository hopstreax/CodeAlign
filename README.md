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
| `codealign verify` | Verify actual code changes against baseline contract and Git state | **Available** |
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

The core alignment workflow progresses in four deliberate stages:

```text
codealign analyze <plan.md>   →  Resolve plan references against repository evidence
codealign baseline <plan.md>  →  Produce canonical implementation contract (.codealign/baseline.json)
codealign context             →  Export concise, agent-consumable context (.codealign/context.md)
codealign verify              →  Verify Git changes against the baseline contract
```

- **`baseline` is the canonical implementation contract:** It locks plan intent, repository identity (branch, commit), resolved/unresolved repository evidence, and explicit expectations into a machine-readable, deterministic schema.
- **`context` packages that baseline for an implementation agent:** It transforms the baseline into concise, structured Markdown (`.codealign/context.md` or stdout) containing the intent, expected files, symbols, tests, evidence (callers, callees, relationships), and constraints.
- **`verify` checks actual implementation against developer intent:** It compares actual Git changes (modified, created, deleted, and untracked files) against baseline expectations, producing deterministic evidence without using an LLM.

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

# 8. Verify implementation changes against the baseline
codealign verify

# 9. Verify in strict mode (fails on warnings)
codealign verify --strict

# 10. Output machine-readable verification findings in JSON
codealign verify --format json
```

### Agent Handoff Boundary

CodeAlign is strictly agent-agnostic. It does not embed an LLM or execute proprietary coding agents. Instead, it provides a clean, trusted boundary for any external agent or developer:

1. **File Handoff (Workspace & IDE Agents):**
   Workspace agents (such as Claude Code, Cursor Composer, or OpenCode) directly consume the generated context file:
   ```bash
   # In Cursor Composer or chat:
   @.codealign/context.md

   # In Claude Code:
   claude "Implement the task described in .codealign/context.md"
   ```

2. **Stream Handoff (Unix Pipelines & CLI Tools):**
   Pipe deterministic context directly into stdin:
   ```bash
   codealign context --stdout | my-coding-agent
   ```

3. **Programmatic Python API:**
   External tools or harnesses can consume the canonical handoff contract directly:
   ```python
   from codealign.handoff import prepare_agent_handoff

   handoff = prepare_agent_handoff(repo_root)
   print(handoff.intent.goal)
   print(handoff.context_markdown)
   ```

> **Division of Responsibility:** CodeAlign provides codebase-aware implementation context and constraints grounded in repository code intelligence. The external implementation agent remains solely responsible for reading source code, designing algorithms, writing code, and running tests.

---

## Verification Semantics (`codealign verify`)

`codealign verify` validates the actual implementation state against the trusted baseline contract:

- **Repository Binding:** Confirms the repository name and ensures the baseline commit exists in Git history.
- **Expected File Changes:**
  - `modify`: Verifies that the expected file was modified relative to the baseline commit (`FAIL` if unchanged or deleted).
  - `create`: Verifies that the file exists and is newly introduced (`FAIL` if missing).
  - `unresolved`: Preserves uncertainty as a warning (`WARN`); does not guess developer intent.
- **Scope Drift:** Identifies unexpected modified or added files outside baseline expectations (`WARN`).
- **Expected Tests:** Confirms whether planned test files were created or modified (`FAIL` if missing).
- **Expected Symbols:** Confirms presence of target symbols in modified files.
- **Constraints:** Preserves natural-language constraints as items requiring manual review (`WARN`).

### Exit Code Rules

- **`0`**: Verification passed (`PASS`), or passed with warnings (`WARN` in standard mode).
- **`1`**: Verification failed (`FAIL`), or warnings encountered when `--strict` is enabled.



---

## License

This project is licensed under the [MIT License](LICENSE).
