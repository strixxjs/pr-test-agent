"""Agent loop for analyzing PR diffs, writing tests, and fixing failures."""

import contextlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pr_test_agent.guards import GuardError
from pr_test_agent.llm import LLMClient
from pr_test_agent.runlog import redact_data
from pr_test_agent.tools import (
    PytestResult,
    get_coverage,
    read_diff,
    read_file,
    run_pytest,
    write_test,
)

SYSTEM_PROMPT = (
    "You are an expert test agent that writes pytest tests for code changed in a pull request. "
    "Write tests only for the changed functions. Use pytest-asyncio for async functions. "
    "Write tests only under tests/ with file names matching test_*.py. "
    "Never edit production code. After writing tests, run pytest. "
    "If tests fail, fix the test (never the production code). "
    "Stop with a one-line summary when tests pass."
)

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read content of a file in the repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_test",
            "description": "Write a test file inside tests/ directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path inside tests/, e.g. tests/test_foo.py",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full python test code",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_pytest",
            "description": "Run pytest on the test suite or specific targets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "targets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of test files or targets to run",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_coverage",
            "description": "Run pytest and calculate line coverage without modifying the repo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of files to check coverage for",
                    },
                },
            },
        },
    },
]


@dataclass
class Limits:
    max_steps: int = 12
    max_total_tokens: int = 60000
    max_fix_attempts: int = 3
    max_tool_output_chars: int = 3000


@dataclass
class AgentResult:
    stop_reason: str
    steps: int
    total_tokens: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    pytest_runs: list[PytestResult] = field(default_factory=list)
    written_tests: list[str] = field(default_factory=list)
    final_message: str = ""


def _emit_event(
    on_event: Callable[[dict[str, Any]], None] | None, event: dict[str, Any]
) -> None:
    if on_event is not None:
        with contextlib.suppress(Exception):
            on_event(event)


def run_agent(
    repo_root: Path,
    base_ref: str,
    client: LLMClient,
    limits: Limits | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    python: str = sys.executable,
) -> AgentResult:
    """Execute the PR test writing agent loop."""
    active_limits = limits if limits is not None else Limits()
    try:
        diff_res = read_diff(repo_root, base_ref)
        has_changed_funcs = any(len(f.functions) > 0 for f in diff_res.files)
        if not has_changed_funcs:
            return AgentResult(
                stop_reason="done",
                steps=0,
                total_tokens=0,
                prompt_tokens=0,
                completion_tokens=0,
                pytest_runs=[],
                written_tests=[],
                final_message="No changed functions found in diff.",
            )

        file_summaries: list[str] = []
        for f in diff_res.files:
            func_strs = [
                f"{fn.name} ({'async' if fn.is_async else 'sync'}, lines {fn.start_line}-{fn.end_line})"
                for fn in f.functions
            ]
            file_summaries.append(
                f"File: {f.path}\nChanged functions: {', '.join(func_strs) if func_strs else 'none'}"
            )

        first_user_content = (
            "Please write pytest tests for the following changed code in this PR.\n\n"
            + "\n".join(file_summaries)
            + "\n\nGit diff:\n"
            + diff_res.diff_text
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": first_user_content},
        ]
    except Exception as exc:  # noqa: BLE001
        err_type = type(exc).__name__
        msg = str(redact_data(str(exc)[:800]))
        _emit_event(
            on_event,
            {
                "type": "error",
                "where": "setup",
                "step": 0,
                "error_type": err_type,
                "message": msg,
            },
        )
        return AgentResult(
            stop_reason="error",
            steps=0,
            total_tokens=0,
            prompt_tokens=0,
            completion_tokens=0,
            pytest_runs=[],
            written_tests=[],
            final_message=f"{err_type}: {msg}",
        )

    steps = 0
    total_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0
    pytest_runs: list[PytestResult] = []
    written_tests: list[str] = []
    final_message = ""
    stop_reason = "done"

    last_pytest_failed = False
    fix_attempts = 0

    while True:
        if steps >= active_limits.max_steps:
            stop_reason = "max_steps"
            break
        if total_tokens >= active_limits.max_total_tokens:
            stop_reason = "token_budget"
            break

        steps += 1

        try:
            reply = client.chat(messages=messages, tools=TOOL_DEFINITIONS)
        except Exception as exc:  # noqa: BLE001
            err_type = type(exc).__name__
            msg = str(redact_data(str(exc)[:800]))
            stop_reason = "error"
            final_message = f"{err_type}: {msg}"
            _emit_event(
                on_event,
                {
                    "type": "error",
                    "where": "llm",
                    "step": steps,
                    "error_type": err_type,
                    "message": msg,
                },
            )
            break

        prompt_tokens += reply.prompt_tokens
        completion_tokens += reply.completion_tokens
        call_tokens = reply.prompt_tokens + reply.completion_tokens
        total_tokens += call_tokens

        res_summary = (
            reply.content[:200]
            if reply.content
            else f"{len(reply.tool_calls)} tool calls"
        )
        _emit_event(
            on_event,
            {
                "type": "llm",
                "step": steps,
                "name": "chat",
                "args_summary": f"{len(messages)} messages",
                "result_summary": res_summary,
                "tokens": call_tokens,
            },
        )

        if not reply.tool_calls:
            stop_reason = "done"
            final_message = reply.content or ""
            break

        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": reply.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": (
                            tc.raw_arguments
                            if tc.raw_arguments is not None
                            else json.dumps(tc.arguments)
                        ),
                    },
                }
                for tc in reply.tool_calls
            ],
        }
        messages.append(assistant_msg)

        should_stop = False
        for tc in reply.tool_calls:
            tool_output = ""
            try:
                if tc.raw_arguments is not None:
                    tool_output = f"ERROR: Invalid JSON arguments: {tc.raw_arguments}"
                elif tc.name == "read_file":
                    path = tc.arguments.get("path", "")
                    try:
                        tool_output = read_file(repo_root, path)
                    except GuardError as ge:
                        tool_output = f"ERROR: {ge}"

                elif tc.name == "write_test":
                    path = tc.arguments.get("path", "")
                    content = tc.arguments.get("content", "")
                    if last_pytest_failed:
                        fix_attempts += 1
                        if fix_attempts > active_limits.max_fix_attempts:
                            stop_reason = "fix_attempts_exhausted"
                            should_stop = True
                            break

                    try:
                        written_path = write_test(repo_root, path, content)
                        if path not in written_tests:
                            written_tests.append(path)
                        tool_output = f"Wrote test file to {written_path}"
                    except GuardError as ge:
                        tool_output = f"ERROR: {ge}"

                elif tc.name == "run_pytest":
                    targets = tc.arguments.get("targets")
                    res = run_pytest(repo_root, targets=targets, python=python)
                    pytest_runs.append(res)
                    last_pytest_failed = (
                        res.failed > 0 or res.errors > 0 or res.exit_code != 0
                    )
                    tool_output = (
                        f"Exit code: {res.exit_code}, passed: {res.passed}, "
                        f"failed: {res.failed}, errors: {res.errors}, "
                        f"skipped: {res.skipped}, timed_out: {res.timed_out}\n"
                        f"Output:\n{res.output}"
                    )

                elif tc.name == "get_coverage":
                    files = tc.arguments.get("files")
                    cov = get_coverage(repo_root, files=files, python=python)
                    tool_output = (
                        f"Total coverage: {cov.total_percent:.2f}%, "
                        f"files coverage: {cov.files_percent}%\n"
                        f"Per file: {cov.per_file}"
                    )

                else:
                    tool_output = f"ERROR: Unknown tool '{tc.name}'"

            except Exception as exc:  # noqa: BLE001
                err_type = type(exc).__name__
                msg = str(redact_data(str(exc)[:800]))
                stop_reason = "error"
                final_message = f"{err_type}: {msg}"
                _emit_event(
                    on_event,
                    {
                        "type": "error",
                        "where": "tool",
                        "step": steps,
                        "error_type": err_type,
                        "message": msg,
                    },
                )
                should_stop = True
                break

            if should_stop:
                break

            if len(tool_output) > active_limits.max_tool_output_chars:
                tool_output = tool_output[: active_limits.max_tool_output_chars]

            args_str = json.dumps(tc.arguments) if tc.arguments else ""
            _emit_event(
                on_event,
                {
                    "type": "tool",
                    "step": steps,
                    "name": tc.name,
                    "args_summary": args_str[:200],
                    "result_summary": tool_output[:200],
                    "tokens": 0,
                },
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": tool_output,
                }
            )

        if should_stop:
            break

    return AgentResult(
        stop_reason=stop_reason,
        steps=steps,
        total_tokens=total_tokens,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        pytest_runs=pytest_runs,
        written_tests=written_tests,
        final_message=final_message,
    )
