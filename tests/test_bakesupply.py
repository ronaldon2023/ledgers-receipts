import asyncio
from pathlib import Path

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from bakesupply import server
from bakesupply.seed import seed
from bakesupply.server import get_price, list_ingredients, list_orders, place_order


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "bakesupply.db"
    seed(path)
    return path


def test_seed_has_flour(db: Path) -> None:
    names = {i["name"] for i in list_ingredients(db)}
    assert {"flour", "sugar", "butter", "eggs"} <= names


def test_price_is_integer_cents(db: Path) -> None:
    quote = get_price("flour", 10, db)
    assert quote["unit_price_cents"] == 120
    assert quote["total_cents"] == 1200
    assert quote["in_stock"] is True


def test_ingredient_name_is_case_insensitive(db: Path) -> None:
    assert get_price("Flour", 1, db)["ingredient"] == "flour"


def test_order_records_and_reduces_stock(db: Path) -> None:
    order = place_order("flour", 25, db)
    assert order["total_cents"] == 3000
    assert list_orders(db) == [order]
    flour = next(i for i in list_ingredients(db) if i["name"] == "flour")
    assert flour["stock"] == 475


def test_out_of_stock_is_rejected_and_changes_nothing(db: Path) -> None:
    with pytest.raises(ValueError, match="not enough"):
        place_order("butter", 101, db)
    assert list_orders(db) == []
    butter = next(i for i in list_ingredients(db) if i["name"] == "butter")
    assert butter["stock"] == 100


@pytest.mark.parametrize("quantity", [0, -5])
def test_invalid_quantity(db: Path, quantity: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        get_price("flour", quantity, db)
    with pytest.raises(ValueError, match="positive"):
        place_order("flour", quantity, db)


def test_unknown_ingredient(db: Path) -> None:
    with pytest.raises(ValueError, match="unknown"):
        place_order("unicorn dust", 1, db)


def test_catalog_lists_bakesupply_sku_and_supplier(db: Path) -> None:
    flour = next(i for i in list_ingredients(db) if i["name"] == "flour")
    assert flour["sku"] == "FLOUR-25KG"
    assert flour["pack_size"] == "25 kg bag"
    assert flour["supplier"] == "BakeSupply"
    assert flour["supplier_email"] == "orders@bakesupply.example"


def test_rejected_order_explains_why_over_mcp(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "DB_PATH", db)
    call = server.mcp.call_tool("place_order", {"ingredient": "butter", "quantity": 101})
    with pytest.raises(ToolError, match="not enough butter"):
        asyncio.run(call)
