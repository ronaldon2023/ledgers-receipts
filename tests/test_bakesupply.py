import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

import pytest

from bakery.seed import VENDORS
from bakesupply import server
from bakesupply.seed import SCHEMA_VERSION, SUPPLIER, SUPPLIER_EMAIL, seed
from bakesupply.server import (
    MAX_QUANTITY,
    get_invoice,
    get_price,
    list_orders,
    list_products,
    place_order,
)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "bakesupply.db"
    seed(path)
    return path


def stock(db: Path, sku: str) -> int:
    return next(p["stock"] for p in list_products(db) if p["sku"] == sku)


def test_catalog_matches_the_bakerys_vendor_records(db: Path) -> None:
    products = {p["sku"]: p for p in list_products(db)}
    assert {"FLR-AP-50", "FLR-BR-50", "SUG-CN-50"} == set(products)
    flour = products["FLR-AP-50"]
    assert flour["name"] == "All-purpose flour, 50 lb bag"
    assert flour["unit"] == "bag"
    assert flour["price_cents"] == 5000
    assert flour["supplier"] == SUPPLIER == "Flour Co"
    assert flour["supplier_email"] == SUPPLIER_EMAIL == "billing@flourco.example"


def test_price_is_integer_cents(db: Path) -> None:
    quote = get_price("FLR-AP-50", 12, db)
    assert (quote["unit_price_cents"], quote["total_cents"], quote["in_stock"]) == (
        5000,
        60000,
        True,
    )


def test_sku_is_case_and_space_insensitive(db: Path) -> None:
    assert get_price(" flr-ap-50 ", 1, db)["sku"] == "FLR-AP-50"


def test_order_records_and_reduces_stock(db: Path) -> None:
    order = place_order("FLR-AP-50", 30, db)
    assert order["ok"] is True
    assert order["id"] == "ord_1"
    assert order["total_cents"] == 150000
    assert list_orders(db) == [{k: v for k, v in order.items() if k != "ok"}]
    assert stock(db, "FLR-AP-50") == 470


def test_out_of_stock_is_refused_and_changes_nothing(db: Path) -> None:
    result = place_order("SUG-CN-50", 151, db)
    assert result["ok"] is False
    assert "not enough SUG-CN-50" in result["error"]
    assert list_orders(db) == []
    assert stock(db, "SUG-CN-50") == 150


def test_ordering_exactly_the_remaining_stock_is_accepted(db: Path) -> None:
    assert place_order("SUG-CN-50", 150, db)["ok"] and not place_order("SUG-CN-50", 1, db)["ok"]


@pytest.mark.parametrize(
    "quantity", [0, -5, True, False, "3", 2.0, 2.5, None, MAX_QUANTITY + 1, 10**30]
)
def test_quantity_must_be_a_whole_number_in_range(db: Path, quantity: object) -> None:
    for call in (get_price, place_order):
        result = call("FLR-AP-50", quantity, db)
        assert result["ok"] is False
        assert "whole number" in result["error"]
    assert list_orders(db) == []
    assert stock(db, "FLR-AP-50") == 500


def test_unknown_sku_is_refused(db: Path) -> None:
    assert place_order("NOPE-1", 1, db) == {"ok": False, "error": "unknown sku: NOPE-1"}
    assert get_price("NOPE-1", 1, db)["ok"] is False


def test_connections_are_closed(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[sqlite3.Connection] = []
    real = sqlite3.connect
    monkeypatch.setattr(
        server.sqlite3, "connect", lambda *a, **k: opened.append(real(*a, **k)) or opened[-1]
    )
    place_order("FLR-AP-50", 1, db)
    list_orders(db)
    assert opened
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


def test_tools_never_raise(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "DB_PATH", db)
    assert not server._place_order("FLR-AP-50", "3")["ok"]


def test_relative_db_path_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Claude Code starts the server with BAKESUPPLY_DB=bakesupply.db, a relative path.
    monkeypatch.chdir(tmp_path)
    seed(Path("bakesupply.db"))
    assert list_products(Path("bakesupply.db"))


def test_order_can_carry_the_bakerys_po_number(db: Path) -> None:
    order = place_order("FLR-AP-50", 12, db, po_number=" po-2041 ")
    assert order["ok"] is True
    assert order["po_number"] == "PO-2041"
    assert list_orders(db)[0]["po_number"] == "PO-2041"


def test_po_number_is_optional(db: Path) -> None:
    assert place_order("FLR-AP-50", 1, db)["po_number"] is None


@pytest.mark.parametrize("po", ["2041", "PO-12", "PO-20411", "PO-ABCD", "", 2041, ["PO-2041"]])
def test_bad_po_number_is_refused_and_changes_nothing(db: Path, po: object) -> None:
    result = place_order("FLR-AP-50", 1, db, po_number=po)
    assert result == {"ok": False, "error": "po_number must look like PO-2041"}
    assert list_orders(db) == [] and stock(db, "FLR-AP-50") == 500


def test_invoice_matches_the_order(db: Path) -> None:
    place_order("FLR-AP-50", 12, db, po_number="PO-2041")
    place_order("FLR-BR-50", 4, db, po_number="PO-2041")
    first, second = get_invoice("ord_1", db), get_invoice("ord_2", db)
    assert (first["id"], first["order_id"], first["po_number"]) == ("inv_1", "ord_1", "PO-2041")
    assert (first["amount_cents"], second["amount_cents"]) == (60000, 20000)
    assert first["supplier"] == "Flour Co" and first["supplier_email"] == SUPPLIER_EMAIL
    issued = date.fromisoformat(first["issued_at"][:10])
    assert first["due_date"] == (issued + timedelta(days=14)).isoformat()


@pytest.mark.parametrize("order_id", ["ord_99", "1", "ord_", "ord_1; DROP", "", None])
def test_invoice_for_a_bad_order_id_is_refused(db: Path, order_id: object) -> None:
    place_order("FLR-AP-50", 1, db)
    assert get_invoice(order_id, db)["ok"] is False


def test_tools_accept_a_po_number_and_issue_an_invoice(db: Path, monkeypatch) -> None:
    monkeypatch.setattr(server, "DB_PATH", db)
    assert server._place_order("FLR-AP-50", 2, "PO-2041")["po_number"] == "PO-2041"
    assert server._get_invoice("ord_1")["amount_cents"] == 10000


def drop_po_column(db: Path) -> None:
    """Make the database look like one seeded before PO numbers existed."""
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("ALTER TABLE orders DROP COLUMN po_number")


def test_an_older_database_gets_a_refusal_not_an_exception(db: Path) -> None:
    drop_po_column(db)
    result = place_order("FLR-AP-50", 1, db)
    assert result["ok"] is False and "make reset" in result["error"]
    assert stock(db, "FLR-AP-50") == 500 and list_orders(db) == []


def test_invoice_for_an_order_in_an_older_database(db: Path) -> None:
    place_order("FLR-AP-50", 1, db)
    drop_po_column(db)
    invoice = get_invoice("ord_1", db)
    assert invoice["ok"] is True and invoice["po_number"] is None


def test_invoice_says_where_to_pay_and_it_matches_the_bakerys_vendor(db: Path) -> None:
    place_order("FLR-AP-50", 1, db)
    assert get_invoice("ord_1", db)["pay_to_account"] == VENDORS[0][3]


def set_version(db: Path, version: int) -> None:
    with closing(sqlite3.connect(db)) as conn:
        conn.execute(f"PRAGMA user_version = {version}")


def test_a_fresh_database_is_stamped_and_passes_the_check(db: Path) -> None:
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    server.check_schema(db)


@pytest.mark.parametrize("version", [0, SCHEMA_VERSION + 1])
def test_an_out_of_date_database_fails_the_check_with_the_fix(db: Path, version: int) -> None:
    set_version(db, version)
    with pytest.raises(RuntimeError, match="out of date.*make reset"):
        server.check_schema(db)


def test_a_missing_database_fails_the_check(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="doesn't exist.*make reset"):
        server.check_schema(tmp_path / "nope.db")


def test_the_server_refuses_to_start_on_an_old_database(db: Path) -> None:
    set_version(db, 0)
    run = subprocess.run(
        [sys.executable, "-m", "bakesupply.server"],
        env={**os.environ, "BAKESUPPLY_DB": str(db)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert run.returncode != 0
    assert "out of date" in run.stderr and "make reset" in run.stderr
