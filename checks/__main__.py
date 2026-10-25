"""Run the checks for one write against a database, the way the MCP server would.

Usage: python -m checks pay_bill '{"bill_id": "BILL-07", ...}' [--db bakery.db]
   prints one line per check. Exit 0: allowed. Exit 1: a check blocks the payment.
   Exit 2: the checks couldn't run (bad JSON, an unreadable database, a missing argument:
   anything evaluate() reports as C0), so no check decided. The payment stays refused.
"""

import argparse
import json
import os
import sqlite3
import sys

from checks.gate import allowed, evaluate
from checks.source import SqliteSource


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m checks")
    parser.add_argument("action")
    parser.add_argument("args", help="the tool's arguments as JSON")
    parser.add_argument("--db", default=os.environ.get("BAKERY_DB", "bakery.db"))
    opts = parser.parse_args()
    try:
        args = json.loads(opts.args)
        with SqliteSource(opts.db) as source:
            results = evaluate(opts.action, args, source)
    except (ValueError, RecursionError, sqlite3.Error) as e:  # JSONDecodeError is a ValueError
        print(f"ERROR   checks couldn't run: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)
    for r in results:
        print(f"{r.status.upper():7} {r.id:3} {r.title}")
    if any(r.id == "C0" for r in results):
        sys.exit(2)
    sys.exit(0 if allowed(results) else 1)


if __name__ == "__main__":
    main()
