"""Agent tools for inspecting diffs, reading/writing files, running tests and coverage."""

import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pr_test_agent.guards import GuardError, resolve_read_path, resolve_test_path


@dataclass(frozen=True)
class ChangedFunction:
    name: str
    is_async: bool
    start_line: int
    end_line: int


@dataclass(frozen=True)
class ChangedFile:
    path: str
    changed_lines: list[int]
    functions: list[ChangedFunction]


@dataclass(frozen=True)
class DiffResult:
    files: list[ChangedFile]
    diff_text: str
    truncated: bool


@dataclass(frozen=True)
class PytestResult:
    exit_code: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_s: float
    output: str
    timed_out: bool


@dataclass(frozen=True)
class CoverageResult:
    total_percent: float
    files_percent: float | None
    per_file: dict[str, float]
    exit_code: int


class _FunctionVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope: list[str] = []
        self.functions: list[ChangedFunction] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        name = ".".join(self.scope + [node.name])
        start = node.lineno
        end = node.end_lineno if node.end_lineno is not None else node.lineno
        self.functions.append(
            ChangedFunction(name=name, is_async=False, start_line=start, end_line=end)
        )
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        name = ".".join(self.scope + [node.name])
        start = node.lineno
        end = node.end_lineno if node.end_lineno is not None else node.lineno
        self.functions.append(
            ChangedFunction(name=name, is_async=True, start_line=start, end_line=end)
        )
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()


def _find_functions_for_lines(
    file_path: Path, changed_lines: list[int]
) -> list[ChangedFunction]:
    if not file_path.exists() or not changed_lines:
        return []
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return []

    visitor = _FunctionVisitor()
    visitor.visit(tree)
    if not visitor.functions:
        return []

    matched: dict[tuple[str, int, int], ChangedFunction] = {}
    for line in changed_lines:
        enclosing = [
            f for f in visitor.functions if f.start_line <= line <= f.end_line
        ]
        if enclosing:
            innermost = min(
                enclosing,
                key=lambda f: (f.end_line - f.start_line, -f.start_line),
            )
            key = (innermost.name, innermost.start_line, innermost.end_line)
            matched[key] = innermost

    return sorted(matched.values(), key=lambda f: f.start_line)


def _should_skip_diff_file(path_str: str) -> bool:
    p = Path(path_str)
    return "tests" in p.parts or fnmatch.fnmatch(p.name, "test_*.py") or p.name == "conftest.py"


def _parse_diff_output(repo_root: Path, diff_text: str) -> list[ChangedFile]:
    file_chunks: list[tuple[str, list[str]]] = []
    current_file: str | None = None
    current_lines: list[str] = []

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if current_file is not None:
                file_chunks.append((current_file, current_lines))
            current_file = None
            current_lines = []
        elif line.startswith("+++ b/"):
            current_file = line[6:].strip()
        current_lines.append(line)

    if current_file is not None:
        file_chunks.append((current_file, current_lines))

    result: list[ChangedFile] = []
    hunk_regex = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

    for file_path, lines in file_chunks:
        if _should_skip_diff_file(file_path):
            continue

        changed_lines: list[int] = []
        in_hunk = False
        new_lineno = 0

        idx = 0
        while idx < len(lines):
            line = lines[idx]
            match = hunk_regex.match(line)
            if match:
                in_hunk = True
                new_lineno = int(match.group(1))
                idx += 1
                continue

            if not in_hunk:
                idx += 1
                continue

            if line.startswith("+") and not line.startswith("+++"):
                changed_lines.append(new_lineno)
                new_lineno += 1
                idx += 1
            elif line.startswith("-") and not line.startswith("---"):
                while (
                    idx < len(lines)
                    and lines[idx].startswith("-")
                    and not lines[idx].startswith("---")
                ):
                    idx += 1
                if idx < len(lines) and lines[idx].startswith("+") and not lines[idx].startswith("+++"):
                    pass
                else:
                    changed_lines.append(max(1, new_lineno))
            elif line.startswith(" "):
                new_lineno += 1
                idx += 1
            else:
                idx += 1

        unique_lines = sorted(set(changed_lines))
        abs_path = repo_root / file_path
        functions = _find_functions_for_lines(abs_path, unique_lines)
        result.append(
            ChangedFile(
                path=file_path,
                changed_lines=unique_lines,
                functions=functions,
            )
        )

    return result


def read_diff(
    repo_root: Path, base_ref: str, max_chars: int = 20000
) -> DiffResult:
    """Run git diff against base_ref and analyze changed Python files and functions."""
    cmd = [
        "git",
        "diff",
        "--unified=3",
        "--no-color",
        "--diff-filter=AM",
        f"{base_ref}...HEAD",
        "--",
        "*.py",
    ]
    proc = subprocess.run(
        cmd,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
    )
    raw_diff = proc.stdout
    files = _parse_diff_output(repo_root, raw_diff)

    truncated = len(raw_diff) > max_chars
    diff_text = raw_diff[:max_chars] if truncated else raw_diff
    return DiffResult(files=files, diff_text=diff_text, truncated=truncated)


def read_file(repo_root: Path, rel_path: str, max_chars: int = 20000) -> str:
    """Read a repository file within limits, respecting path guards."""
    resolved = resolve_read_path(repo_root, rel_path)
    content = resolved.read_text(encoding="utf-8")
    if len(content) > max_chars:
        return content[:max_chars]
    return content


def write_test(repo_root: Path, rel_path: str, content: str) -> Path:
    """Write test file inside tests/ after validating Python syntax and path guards."""
    resolved = resolve_test_path(repo_root, rel_path)
    try:
        ast.parse(content)
    except SyntaxError as exc:
        raise GuardError(f"Invalid Python syntax: {exc}") from exc

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return resolved


def _parse_junit_xml(xml_path: Path) -> tuple[int, int, int, int, float]:
    if not xml_path.exists():
        return (0, 0, 0, 0, 0.0)
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except (ET.ParseError, OSError):
        return (0, 0, 0, 0, 0.0)

    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    if not suites and root.tag == "testsuites":
        suites = [root]

    failures = 0
    errors = 0
    skipped = 0
    tests = 0
    duration = 0.0

    for suite in suites:
        failures += int(suite.attrib.get("failures", 0))
        errors += int(suite.attrib.get("errors", 0))
        skipped += int(suite.attrib.get("skipped", 0))
        tests += int(suite.attrib.get("tests", 0))
        duration += float(suite.attrib.get("time", 0.0))

    passed = max(0, tests - failures - errors - skipped)
    return (passed, failures, errors, skipped, duration)


def run_pytest(
    repo_root: Path,
    targets: list[str] | None = None,
    python: str = sys.executable,
    timeout: int = 120,
) -> PytestResult:
    """Run pytest with JUnit XML output and timeout guard."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        junit_path = Path(tmp_dir) / "junit.xml"
        cmd = [
            python,
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            "-p",
            "no:cacheprovider",
            f"--junitxml={junit_path}",
        ]
        if targets:
            cmd.extend(targets)

        timed_out = False
        stdout = ""
        stderr = ""
        exit_code = 0

        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        try:
            proc = subprocess.run(
                cmd,
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                stdin=subprocess.DEVNULL,
            )
            exit_code = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = -1
            stdout = (
                exc.stdout.decode("utf-8", errors="replace")
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or "")
            )
            stderr = (
                exc.stderr.decode("utf-8", errors="replace")
                if isinstance(exc.stderr, bytes)
                else (exc.stderr or "")
            )

        raw_output = stdout + stderr
        output = raw_output[-4000:] if len(raw_output) > 4000 else raw_output
        passed, failed, errors, skipped, duration_s = _parse_junit_xml(junit_path)

        return PytestResult(
            exit_code=exit_code,
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            duration_s=duration_s,
            output=output,
            timed_out=timed_out,
        )


def _should_skip_coverage_file(rel_path: str) -> bool:
    p = Path(rel_path)
    return (
        "tests" in p.parts
        or ".venv" in p.parts
        or "venv" in p.parts
        or fnmatch.fnmatch(p.name, "test_*.py")
        or p.name == "conftest.py"
    )


def get_coverage(
    repo_root: Path,
    files: list[str] | None = None,
    python: str = sys.executable,
    timeout: int = 300,
) -> CoverageResult:
    """Run pytest-cov safely without modifying repository files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        cov_json = Path(tmp_dir) / "coverage.json"
        cov_file = Path(tmp_dir) / ".coverage"
        env = dict(os.environ)
        env["COVERAGE_FILE"] = str(cov_file)
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        cmd = [
            python,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--cov=.",
            f"--cov-report=json:{cov_json}",
        ]

        exit_code = 0
        try:
            proc = subprocess.run(
                cmd,
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                stdin=subprocess.DEVNULL,
            )
            exit_code = proc.returncode
        except (subprocess.TimeoutExpired, OSError):
            exit_code = -1

        if not cov_json.exists():
            return CoverageResult(
                total_percent=0.0,
                files_percent=0.0 if files is not None else None,
                per_file={},
                exit_code=exit_code,
            )

        try:
            data = json.loads(cov_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return CoverageResult(
                total_percent=0.0,
                files_percent=0.0 if files is not None else None,
                per_file={},
                exit_code=exit_code,
            )

        raw_files: dict[str, Any] = data.get("files", {})
        per_file: dict[str, float] = {}
        total_covered = 0
        total_statements = 0
        file_stats: dict[str, dict[str, int]] = {}

        root_resolved = repo_root.resolve()
        for f_path, f_info in raw_files.items():
            try:
                rel = Path(f_path).resolve().relative_to(root_resolved).as_posix()
            except ValueError:
                rel = Path(f_path).as_posix()

            if _should_skip_coverage_file(rel):
                continue

            summary = f_info.get("summary", {})
            covered = int(summary.get("covered_lines", 0))
            statements = int(summary.get("num_statements", 0))
            percent = (covered / statements * 100.0) if statements > 0 else 0.0

            per_file[rel] = percent
            file_stats[rel] = {"covered": covered, "statements": statements}
            total_covered += covered
            total_statements += statements

        total_percent = (
            (total_covered / total_statements * 100.0)
            if total_statements > 0
            else 0.0
        )

        files_percent: float | None = None
        if files is not None:
            f_covered = 0
            f_statements = 0
            for target_file in files:
                norm = Path(target_file).as_posix()
                stats = file_stats.get(norm)
                if not stats:
                    for rel, s in file_stats.items():
                        if rel == norm or rel.endswith(f"/{norm}"):
                            stats = s
                            break
                if stats:
                    f_covered += stats["covered"]
                    f_statements += stats["statements"]

            files_percent = (
                (f_covered / f_statements * 100.0) if f_statements > 0 else 0.0
            )

        return CoverageResult(
            total_percent=total_percent,
            files_percent=files_percent,
            per_file=per_file,
            exit_code=exit_code,
        )
