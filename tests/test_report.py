from pr_test_agent.metrics import RunMetrics
from pr_test_agent.report import render_comment


def test_render_comment_marker_and_format() -> None:
    metrics = RunMetrics(
        tests_added=3,
        first_run_total=4,
        first_run_passed=3,
        first_attempt_pass_pct=75.0,
        final_passed=4,
        final_failed=0,
        fix_attempts=1,
        coverage_before_pct=50.0,
        coverage_after_pct=80.0,
        coverage_delta_pct=30.0,
        prompt_tokens=1000,
        completion_tokens=500,
        estimated_cost_usd=0.0012,
        duration_s=4.5,
        stop_reason="done",
    )
    written_tests = ["tests/test_a.py", "tests/test_b.py"]

    comment = render_comment(metrics, written_tests, model="llama-3.3-70b-versatile")

    # Marker must be first line
    lines = comment.strip().splitlines()
    assert lines[0] == "<!-- pr-test-agent -->"
    assert lines[1] == "## PR Test Agent"

    assert "| Tests added | 3 |" in comment
    assert "| Passed on first attempt | 3/4 (75.0%) |" in comment
    assert "| Fix attempts | 1 |" in comment
    assert "| Coverage | 50.0% -> 80.0% (+30.0%) |" in comment
    assert "| Estimated cost | $0.0012 |" in comment
    assert "| Duration | 4.5s |" in comment
    assert "| Stop reason | done |" in comment
    assert "| Model | llama-3.3-70b-versatile |" in comment

    assert "- `tests/test_a.py`" in comment
    assert "- `tests/test_b.py`" in comment
    assert "Stopped early:" not in comment


def test_render_comment_na_rendering() -> None:
    metrics = RunMetrics(
        tests_added=0,
        first_run_total=0,
        first_run_passed=0,
        first_attempt_pass_pct=None,
        final_passed=0,
        final_failed=0,
        fix_attempts=0,
        coverage_before_pct=None,
        coverage_after_pct=None,
        coverage_delta_pct=None,
        prompt_tokens=0,
        completion_tokens=0,
        estimated_cost_usd=None,
        duration_s=0.0,
        stop_reason="done",
    )

    comment = render_comment(metrics, written_tests=[], model="")

    lines = comment.strip().splitlines()
    assert lines
    assert lines[0] == "<!-- pr-test-agent -->"
    assert "| Passed on first attempt | n/a |" in comment
    assert "| Coverage | n/a |" in comment
    assert "| Estimated cost | n/a |" in comment
    assert "| Model | n/a |" in comment
    assert "- None" in comment
    assert "Stopped early:" not in comment


def test_render_comment_early_stop() -> None:
    metrics = RunMetrics(
        tests_added=1,
        first_run_total=1,
        first_run_passed=0,
        first_attempt_pass_pct=0.0,
        final_passed=0,
        final_failed=1,
        fix_attempts=2,
        coverage_before_pct=20.0,
        coverage_after_pct=25.0,
        coverage_delta_pct=5.0,
        prompt_tokens=5000,
        completion_tokens=2000,
        estimated_cost_usd=0.005,
        duration_s=15.2,
        stop_reason="max_steps",
    )

    comment = render_comment(metrics, written_tests=["tests/test_f.py"], model="test-model")

    lines = comment.strip().splitlines()
    assert lines
    assert lines[0] == "<!-- pr-test-agent -->"
    assert "Stopped early: max_steps" in comment
