"""Run the checks for one write against a database, the way the MCP server would.

Usage: python -m checks pay_bill '{"bill_id": "BILL-07", ...}' [--db bakery.db]
   prints one line per check, exits 1 if any check blocks
"""

import argparse
import json
import os
import sys

from checks.gate import evaluate
from checks.source import SqliteSource


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m checks")
    parser.add_argument("action")
    parser.add_argument("args", help="the tool's arguments as JSON")
    parser.add_argument("--db", default=os.environ.get("BAKERY_DB", "bakery.db"))
    opts = parser.parse_args()
    with SqliteSource(opts.db) as source:
        results = evaluate(opts.action, json.loads(opts.args), source)
    for r in results:
        print(f"{r.status.upper():7} {r.id:3} {r.title}")
    sys.exit(1 if any(r.status == "block" for r in results) else 0)


if __name__ == "__main__":
    main()
