# Agent Guidelines

Practical patterns and guardrails for building and operating coding agents.

## Writing AGENTS.md / CLAUDE.md

Keep instruction files concise, directive, and high-signal. Avoid lengthy explanations; models follow short, unambiguous constraints best.

Key elements to include:
- **Commands to run**: Specify the exact lint and test commands (e.g., `ruff check .` and `pytest -q`).
- **Commit format**: Require conventional commit prefixes (`feat:`, `fix:`, `chore:`, `test:`, `docs:`).
- **Hard rules**: Explicit non-negotiables (never edit secrets, English only, type hints everywhere).
- **One-step-at-a-time**: Instruct the agent to execute only the current step without implementing future steps.

Example from this repo's `AGENTS.md`:
```markdown
- Type hints everywhere, small functions, no unused abstractions.
- Never open, print or commit .env or any secret. API keys come only from environment variables.
- Do only what the current step asks. Do not implement future steps.
- After each step run `ruff check .` and `pytest -q`. Commit only if both pass.
- One commit per step. Message format: `feat: ...`, `fix: ...`, `chore: ...`, `test: ...`, `docs: ...`.
- Before committing run `git status` and make sure .env is not staged.
```

## When to Grant Write Access

Autonomous code modification requires strict sandboxing:
- **Allowlist paths**: Only allow writes to `tests/` matching `test_*.py`. Never grant write access to application source code or repository configuration.
- **Validate content before write**: Run `ast.parse` on all generated Python files before persisting to disk to reject malformed syntax early.
- **Reject unsafe paths**: Block paths containing directory traversal (`..`) or symlinks to prevent escaping the workspace.
- **Protect secrets**: Never allow reading, writing, or logging `.env` files or credentials.
- **Strip secrets from subprocess environments**: When executing generated tests or measuring coverage, sanitize `os.environ` to strip API keys, tokens, and credentials so generated code cannot exfiltrate secrets.

## Limiting Loops and Cost

Prevent runaway execution and spiraling token consumption with hard bounds:
- **Step cap**: Enforce a strict iteration limit (`--max-steps`, default: 12).
- **Token budget**: Set a global token cap across prompts and completions (`--max-tokens`, default: 60,000).
- **Bounded fix attempts**: Cap test repair attempts (`--max-fix-attempts`, default: 3). If a test still fails, stop rather than burning tokens on intractable fixes.
- **Truncate tool output**: Truncate pytest outputs and stack traces to a fixed character budget to keep prompts lean.
- **Targeted retries**: Retry only on known transient errors (HTTP 429 rate limits, Groq `tool_use_failed` JSON parsing failures) with exponential backoff and a hard retry cap (e.g., 3). Fail fast on persistent errors.

## Evaluating Agent Quality

Track measurable outcomes across every run:
- **Core metrics**:
  - *Changed functions with tests*: Ratio of modified functions covered by written tests.
  - *First-attempt pass rate*: Percentage of generated tests that pass without any fix loop.
  - *Fix attempts*: Number of iterations spent repairing broken tests.
  - *Coverage delta*: Line coverage before vs. after generated tests (`coverage_before_pct -> coverage_after_pct`).
  - *Resource usage*: Total prompt and completion tokens, plus wall-clock duration in seconds.
- **Step-by-step JSONL logs**: Persist every prompt, model response, tool invocation, and stdout to a JSONL log file. Detailed logs are vital for debugging failure modes and comparing prompt iterations.
- **Deterministic test suite**: Test the agent harness itself with mocked LLM responses to verify tool calling, guardrails, and parsing logic without live API calls.
- **Assertive, isolated tests**: Verify that generated tests actually assert the changed behavior rather than trivial assertions (`assert True`), and ensure they use mocks so tests never hit the network.

## Lessons from Building This Agent (Real Incidents)

1. **Model availability differs across accounts**: A configured model was not accessible on a Groq account, causing immediate API failures. Always query `models.list` or validate model identifiers dynamically rather than relying on hardcoded defaults.
2. **Small models emit invalid tool-call JSON**: Smaller models often emit malformed JSON arguments (unclosed strings, unescaped characters). Catch `tool_use_failed` errors and feed the parser error back to the model for bounded retries.
3. **Silently swallowed errors hide failures**: Early iterations swallowed agent execution crashes, producing empty reports that looked successful. Always capture and surface errors directly in reports, logs, and PR comments.
4. **Child processes hung on stdin**: Tests invoking interactive utilities hung indefinitely waiting on stdin. Always pass `stdin=subprocess.DEVNULL` to child process invocations.
5. **Skipped modified files**: Given multiple modified files in a PR, the model frequently generated tests for only the first file and stopped. Adding an explicit completion check that validates coverage across every changed function fixed this omission.
