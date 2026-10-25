# Receipts

Receipts makes an AI agent's work auditable. Every tool call is logged into a
tamper-evident hash chain, a guard blocks risky actions before they run, and
plain code checks the log against the real records. The AI does the work, code
checks the work, and the AI never grades itself.

Built by The Ledgers at the Claude Impact Lab Hackathon, Seattle, October 2026.

## What the owner sees

Design mock with sample data (see `docs/mock/`). Feedback welcome.

![Receipt mock for Sweet Rose Bakery: an ISSUES FOUND verdict, a grid showing where each problem was caught, and the list of checks](docs/mock/receipt.png)

## Quick start

```sh
./setup.sh      # Python 3.12 required
make test
```

## Layout

- `bakery/`: mock bakery MCP server (the "real world" the agent works in)
- `claims/`: turns the agent's final summary into structured claims
- `receipts/`: guard, log masking, hash chain, verifier
- `render/`: renders `receipt.json` as a one-page HTML receipt
- `contracts/`: the shared JSON schemas and samples

The build plan is in `docs/PLAN.md`. See `CLAUDE.md` for how the team works with Claude in this repo.

## License

MIT
