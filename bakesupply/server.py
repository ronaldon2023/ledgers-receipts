"""Mock BakeSupply (Flour Co) MCP server. Run with: python -m bakesupply.server

Only this module writes to bakesupply.db (besides bakesupply.seed). Money is integer cents.
Tools never raise: a refused call returns {"ok": false, "error": "..."}.
"""

import re
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from bakesupply.seed import (
    DB_PATH,
    SCHEMA_VERSION,
    SUPPLIER,
    SUPPLIER_BANK_ACCOUNT,
    SUPPLIER_EMAIL,
)

MAX_QUANTITY = 10_000
PAYMENT_TERMS_DAYS = 14

mcp = FastMCP("bakesupply")

# Typed loosely so _check_quantity refuses bad values as {"ok": false}, not the SDK.
Quantity = Annotated[Any, Field(description=f"Whole number of units, 1 to {MAX_QUANTITY}")]
PoNumber = Annotated[Any, Field(description="The bakery's purchase order, like PO-2041")]


def _db_error(exc: sqlite3.Error) -> dict[str, Any]:
    """A database failure as a refusal. The usual cause is a bakesupply.db from an older version."""
    msg = f"database problem ({exc}). If bakesupply.db was made before this version, run make reset"
    return {"ok": False, "error": msg}


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


def _check_po(po_number: object) -> str | None:
    """The bakery's purchase order number, like PO-2041. Optional."""
    if po_number is None:
        return None
    po = po_number.strip().upper() if isinstance(po_number, str) else ""
    if not re.fullmatch(r"PO-\d{4}", po):
        raise Refused("po_number must look like PO-2041")
    return po


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


def place_order(
    sku: str, quantity: int, db_path: Path | None = None, *, po_number: str | None = None
) -> dict[str, Any]:
    try:
        count = _check_quantity(quantity)
        po = _check_po(po_number)
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
                "INSERT INTO orders (sku, po_number, quantity, unit_price_cents, total_cents)"
                " VALUES (?, ?, ?, ?, ?)",
                (product["sku"], po, count, product["price_cents"], product["price_cents"] * count),
            )
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (cur.lastrowid,)).fetchone()
    except Refused as exc:
        return {"ok": False, "error": str(exc)}
    except sqlite3.OperationalError as exc:
        return _db_error(exc)
    return {"ok": True, **_order(order)}


def get_invoice(order_id: str, db_path: Path | None = None) -> dict[str, Any]:
    """The invoice Flour Co sends once an order is placed. It's derived from the order."""
    match = re.fullmatch(r"ord_(\d+)", order_id.strip()) if isinstance(order_id, str) else None
    if match is None:
        return {"ok": False, "error": "order_id must look like ord_1"}
    try:
        with _connect(db_path) as conn:
            row = conn.execute("SELECT * FROM orders WHERE id = ?", (int(match[1]),)).fetchone()
    except sqlite3.OperationalError as exc:
        return _db_error(exc)
    if row is None:
        return {"ok": False, "error": f"unknown order: {order_id}"}
    issued = date.fromisoformat(row["created_at"][:10])
    return {
        "ok": True,
        "id": f"inv_{row['id']}",
        "order_id": f"ord_{row['id']}",
        "po_number": dict(row).get("po_number"),  # an older database has no such column
        "supplier": SUPPLIER,
        "supplier_email": SUPPLIER_EMAIL,
        "pay_to_account": SUPPLIER_BANK_ACCOUNT,
        "amount_cents": row["total_cents"],
        "issued_at": row["created_at"],
        "due_date": (issued + timedelta(days=PAYMENT_TERMS_DAYS)).isoformat(),
    }


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
def _place_order(sku: str, quantity: Quantity, po_number: PoNumber = None) -> dict[str, Any]:
    """Order a quantity of a SKU, optionally against a purchase order like PO-2041.

    Reduces stock and returns the order with total_cents.
    """
    return place_order(sku, quantity, po_number=po_number)


@mcp.tool(name="get_invoice")
def _get_invoice(order_id: str) -> dict[str, Any]:
    """Get the invoice for an order id like ord_1: amount in cents, supplier and due date."""
    return get_invoice(order_id)


@mcp.tool(name="list_orders")
def _list_orders() -> list[dict[str, Any]]:
    """List all orders placed so far."""
    return list_orders()


def check_schema(db_path: Path | None = None) -> None:
    """Fail clearly, at startup, if bakesupply.db is missing or was made by another version."""
    path = db_path or DB_PATH
    fix = "Run make reset (or: python -m bakesupply.seed)."
    if not path.exists():
        raise RuntimeError(f"{path.name} doesn't exist. {fix}")
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
        found = conn.execute("PRAGMA user_version").fetchone()[0]
    if found != SCHEMA_VERSION:
        raise RuntimeError(
            f"{path.name} is out of date (schema {found}, this code needs {SCHEMA_VERSION}). {fix}"
        )


def main() -> None:
    try:
        check_schema()
    except RuntimeError as exc:
        sys.exit(f"bakesupply: {exc}")
    mcp.run()


if __name__ == "__main__":
    main()
