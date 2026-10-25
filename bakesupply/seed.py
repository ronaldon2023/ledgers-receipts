"""Create and seed bakesupply.db. Run with: python -m bakesupply.seed (path: $BAKESUPPLY_DB)"""

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(
    os.environ.get("BAKESUPPLY_DB") or Path(__file__).resolve().parent.parent / "bakesupply.db"
)

SCHEMA = """
CREATE TABLE ingredients (
    name TEXT PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    pack_size TEXT NOT NULL,
    unit TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents > 0),
    stock INTEGER NOT NULL CHECK (stock >= 0),
    supplier TEXT NOT NULL,
    supplier_email TEXT NOT NULL
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient TEXT NOT NULL REFERENCES ingredients(name),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL,
    total_cents INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""

SUPPLIER = "BakeSupply"
SUPPLIER_EMAIL = "orders@bakesupply.example"

# (name, sku, pack_size, unit, price per unit in cents, stock). SKU and pack size are catalog
# info only; orders are placed by ingredient name, in units.
CATALOG = [
    ("flour", "FLOUR-25KG", "25 kg bag", "kg", 120, 500),
    ("sugar", "SUGAR-25KG", "25 kg bag", "kg", 95, 300),
    ("butter", "BUTTER-5KG", "5 kg block", "kg", 650, 100),
    ("eggs", "EGGS-30CT", "30-count tray", "dozen", 380, 200),
]


def seed(db_path: Path = DB_PATH) -> None:
    """Drop and recreate the database with the starting inventory."""
    db_path.unlink(missing_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO ingredients VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(*row, SUPPLIER, SUPPLIER_EMAIL) for row in CATALOG],
        )


if __name__ == "__main__":
    seed()
    print(f"Seeded {DB_PATH}")
