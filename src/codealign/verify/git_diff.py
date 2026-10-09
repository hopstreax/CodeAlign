"""Git diff and working tree change inspection for verification."""

import ast
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from codealign.git.repository import GitError, run_git_command


class BaseCommitNotFoundError(GitError):
    """Raised when the baseline commit does not exist in repository Git history."""


@dataclass
class GitChangeSet:
    """Deterministic snapshot of changes between baseline commit and current working tree."""

    base_commit: str
    modified: set[str] = field(default_factory=set)
    added: set[str] = field(default_factory=set)
    deleted: set[str] = field(default_factory=set)
    renamed: dict[str, str] = field(default_factory=dict)  # new_path -> old_path

    @property
    def all_changed_files(self) -> set[str]:
        """Return unified set of all changed (modified, added, deleted, renamed) file paths."""
        return self.modified | self.added | self.deleted | set(self.renamed.keys())

    def to_dict(self) -> dict[str, Any]:
        """Return deterministic dictionary representation of changed files."""
        return {
            "modified": sorted(self.modified),
            "added": sorted(self.added),
            "deleted": sorted(self.deleted),
            "renamed": dict(sorted(self.renamed.items())),
        }


@dataclass(frozen=True)
class SymbolFingerprint:
    """Deterministic fingerprint of a callable symbol's signature and body."""

    sig_hash: str
    body_hash: str
    line: int


@dataclass(frozen=True)
class WorkingTreeSnapshot:
    """Deterministic snapshot of repository working-tree state, dirty hashes, and symbols."""

    changeset: GitChangeSet
    dirty_hashes: dict[str, str] = field(default_factory=dict)
    file_symbols: dict[str, set[str]] = field(default_factory=dict)
    symbol_fingerprints: dict[str, dict[str, SymbolFingerprint]] = field(default_factory=dict)
    parse_errors: dict[str, str] = field(default_factory=dict)


def _normalize_path(p: str) -> str:
    """Normalize file path to forward slashes with no leading './'."""
    norm = p.strip().replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm.lstrip("/")


def get_git_changes(repo_root: Path, base_commit: str) -> GitChangeSet:
    """Inspect the repository and compute all changes relative to the baseline commit.

    Includes:
    - Tracked file modifications, additions, and deletions (committed, staged, or unstaged)
    - Untracked, non-ignored working tree files

    Args:
        repo_root: Path to repository root.
        base_commit: Baseline commit SHA to compare against.

    Returns:
        GitChangeSet with normalized paths.

    Raises:
        BaseCommitNotFoundError: If base_commit cannot be resolved in Git history.
        GitError: If underlying Git operations fail.
    """
    modified: set[str] = set()
    added: set[str] = set()
    deleted: set[str] = set()
    renamed: dict[str, str] = {}

    # 1. Validate that the baseline commit exists in Git history if specified
    if base_commit and base_commit != "uncommitted":
        try:
            run_git_command(["cat-file", "-e", f"{base_commit}^{{commit}}"], cwd=repo_root)
        except GitError as exc:
            raise BaseCommitNotFoundError(
                f"Baseline commit '{base_commit}' does not exist in current Git history."
            ) from exc

    # 2. Query diff of tracked files relative to base_commit
    # 'git diff --name-status <commit>' compares the commit tree directly to the working tree
    diff_args = (
        ["diff", "--name-status", base_commit]
        if (base_commit and base_commit != "uncommitted")
        else ["diff", "--name-status", "HEAD"]
    )
    try:
        diff_output = run_git_command(diff_args, cwd=repo_root)
    except GitError:
        # Fallback if HEAD does not exist (empty repo)
        diff_output = ""

    if diff_output:
        for line in diff_output.splitlines():
            parts = line.split("\t")
            if not parts or not parts[0]:
                continue
            status_code = parts[0][0].upper()
            if status_code in ("M", "T"):
                if len(parts) >= 2:
                    modified.add(_normalize_path(parts[1]))
            elif status_code == "A":
                if len(parts) >= 2:
                    added.add(_normalize_path(parts[1]))
            elif status_code == "D":
                if len(parts) >= 2:
                    deleted.add(_normalize_path(parts[1]))
            elif status_code == "R":
                if len(parts) >= 3:
                    old_path = _normalize_path(parts[1])
                    new_path = _normalize_path(parts[2])
                    renamed[new_path] = old_path
                    modified.add(new_path)

    # 3. Query untracked, non-ignored files in working tree
    try:
        untracked_output = run_git_command(
            ["ls-files", "--others", "--exclude-standard"],
            cwd=repo_root,
        )
    except GitError:
        untracked_output = ""

    if untracked_output:
        for line in untracked_output.splitlines():
            path_str = _normalize_path(line)
            if path_str:
                added.add(path_str)

    return GitChangeSet(
        base_commit=base_commit,
        modified=modified,
        added=added,
        deleted=deleted,
        renamed=renamed,
    )


def _hash_file(path: Path) -> str | None:
    """Compute SHA-256 hash of a file if it exists on disk."""
    if not path.is_file():
        return None
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _normalize_ast_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Compute normalized SHA-256 hash of callable signature."""
    returns_dump = (
        ast.dump(node.returns, include_attributes=False) if node.returns is not None else ""
    )
    args_dump = ast.dump(node.args, include_attributes=False)
    decorators_dump = [ast.dump(d, include_attributes=False) for d in node.decorator_list]
    async_prefix = "async" if isinstance(node, ast.AsyncFunctionDef) else "def"
    sig_repr = f"{async_prefix}|{returns_dump}|{args_dump}|{decorators_dump}"
    return hashlib.sha256(sig_repr.encode("utf-8")).hexdigest()


def _normalize_ast_body(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Compute normalized SHA-256 hash of callable body, excluding leading docstring."""
    body_stmts = node.body
    if body_stmts and isinstance(body_stmts[0], ast.Expr):
        val = body_stmts[0].value
        if isinstance(val, ast.Constant) and isinstance(val.value, str):
            body_stmts = body_stmts[1:]

    body_repr = "\n".join(ast.dump(stmt, include_attributes=False) for stmt in body_stmts)
    return hashlib.sha256(body_repr.encode("utf-8")).hexdigest()


def _extract_python_symbols_and_fingerprints(
    content: str,
) -> tuple[set[str], dict[str, SymbolFingerprint], str | None]:
    """Extract functions, async functions, classes, methods, and fingerprints from Python source."""
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError) as exc:
        line_info = f" (line {exc.lineno})" if getattr(exc, "lineno", None) else ""
        msg = getattr(exc, "msg", str(exc))
        return set(), {}, f"SyntaxError: {msg}{line_info}"

    symbols: set[str] = set()
    fingerprints: dict[str, SymbolFingerprint] = {}

    def _walk_class(class_node: ast.ClassDef, prefix: str) -> None:
        for item in class_node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sym_name = f"{prefix}.{item.name}"
                symbols.add(sym_name)
                fingerprints[sym_name] = SymbolFingerprint(
                    sig_hash=_normalize_ast_signature(item),
                    body_hash=_normalize_ast_body(item),
                    line=getattr(item, "lineno", 1),
                )
            elif isinstance(item, ast.ClassDef):
                sym_name = f"{prefix}.{item.name}"
                symbols.add(sym_name)
                _walk_class(item, sym_name)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.add(node.name)
            fingerprints[node.name] = SymbolFingerprint(
                sig_hash=_normalize_ast_signature(node),
                body_hash=_normalize_ast_body(node),
                line=getattr(node, "lineno", 1),
            )
        elif isinstance(node, ast.ClassDef):
            symbols.add(node.name)
            _walk_class(node, node.name)

    return symbols, fingerprints, None


def _extract_python_symbols(content: str) -> set[str]:
    """Extract functions, async functions, classes, and methods from Python source."""
    symbols, _, _ = _extract_python_symbols_and_fingerprints(content)
    return symbols


_GENERIC_CALLABLE_PATTERNS = [
    re.compile(r"\bfunction\s+([A-Za-z0-9_$]+)"),
    re.compile(r"\bclass\s+([A-Za-z0-9_$]+)"),
    re.compile(r"\bfunc\s+(?:\([^)]+\)\s+)?([A-Za-z0-9_]+)"),
    re.compile(r"\bfn\s+([A-Za-z0-9_]+)"),
    re.compile(r"\bstruct\s+([A-Za-z0-9_]+)"),
    re.compile(r"\benum\s+([A-Za-z0-9_]+)"),
    re.compile(
        r"^\s*(?:(?:public|private|protected|static|readonly|async)\s+)+([A-Za-z0-9_$]+)\s*\([^)]*\)\s*(?:\{|:)",
        re.MULTILINE,
    ),
]


def _extract_generic_symbols(content: str) -> set[str]:
    """Extract functions, classes, and methods from non-Python source using regex."""
    symbols: set[str] = set()
    for pattern in _GENERIC_CALLABLE_PATTERNS:
        for match in pattern.finditer(content):
            name = match.group(1).strip()
            if name:
                symbols.add(name)
    return symbols


def extract_file_symbols_and_fingerprints(
    path: Path,
) -> tuple[set[str], dict[str, SymbolFingerprint], str | None]:
    """Extract callable and class symbol names and fingerprints defined in a file."""
    if not path.is_file():
        return set(), {}, None
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set(), {}, None

    if path.suffix == ".py":
        return _extract_python_symbols_and_fingerprints(content)
    return _extract_generic_symbols(content), {}, None


def extract_file_symbols(path: Path) -> set[str]:
    """Extract callable and class symbol names defined in a file."""
    syms, _, _ = extract_file_symbols_and_fingerprints(path)
    return syms


def capture_working_tree_snapshot(
    repo_root: Path,
    base_commit: str,
    relevant_files: Iterable[str] | None = None,
) -> WorkingTreeSnapshot:
    """Capture snapshot of repository working-tree state, dirty hashes, and symbols.

    Reuses get_git_changes() and only hashes files present in the resulting changeset.
    Extracts symbols for dirty files and any explicitly passed relevant files.
    """
    try:
        changeset = get_git_changes(repo_root, base_commit)
    except (BaseCommitNotFoundError, GitError):
        changeset = GitChangeSet(base_commit=base_commit)

    dirty_hashes: dict[str, str] = {}
    for file_path in changeset.all_changed_files:
        full_path = repo_root / file_path
        h = _hash_file(full_path)
        if h is not None:
            dirty_hashes[file_path] = h

    files_to_scan = set(changeset.all_changed_files)
    if relevant_files:
        files_to_scan.update(_normalize_path(f) for f in relevant_files)

    file_symbols: dict[str, set[str]] = {}
    symbol_fingerprints: dict[str, dict[str, SymbolFingerprint]] = {}
    parse_errors: dict[str, str] = {}

    for file_path in sorted(files_to_scan):
        full_path = repo_root / file_path
        if full_path.is_file():
            syms, fps, err = extract_file_symbols_and_fingerprints(full_path)
            file_symbols[file_path] = syms
            if fps:
                symbol_fingerprints[file_path] = fps
            if err:
                parse_errors[file_path] = err

    return WorkingTreeSnapshot(
        changeset=changeset,
        dirty_hashes=dirty_hashes,
        file_symbols=file_symbols,
        symbol_fingerprints=symbol_fingerprints,
        parse_errors=parse_errors,
    )


def compute_session_changes(
    pre: WorkingTreeSnapshot,
    post: WorkingTreeSnapshot,
    repo_root: Path,
) -> GitChangeSet:
    """Compute GitChangeSet representing only changes during the agent session.

    Excludes working-tree changes that already existed before the session started.
    """
    pre_cs = pre.changeset
    post_cs = post.changeset
    pre_hashes = pre.dirty_hashes
    post_hashes = post.dirty_hashes

    session_modified: set[str] = set()
    session_added: set[str] = set()
    session_deleted: set[str] = set()
    session_renamed: dict[str, str] = {}

    # 1. Renames occurring during session
    for new_path, old_path in post_cs.renamed.items():
        if new_path not in pre_cs.renamed:
            session_renamed[new_path] = old_path
            session_modified.add(new_path)

    # 2. Additions / untracked files
    for path in post_cs.added:
        if path in pre_cs.added:
            # File was already untracked before session.
            # Check if agent modified its content during session.
            pre_h = pre_hashes.get(path)
            post_h = post_hashes.get(path)
            if pre_h != post_h:
                session_modified.add(path)
        elif path not in pre_cs.all_changed_files:
            # Newly added/created during session
            session_added.add(path)
        else:
            pre_h = pre_hashes.get(path)
            post_h = post_hashes.get(path)
            if pre_h != post_h:
                session_modified.add(path)

    # 3. Deletions
    for path in post_cs.deleted:
        if path not in pre_cs.deleted:
            session_deleted.add(path)

    # 4. Modifications
    for path in post_cs.modified:
        if path in session_renamed:
            continue
        if path in pre_cs.modified or path in pre_cs.added:
            # File was already dirty before session.
            # Check if agent changed its content during session.
            pre_h = pre_hashes.get(path)
            post_h = post_hashes.get(path)
            if pre_h != post_h:
                session_modified.add(path)
        elif path not in pre_cs.all_changed_files:
            # Clean file before session, modified during session
            session_modified.add(path)
        else:
            pre_h = pre_hashes.get(path)
            post_h = post_hashes.get(path)
            if pre_h != post_h:
                session_modified.add(path)

    # 5. Pre-existing dirty files that became clean during session
    # (e.g. agent restored a modified file to base commit, or removed an untracked file)
    restored_files = pre_cs.all_changed_files - post_cs.all_changed_files
    for path in restored_files:
        if path in pre_cs.added:
            # An untracked file that was removed by the agent
            session_deleted.add(path)
        elif path in pre_cs.modified or path in pre_cs.deleted:
            # A modified/deleted file restored back to base commit by agent
            session_modified.add(path)

    return GitChangeSet(
        base_commit=post_cs.base_commit,
        modified=session_modified,
        added=session_added,
        deleted=session_deleted,
        renamed=session_renamed,
    )
