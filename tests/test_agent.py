import json
from pathlib import Path
from typing import Any

import pytest

from pr_test_agent.agent import Limits, run_agent
from pr_test_agent.llm import LLMReply, LLMToolCallError, ToolCall
from pr_test_agent.runlog import RunLog


class FakeClient:
    def __init__(self, replies: list[LLMReply | Exception]) -> None:
        self.replies = list(replies)
        self.call_count = 0
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMReply:
        self.calls.append((list(messages), tools))
        if self.call_count < len(self.replies):
            reply = self.replies[self.call_count]
            self.call_count += 1
            if isinstance(reply, Exception):
                raise reply
            return reply
        return LLMReply(
            content="Done",
            tool_calls=[],
            prompt_tokens=10,
            completion_tokens=10,
        )


def test_agent_happy_path(git_repo: Path) -> None:
    test_code = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))\n"
        "from math_ops import add, async_mul\n\n"
        "def test_math_add() -> None:\n"
        "    assert add(1, 2) == 3\n"
        "    assert callable(async_mul)\n"
    )
    replies = [
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="write_test",
                    arguments={"path": "tests/test_math_add.py", "content": test_code},
                )
            ],
            prompt_tokens=50,
            completion_tokens=20,
        ),
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_2",
                    name="run_pytest",
                    arguments={"targets": ["tests/test_math_add.py"]},
                )
            ],
            prompt_tokens=60,
            completion_tokens=15,
        ),
        LLMReply(
            content="All tests pass successfully.",
            tool_calls=[],
            prompt_tokens=40,
            completion_tokens=10,
        ),
    ]
    client = FakeClient(replies)
    result = run_agent(git_repo, "main", client)

    assert result.stop_reason == "done"
    assert result.written_tests == ["tests/test_math_add.py"]
    assert len(result.pytest_runs) == 1
    assert result.pytest_runs[0].passed >= 1
    assert result.final_message == "All tests pass successfully."
    assert result.steps == 3


def test_agent_fix_path(git_repo: Path) -> None:
    failing_test = "def test_fail() -> None:\n    assert False  # add async_mul\n"
    passing_test = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))\n"
        "from math_ops import add, async_mul\n\n"
        "def test_pass() -> None:\n"
        "    assert add(1, 2) == 3\n"
        "    assert callable(async_mul)\n"
    )
    replies = [
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="write_test",
                    arguments={"path": "tests/test_fix.py", "content": failing_test},
                )
            ],
            prompt_tokens=50,
            completion_tokens=20,
        ),
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_2",
                    name="run_pytest",
                    arguments={"targets": ["tests/test_fix.py"]},
                )
            ],
            prompt_tokens=60,
            completion_tokens=15,
        ),
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_3",
                    name="write_test",
                    arguments={"path": "tests/test_fix.py", "content": passing_test},
                )
            ],
            prompt_tokens=70,
            completion_tokens=20,
        ),
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_4",
                    name="run_pytest",
                    arguments={"targets": ["tests/test_fix.py"]},
                )
            ],
            prompt_tokens=80,
            completion_tokens=15,
        ),
        LLMReply(
            content="Tests fixed and passed.",
            tool_calls=[],
            prompt_tokens=30,
            completion_tokens=10,
        ),
    ]
    client = FakeClient(replies)
    result = run_agent(git_repo, "main", client)

    assert result.stop_reason == "done"
    assert len(result.pytest_runs) == 2
    assert result.pytest_runs[0].failed == 1
    assert result.pytest_runs[1].passed == 1


def test_agent_fix_attempts_exhausted(git_repo: Path) -> None:
    failing_test = "def test_fail() -> None:\n    assert False\n"
    replies = [
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="write_test",
                    arguments={"path": "tests/test_exhaust.py", "content": failing_test},
                )
            ],
            prompt_tokens=20,
            completion_tokens=10,
        ),
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="c2",
                    name="run_pytest",
                    arguments={"targets": ["tests/test_exhaust.py"]},
                )
            ],
            prompt_tokens=20,
            completion_tokens=10,
        ),
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="c3",
                    name="write_test",
                    arguments={"path": "tests/test_exhaust.py", "content": failing_test},
                )
            ],
            prompt_tokens=20,
            completion_tokens=10,
        ),
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="c4",
                    name="run_pytest",
                    arguments={"targets": ["tests/test_exhaust.py"]},
                )
            ],
            prompt_tokens=20,
            completion_tokens=10,
        ),
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="c5",
                    name="write_test",
                    arguments={"path": "tests/test_exhaust.py", "content": failing_test},
                )
            ],
            prompt_tokens=20,
            completion_tokens=10,
        ),
    ]
    client = FakeClient(replies)
    limits = Limits(max_fix_attempts=1)
    result = run_agent(git_repo, "main", client, limits=limits)

    assert result.stop_reason == "fix_attempts_exhausted"


def test_agent_max_steps(git_repo: Path) -> None:
    replies = [
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id=f"step_{i}",
                    name="read_file",
                    arguments={"path": "src/math_ops.py"},
                )
            ],
            prompt_tokens=10,
            completion_tokens=10,
        )
        for i in range(5)
    ]
    client = FakeClient(replies)
    limits = Limits(max_steps=2)
    result = run_agent(git_repo, "main", client, limits=limits)

    assert result.stop_reason == "max_steps"
    assert result.steps == 2


def test_agent_token_budget(git_repo: Path) -> None:
    replies = [
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="read_file",
                    arguments={"path": "src/math_ops.py"},
                )
            ],
            prompt_tokens=60,
            completion_tokens=50,
        ),
        LLMReply(
            content="Done",
            tool_calls=[],
            prompt_tokens=10,
            completion_tokens=10,
        ),
    ]
    client = FakeClient(replies)
    limits = Limits(max_total_tokens=100)
    result = run_agent(git_repo, "main", client, limits=limits)

    assert result.stop_reason == "token_budget"
    assert result.total_tokens == 110


def test_agent_guard_error_preserves_production_file(git_repo: Path) -> None:
    prod_file = git_repo / "src" / "math_ops.py"
    original_code = prod_file.read_text(encoding="utf-8")

    replies = [
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="write_test",
                    arguments={
                        "path": "src/math_ops.py",
                        "content": "def hacked() -> None: pass\n",
                    },
                )
            ],
            prompt_tokens=20,
            completion_tokens=10,
        ),
        LLMReply(
            content="Cannot write to production files.",
            tool_calls=[],
            prompt_tokens=20,
            completion_tokens=10,
        ),
    ]
    client = FakeClient(replies)
    result = run_agent(git_repo, "main", client)

    assert result.stop_reason == "done"
    assert prod_file.read_text(encoding="utf-8") == original_code

    second_call_messages = client.calls[1][0]
    tool_resp = next(m for m in second_call_messages if m.get("role") == "tool")
    assert tool_resp["content"].startswith("ERROR: Path must be inside tests directory")


def test_agent_no_changed_functions(git_repo: Path) -> None:
    client = FakeClient([])
    # Comparing feature branch against feature branch yields no changes
    result = run_agent(git_repo, "feature", client)

    assert result.stop_reason == "done"
    assert result.steps == 0
    assert client.call_count == 0


def test_agent_events_emitted(git_repo: Path) -> None:
    events: list[dict[str, Any]] = []
    replies = [
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="read_file",
                    arguments={"path": "src/math_ops.py"},
                )
            ],
            prompt_tokens=15,
            completion_tokens=10,
        ),
        LLMReply(
            content="Finished inspecting.",
            tool_calls=[],
            prompt_tokens=15,
            completion_tokens=5,
        ),
    ]
    client = FakeClient(replies)
    result = run_agent(git_repo, "main", client, on_event=events.append)

    assert result.stop_reason == "done"
    assert len(events) >= 3  # 2 llm events + 1 tool event

    types = [e["type"] for e in events]
    assert "llm" in types
    assert "tool" in types

    for ev in events:
        assert "type" in ev
        assert "step" in ev
        assert "name" in ev
        assert "tokens" in ev


def test_agent_error_on_second_llm_call(git_repo: Path, tmp_path: Path) -> None:
    reply1 = LLMReply(
        content=None,
        tool_calls=[
            ToolCall(
                id="call_1",
                name="write_test",
                arguments={
                    "path": "tests/test_err.py",
                    "content": "def test_err() -> None:\n    assert True\n",
                },
            )
        ],
        prompt_tokens=20,
        completion_tokens=10,
    )
    client = FakeClient([reply1, RuntimeError("Groq server failure")])
    log_file = tmp_path / "run.jsonl"
    with RunLog(log_file) as run_log:
        result = run_agent(git_repo, "main", client, on_event=run_log.as_callback())

    assert result.stop_reason == "error"
    assert result.final_message != ""
    assert "RuntimeError: Groq server failure" in result.final_message

    lines = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
    ]
    error_events = [ev for ev in lines if ev.get("type") == "error"]
    assert len(error_events) == 1
    err_ev = error_events[0]
    assert err_ev["where"] == "llm"
    assert err_ev["error_type"] == "RuntimeError"
    assert "Groq server failure" in err_ev["message"]


def test_agent_error_on_setup(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    events: list[dict[str, Any]] = []
    client = FakeClient([])
    result = run_agent(empty_dir, "main", client, on_event=events.append)

    assert result.stop_reason == "error"
    assert result.final_message != ""
    error_events = [ev for ev in events if ev.get("type") == "error"]
    assert len(error_events) == 1
    assert error_events[0]["where"] == "setup"


def test_agent_error_on_tool_execution(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reply = LLMReply(
        content=None,
        tool_calls=[
            ToolCall(
                id="call_1",
                name="read_file",
                arguments={"path": "src/math_ops.py"},
            )
        ],
        prompt_tokens=10,
        completion_tokens=10,
    )

    def _crash(*_args: Any, **_kwargs: Any) -> str:
        raise OSError("Simulated disk read crash")

    monkeypatch.setattr("pr_test_agent.agent.read_file", _crash)

    events: list[dict[str, Any]] = []
    client = FakeClient([reply])
    result = run_agent(git_repo, "main", client, on_event=events.append)

    assert result.stop_reason == "error"
    assert "OSError: Simulated disk read crash" in result.final_message
    error_events = [ev for ev in events if ev.get("type") == "error"]
    assert len(error_events) == 1
    assert error_events[0]["where"] == "tool"


def test_agent_nudge_when_function_missing(git_repo: Path) -> None:
    # Model only tests add at first, gets nudged, then tests async_mul
    test_add_only = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))\n"
        "from math_ops import add\n\n"
        "def test_math_add():\n"
        "    assert add(1, 2) == 3\n"
    )
    test_async_mul = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))\n"
        "from math_ops import async_mul\n\n"
        "def test_math_mul():\n"
        "    assert callable(async_mul)\n"
    )
    replies = [
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="write_test",
                    arguments={
                        "path": "tests/test_math_add.py",
                        "content": test_add_only,
                    },
                )
            ],
            prompt_tokens=30,
            completion_tokens=15,
        ),
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_2",
                    name="run_pytest",
                    arguments={"targets": ["tests/test_math_add.py"]},
                )
            ],
            prompt_tokens=40,
            completion_tokens=10,
        ),
        # Model tries to finish having only tested add
        LLMReply(
            content="Finished writing tests for add.",
            tool_calls=[],
            prompt_tokens=20,
            completion_tokens=5,
        ),
        # After nudge, model writes test for async_mul
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_3",
                    name="write_test",
                    arguments={
                        "path": "tests/test_math_mul.py",
                        "content": test_async_mul,
                    },
                )
            ],
            prompt_tokens=40,
            completion_tokens=15,
        ),
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_4",
                    name="run_pytest",
                    arguments={"targets": ["tests/test_math_mul.py"]},
                )
            ],
            prompt_tokens=40,
            completion_tokens=10,
        ),
        # Model finishes
        LLMReply(
            content="Now all functions tested.",
            tool_calls=[],
            prompt_tokens=20,
            completion_tokens=5,
        ),
    ]

    client = FakeClient(replies)
    result = run_agent(git_repo, "main", client)

    assert result.stop_reason == "done"
    assert result.uncovered_functions == []
    assert result.functions_total == 2
    assert result.functions_referenced == 2

    # Verify that the 4th client call (after nudge) has the nudge message
    fourth_call_messages = client.calls[3][0]
    nudge_user_msg = fourth_call_messages[-1]
    assert nudge_user_msg["role"] == "user"
    assert (
        "Missing tests for: src/math_ops.py:async_mul. Write them now, then run pytest."
        in nudge_user_msg["content"]
    )


def test_agent_nudge_ignored_twice_stops_done_with_uncovered(git_repo: Path) -> None:
    test_add_only = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))\n"
        "from math_ops import add\n\n"
        "def test_math_add():\n"
        "    assert add(1, 2) == 3\n"
    )
    replies = [
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="write_test",
                    arguments={
                        "path": "tests/test_math_add.py",
                        "content": test_add_only,
                    },
                )
            ],
            prompt_tokens=30,
            completion_tokens=15,
        ),
        # Model tries to finish
        LLMReply(
            content="Done with add.",
            tool_calls=[],
            prompt_tokens=20,
            completion_tokens=5,
        ),
        # Model ignores nudge 1
        LLMReply(
            content="Ignoring nudge 1.",
            tool_calls=[],
            prompt_tokens=20,
            completion_tokens=5,
        ),
        # Model ignores nudge 2
        LLMReply(
            content="Ignoring nudge 2.",
            tool_calls=[],
            prompt_tokens=20,
            completion_tokens=5,
        ),
    ]

    client = FakeClient(replies)
    result = run_agent(git_repo, "main", client)

    assert result.stop_reason == "done"
    assert result.uncovered_functions == ["src/math_ops.py:async_mul"]
    assert result.functions_total == 2
    assert result.functions_referenced == 1


def test_agent_tool_use_failed_retry_once_then_success(git_repo: Path) -> None:
    test_code = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))\n"
        "from math_ops import add, async_mul\n\n"
        "def test_math_add():\n"
        "    assert add(1, 2) == 3\n"
        "    assert callable(async_mul)\n"
    )
    replies: list[LLMReply | Exception] = [
        LLMToolCallError("tool_use_failed: Failed to parse tool call arguments as JSON"),
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="write_test",
                    arguments={"path": "tests/test_retry.py", "content": test_code},
                )
            ],
            prompt_tokens=30,
            completion_tokens=15,
        ),
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_2",
                    name="run_pytest",
                    arguments={"targets": ["tests/test_retry.py"]},
                )
            ],
            prompt_tokens=40,
            completion_tokens=10,
        ),
        LLMReply(
            content="Tests passed.",
            tool_calls=[],
            prompt_tokens=20,
            completion_tokens=5,
        ),
    ]

    events: list[dict[str, Any]] = []
    client = FakeClient(replies)
    result = run_agent(git_repo, "main", client, on_event=events.append)

    assert result.stop_reason == "done"
    retry_events = [e for e in events if e.get("type") == "retry"]
    assert len(retry_events) == 1
    assert retry_events[0]["reason"] == "tool_use_failed"
    assert retry_events[0]["attempt"] == 1

    second_call_messages = client.calls[1][0]
    last_msg = second_call_messages[-1]
    assert last_msg["role"] == "user"
    assert "Your last tool call was rejected because its JSON arguments were invalid." in last_msg["content"]


def test_agent_four_tool_use_failed_stops_with_error(git_repo: Path) -> None:
    replies: list[LLMReply | Exception] = [
        LLMToolCallError("tool_use_failed: 1"),
        LLMToolCallError("tool_use_failed: 2"),
        LLMToolCallError("tool_use_failed: 3"),
        LLMToolCallError("tool_use_failed: 4"),
    ]
    events: list[dict[str, Any]] = []
    client = FakeClient(replies)
    result = run_agent(git_repo, "main", client, on_event=events.append)

    assert result.stop_reason == "error"
    assert "LLMToolCallError" in result.final_message
    retry_events = [e for e in events if e.get("type") == "retry"]
    assert len(retry_events) == 3
    assert [e["attempt"] for e in retry_events] == [1, 2, 3]

    error_events = [e for e in events if e.get("type") == "error"]
    assert len(error_events) == 1
    assert error_events[0]["error_type"] == "LLMToolCallError"
