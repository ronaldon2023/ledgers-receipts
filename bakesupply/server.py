"""Mock BakeSupply (ingredient distributor) MCP server. Run with: python -m bakesupply.server

This is the only module that writes to bakesupply.db (besides bakesupply.seed).
All money is integer cents.
"""

import sqlite3
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from bakesupply.seed import DB_PATH

mcp = FastMCP("bakesupply")


def _connect(db_path: Path | None, read_only: bool = True) -> sqlite3.Connection:
    mode = "ro" if read_only else "rw"
    conn = sqlite3.connect(f"{(db_path or DB_PATH).as_uri()}?mode={mode}", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _check_quantity(quantity: int) -> None:
    if quantity <= 0:
        raise ValueError("quantity must be a positive whole number")


def _get_ingredient(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM ingredients WHERE name = ?", (name.lower(),)).fetchone()
    if row is None:
        raise ValueError(f"unknown ingredient: {name}")
    return row


def list_ingredients(db_path: Path | None = None) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM ingredients ORDER BY name")]


def get_price(ingredient: str, quantity: int, db_path: Path | None = None) -> dict[str, Any]:
    _check_quantity(quantity)
    with _connect(db_path) as conn:
        row = _get_ingredient(conn, ingredient)
    return {
        "ingredient": row["name"],
        "quantity": quantity,
        "unit": row["unit"],
        "unit_price_cents": row["price_cents"],
        "total_cents": row["price_cents"] * quantity,
        "in_stock": row["stock"] >= quantity,
    }


def place_order(ingredient: str, quantity: int, db_path: Path | None = None) -> dict[str, Any]:
    _check_quantity(quantity)
    with _connect(db_path, read_only=False) as conn:
        row = _get_ingredient(conn, ingredient)
        updated = conn.execute(
            "UPDATE ingredients SET stock = stock - ? WHERE name = ? AND stock >= ?",
            (quantity, row["name"], quantity),
        )
        if updated.rowcount == 0:
            raise ValueError(f"not enough {row['name']} in stock ({row['stock']} {row['unit']})")
        total = row["price_cents"] * quantity
        cur = conn.execute(
            "INSERT INTO orders (ingredient, quantity, unit_price_cents, total_cents)"
            " VALUES (?, ?, ?, ?)",
            (row["name"], quantity, row["price_cents"], total),
        )
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(order)


def list_orders(db_path: Path | None = None) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM orders ORDER BY id")]


@mcp.tool(name="list_ingredients")
def _list_ingredients() -> list[dict[str, Any]]:
    """List ingredients with unit, price per unit in cents, stock and supplier."""
    return list_ingredients()


@mcp.tool(name="get_price")
def _get_price(ingredient: str, quantity: int) -> dict[str, Any]:
    """Quote the total cost in cents for a quantity of an ingredient, without ordering."""
    return get_price(ingredient, quantity)


@mcp.tool(name="place_order")
def _place_order(ingredient: str, quantity: int) -> dict[str, Any]:
    """Order a quantity of an ingredient. Reduces stock and returns the order with total_cents."""
    return place_order(ingredient, quantity)


@mcp.tool(name="list_orders")
def _list_orders() -> list[dict[str, Any]]:
    """List all orders placed so far."""
    return list_orders()


if __name__ == "__main__":
    mcp.run()
