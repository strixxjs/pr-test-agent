"""Path and security guards."""

import fnmatch
from pathlib import Path


class GuardError(Exception):
    """Raised when a path or content violates safety guards."""


def _safe_resolve(base_dir: Path, rel_path: str) -> Path:
    target = base_dir / rel_path
    parts: list[str] = []
    curr = target
    while not (curr.exists() or curr.is_symlink()) and curr != curr.parent:
        parts.append(curr.name)
        curr = curr.parent
    resolved = curr.resolve()
    for part in reversed(parts):
        resolved = resolved / part
    return resolved


def resolve_test_path(repo_root: Path, rel_path: str) -> Path:
    """Resolve and validate write path for test files."""
    path_obj = Path(rel_path)
    if path_obj.is_absolute() or rel_path.startswith(("/", "\\")):
        raise GuardError(f"Absolute paths not allowed: {rel_path}")
    if ".." in path_obj.parts:
        raise GuardError(f"Path traversals not allowed: {rel_path}")

    root = repo_root.resolve()
    tests_dir = (root / "tests").resolve()
    resolved = _safe_resolve(root, rel_path)

    if not resolved.is_relative_to(tests_dir) or resolved == tests_dir:
        raise GuardError(f"Path must be inside tests directory: {rel_path}")
    if not fnmatch.fnmatch(resolved.name, "test_*.py"):
        raise GuardError(f"Test file name must match 'test_*.py': {rel_path}")

    return resolved


def resolve_read_path(repo_root: Path, rel_path: str) -> Path:
    """Resolve and validate read path within repo root."""
    path_obj = Path(rel_path)
    if path_obj.is_absolute() or rel_path.startswith(("/", "\\")):
        raise GuardError(f"Absolute paths not allowed: {rel_path}")
    if ".." in path_obj.parts:
        raise GuardError(f"Path traversals not allowed: {rel_path}")

    root = repo_root.resolve()
    resolved = _safe_resolve(root, rel_path)

    if not resolved.is_relative_to(root):
        raise GuardError(f"Path must resolve inside repository root: {rel_path}")

    git_dir = (root / ".git").resolve()
    if resolved == git_dir or resolved.is_relative_to(git_dir) or ".git" in path_obj.parts:
        raise GuardError(f"Access to .git is forbidden: {rel_path}")

    if (
        resolved.name == ".env"
        or resolved.name.startswith(".env.")
        or path_obj.name == ".env"
        or path_obj.name.startswith(".env.")
    ):
        raise GuardError(f"Access to .env files is forbidden: {rel_path}")

    return resolved
