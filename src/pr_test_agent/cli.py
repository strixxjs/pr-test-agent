"""Command line interface for pr-test-agent."""

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv

from pr_test_agent import __version__
from pr_test_agent.agent import Limits, run_agent
from pr_test_agent.llm import GroqClient, LLMClient
from pr_test_agent.metrics import compute_metrics, read_price_config_from_env
from pr_test_agent.report import render_comment
from pr_test_agent.runlog import RunLog, make_log_path
from pr_test_agent.tools import get_coverage, read_diff


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pr-test-agent",
        description="Autonomous agent that writes pytest tests for code changed in a pull request.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    run_parser = subparsers.add_parser(
        "run", help="Run the test agent on code changed in a pull request"
    )

    run_parser.add_argument(
        "--repo",
        default=".",
        help="Path to git repository (default: .)",
    )
    run_parser.add_argument(
        "--base",
        required=True,
        help="Base reference or commit to compare against (required)",
    )
    run_parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter to use (default: sys.executable)",
    )
    run_parser.add_argument(
        "--log-dir",
        default="./logs",
        help="Directory to save JSONL run logs (default: ./logs)",
    )
    run_parser.add_argument(
        "--json-out",
        help="Path to write JSON metrics output",
    )
    run_parser.add_argument(
        "--comment-out",
        help="Path to write markdown PR comment",
    )
    run_parser.add_argument(
        "--max-steps",
        type=int,
        help="Maximum number of agent steps",
    )
    run_parser.add_argument(
        "--max-tokens",
        type=int,
        help="Maximum total tokens allowed",
    )
    run_parser.add_argument(
        "--max-fix-attempts",
        type=int,
        help="Maximum fix attempts for failing tests",
    )

    return parser


def main(
    argv: list[str] | None = None,
    client_factory: Callable[[], LLMClient] = GroqClient,
) -> int:
    """Entry point for pr-test-agent CLI."""
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        print(f"pr-test-agent {__version__}")
        return 0

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "run":
        cwd_env = Path.cwd() / ".env"
        if cwd_env.is_file():
            load_dotenv(dotenv_path=cwd_env, override=False)

        api_key = os.environ.get("GROQ_API_KEY")
        model = os.environ.get("GROQ_MODEL")
        if not api_key:
            sys.stderr.write("ERROR: GROQ_API_KEY environment variable is not set.\n")
            return 2
        if not model:
            sys.stderr.write("ERROR: GROQ_MODEL environment variable is not set.\n")
            return 2

        repo_path = Path(args.repo).resolve()
        log_dir = Path(args.log_dir).resolve()
        limits = Limits(
            max_steps=args.max_steps if args.max_steps is not None else 12,
            max_total_tokens=args.max_tokens if args.max_tokens is not None else 60000,
            max_fix_attempts=(
                args.max_fix_attempts if args.max_fix_attempts is not None else 3
            ),
        )

        diff_res = read_diff(repo_path, args.base)
        changed_files = [f.path for f in diff_res.files]

        start_time = time.perf_counter()
        coverage_before = get_coverage(
            repo_path, files=changed_files, python=args.python
        )

        log_path = make_log_path(log_dir)
        sys.stderr.write(f"Log: {log_path}\n")

        client = client_factory()
        with RunLog(log_path) as run_log:
            result = run_agent(
                repo_root=repo_path,
                base_ref=args.base,
                client=client,
                limits=limits,
                on_event=run_log.as_callback(),
                python=args.python,
            )

        coverage_after = get_coverage(
            repo_path, files=changed_files, python=args.python
        )
        duration_s = time.perf_counter() - start_time

        price_in, price_out = read_price_config_from_env()
        metrics = compute_metrics(
            repo_root=repo_path,
            result=result,
            coverage_before=coverage_before,
            coverage_after=coverage_after,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            duration_s=duration_s,
            price_in_per_mtok=price_in,
            price_out_per_mtok=price_out,
        )

        comment = render_comment(
            metrics,
            result.written_tests,
            model=model,
            final_message=result.final_message,
        )
        print(comment)

        if args.comment_out:
            comment_path = Path(args.comment_out).resolve()
            comment_path.parent.mkdir(parents=True, exist_ok=True)
            comment_path.write_text(comment, encoding="utf-8")

        if args.json_out:
            json_path = Path(args.json_out).resolve()
            json_path.parent.mkdir(parents=True, exist_ok=True)
            out_data = {
                "metrics": metrics.to_dict(),
                "written_tests": result.written_tests,
                "stop_reason": result.stop_reason,
                "steps": result.steps,
            }
            json_path.write_text(json.dumps(out_data, indent=2), encoding="utf-8")

        if result.stop_reason != "done":
            print(result.final_message, file=sys.stderr)

        return 0 if result.stop_reason == "done" else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
