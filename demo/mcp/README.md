# Running the MCP servers with or without the firewall

Both servers work on their own. The firewall is an add-on: if it's ready, point Claude at it, and if it isn't, use the direct setup. The demo story is the same either way.

## Direct (no firewall): the default

1. Activate the virtualenv (`.venv/bin/activate` in WSL or macOS, `.venv\Scripts\activate` in native Windows).
2. Run `python demo/mcp/smoke.py`. It starts both servers with temporary databases and checks the money path: the account ending 3210 is blocked, the account on file is paid, the same bill can't be paid twice, and BakeSupply quotes and takes an order. It should end with `ALL PASS`.
3. Start Claude with the direct config: `claude --strict-mcp-config --mcp-config demo/mcp/direct.json`. The strict flag keeps Claude from also loading the repo's `.mcp.json`. The repo's own `.mcp.json` does the same job, but it points at `.venv/bin/python`, which doesn't exist on native Windows.

## Through the firewall

1. Start both servers over HTTP, each on its own port:
   - `python -m bakery.server --http` (port 8000)
   - `python -m bakesupply.server --http --port 8102`
2. Point the firewall's upstreams at `http://127.0.0.1:8000/mcp` and `http://127.0.0.1:8102/mcp`.
3. Fill in the two URLs in `firewall.json` with the firewall's own addresses, and start Claude with `claude --strict-mcp-config --mcp-config demo/mcp/firewall.json`.
4. Check it: `python demo/mcp/smoke.py --bakery-url <firewall URL for the bakery> --bakesupply-url <firewall URL for BakeSupply>`. In this mode it changes nothing, so it's safe to run against the demo database.

## If the firewall breaks on the day

Switch back to the direct setup above. No code changes are needed, and the receipt, the guard checks and the log work the same.
