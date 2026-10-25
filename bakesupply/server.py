"""Mock BakeSupply (Flour Co) MCP server. Run with: python -m bakesupply.server

Only this module writes to bakesupply.db (besides bakesupply.seed). Money is integer cents.
Tools never raise: a refused call returns {"ok": false, "error": "..."}.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from bakesupply.seed import DB_PATH

MAX_QUANTITY = 10_000

mcp = FastMCP("bakesupply")

# Typed loosely so _check_quantity refuses bad values as {"ok": false}, not the SDK.
Quantity = Annotated[Any, Field(description=f"Whole number of units, 1 to {MAX_QUANTITY}")]


class Refused(Exception):
    """A request BakeSupply turns down; the message goes to the caller."""


@contextmanager
def _connect(db_path: Path | None, read_only: bool = True) -> Iterator[sqlite3.Connection]:
    """Open the database, commit on success, and always close it."""
    mode = "ro" if read_only else "rw"
    conn = sqlite3.connect(f"{(db_path or DB_PATH).resolve().as_uri()}?mode={mode}", uri=True)
    conn.row_factory = sqlite3.Row
    with closing(conn), conn:
        yield conn


def _check_quantity(quantity: object) -> int:
    if type(quantity) is not int or not 1 <= quantity <= MAX_QUANTITY:
        raise Refused(f"quantity must be a whole number from 1 to {MAX_QUANTITY}")
    return quantity


def _get_product(conn: sqlite3.Connection, sku: str) -> sqlite3.Row:
    sql = "SELECT * FROM products WHERE sku = ?"
    product = conn.execute(sql, (str(sku).strip().upper(),)).fetchone()
    if product is None:
        raise Refused(f"unknown sku: {sku}")
    return product


def _order(row: sqlite3.Row) -> dict[str, Any]:
    """An orders row as the caller sees it, with an id like the bakery's `pay_1`."""
    return {**dict(row), "id": f"ord_{row['id']}"}


def list_products(db_path: Path | None = None) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM products ORDER BY sku")]


def get_price(sku: str, quantity: int, db_path: Path | None = None) -> dict[str, Any]:
    try:
        count = _check_quantity(quantity)
        with _connect(db_path) as conn:
            product = _get_product(conn, sku)
    except Refused as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "sku": product["sku"],
        "quantity": count,
        "unit": product["unit"],
        "unit_price_cents": product["price_cents"],
        "total_cents": product["price_cents"] * count,
        "in_stock": product["stock"] >= count,
    }


def place_order(sku: str, quantity: int, db_path: Path | None = None) -> dict[str, Any]:
    try:
        count = _check_quantity(quantity)
        with _connect(db_path, read_only=False) as conn:
            product = _get_product(conn, sku)
            updated = conn.execute(
                "UPDATE products SET stock = stock - ? WHERE sku = ? AND stock >= ?",
                (count, product["sku"], count),
            )
            if updated.rowcount == 0:
                raise Refused(
                    f"not enough {product['sku']} in stock ({product['stock']} {product['unit']})"
                )
            cur = conn.execute(
                "INSERT INTO orders (sku, quantity, unit_price_cents, total_cents)"
                " VALUES (?, ?, ?, ?)",
                (product["sku"], count, product["price_cents"], product["price_cents"] * count),
            )
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (cur.lastrowid,)).fetchone()
    except Refused as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, **_order(order)}


def list_orders(db_path: Path | None = None) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        return [_order(r) for r in conn.execute("SELECT * FROM orders ORDER BY id")]


@mcp.tool(name="list_products")
def _list_products() -> list[dict[str, Any]]:
    """List Flour Co's products: sku, name, unit, price per unit in cents, stock."""
    return list_products()


@mcp.tool(name="get_price")
def _get_price(sku: str, quantity: Quantity) -> dict[str, Any]:
    """Quote the total cost in cents for a quantity of a SKU, without ordering."""
    return get_price(sku, quantity)


@mcp.tool(name="place_order")
def _place_order(sku: str, quantity: Quantity) -> dict[str, Any]:
    """Order a quantity of a SKU. Reduces stock and returns the order with total_cents."""
    return place_order(sku, quantity)


@mcp.tool(name="list_orders")
def _list_orders() -> list[dict[str, Any]]:
    """List all orders placed so far."""
    return list_orders()


if __name__ == "__main__":
    mcp.run()
