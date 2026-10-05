# PR Test Agent

An autonomous agent that analyzes code changes in pull requests and writes pytest unit tests to verify changed behavior and ensure test coverage.

Status: work in progress

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
- `GROQ_MODEL`: Supported Groq model ID (e.g. `llama-3.3-70b-versatile`).
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
