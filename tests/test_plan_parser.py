"""Unit tests for implementation plan parsing."""

from pathlib import Path

from codealign.analysis.plan_parser import parse_plan_file, parse_plan_text


def test_parse_plan_text_with_code_spans() -> None:
    """Verify inline code spans and references are extracted correctly."""
    content = """# Add Redis Caching

## Goal
Improve lookup latency.

## Implementation
1. Update `UserService.getProfile()` to check cache first.
2. Configure Redis connection in `src/config/redis.ts`.
3. Update `User` entity if necessary.
4. Call `cacheService.invalidate()` on update.
"""
    plan = parse_plan_text(content)
    assert plan.title == "Add Redis Caching"
    assert len(plan.references) == 4

    targets = [r.target for r in plan.references]
    assert "UserService.getProfile()" in targets
    assert "src/config/redis.ts" in targets
    assert "User" in targets
    assert "cacheService.invalidate()" in targets

    kinds = {r.target: r.kind for r in plan.references}
    assert kinds["src/config/redis.ts"] == "file"
    assert kinds["UserService.getProfile()"] == "method"
    assert kinds["User"] == "symbol"


def test_parse_plan_text_plain_references() -> None:
    """Verify plain text file paths and dotted symbols are extracted without backticks."""
    content = """
# Refactor Auth Module

Please modify src/auth/service.py and call AuthService.authenticate().
Also review tests/test_auth.py.
"""
    plan = parse_plan_text(content)
    assert plan.title == "Refactor Auth Module"
    targets = [r.target for r in plan.references]
    assert "src/auth/service.py" in targets
    assert "AuthService.authenticate()" in targets
    assert "tests/test_auth.py" in targets


def test_parse_plan_file(tmp_path: Path) -> None:
    """Verify reading and parsing plan directly from file."""
    plan_path = tmp_path / "custom_plan.md"
    plan_path.write_text("# Custom Feature\nTouch `src/app.py`.\n", encoding="utf-8")

    plan = parse_plan_file(plan_path)
    assert plan.title == "Custom Feature"
    assert len(plan.references) == 1
    assert plan.references[0].target == "src/app.py"
    assert plan.references[0].kind == "file"


def test_parse_plan_escaped_underscores_code_spans() -> None:
    """Verify escaped underscores in code spans are normalized without turning into slashes."""
    content = r"""# Improve Git Detection
1. Update `get\_git\_repo\_info()` in `src/codealign/git/repository.py`.
2. Add tests in `tests/test\_git.py`.
3. Check unescaped `get_git_repo_info()` and `tests/test_git.py`.
"""
    plan = parse_plan_text(content)
    targets = {r.target: r for r in plan.references}

    assert "get_git_repo_info()" in targets
    assert targets["get_git_repo_info()"].kind == "symbol"
    assert targets["get_git_repo_info()"].raw == r"get\_git\_repo\_info()"

    assert "tests/test_git.py" in targets
    assert targets["tests/test_git.py"].kind == "file"
    assert targets["tests/test_git.py"].raw == r"tests/test\_git.py"

    assert "src/codealign/git/repository.py" in targets
    assert targets["src/codealign/git/repository.py"].kind == "file"


def test_parse_plan_escaped_underscores_plain_text() -> None:
    """Verify plain text file paths with escaped underscores are recognized as files."""
    content = r"""# Plain Text Plan
Please update tests/test\_git.py and verify against tests/test_git.py.
"""
    plan = parse_plan_text(content)
    targets = {r.target: r for r in plan.references}

    assert "tests/test_git.py" in targets
    assert targets["tests/test_git.py"].kind == "file"
