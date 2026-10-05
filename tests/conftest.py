import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)

    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")

    src = repo / "src"
    src.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "math_ops.py").write_text(
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n\n"
        "def sub(a: int, b: int) -> int:\n"
        "    return a - b\n",
        encoding="utf-8",
    )
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_initial.py").write_text(
        "def test_smoke() -> None:\n"
        "    assert True\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo, check=True)

    subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True)
    (src / "math_ops.py").write_text(
        "def add(a: int, b: int) -> int:\n"
        "    result = a + b\n"
        "    return result\n\n"
        "async def async_mul(a: int, b: int) -> int:\n"
        "    return a * b\n\n"
        "def sub(a: int, b: int) -> int:\n"
        "    return a - b\n",
        encoding="utf-8",
    )
    (tests / "test_feature.py").write_text(
        "def test_feature() -> None:\n"
        "    assert True\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "feature commit"], cwd=repo, check=True)

    return repo
