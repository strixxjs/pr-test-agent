"""Run metrics calculation and aggregation."""

import ast
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pr_test_agent.agent import AgentResult
from pr_test_agent.tools import CoverageResult


@dataclass(frozen=True)
class RunMetrics:
    tests_added: int
    first_run_total: int
    first_run_passed: int
    first_attempt_pass_pct: float | None
    final_passed: int
    final_failed: int
    fix_attempts: int
    coverage_before_pct: float | None
    coverage_after_pct: float | None
    coverage_delta_pct: float | None
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float | None
    duration_s: float
    stop_reason: str
    final_message: str = ""
    functions_total: int = 0
    functions_referenced: int = 0
    test_cases: int | None = None
    uncovered_functions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary."""
        return asdict(self)


def _count_tests_in_file(file_path: Path) -> int:
    if not file_path.exists():
        return 0
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return 0

    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            count += 1
    return count


def _get_coverage_pct(cov: CoverageResult | None) -> float | None:
    if cov is None:
        return None
    return cov.files_percent if cov.files_percent is not None else cov.total_percent


def read_price_config_from_env() -> tuple[float | None, float | None]:
    """Read optional token pricing per million tokens from environment."""
    p_in_str = os.environ.get("PRICE_IN_PER_MTOK")
    p_out_str = os.environ.get("PRICE_OUT_PER_MTOK")
    p_in: float | None = None
    p_out: float | None = None

    if p_in_str is not None and p_in_str.strip():
        try:
            p_in = float(p_in_str.strip())
        except ValueError:
            p_in = None

    if p_out_str is not None and p_out_str.strip():
        try:
            p_out = float(p_out_str.strip())
        except ValueError:
            p_out = None

    return p_in, p_out


def compute_metrics(
    repo_root: Path,
    result: AgentResult,
    coverage_before: CoverageResult | None,
    coverage_after: CoverageResult | None,
    prompt_tokens: int,
    completion_tokens: int,
    duration_s: float,
    price_in_per_mtok: float | None,
    price_out_per_mtok: float | None,
) -> RunMetrics:
    """Compute run metrics from execution results and coverage."""
    tests_added = sum(
        _count_tests_in_file(repo_root / path_str)
        for path_str in result.written_tests
    )

    if result.pytest_runs:
        first_run = result.pytest_runs[0]
        first_run_total = first_run.passed + first_run.failed + first_run.errors
        first_run_passed = first_run.passed
        first_attempt_pass_pct = (
            (first_run_passed / first_run_total * 100.0)
            if first_run_total > 0
            else None
        )

        last_run = result.pytest_runs[-1]
        final_passed = last_run.passed
        final_failed = last_run.failed + last_run.errors
        fix_attempts = max(0, len(result.pytest_runs) - 1)
        test_cases = final_passed + final_failed
    else:
        first_run_total = 0
        first_run_passed = 0
        first_attempt_pass_pct = None
        final_passed = 0
        final_failed = 0
        fix_attempts = 0
        test_cases = None

    cov_before_pct = _get_coverage_pct(coverage_before)
    cov_after_pct = _get_coverage_pct(coverage_after)
    cov_delta_pct = (
        (cov_after_pct - cov_before_pct)
        if (cov_before_pct is not None and cov_after_pct is not None)
        else None
    )

    if price_in_per_mtok is not None and price_out_per_mtok is not None:
        estimated_cost_usd = (
            (prompt_tokens / 1_000_000.0 * price_in_per_mtok)
            + (completion_tokens / 1_000_000.0 * price_out_per_mtok)
        )
    else:
        estimated_cost_usd = None

    return RunMetrics(
        tests_added=tests_added,
        first_run_total=first_run_total,
        first_run_passed=first_run_passed,
        first_attempt_pass_pct=first_attempt_pass_pct,
        final_passed=final_passed,
        final_failed=final_failed,
        fix_attempts=fix_attempts,
        coverage_before_pct=cov_before_pct,
        coverage_after_pct=cov_after_pct,
        coverage_delta_pct=cov_delta_pct,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=estimated_cost_usd,
        duration_s=duration_s,
        stop_reason=result.stop_reason,
        final_message=result.final_message,
        functions_total=getattr(result, "functions_total", 0),
        functions_referenced=getattr(result, "functions_referenced", 0),
        test_cases=test_cases,
        uncovered_functions=list(getattr(result, "uncovered_functions", [])),
    )
