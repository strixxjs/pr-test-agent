import json
from pathlib import Path

import pytest

from pr_test_agent.runlog import RunLog, make_log_path, redact_data


def test_make_log_path(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs" / "subdir"
    path = make_log_path(log_dir, run_id="12345")
    assert path.name == "run-12345.jsonl"
    assert log_dir.is_dir()

    path_auto = make_log_path(log_dir)
    assert path_auto.name.startswith("run-")
    assert path_auto.name.endswith(".jsonl")


def test_redact_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "env_secret_key_999")

    raw = {
        "text": "Using key gsk_abc123XYZ and also env_secret_key_999",
        "nested": [
            "gsk_nestedkey",
            {"inner_key": "some text with gsk_secret", "normal": 42},
        ],
    }

    cleaned = redact_data(raw)
    assert cleaned["text"] == "Using key [REDACTED] and also [REDACTED]"
    assert cleaned["nested"][0] == "[REDACTED]"
    assert cleaned["nested"][1]["inner_key"] == "some text with [REDACTED]"
    assert cleaned["nested"][1]["normal"] == 42


def test_runlog_context_manager_and_flush(tmp_path: Path) -> None:
    log_file = tmp_path / "run.jsonl"

    with RunLog(log_file) as logger:
        logger.write({"event": "start", "secret": "gsk_test123"})
        # Verify file is flushed immediately
        assert log_file.exists()
        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["event"] == "start"
        assert data["secret"] == "[REDACTED]"
        assert "ts" in data

        logger.write({"event": "tool", "output": "done"})
        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    # Verify each line is valid JSON
    with log_file.open("r", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            assert isinstance(obj, dict)
            assert "ts" in obj


def test_runlog_callback(tmp_path: Path) -> None:
    log_file = tmp_path / "callback.jsonl"
    logger = RunLog(log_file)
    cb = logger.as_callback()

    cb({"msg": "hello from callback"})

    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["msg"] == "hello from callback"
    assert "ts" in data
