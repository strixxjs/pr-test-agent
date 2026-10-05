"""Markdown PR comment report generation."""

from pr_test_agent.metrics import RunMetrics


def render_comment(
    metrics: RunMetrics,
    written_tests: list[str],
    model: str,
    final_message: str = "",
) -> str:
    """Render PR comment markdown from run metrics and written tests."""
    if metrics.first_attempt_pass_pct is not None:
        first_pass_str = (
            f"{metrics.first_run_passed}/{metrics.first_run_total} "
            f"({metrics.first_attempt_pass_pct:.1f}%)"
        )
    else:
        first_pass_str = "n/a"

    if (
        metrics.coverage_before_pct is not None
        and metrics.coverage_after_pct is not None
        and metrics.coverage_delta_pct is not None
    ):
        sign = "+" if metrics.coverage_delta_pct >= 0 else ""
        cov_str = (
            f"{metrics.coverage_before_pct:.1f}% -> "
            f"{metrics.coverage_after_pct:.1f}% "
            f"({sign}{metrics.coverage_delta_pct:.1f}%)"
        )
    else:
        cov_str = "n/a"

    total_tokens = metrics.prompt_tokens + metrics.completion_tokens
    tokens_str = f"{total_tokens:,} ({metrics.prompt_tokens:,} prompt + {metrics.completion_tokens:,} completion)"

    cost_str = (
        f"${metrics.estimated_cost_usd:.4f}"
        if metrics.estimated_cost_usd is not None
        else "n/a"
    )

    tests_list_str = (
        "\n".join(f"- `{t}`" for t in written_tests)
        if written_tests
        else "- None"
    )

    lines = [
        "<!-- pr-test-agent -->",
        "## PR Test Agent",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Tests added | {metrics.tests_added} |",
        f"| Passed on first attempt | {first_pass_str} |",
        f"| Fix attempts | {metrics.fix_attempts} |",
        f"| Coverage | {cov_str} |",
        f"| Tokens | {tokens_str} |",
        f"| Estimated cost | {cost_str} |",
        f"| Duration | {metrics.duration_s:.1f}s |",
        f"| Stop reason | {metrics.stop_reason} |",
        f"| Model | {model or 'n/a'} |",
        "",
        "### Written Tests",
        tests_list_str,
    ]

    if metrics.stop_reason != "done":
        lines.append("")
        lines.append(f"Stopped early: {metrics.stop_reason}")
        if metrics.stop_reason == "error":
            err_msg = final_message or getattr(metrics, "final_message", "")
            lines.append(f"Error: {err_msg}")

    return "\n".join(lines) + "\n"
