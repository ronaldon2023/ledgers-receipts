"""Create and seed bakesupply.db. Run with: python -m bakesupply.seed (path: $BAKESUPPLY_DB)

BakeSupply plays Flour Co: same name, email, SKUs and units as bakery/seed.py.
"""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

DB_PATH = Path(
    os.environ.get("BAKESUPPLY_DB") or Path(__file__).resolve().parent.parent / "bakesupply.db"
)

SCHEMA = """
CREATE TABLE products (
    sku TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents > 0),
    stock INTEGER NOT NULL CHECK (stock >= 0),
    supplier TEXT NOT NULL,
    supplier_email TEXT NOT NULL
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL REFERENCES products(sku),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL,
    total_cents INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""

SUPPLIER = "Flour Co"
SUPPLIER_EMAIL = "billing@flourco.example"

# (sku, name, unit, price per unit in cents, stock)
CATALOG = [
    ("FLR-AP-50", "All-purpose flour, 50 lb bag", "bag", 5000, 500),
    ("FLR-BR-50", "Bread flour, 50 lb bag", "bag", 5000, 200),
    ("SUG-CN-50", "Cane sugar, 50 lb bag", "bag", 4000, 150),
]


def seed(db_path: Path = DB_PATH) -> None:
    """Drop and recreate the database with the starting inventory."""
    db_path.unlink(missing_ok=True)
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(*row, SUPPLIER, SUPPLIER_EMAIL) for row in CATALOG],
        )


if __name__ == "__main__":
    seed()
    print(f"Seeded {DB_PATH}")
