import asyncio
import sqlite3
from pathlib import Path

import pytest

from bakery import server
from bakery.seed import seed


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "bakery.db"
    seed(path)
    monkeypatch.setenv("BAKERY_DB", str(path))
    monkeypatch.delenv("BAKERY_FAULTS", raising=False)
    return path


def rows(db: Path, sql: str, *args: object) -> list[tuple]:
    with sqlite3.connect(db) as conn:
        return conn.execute(sql, args).fetchall()


def test_all_tools_registered() -> None:
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert names == {
        "list_invoices",
        "list_bills",
        "read_inbox",
        "save_draft",
        "send_email",
        "pay_bill",
        "list_orders",
        "create_order",
    }


def test_list_invoices_returns_three_open_with_email(db: Path) -> None:
    result = server.list_invoices()
    assert result["ok"]
    assert [i["id"] for i in result["invoices"]] == ["INV-1043", "INV-1044", "INV-1045"]
    assert all("@" in i["email"] for i in result["invoices"])


def test_list_bills_and_inbox(db: Path) -> None:
    assert server.list_bills()["bills"][0]["vendor"] == "Flour Co"
    assert len(server.read_inbox()["messages"]) == 6


def test_save_draft_writes_row_with_returned_id(db: Path) -> None:
    result = server.save_draft("maria@sweetrose-customers.example", "Reminder", "INV-1043 is due")
    assert result == {"ok": True, "id": "out_1"}
    assert rows(db, "SELECT id, kind FROM outbox") == [("out_1", "draft")]


def test_send_email_writes_sent(db: Path) -> None:
    server.send_email("ap@pearlst-bistro.example", "Hi", "Thanks")
    assert rows(db, "SELECT kind FROM outbox") == [("sent",)]


def test_pay_bill_writes_payment_with_given_account(db: Path) -> None:
    result = server.pay_bill("BILL-07", 80000, "9876543210")
    assert result == {"ok": True, "id": "pay_1"}
    assert rows(db, "SELECT bill_id, amount_cents, to_account FROM payments") == [
        ("BILL-07", 80000, "9876543210")
    ]


def test_drop_draft_reports_ok_but_writes_nothing(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BAKERY_FAULTS", "drop_draft:orders@oakcafe.example")
    dropped = server.save_draft("orders@oakcafe.example", "Reminder", "INV-1045 is due")
    assert dropped == {"ok": True, "id": "out_1"}
    assert rows(db, "SELECT COUNT(*) FROM outbox") == [(0,)]
    # The next draft gets a new id, so the log never points two calls at one row.
    assert server.save_draft("maria@sweetrose-customers.example", "R", "B")["id"] == "out_2"


def test_bounce_adds_inbox_notice(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAKERY_FAULTS", "bounce:ap@pearlst-bistro.example")
    server.send_email("ap@pearlst-bistro.example", "Hi", "Thanks")
    assert rows(db, "SELECT kind FROM outbox") == [("sent",)]
    assert len(server.read_inbox()["messages"]) == 7


def test_error_fault_returns_timeout(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAKERY_FAULTS", "error:pay_bill")
    assert server.pay_bill("BILL-07", 80000, "000123454471") == {"ok": False, "error": "timeout"}
    assert rows(db, "SELECT COUNT(*) FROM payments") == [(0,)]


@pytest.mark.parametrize(
    "call",
    [
        lambda: server.pay_bill("BILL-99", 100, "123"),
        lambda: server.pay_bill("BILL-07", -5, "123"),
        lambda: server.pay_bill("BILL-07", 100, ""),
        lambda: server.save_draft("not-an-email", "s", "b"),
        lambda: server.send_email("a@b.example", "", "b"),
        lambda: server.list_invoices(status="weird"),
    ],
)
def test_bad_input_returns_error_without_raising(db: Path, call) -> None:
    result = call()
    assert result["ok"] is False
    assert result["error"]


def test_list_orders_includes_items(db: Path) -> None:
    orders = {o["id"]: o for o in server.list_orders()["orders"]}
    assert orders["PO-2041"]["total_cents"] == 80000
    assert len(orders["PO-2041"]["items"]) == 2
    assert server.list_bills()["bills"][0]["order_id"] == "PO-2041"


def test_create_order_writes_order_and_items(db: Path) -> None:
    item = {
        "sku": "SUG-CN-50",
        "name": "Cane sugar, 50 lb bag",
        "quantity": 5,
        "unit_price_cents": 4000,
    }
    result = server.create_order("V-1", [item])
    assert result == {"ok": True, "id": "PO-2042", "total_cents": 20000}
    assert rows(db, "SELECT status, total_cents FROM orders WHERE id = 'PO-2042'") == [
        ("placed", 20000)
    ]
    assert rows(db, "SELECT quantity FROM order_items WHERE order_id = 'PO-2042'") == [(5,)]


@pytest.mark.parametrize(
    "vendor, items",
    [
        ("V-9", [{"sku": "A", "name": "a", "quantity": 1, "unit_price_cents": 1}]),
        ("V-1", []),
        ("V-1", [{"sku": "A", "name": "a", "quantity": 0, "unit_price_cents": 1}]),
        ("V-1", [{"sku": "", "name": "a", "quantity": 1, "unit_price_cents": 1}]),
    ],
)
def test_create_order_bad_input(db: Path, vendor: str, items: list) -> None:
    assert server.create_order(vendor, items)["ok"] is False
