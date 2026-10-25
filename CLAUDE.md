# Receipts — team guide for Claude

Receipts makes an AI agent's work auditable: hooks log every tool call into a
hash chain, a guard blocks risky actions, and plain code checks the log against
the bakery database. The AI never grades itself. Full plan: the team doc
"The Ledgers: Receipts build plan".

Many of us are new to this. Work in small, explained steps.

## Who owns what

Only edit your own folder. Build against `contracts/samples/`, not against
someone else's half-finished code.

| Folder | Owner | What it is |
| --- | --- | --- |
| `bakery/` | Person 1 | Mock bakery MCP server, seed data, faults |
| `claims/` | Person 2 | Claim extractor (the only LLM step) |
| `render/` | Person 3 | Receipt HTML page |
| `receipts/` | Ronaldo | Guard, log masking, hash chain, verifier |
| `contracts/` | Everyone | The 4 shared JSON shapes. Changes need team agreement |

## How to work

1. Before writing code, state the plan in 3 bullets and wait for a yes.
2. Make one small change at a time. A commit is at most 300 changed lines
   (samples, fixtures and lock files don't count). The pre-commit hook enforces
   this; if it blocks you, split the work into smaller commits.
3. Run `make test` before every commit. Never commit failing tests, and never
   skip or delete a test to get green.
4. After each change, explain in plain words what changed and why.
5. Ask before adding a dependency, touching another owner's folder, or changing
   a contract.

## Code standards

- Python 3.12, type hints on public functions, `ruff` for lint and format.
- Every module works two ways: importable functions for tests, and a CLI
  (`python -m bakery.seed`).
- Tests in pytest under `tests/`. Tests that call the Claude API are marked
  `@pytest.mark.live` and skipped by default.
- Money is always integer cents.
- Only `bakery/server.py` writes to `bakery.db`. Everything else opens it
  read-only (`?mode=ro`).
- Use example domains only (`*.example`), never real people or addresses.

## Never

- Commit secrets. `ANTHROPIC_API_KEY` comes from the environment only.
- Write to `bakery.db` outside `bakery/server.py`, or edit the log by hand.
- Use `git commit --no-verify` or `git push --force`.
- Render text into HTML without escaping it (emails contain attacker text).

## When asked to review

Check, in order: matches the contract schema; tests cover the change and pass;
no secrets; no unescaped output; stays inside the owner's folder; commit is
under 300 lines. Report problems as a short list, most serious first.

## Commands

- `make setup`: create `.venv`, install dependencies, install the git hook
- `make test`: lint and run tests (must pass before merging)
- `make reset`: re-seed the database and clear the log
- `make replay`: run the scripted demo without an LLM
