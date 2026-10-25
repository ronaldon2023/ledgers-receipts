"""Print the suppliers and payment rules bakery.db already holds, for the onboarding skill.

The onboarding skill runs this before asking the owner anything, so it can show what the
database says and ask the owner to confirm it instead of typing it again.

The database is opened read-only: env BAKERY_DB (a relative path resolves against
CLAUDE_PROJECT_DIR), else $CLAUDE_PROJECT_DIR/bakery.db, else ./bakery.db.

Prints one JSON object:
  {"vendors": [{"name", "email_domain", "account_last4"}],
   "approval_threshold_cents": int|null, "monthly_budget_cents": int|null}
taken from the vendors table and the POL-PAY-THRESHOLD and POL-BUDGET-MONTHLY policies.
Account numbers are printed as their last 4 characters only, never in full.
On a missing database or any error it prints {"error": "<short reason>"} and exits 0.
Standard library only, so it runs on the system python3.
Runnable by hand: python3 skills/onboarding/read_bakery.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

THRESHOLD_POLICY = "POL-PAY-THRESHOLD"
BUDGET_POLICY = "POL-BUDGET-MONTHLY"


def db_path() -> Path:
    """BAKERY_DB (relative to CLAUDE_PROJECT_DIR), else CLAUDE_PROJECT_DIR/bakery.db."""
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    env = os.environ.get("BAKERY_DB")
    if env:
        path = Path(env)
        return path if path.is_absolute() else root / path
    return root / "bakery.db"


def _domain(email: Any) -> str | None:
    text = str(email or "")
    return text.rsplit("@", 1)[1] if "@" in text else None


def _last4(account: Any) -> str | None:
    digits = "".join(ch for ch in str(account or "") if ch.isalnum())
    return digits[-4:] if len(digits) > 4 else None


def _limit(conn: sqlite3.Connection, policy_id: str) -> int | None:
    row = conn.execute("SELECT limit_cents FROM policies WHERE id = ?", (policy_id,)).fetchone()
    value = row[0] if row else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def read(path: Path) -> dict[str, Any]:
    """What the database holds, or {"error": ...} when it can't be read."""
    if not path.is_file():
        return {"error": f"no database at {path.name}"}
    uri = path.resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            rows = conn.execute(
                "SELECT name, email, bank_account FROM vendors ORDER BY name"
            ).fetchall()
            vendors = [
                {"name": name, "email_domain": _domain(email), "account_last4": _last4(account)}
                for name, email, account in rows
            ]
            return {
                "vendors": vendors,
                "approval_threshold_cents": _limit(conn, THRESHOLD_POLICY),
                "monthly_budget_cents": _limit(conn, BUDGET_POLICY),
            }
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {"error": f"couldn't read {path.name} ({type(exc).__name__})"}


def main() -> None:
    try:
        result = read(db_path())
    except Exception as exc:  # noqa: BLE001 - the skill falls back to asking on any error
        result = {"error": f"read failed ({type(exc).__name__})"}
    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
