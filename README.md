# PR Test Agent

An autonomous agent that analyzes code changes in pull requests and writes pytest unit tests to verify changed behavior and ensure test coverage.

See [GUIDELINES.md](GUIDELINES.md) for practical agent design guidelines, sandboxing rules, cost controls, and lessons learned.

## Quick start (2 minutes)

1. Add the secret `GROQ_API_KEY` to your GitHub repository under **Settings > Secrets and variables > Actions**.
2. Copy `examples/pr-test-agent.yml` into `.github/workflows/pr-test-agent.yml` in your repository:

```yaml
name: PR Test Agent

on:
  pull_request:

permissions:
  contents: read
  pull-requests: write

concurrency:
  group: pr-test-agent-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  test-agent:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    if: github.event.pull_request.head.repo.full_name == github.repository
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run PR Test Agent
        uses: strixxjs/pr-test-agent@main
        with:
          groq-api-key: ${{ secrets.GROQ_API_KEY }}
```

3. Open a pull request. The agent runs in the runner workspace, executes tests, and posts a markdown summary comment.

## Safety

- **Writes only to `tests/`**: Restricted to writing test files matching `tests/test_*.py`. Cannot modify application source code.
- **Nothing is committed or pushed**: Executes inside the ephemeral runner workspace; never commits or pushes to the repository branch.
- **Iteration, token, and fix limits**: Strict limits (`max-steps`, `max-tokens`, `max-fix-attempts`) prevent runaway execution and unbounded token consumption.
- **Fork security**: Triggers strictly on `pull_request` (never `pull_request_target`) with fork guards so repository secrets are not exposed to untrusted PRs.
- **Minimal permissions**: Requests only `contents: read` and `pull-requests: write`.
- **Sanitized test execution**: Strips sensitive environment variables (API keys, tokens, credentials) before running generated tests or measuring coverage.

## Results

| Target repo | Model | Changed functions with tests | Passed on first attempt | Fix attempts | Coverage before -> after | Tokens | Duration | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RAG service (FastAPI + Qdrant) | `qwen/qwen3.8-27b` | 3/3 | 8/9 (88.9%) | 1 | 0.0% -> 74.6% | 19,110 | 96.0s | done |
| RAG service (FastAPI + Qdrant) | `openai/gpt-oss-120b` | 3/3 | 0/1 (0.0%) | 0 | 0.0% -> 0.0% | 15,537 | 183.0s | error |

Notes:
- The target repo had no tests before, so "0% -> X%" is a starting point, not an improvement over existing tests.
- One run per model, not statistics.
- The `openai/gpt-oss-120b` run stopped with an error because Groq rejected a tool call with invalid JSON (`tool_use_failed`) after 3 retries.
- Estimated cost is n/a because the free tier was used.

## Example PR comment

| Metric | Value |
| --- | --- |
| Tests added | 9 functions / 9 cases |
| Changed functions with tests | 3/3 |
| Passed on first attempt | 8/9 (88.9%) |
| Fix attempts | 1 |
| Coverage | 0.0% -> 74.6% (+74.6%) |
| Tokens | 19,110 (17,891 prompt + 1,219 completion) |
| Duration | 96.0s |
| Stop reason | done |
| Model | qwen/qwen3.8-27b |

## Known limitations

- **Live PR verification**: The GitHub Action has not yet been verified on a live pull request.
- **Free-tier rate limits**: Groq free-tier accounts are subject to requests-per-minute (RPM) and tokens-per-minute (TPM) limits that may be reached on larger PR diffs.
- **Tool-call JSON parsing**: Smaller models may occasionally produce invalid tool-call JSON arguments; transient tool call failures are retried automatically, but retries are limited.
- **Fix limits**: Test repair attempts are bounded (default: 3) to prevent wasting tokens on tests that require deep architectural changes or external mocks.

## Local usage

### Requirements

The target repository's Python environment must have the following dependencies installed:
- `pytest`
- `pytest-asyncio`
- `pytest-cov`

### Installation

Clone the repository and install dependencies in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Environment configuration

Create a `.env` file from `.env.example`:

```bash
cp .env.example .env
```

Set the required environment variables:
- `GROQ_API_KEY`: Your Groq API key.
- `GROQ_MODEL`: Supported Groq model ID (e.g. `qwen/qwen3.8-27b`).
- `PRICE_IN_PER_MTOK`: (Optional) Price in USD per million input tokens.
- `PRICE_OUT_PER_MTOK`: (Optional) Price in USD per million output tokens.

### Running the agent

Run the agent on a target repository by comparing against a base git reference:

```bash
pr-test-agent run \
  --repo . \
  --base main \
  --python .venv/bin/python \
  --log-dir ./logs \
  --json-out ./results.json \
  --comment-out ./comment.md \
  --max-steps 12 \
  --max-tokens 60000 \
  --max-fix-attempts 3
```

#### CLI Options

- `--repo PATH`: Path to target git repository (default: `.`).
- `--base REF`: Base reference or commit to compare against (required).
- `--python PATH`: Path to the Python executable in the target repo's environment (default: `sys.executable`).
- `--log-dir PATH`: Directory where JSONL step logs are written (default: `./logs`).
- `--json-out PATH`: Optional path to write run metrics and test list in JSON format.
- `--comment-out PATH`: Optional path to write markdown PR comment output.
- `--max-steps INT`: Maximum agent loop iterations (default: `12`).
- `--max-tokens INT`: Maximum token budget across prompt and completion (default: `60000`).
- `--max-fix-attempts INT`: Maximum test rewrite attempts after failures (default: `3`).

## Guidelines

See [GUIDELINES.md](GUIDELINES.md) for practical guidelines on writing agent rules, sandboxing write access, limiting token costs, quality evaluation, and real-world failure modes.
