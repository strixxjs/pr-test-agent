import json
from pathlib import Path
from typing import Any

import pytest

from pr_test_agent.cli import main
from pr_test_agent.llm import LLMReply, ToolCall


class FakeCLIClient:
    def __init__(self, replies: list[LLMReply | Exception]) -> None:
        self.replies = list(replies)
        self.call_count = 0

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMReply:
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
            completion_tokens=5,
        )


def test_cli_missing_env_returns_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)

    code = main(["run", "--base", "main"])
    assert code == 2


def test_cli_full_run_with_fake_client(
    git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    monkeypatch.chdir(work_dir)

    monkeypatch.setenv("GROQ_API_KEY", "fake_cli_key")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    test_content = "def test_cli_add() -> None:\n    assert True\n"
    replies = [
        LLMReply(
            content=None,
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="write_test",
                    arguments={
                        "path": "tests/test_cli_add.py",
                        "content": test_content,
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
                    id="c2",
                    name="run_pytest",
                    arguments={"targets": ["tests/test_cli_add.py"]},
                )
            ],
            prompt_tokens=40,
            completion_tokens=10,
        ),
        LLMReply(
            content="Tests written and verified.",
            tool_calls=[],
            prompt_tokens=20,
            completion_tokens=5,
        ),
    ]

    client = FakeCLIClient(replies)

    json_file = work_dir / "results.json"
    comment_file = work_dir / "comment.md"
    log_dir = work_dir / "logs"

    argv = [
        "run",
        "--repo",
        str(git_repo),
        "--base",
        "main",
        "--log-dir",
        str(log_dir),
        "--json-out",
        str(json_file),
        "--comment-out",
        str(comment_file),
    ]

    exit_code = main(argv, client_factory=lambda: client)
    assert exit_code == 0

    # Verify comment output
    assert comment_file.exists()
    comment_text = comment_file.read_text(encoding="utf-8")
    assert "<!-- pr-test-agent -->" in comment_text
    assert "## PR Test Agent" in comment_text

    # Verify stdout has comment
    captured = capsys.readouterr()
    assert "<!-- pr-test-agent -->" in captured.out
    assert "Log:" in captured.err

    # Verify JSON output
    assert json_file.exists()
    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert data["stop_reason"] == "done"
    assert "metrics" in data
    assert "tests_added" in data["metrics"]
    assert data["metrics"]["tests_added"] == 1

    # Verify log file exists
    log_files = list(log_dir.glob("run-*.jsonl"))
    assert len(log_files) == 1
    assert log_files[0].stat().st_size > 0


def test_cli_version(capsys: pytest.CaptureFixture) -> None:
    code = main([])
    assert code == 0
    captured = capsys.readouterr()
    assert "pr-test-agent 0.1.0" in captured.out


def test_cli_error_prints_final_message_to_stderr(
    git_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    monkeypatch.chdir(work_dir)
    monkeypatch.setenv("GROQ_API_KEY", "fake_cli_key")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    reply1 = LLMReply(
        content=None,
        tool_calls=[
            ToolCall(
                id="c1",
                name="write_test",
                arguments={
                    "path": "tests/test_cli_err.py",
                    "content": "def test_cli_err() -> None: assert True\n",
                },
            )
        ],
        prompt_tokens=20,
        completion_tokens=10,
    )
    client = FakeCLIClient([reply1, RuntimeError("API connection dropped")])

    argv = ["run", "--repo", str(git_repo), "--base", "main"]
    exit_code = main(argv, client_factory=lambda: client)
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "RuntimeError: API connection dropped" in captured.err
