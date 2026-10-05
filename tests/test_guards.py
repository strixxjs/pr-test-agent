from pathlib import Path

import pytest

from pr_test_agent.guards import GuardError, resolve_read_path, resolve_test_path


def test_guards_accept_and_reject(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    tests_dir = repo_root / "tests"
    tests_dir.mkdir()
    src_dir = repo_root / "src"
    src_dir.mkdir()
    git_dir = repo_root / ".git"
    git_dir.mkdir()

    (src_dir / "x.py").write_text("x = 1\n", encoding="utf-8")
    (tests_dir / "test_x.py").write_text("def test_x() -> None: pass\n", encoding="utf-8")
    (tests_dir / "helper.py").write_text("def helper() -> None: pass\n", encoding="utf-8")
    (git_dir / "config").write_text("[core]\n", encoding="utf-8")
    (repo_root / ".env").write_text("SECRET=1\n", encoding="utf-8")

    # Guard accepts tests/test_x.py
    resolved = resolve_test_path(repo_root, "tests/test_x.py")
    assert resolved == (tests_dir / "test_x.py").resolve()

    # Rejects src/x.py
    with pytest.raises(GuardError):
        resolve_test_path(repo_root, "src/x.py")

    # Rejects ../x.py
    with pytest.raises(GuardError):
        resolve_test_path(repo_root, "../x.py")

    # Rejects absolute path
    with pytest.raises(GuardError):
        resolve_test_path(repo_root, str((tests_dir / "test_x.py").resolve()))

    # Rejects tests/helper.py
    with pytest.raises(GuardError):
        resolve_test_path(repo_root, "tests/helper.py")

    # Rejects symlink escape
    escape_target = repo_root / "secret.txt"
    escape_target.write_text("secret\n", encoding="utf-8")
    symlink_path = tests_dir / "test_escape.py"
    symlink_path.symlink_to(escape_target)

    with pytest.raises(GuardError):
        resolve_test_path(repo_root, "tests/test_escape.py")

    # resolve_read_path accepts normal files
    read_resolved = resolve_read_path(repo_root, "src/x.py")
    assert read_resolved == (src_dir / "x.py").resolve()

    # resolve_read_path rejects .env
    with pytest.raises(GuardError):
        resolve_read_path(repo_root, ".env")

    # resolve_read_path rejects .git/config
    with pytest.raises(GuardError):
        resolve_read_path(repo_root, ".git/config")
