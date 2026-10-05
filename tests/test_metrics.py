from pathlib import Path

import pytest

from pr_test_agent.agent import AgentResult
from pr_test_agent.metrics import (
    RunMetrics,
    compute_metrics,
    read_price_config_from_env,
)
from pr_test_agent.tools import CoverageResult, PytestResult


def test_metrics_tests_added_counts_sync_async_ignores_helpers(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "test_example.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def helper_func():\n"
        "    return 1\n\n"
        "def test_sync():\n"
        "    assert helper_func() == 1\n\n"
        "async def test_async():\n"
        "    assert True\n\n"
        "class HelperClass:\n"
        "    def method(self):\n"
        "        pass\n",
        encoding="utf-8",
    )

    agent_result = AgentResult(
        stop_reason="done",
        steps=1,
        total_tokens=100,
        prompt_tokens=60,
        completion_tokens=40,
        written_tests=["tests/test_example.py"],
    )

    metrics = compute_metrics(
        repo_root=tmp_path,
        result=agent_result,
        coverage_before=None,
        coverage_after=None,
        prompt_tokens=60,
        completion_tokens=40,
        duration_s=2.5,
        price_in_per_mtok=None,
        price_out_per_mtok=None,
    )

    assert isinstance(metrics, RunMetrics)
    assert metrics.tests_added == 2


def test_metrics_first_attempt_pass_pct_and_runs(tmp_path: Path) -> None:
    run1 = PytestResult(
        exit_code=1,
        passed=3,
        failed=1,
        errors=0,
        skipped=0,
        duration_s=1.0,
        output="3 passed, 1 failed",
        timed_out=False,
    )
    run2 = PytestResult(
        exit_code=0,
        passed=4,
        failed=0,
        errors=0,
        skipped=0,
        duration_s=1.0,
        output="4 passed",
        timed_out=False,
    )

    agent_result = AgentResult(
        stop_reason="done",
        steps=2,
        total_tokens=200,
        prompt_tokens=120,
        completion_tokens=80,
        pytest_runs=[run1, run2],
    )

    metrics = compute_metrics(
        repo_root=tmp_path,
        result=agent_result,
        coverage_before=None,
        coverage_after=None,
        prompt_tokens=120,
        completion_tokens=80,
        duration_s=3.0,
        price_in_per_mtok=None,
        price_out_per_mtok=None,
    )

    assert metrics.first_run_total == 4
    assert metrics.first_run_passed == 3
    assert metrics.first_attempt_pass_pct == 75.0
    assert metrics.final_passed == 4
    assert metrics.final_failed == 0
    assert metrics.fix_attempts == 1


def test_metrics_zero_pytest_runs(tmp_path: Path) -> None:
    agent_result = AgentResult(
        stop_reason="done",
        steps=0,
        total_tokens=0,
        prompt_tokens=0,
        completion_tokens=0,
        pytest_runs=[],
    )

    metrics = compute_metrics(
        repo_root=tmp_path,
        result=agent_result,
        coverage_before=None,
        coverage_after=None,
        prompt_tokens=0,
        completion_tokens=0,
        duration_s=0.5,
        price_in_per_mtok=None,
        price_out_per_mtok=None,
    )

    assert metrics.first_run_total == 0
    assert metrics.first_run_passed == 0
    assert metrics.first_attempt_pass_pct is None
    assert metrics.final_passed == 0
    assert metrics.final_failed == 0
    assert metrics.fix_attempts == 0


def test_metrics_coverage_delta_and_cost_calculation(tmp_path: Path) -> None:
    cov_before = CoverageResult(
        total_percent=40.0,
        files_percent=50.0,
        per_file={"src/x.py": 50.0},
        exit_code=0,
    )
    cov_after = CoverageResult(
        total_percent=70.0,
        files_percent=80.0,
        per_file={"src/x.py": 80.0},
        exit_code=0,
    )

    agent_result = AgentResult(
        stop_reason="done",
        steps=1,
        total_tokens=1500,
        prompt_tokens=1000,
        completion_tokens=500,
    )

    # Cost with prices
    metrics_with_cost = compute_metrics(
        repo_root=tmp_path,
        result=agent_result,
        coverage_before=cov_before,
        coverage_after=cov_after,
        prompt_tokens=1000,
        completion_tokens=500,
        duration_s=1.2,
        price_in_per_mtok=0.59,
        price_out_per_mtok=0.79,
    )

    assert metrics_with_cost.coverage_before_pct == 50.0
    assert metrics_with_cost.coverage_after_pct == 80.0
    assert metrics_with_cost.coverage_delta_pct == 30.0

    expected_cost = (1000 / 1e6 * 0.59) + (500 / 1e6 * 0.79)
    assert metrics_with_cost.estimated_cost_usd is not None
    assert abs(metrics_with_cost.estimated_cost_usd - expected_cost) < 1e-9

    # Cost without prices
    metrics_no_cost = compute_metrics(
        repo_root=tmp_path,
        result=agent_result,
        coverage_before=cov_before,
        coverage_after=cov_after,
        prompt_tokens=1000,
        completion_tokens=500,
        duration_s=1.2,
        price_in_per_mtok=None,
        price_out_per_mtok=None,
    )
    assert metrics_no_cost.estimated_cost_usd is None

    # Test to_dict
    m_dict = metrics_with_cost.to_dict()
    assert isinstance(m_dict, dict)
    assert m_dict["tests_added"] == 0
    assert m_dict["coverage_delta_pct"] == 30.0


def test_read_price_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRICE_IN_PER_MTOK", raising=False)
    monkeypatch.delenv("PRICE_OUT_PER_MTOK", raising=False)
    p_in, p_out = read_price_config_from_env()
    assert p_in is None
    assert p_out is None

    monkeypatch.setenv("PRICE_IN_PER_MTOK", "0.59")
    monkeypatch.setenv("PRICE_OUT_PER_MTOK", "0.79")
    p_in, p_out = read_price_config_from_env()
    assert p_in == 0.59
    assert p_out == 0.79
