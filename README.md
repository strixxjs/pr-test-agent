# PR Test Agent

An autonomous agent that analyzes code changes in pull requests and writes pytest unit tests to verify changed behavior and ensure test coverage.

Status: work in progress

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

- **Writes only to `tests/`**: The agent is restricted to writing test files in `tests/test_*.py`. It cannot modify application source code.
- **Nothing is committed or pushed**: The agent executes purely within the ephemeral runner workspace. It never commits, pushes, or alters the pull request branch.
- **Iteration, token, and fix limits**: Strict limits (`max-steps`, `max-tokens`, `max-fix-attempts`) prevent runaway execution, high token usage, and endless test fix loops.
- **No fork secrets**: The example workflow triggers strictly on `pull_request` (never `pull_request_target`) and enforces a fork guard (`if: github.event.pull_request.head.repo.full_name == github.repository`) so repository secrets are not exposed to external forks.
- **Minimal permissions**: Requests only `contents: read` and `pull-requests: write`.

## Known limitations

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
