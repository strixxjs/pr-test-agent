- Code, comments, docs and commit messages are in English.
- Type hints everywhere, small functions, no unused abstractions.
- Never open, print or commit .env or any secret. API keys come only from
  environment variables.
- Do only what the current step asks. Do not implement future steps.
- After each step run `ruff check .` and `pytest -q`. Commit only if both pass.
- One commit per step. Message format: `feat: ...`, `fix: ...`, `chore: ...`,
  `test: ...`, `docs: ...`. I give you the exact message.
- Before committing run `git status` and make sure .env is not staged.
  Then `git add -A`, `git commit`, `git push`.
- Never force-push and never rewrite history. If push or tests fail and you
  cannot fix it in 2 attempts, stop and show me the error.
