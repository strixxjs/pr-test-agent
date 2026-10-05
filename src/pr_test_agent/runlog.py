"""JSONL run logging and secret redaction."""

import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self, TextIO

GSK_PATTERN = re.compile(r"gsk_[A-Za-z0-9]+")


def redact_data(obj: Any) -> Any:
    """Recursively redact Groq API keys from strings, dicts, lists, and tuples."""
    env_key = os.environ.get("GROQ_API_KEY")

    def _redact_str(s: str) -> str:
        s = GSK_PATTERN.sub("[REDACTED]", s)
        if env_key:
            s = s.replace(env_key, "[REDACTED]")
        return s

    if isinstance(obj, str):
        return _redact_str(obj)
    if isinstance(obj, dict):
        return {
            _redact_str(k) if isinstance(k, str) else k: redact_data(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_data(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(redact_data(item) for item in obj)
    return obj


def make_log_path(log_dir: Path, run_id: str | None = None) -> Path:
    """Create directory and return path to run log file."""
    log_dir.mkdir(parents=True, exist_ok=True)
    suffix = run_id if run_id else datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return log_dir / f"run-{suffix}.jsonl"


class RunLog:
    """Context manager for append-only JSONL run logs with secret redaction."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: TextIO | None = None

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", encoding="utf-8")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def write(self, event: dict[str, Any]) -> None:
        """Write an event dictionary as a JSON line with UTC timestamp and secret redaction."""
        event_copy = dict(event)
        event_copy["ts"] = datetime.now(UTC).isoformat()
        clean_event = redact_data(event_copy)
        line = json.dumps(clean_event) + "\n"

        if self._file is not None:
            self._file.write(line)
            self._file.flush()
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()

    def as_callback(self) -> Callable[[dict[str, Any]], None]:
        """Return a callback function suitable for run_agent on_event."""
        return self.write
