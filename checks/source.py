"""Where the checks read records from. They never write.

SqliteSource opens bakery.db read-only (?mode=ro), so a check can't change the records it
judges. Tests and the MCP server pass a Source in; any object with these methods works.
"""

import sqlite3
from pathlib import Path
from typing import Protocol, Self


class Source(Protocol):
    def vendor(self, vendor_id: str) -> dict | None: ...
    def bill(self, bill_id: str) -> dict | None: ...
    def order(self, order_id: str) -> dict | None: ...
    def payments_for_bill(self, bill_id: str) -> list[dict]: ...


class SqliteSource:
    def __init__(self, db_path: str | Path) -> None:
        # as_uri() percent-encodes "?" and "#", so the path can't drop or override mode=ro.
        uri = Path(db_path).resolve().as_uri() + "?mode=ro"
        self.conn = sqlite3.connect(uri, uri=True)
        self.conn.row_factory = sqlite3.Row

    def _one(self, sql: str, *args: object) -> dict | None:
        row = self.conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def vendor(self, vendor_id: str) -> dict | None:
        return self._one("SELECT * FROM vendors WHERE id = ?", vendor_id)

    def bill(self, bill_id: str) -> dict | None:
        return self._one("SELECT * FROM bills WHERE id = ?", bill_id)

    def order(self, order_id: str) -> dict | None:
        return self._one("SELECT * FROM orders WHERE id = ?", order_id)

    def payments_for_bill(self, bill_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM payments WHERE bill_id = ? ORDER BY id", (bill_id,))
        return [dict(r) for r in rows]

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
