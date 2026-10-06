"""Tests for GitHub Action and workflow definitions."""

from pathlib import Path

import yaml


def _load_yaml(rel_path: str) -> dict:
    repo_root = Path(__file__).resolve().parent.parent
    file_path = repo_root / rel_path
    assert file_path.is_file(), f"File {rel_path} does not exist"
    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), f"Expected dict from {rel_path}"
    return data


def test_action_yml_structure() -> None:
    action = _load_yaml("action.yml")
    assert action.get("name") == "PR Test Agent"
    assert "description" in action
    runs = action.get("runs", {})
    assert runs.get("using") == "composite"

    inputs = action.get("inputs", {})
    assert "groq-api-key" in inputs
    assert inputs["groq-api-key"].get("required") is True

    expected_inputs = [
        "groq-api-key",
        "model",
        "python-version",
        "install-command",
        "base-ref",
        "max-steps",
        "max-tokens",
        "max-fix-attempts",
    ]
    for inp in expected_inputs:
        assert inp in inputs, f"Missing input {inp} in action.yml"

    assert inputs["model"].get("default") == "qwen/qwen3.8-27b"
    assert inputs["python-version"].get("default") == "3.12"
    assert inputs["install-command"].get("default") == "pip install -r requirements.txt"

    steps = runs.get("steps", [])
    assert len(steps) >= 5
    # Verify setup-python is used
    step_uses = [s.get("uses", "") for s in steps]
    assert any("setup-python" in u for u in step_uses)
    assert any("upload-artifact" in u for u in step_uses)

    # Verify no run block contains ${{ inputs.
    for step in steps:
        if "run" in step:
            assert "${{ inputs." not in step["run"], (
                f"step {step.get('name')} contains '${{{{ inputs.' in run block"
            )

        step_env = step.get("env", {})
        if step.get("name") == "Run pr-test-agent":
            assert step_env.get("GROQ_API_KEY") == "${{ inputs.groq-api-key }}"
        else:
            assert "GROQ_API_KEY" not in step_env
            for val in step_env.values():
                assert "inputs.groq-api-key" not in str(val)


def test_example_pr_test_agent_workflow() -> None:
    raw_text = (Path(__file__).resolve().parent.parent / "examples/pr-test-agent.yml").read_text(
        encoding="utf-8"
    )
    # Assert no pull_request_target in workflow text or parsed dict
    assert "pull_request_target" not in raw_text

    workflow = _load_yaml("examples/pr-test-agent.yml")

    # Trigger: pull_request only
    triggers = workflow.get("on") or workflow.get(True)
    if isinstance(triggers, dict):
        assert "pull_request" in triggers
        assert "pull_request_target" not in triggers
    elif isinstance(triggers, list):
        assert triggers == ["pull_request"]
    else:
        assert triggers == "pull_request"

    # Permissions minimal: contents: read, pull-requests: write
    perms = workflow.get("permissions", {})
    assert perms.get("contents") == "read"
    assert perms.get("pull-requests") == "write"
    # Ensure no excessive permissions
    for key in perms:
        assert key in ("contents", "pull-requests")

    # Concurrency
    concurrency = workflow.get("concurrency", {})
    assert concurrency.get("cancel-in-progress") is True

    # Job safety checks
    jobs = workflow.get("jobs", {})
    assert len(jobs) == 1
    job = next(iter(jobs.values()))

    # Timeout
    assert job.get("timeout-minutes") == 15

    # Fork guard
    fork_guard = "github.event.pull_request.head.repo.full_name == github.repository"
    job_if = job.get("if", "")
    assert fork_guard in job_if

    # Checkout fetch-depth: 0
    steps = job.get("steps", [])
    checkout_step = next(s for s in steps if "checkout" in s.get("uses", ""))
    assert checkout_step.get("with", {}).get("fetch-depth") == 0


def test_ci_workflow() -> None:
    raw_text = (Path(__file__).resolve().parent.parent / ".github/workflows/ci.yml").read_text(
        encoding="utf-8"
    )
    assert "pull_request_target" not in raw_text

    workflow = _load_yaml(".github/workflows/ci.yml")
    triggers = workflow.get("on") or workflow.get(True)
    if isinstance(triggers, (dict, list)):
        assert "pull_request_target" not in triggers

    perms = workflow.get("permissions", {})
    assert perms.get("contents") == "read"
