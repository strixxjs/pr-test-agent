import subprocess
from pathlib import Path

import pytest

from pr_test_agent.guards import GuardError
from pr_test_agent.tools import (
    get_coverage,
    read_diff,
    read_file,
    run_pytest,
    safe_env,
    write_test,
)


def test_read_diff_and_read_file(git_repo: Path) -> None:
    diff_res = read_diff(git_repo, "main")
    assert not diff_res.truncated
    assert len(diff_res.files) == 1

    changed_file = diff_res.files[0]
    assert changed_file.path == "src/math_ops.py"
    assert len(changed_file.changed_lines) > 0

    func_names = [f.name for f in changed_file.functions]
    assert "add" in func_names
    assert "async_mul" in func_names

    async_funcs = [f for f in changed_file.functions if f.name == "async_mul"]
    assert len(async_funcs) == 1
    assert async_funcs[0].is_async is True

    # Verify read_file
    content = read_file(git_repo, "src/math_ops.py")
    assert "async def async_mul" in content

    # Verify read_file with max_chars
    truncated_content = read_file(git_repo, "src/math_ops.py", max_chars=10)
    assert len(truncated_content) == 10


def test_write_test_validation(git_repo: Path) -> None:
    # Valid Python test
    valid_content = "def test_added() -> None:\n    assert 1 + 1 == 2\n"
    created = write_test(git_repo, "tests/test_added.py", valid_content)
    assert created.exists()
    assert created.read_text(encoding="utf-8") == valid_content

    # Invalid Python syntax rejected
    with pytest.raises(GuardError):
        write_test(git_repo, "tests/test_invalid.py", "def broken_syntax(")


def test_run_pytest_counts_and_timeout(git_repo: Path) -> None:
    pass_content = "def test_ok() -> None:\n    assert True\n"
    fail_content = "def test_bad() -> None:\n    assert False\n"
    slow_content = "import time\ndef test_slow() -> None:\n    time.sleep(3)\n"

    write_test(git_repo, "tests/test_pass.py", pass_content)
    write_test(git_repo, "tests/test_fail.py", fail_content)
    write_test(git_repo, "tests/test_slow.py", slow_content)

    res = run_pytest(
        git_repo,
        targets=["tests/test_pass.py", "tests/test_fail.py"],
    )
    assert res.passed == 1
    assert res.failed == 1
    assert res.errors == 0
    assert res.timed_out is False
    assert res.exit_code != 0

    # Test timeout
    timeout_res = run_pytest(
        git_repo,
        targets=["tests/test_slow.py"],
        timeout=1,
    )
    assert timeout_res.timed_out is True
    assert timeout_res.exit_code == -1


def test_get_coverage_clean_repo(git_repo: Path) -> None:
    # Set up a test for math_ops and commit so working tree is clean
    test_content = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))\n"
        "from math_ops import add\n\n"
        "def test_add_op() -> None:\n"
        "    assert add(2, 3) == 5\n"
    )
    write_test(git_repo, "tests/test_math.py", test_content)
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "add test for math_ops"], cwd=git_repo, check=True)

    # Ensure repo is clean before running get_coverage
    status_before = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=git_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert status_before == ""

    cov_res = get_coverage(git_repo, files=["src/math_ops.py"])
    assert cov_res.total_percent > 0.0
    assert cov_res.files_percent is not None
    assert cov_res.files_percent > 0.0
    assert "src/math_ops.py" in cov_res.per_file
    assert cov_res.exit_code == 0

    # Verify repository remains clean
    status_after = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=git_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert status_after == ""


def test_safe_env_in_run_pytest_and_get_coverage(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_secret_key_12345")
    monkeypatch.setenv("MY_SECRET_TOKEN", "super_secret_token_abc")

    # Direct safe_env check
    env = safe_env()
    assert "GROQ_API_KEY" not in env
    assert "MY_SECRET_TOKEN" not in env
    assert "PATH" in env

    test_content = (
        "import os\n\n"
        "def test_secrets_stripped() -> None:\n"
        "    assert 'GROQ_API_KEY' not in os.environ\n"
        "    assert 'MY_SECRET_TOKEN' not in os.environ\n"
        "    assert 'PATH' in os.environ\n"
    )
    write_test(git_repo, "tests/test_env_sanitized.py", test_content)

    res = run_pytest(git_repo, targets=["tests/test_env_sanitized.py"])
    assert res.passed == 1
    assert res.failed == 0
    assert res.exit_code == 0

    cov_res = get_coverage(git_repo, files=["src/math_ops.py"])
    assert cov_res.exit_code == 0
