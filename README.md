# CodeAlign

> **Keep implementations aligned with developer intent.**

CodeAlign is a standalone, open-source developer CLI that analyzes an implementation plan against your real codebase, generates an **Implementation Baseline**, hands off context to coding agents, and deterministically verifies whether the actual implementation matches that baseline.

---

## The Problem

AI-assisted coding agents and human developers frequently introduce:
- **Scope drift:** Modifying unrelated files or creating unintended abstractions.
- **Architectural drift:** Violating architectural patterns, introducing forbidden dependencies, or ignoring existing conventions.
- **Missing implementation:** Skipping test coverage, error handling, or key requirements from the initial plan.
- **Premature / misaligned code:** Producing hallucinations or poorly grounded changes that look correct on the surface but drift from codebase structure.

Existing tools often rely on subjective "AI-slop" detection or post-hoc heuristics. CodeAlign instead grounds verification in **concrete repository code intelligence, explicit developer intent, and Git diffs**.

---

## The Core Workflow

```text
Implementation Plan
        ↓
codealign init / analyze
        ↓
codealign baseline ─── (Canonical Contract) ───► baseline.json
        ↓
codealign context  ─── (Handoff Context)    ───► context.md
        ↓
codealign implement (Gemini / Antigravity)  OR  Manual / External Agent
        ↓                                                    ↓
Session Changeset / Post-Agent Snapshot             Git Working Tree Changes
        ↓                                                    ↓
Session-Aware Verification                          codealign verify
        ↓                                                    ↓
                  PASS / WARN / FAIL (with Evidence)
```

1. **Repository Setup & Code Intelligence:** `codealign init` discovers the Git repository and invokes [Graphify](https://github.com/Graphify-Labs/graphify) to extract AST symbols, dependencies, callers, and callees into `.codealign/graphify-out/graph.json`.
2. **Intent Analysis:** `codealign analyze <plan.md>` resolves planned file modifications, additions, symbols, and test references against the repository's code graph.
3. **Canonical Baseline Contract:** `codealign baseline <plan.md>` locks developer intent, repository identity (branch, commit), resolved evidence, and explicit expectations into `.codealign/baseline.json`.
4. **Agent Context Generation:** `codealign context` transforms the baseline into concise, agent-consumable Markdown (`.codealign/context.md` or stdout) containing explicit boundaries, expected files, symbols, test paths, and constraints.
5. **Agent Handoff & Orchestration:** `codealign implement` invokes an external coding agent CLI ([Gemini CLI](https://github.com/google-gemini/gemini-cli) or Antigravity CLI) with the generated context in an isolated process tree with configurable timeouts.
6. **Deterministic Verification:**
   - **Session-aware verification** (during `codealign implement`) verifies only the files and lines modified during the agent's run against baseline expectations, ignoring pre-existing dirty changes.
   - **Standalone verification** (`codealign verify`) evaluates all current working tree changes against the baseline commit.

---

## Relationship with Graphify

CodeAlign uses [Graphify](https://github.com/Graphify-Labs/graphify) as its code-intelligence engine for static code analysis (symbol resolution, call graphs, import graphs, and dependency tracking):

- **Graphify** extracts the code intelligence: repository structure, symbols, callers, callees, and dependencies into `.codealign/graphify-out/graph.json`.
- **CodeAlign** owns developer intent, the implementation baseline contract, expected impact, agent orchestration, and change verification.
- **Prerequisite & Fallback Behavior:** Graphify is distributed as the PyPI package `graphifyy` (`pip install graphifyy`). If `graphify` is not found on `PATH`:
  - `codealign init` will warn that Graphify is unavailable and skip graph extraction (or you can pass `--skip-graphify`).
  - `codealign analyze` and `codealign baseline` require code intelligence; if the graph has not been generated, they will exit with an error instructing you to install Graphify and run `codealign init --force`.

---

## What CodeAlign Is NOT

- **Not an autonomous code writer:** CodeAlign does not synthesize or write code itself. It delegates code generation to external coding agents (Gemini CLI, Antigravity CLI, Claude, Cursor) or human developers.
- **Not an LLM-based grader or slop detector:** Verification is completely deterministic, comparing concrete Git diffs, modified files, created files, symbols, and tests against baseline expectations without using an LLM.
- **Not an automatic planner:** The developer remains in control of architectural intent and provides the initial plan.

---

## Status & Command Reference

> [!NOTE]
> CodeAlign is in active pre-alpha development.

| Command | Description | Status |
| :--- | :--- | :--- |
| `codealign init` | Initialize repository state (`.codealign/`) and run Graphify extraction | **Available** |
| `codealign analyze` | Resolve plan references against repository code intelligence | **Available** |
| `codealign baseline` | Generate canonical Implementation Baseline contract (`.codealign/baseline.json`) | **Available** |
| `codealign context` | Export agent-consumable Markdown context (`.codealign/context.md`) | **Available** |
| `codealign implement` | Hand off baseline context to a coding agent CLI and verify resulting session changes | **Available** |
| `codealign verify` | Verify actual repository working tree changes against baseline contract | **Available** |
| `codealign status` | View baseline contract metadata, changes since baseline, and fresh verification | **Available** |
| `codealign explain` | Explain findings and provide evidence-backed guidance (preview placeholder) | **Preview (Placeholder)** |

---

## Installation & Prerequisites

### Prerequisites

- **Python 3.12+**
- **Git** (installed and available on `PATH`)
- **[Graphify](https://github.com/Graphify-Labs/graphify)** (`pip install graphifyy`)
- **Coding Agent CLI** (optional, required only for `codealign implement`):
  - Google Gemini CLI (`gemini`)
  - Antigravity CLI (`agy` or `antigravity`)

### Installation

```bash
# Clone the repository
git clone https://github.com/hopstreax/CodeAlign.git
cd CodeAlign

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Install CodeAlign with development dependencies
pip install -e ".[dev]"
```

---

## CLI Workflow & Command Examples

```bash
# View top-level help and available commands
codealign --help

# 1. Initialize CodeAlign and extract code intelligence with Graphify
codealign init

# (Optional: skip Graphify during initial configuration)
codealign init --skip-graphify

# (Force re-initialization and re-run Graphify extraction)
codealign init --force

# 2. Analyze an implementation plan against codebase intelligence
codealign analyze plan.md

# Output structured analysis evidence in JSON
codealign analyze plan.md --format json

# 3. Generate canonical Implementation Baseline contract (.codealign/baseline.json)
codealign baseline plan.md

# Output baseline contract in JSON
codealign baseline plan.md --format json

# 4. Export agent-consumable implementation context (.codealign/context.md)
codealign context

# Print context directly to stdout (for piping into agent prompts or scripts)
codealign context --stdout

# 5. Hand off implementation to a coding agent and verify session changes
codealign implement --agent gemini --timeout 300

# 6. Verify actual changes against the baseline contract
codealign verify

# Verify in strict mode (fails on warnings)
codealign verify --strict

# Output machine-readable verification findings in JSON
codealign verify --format json
```

---

## Agent Orchestration (`codealign implement`)

The `codealign implement` command automates agent handoff and verification:

1. **Pre-execution Snapshot:** Captures the initial working tree state.
2. **Isolated Agent Execution:** Launches the chosen agent CLI in an isolated process group (POSIX `start_new_session=True`) or managed process tree (Windows `taskkill /F /T`).
3. **Process-Tree Cleanup on Timeout:** If the agent exceeds `--timeout` (default: 300s), CodeAlign terminates the entire agent process tree, drains pipes boundedly, and exits with code 1. Non-finite (`NaN`, `inf`) and non-positive timeouts are rejected upfront.
4. **Post-execution Snapshot & Session Changeset:** Captures the post-run working tree state and calculates exactly which files and lines were modified during the agent session.
5. **Session-Aware Verification:** Verifies the session changeset against the baseline contract.

### Supported Agents & Options

- **Google Gemini CLI (`--agent gemini` [default]):**
  - Invokes `gemini`.
  - **Authentication:** Requires Gemini CLI to be authenticated beforehand (`gemini` login or `GEMINI_API_KEY`).
  - **Approval Mode:** `--approval-mode <auto_edit|yolo|default|plan>` (default: `auto_edit`).
  - **YOLO Mode:** `--yolo` auto-approves actions.
  - **Model:** `--model <name>` / `-m <name>`.
  - **Timeout:** `--timeout <seconds>` / `-t <seconds>` (default: 300.0).

- **Antigravity CLI (`--agent antigravity` or `--agent agy`):**
  - Invokes `agy` or `antigravity`.
  - **Authentication:** Relies on the active Antigravity CLI environment and credentials.
  - **Permission Bypass:** `--dangerously-skip-permissions` (or `--yolo`) runs in non-interactive edit mode.
  - **Model:** `--model <name>` / `-m <name>`.
  - **Timeout:** `--timeout <seconds>` / `-t <seconds>` (default: 300.0).

```bash
# Run Gemini with custom timeout and YOLO permissions
codealign implement --agent gemini --timeout 180 --yolo

# Run Antigravity bypassing tool confirmation prompts
codealign implement --agent antigravity --timeout 300 --dangerously-skip-permissions

# Run in strict verification mode
codealign implement --agent gemini --strict
```

---

## Session-Aware Verification vs. Standalone Verification

CodeAlign provides two modes of verification depending on the workflow stage:

| Feature | `codealign implement` (Session-Aware) | `codealign verify` (Standalone) |
| :--- | :--- | :--- |
| **Verification Scope** | Changes made **during the agent session** | All working tree changes relative to the baseline commit |
| **Dirty Repo Tolerance** | Tolerant: pre-existing dirty files outside the session are not flagged as drift | Strict: any unexpected modified or untracked file is flagged |
| **Primary Use Case** | Automated agent handoff and iterative development | CI/CD pipelines, pre-commit checks, or manual developer workflows |

---

## Verification Semantics

When evaluating changes against `.codealign/baseline.json`, CodeAlign verifies:

- **Repository Binding:** Confirms the repository name and ensures the baseline commit exists in Git history.
- **Expected File Changes:**
  - `modify`: Verifies that the expected file was modified relative to the baseline (`FAIL` if unchanged or deleted).
  - `create`: Verifies that the file exists and is newly introduced (`FAIL` if missing).
  - `unresolved`: Preserves uncertainty as a warning (`WARN`).
- **Scope Drift:** Identifies unexpected modified or added files outside baseline expectations (`WARN`).
- **Expected Tests:** Confirms whether planned test files were created or modified (`FAIL` if missing).
- **Expected Symbols:** Confirms presence of target functions, classes, or methods in modified files.
- **Constraints:** Preserves natural-language constraints as items requiring manual review (`WARN`).

### Exit Code Rules

- **`0`**: Verification passed (`PASS`), or passed with warnings (`WARN` in standard mode).
- **`1`**: Verification failed (`FAIL`), warnings encountered in `--strict` mode, or invalid CLI parameters.
- **`2`**: External coding agent returned a non-zero exit code during `codealign implement`.

---

## Preview Commands

The following command is currently registered as an experimental preview:

- **`codealign explain`:** Returns a preview placeholder message. Detailed natural-language explanations of verification findings and remediation guidance are scheduled for a future release.

---

## Testing

Run the test suite and linter locally:

```bash
# Run deterministic unit and integration test suite (211 tests)
pytest -q

# Run Ruff linter
ruff check src tests

# Check Git diff formatting and line endings
git diff --check
```

### Opt-In Real-Agent Acceptance Test (Tier 2)

By default, the test suite skips the live agent end-to-end acceptance test to prevent unexpected external API usage or quota consumption. To run the acceptance test against an installed, authenticated Antigravity CLI:

```bash
CODEALIGN_RUN_REAL_AGENT=1 pytest -q tests/test_e2e_real_agent.py
```

---

## License

This project is licensed under the [MIT License](LICENSE).
