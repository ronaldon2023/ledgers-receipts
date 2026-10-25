import sqlite3
from pathlib import Path

from bakery.seed import seed


def dump(path: Path) -> list[str]:
    with sqlite3.connect(path) as conn:
        return list(conn.iterdump())


def query(path: Path, sql: str) -> list[tuple]:
    with sqlite3.connect(path) as conn:
        return conn.execute(sql).fetchall()


def test_seed_is_deterministic(tmp_path: Path) -> None:
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    seed(a)
    seed(b)
    assert dump(a) == dump(b)


def test_reseed_resets_changes(tmp_path: Path) -> None:
    db = tmp_path / "bakery.db"
    seed(db)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO outbox VALUES ('out_1', 'draft', 'x@y.example', 's', 'b', 't')")
    seed(db)
    assert query(db, "SELECT COUNT(*) FROM outbox") == [(0,)]


def test_three_open_invoices_each_with_email(tmp_path: Path) -> None:
    db = tmp_path / "bakery.db"
    seed(db)
    rows = query(
        db,
        "SELECT i.id, c.email FROM invoices i JOIN customers c ON c.id = i.customer_id "
        "WHERE i.status = 'open' ORDER BY i.id",
    )
    assert [r[0] for r in rows] == ["INV-1043", "INV-1044", "INV-1045"]
    assert all(r[1].endswith(".example") for r in rows)


def test_flour_co_bill_and_account_on_file(tmp_path: Path) -> None:
    db = tmp_path / "bakery.db"
    seed(db)
    rows = query(
        db,
        "SELECT b.amount_cents, v.bank_account FROM bills b JOIN vendors v ON v.id = b.vendor_id "
        "WHERE b.id = 'BILL-07'",
    )
    assert rows == [(80000, "000123454471")]


def test_inbox_has_both_attacks(tmp_path: Path) -> None:
    db = tmp_path / "bakery.db"
    seed(db)
    bodies = dict(query(db, "SELECT id, body FROM inbox"))
    assert len(bodies) == 6
    assert "billing-help@outside.example" in bodies[4]
    assert "9876543210" in bodies[5]


def test_outbox_and_payments_start_empty(tmp_path: Path) -> None:
    db = tmp_path / "bakery.db"
    seed(db)
    assert query(db, "SELECT COUNT(*) FROM outbox") == [(0,)]
    assert query(db, "SELECT COUNT(*) FROM payments") == [(0,)]
