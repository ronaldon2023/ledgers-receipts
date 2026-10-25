# Receipts

Receipts makes an AI agent's work auditable. Every tool call is logged into a
tamper-evident hash chain, a guard blocks risky actions before they run, and
plain code checks the log against the real records. The AI does the work, code
checks the work, and the AI never grades itself.

Built by The Ledgers at the Claude Impact Lab Hackathon, Seattle, October 2026.

## What the owner sees

Design mock with sample data (see `docs/mock/`). Feedback welcome.

![Receipt mock for Sweet Rose Bakery: an ISSUES FOUND verdict, a grid showing where each problem was caught, and the list of checks](docs/mock/receipt.png)

## Team setup (about 5 minutes)

You need Python 3.12 and git. On Windows, use WSL.

1. Accept the GitHub invite, then clone and set up:
   ```sh
   git clone https://github.com/ronaldon2023/ledgers-receipts.git
   cd ledgers-receipts
   ./setup.sh        # virtualenv, dependencies, spaCy model, commit-size hook
   ```
2. Create your local database:
   ```sh
   make reset        # builds bakery.db with the demo data; rerun anytime for a clean copy
   ```
   The database is not in GitHub. Everyone generates the same one from `bakery/seed.py`.
3. Check everything works:
   ```sh
   make test         # all tests should pass
   ```
4. Start Claude from inside this folder so it loads the team rules in `CLAUDE.md`:
   ```sh
   claude
   ```
5. Read your section of `docs/PLAN.md` before kickoff.

Team rules: stay in your own folder (see the table in `CLAUDE.md`), keep commits under
300 lines (the git hook enforces it), and never commit API keys. `ANTHROPIC_API_KEY`
belongs in your environment only.

## Layout

- `bakery/`: mock bakery MCP server (the "real world" the agent works in)
- `claims/`: turns the agent's final summary into structured claims
- `receipts/`: guard, log masking, hash chain, verifier
- `render/`: renders `receipt.json` as a one-page HTML receipt
- `contracts/`: the shared JSON schemas and samples

The build plan is in `docs/PLAN.md`. See `CLAUDE.md` for how the team works with Claude in this repo.

## License

MIT
