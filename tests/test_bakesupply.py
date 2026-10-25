import sqlite3
from pathlib import Path

import pytest

from bakesupply import server
from bakesupply.seed import SUPPLIER, SUPPLIER_EMAIL, seed
from bakesupply.server import MAX_QUANTITY, get_price, list_orders, list_products, place_order


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
    assert quote == {
        "ok": True,
        "sku": "FLR-AP-50",
        "quantity": 12,
        "unit": "bag",
        "unit_price_cents": 5000,
        "total_cents": 60000,
        "in_stock": True,
    }


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
    assert place_order("SUG-CN-50", 150, db)["ok"] is True
    assert stock(db, "SUG-CN-50") == 0
    assert place_order("SUG-CN-50", 1, db)["ok"] is False


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


def test_the_largest_allowed_quantity_gets_a_quote_not_an_overflow(db: Path) -> None:
    quote = get_price("FLR-AP-50", MAX_QUANTITY, db)
    assert quote["ok"] is True
    assert quote["total_cents"] == 50_000_000
    assert quote["in_stock"] is False


def test_unknown_sku_is_refused(db: Path) -> None:
    for call in (get_price, place_order):
        result = call("NOPE-1", 1, db)
        assert result == {"ok": False, "error": "unknown sku: NOPE-1"}


def test_connections_are_closed(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[sqlite3.Connection] = []
    real = sqlite3.connect

    def spy(*args: object, **kwargs: object) -> sqlite3.Connection:
        conn = real(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(server.sqlite3, "connect", spy)
    place_order("FLR-AP-50", 1, db)
    list_orders(db)
    assert opened
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


def test_tools_never_raise(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "DB_PATH", db)
    assert server._get_price("NOPE", 1)["ok"] is False
    assert server._place_order("FLR-AP-50", "3")["ok"] is False
