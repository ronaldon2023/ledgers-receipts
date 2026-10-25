# Receipts

Receipts makes an AI agent's work auditable. Every tool call is logged into a
tamper-evident hash chain, a guard blocks risky actions before they run, and
plain code checks the log against the real records. The AI does the work, code
checks the work, and the AI never grades itself.

Built by The Ledgers at the Claude Impact Lab Hackathon, Seattle, October 2026.

## What the owner sees

Design mock with sample data (see `docs/mock/`). Feedback welcome.

![Receipt mock for Sweet Rose Bakery: an ISSUES FOUND verdict, a grid showing where each problem was caught, and the list of checks](docs/mock/receipt.png)

## Install the plugin

Receipts runs as a Claude Code plugin on top of Anthropic's Small Business plugin. In your
terminal, run these three commands in this order:

```sh
claude plugin marketplace add anthropics/knowledge-work-plugins
claude plugin marketplace add ronaldon2023/ledgers-receipts
claude plugin install ledgers-receipts@the-ledgers
```

The first line adds the marketplace that holds the Small Business plugin. Installing
Receipts then installs the Small Business plugin with it. If you skip that line, the install
finishes with a warning that `small-business@knowledge-work-plugins` was not installed, and
Receipts won't load. Run the first line then, and it installs the missing plugin.

- Already inside Claude Code? The same commands work with `/plugin` in place of `claude plugin`.
  There, `/plugin install` opens the plugin's details first: choose a scope and confirm.
- No GitHub SSH key on your machine? Start Claude Code with
  `CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1 claude`, so the marketplaces download over HTTPS.
- To get the latest versions later, run `claude plugin marketplace update the-ledgers` and
  `claude plugin marketplace update knowledge-work-plugins`.
- Check it worked: `claude plugin list` shows both `ledgers-receipts@the-ledgers` and
  `small-business@knowledge-work-plugins` with `Status: ✔ enabled`.

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

The "real world" the agent works in:

- `bakery/`: the `bakery-local` MCP server (bills, invoices, orders, inbox), its seed data
  and injected faults
- `bakesupply/`: the `bakesupply` MCP server, a mock flour supplier the bakery orders from

Checking the agent's work:

- `receipts/`: the hash chain (`chain.py`), the logging hook (`hook_log.py`), number masking
  (`pii.py`), the verifier that turns the log into receipts (`verify.py`) and the portal's
  dashboard feed (`feed.py`)
- `checks/`: the rules a write must pass before it runs (`gate.py`), payment checks on a
  receipt (`payment.py`), and read-only access to the records (`source.py`)
- `claims/`: will turn the agent's final summary into structured claims (not started yet)

What the owner sees:

- `render/portal/`: the owner portal website (Dashboard, Activities, Policies, one page per
  order receipt). See `render/portal/README.md` to run it
- `docs/mock/`: the receipt design mock and the order receipt schema

The Claude Code plugin:

- `.claude-plugin/`: the plugin and marketplace manifests
- `hooks/`: `session_start.py` starts onboarding, `approve_payment.py` asks the owner before a
  large payment, `show_receipt.py` links the receipt after a payment (wired up in `hooks.json`)
- `skills/onboarding/`: asks the owner about their tools and payment rules
- `.mcp.json`: registers the two MCP servers

Supporting files:

- `contracts/`: the shared JSON schemas and samples
- `fixtures/`: the sample log and the portal's sample feeds and receipts
- `scripts/`: helpers, such as `make_sample_log.py`
- `tests/`: pytest suite, run with `make test`
- `docs/`: the build plan (`PLAN.md`), the order lifecycle plan, plugin research and the
  whiteboard notes

See `CLAUDE.md` for how the team works with Claude in this repo.

## License

MIT
