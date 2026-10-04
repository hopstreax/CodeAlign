"""Developer implementation plan parser extracting explicit repository references."""

import re
from dataclasses import dataclass
from pathlib import Path

CODE_EXTENSIONS = {
    ".py",
    ".ts",
    ".js",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".cs",
    ".cpp",
    ".c",
    ".h",
    ".rb",
    ".toml",
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".html",
    ".css",
}


@dataclass(frozen=True)
class PlanReference:
    """An explicit repository entity referenced in an implementation plan."""

    raw: str
    kind: str  # "file", "method", "symbol"
    target: str  # normalized target name/path


@dataclass(frozen=True)
class ParsedPlan:
    """Structured representation of a developer implementation plan."""

    title: str
    path: Path | None
    references: list[PlanReference]
    raw_content: str


def _clean_token(token: str) -> str:
    """Strip surrounding backticks, quotes, and trailing prose punctuation."""
    t = token.strip(" \t\r\n`'\"")
    if t.endswith((".", ",", ":", ";", "!")):
        t = t[:-1].strip()
    return t


def _classify_reference(raw: str) -> PlanReference | None:
    token = _clean_token(raw)
    if not token or len(token) < 2:
        return None

    # Check for file path
    has_separator = "/" in token or "\\" in token
    has_extension = any(token.lower().endswith(ext) for ext in CODE_EXTENSIONS)
    if has_separator or has_extension:
        normalized = token.replace("\\", "/").lstrip("./")
        return PlanReference(raw=raw, kind="file", target=normalized)

    # Check for Class.method or Class.method()
    if "." in token and not token.startswith(".") and not token.endswith("."):
        parts = token.split(".", 1)
        ext_check = f".{parts[1].lower()}"
        if ext_check not in CODE_EXTENSIONS:
            if parts[0].isidentifier() and parts[1].rstrip("()").isidentifier():
                return PlanReference(raw=raw, kind="method", target=token)

    # Check for symbol (function(), ClassName, snake_case_identifier)
    ident_core = token.rstrip("()")
    if ident_core.isidentifier():
        return PlanReference(raw=raw, kind="symbol", target=token)

    return None


def parse_plan_text(content: str, path: Path | None = None) -> ParsedPlan:
    """Parse markdown text and extract title and explicit repository references."""
    lines = content.splitlines()

    # Extract title
    title = path.stem if path else "Implementation Plan"
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            break

    seen_targets: set[str] = set()
    references: list[PlanReference] = []

    def add_ref(ref: PlanReference | None) -> None:
        if ref and ref.target not in seen_targets:
            seen_targets.add(ref.target)
            references.append(ref)

    # 1. First priority: Extract explicit inline code spans (`...`)
    code_spans = re.findall(r"`([^`\n]+)`", content)
    for span in code_spans:
        add_ref(_classify_reference(span))

    # Mask out inline code spans from plain text to prevent double-matching
    plain_text = re.sub(r"`[^`\n]+`", " ", content)

    # 2. Second priority: Look for explicit file paths in plain text
    path_regex = re.compile(r"(?<!\w)(?:[a-zA-Z0-9_.-]+[/\\])+[a-zA-Z0-9_.-]+\.[a-zA-Z0-9]+\b")
    for match in path_regex.findall(plain_text):
        add_ref(_classify_reference(match))

    # Mask out matched paths so dotted regex doesn't match filenames
    plain_text_no_paths = path_regex.sub(" ", plain_text)

    # 3. Third priority: Dotted references in plain text (e.g. UserService.getProfile())
    dotted_regex = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]+(?:\(\))?")
    for match in dotted_regex.findall(plain_text_no_paths):
        add_ref(_classify_reference(match))

    return ParsedPlan(
        title=title,
        path=path,
        references=references,
        raw_content=content,
    )


def parse_plan_file(path: Path) -> ParsedPlan:
    """Read and parse a Markdown implementation plan file."""
    if not path.is_file():
        raise FileNotFoundError(f"Plan file not found: {path}")
    content = path.read_text(encoding="utf-8")
    return parse_plan_text(content, path=path)
