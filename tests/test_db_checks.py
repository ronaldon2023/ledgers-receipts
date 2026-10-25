import re
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest

from bakery.seed import seed
from checks.gate import PAY_CHECKS, evaluate
from checks.source import SqliteSource

CLEAN = {"bill_id": "BILL-07", "amount_cents": 80000, "to_account": "000123454471"}


@pytest.fixture
def db(tmp_path):
    """A freshly seeded database; tests change rows here, never in bakery.db."""
    path = tmp_path / "bakery.db"
    seed(path)
    return path


def change(db, *statements: str) -> None:
    with closing(sqlite3.connect(db)) as conn, conn:
        for sql in statements:
            conn.execute(sql)


def run(db, args: dict | None = None, action: str = "pay_bill") -> dict[str, str]:
    with SqliteSource(db) as source:
        return {r.id: r.status for r in evaluate(action, args or CLEAN, source)}


def blocked(results: dict[str, str]) -> set[str]:
    return {k for k, v in results.items() if v == "block"}


def test_clean_payment_passes_every_check(db):
    assert run(db) == dict.fromkeys(PAY_CHECKS, "pass")


# (name, rows to change, argument overrides, the checks that must block) - plan section 5
CASES = [
    ("changed_account", [], {"to_account": "9876543210"}, "C4"),
    ("same_last_4", [], {"to_account": "999999994471"}, "C4"),
    ("bill_asks_new_account", ["UPDATE bills SET pay_to_account = '000098763210'"], {}, "C4"),
    ("amount_drift", [], {"amount_cents": 90000}, "C5"),
    ("bill_not_order", ["UPDATE bills SET amount_cents = 88000"], {"amount_cents": 88000}, "C5"),
    ("orphan_bill", ["UPDATE bills SET order_id = NULL"], {}, "C6"),
    (
        "other_suppliers_order",
        [
            "INSERT INTO vendors VALUES ('V-2', 'Mill Co', 'ap@mill.example', '000999990000')",
            "UPDATE orders SET vendor_id = 'V-2' WHERE id = 'PO-2041'",
        ],
        {},
        "C6",
    ),
    (
        "double_pay",
        ["INSERT INTO payments VALUES ('pay_1', 'BILL-07', 80000, '000123454471', 'sent', 'x')"],
        {},
        "C7",
    ),
    (
        "pending_payment",
        ["INSERT INTO payments VALUES ('pay_1', 'BILL-07', 80000, '000123454471', 'pending', 'x')"],
        {},
        "C7",
    ),
    ("bill_marked_paid", ["UPDATE bills SET status = 'paid'"], {}, "C7"),
    (
        "no_domains",
        ["UPDATE bills SET from_addr = ''", "UPDATE vendors SET email = ''"],
        {},
        "C8",
    ),
    (
        "spoofed_sender",
        ["UPDATE bills SET from_addr = 'billing@flourco-payments.example'"],
        {},
        "C8",
    ),
    (
        "sender_subdomain",
        ["UPDATE bills SET from_addr = 'a@flourco.example.evil.example'"],
        {},
        "C8",
    ),
]


@pytest.mark.parametrize("name,rows,args,check_ids", CASES, ids=[c[0] for c in CASES])
def test_case_blocks_exactly_its_checks(db, name, rows, args, check_ids):
    change(db, *rows)
    assert blocked(run(db, {**CLEAN, **args})) == set(check_ids.split())


def test_failed_earlier_payment_doesnt_count(db):
    change(db, "INSERT INTO payments VALUES ('pay_1', 'BILL-07', 80000, 'x', 'failed', 'x')")
    assert run(db)["C7"] == "pass"


def test_orphan_bill_leaves_amount_unknown(db):
    change(db, "UPDATE bills SET order_id = NULL")
    assert run(db)["C5"] == "unknown"


def test_unknown_bill_blocks_on_c6(db):
    results = run(db, {**CLEAN, "bill_id": "BILL-99"})
    assert blocked(results) == {"C6"}
    assert set(results.values()) == {"block", "unknown"}


@pytest.mark.parametrize(
    "action,args", [("send_money", CLEAN), ("pay_bill", {"bill_id": "BILL-07"})]
)
def test_unknown_action_or_missing_argument_blocks(db, action, args):
    assert run(db, args, action) == {"C0": "block"}


def test_crashing_source_blocks():
    class Broken:
        def bill(self, bill_id):
            raise sqlite3.OperationalError("disk I/O error")

    assert [(r.id, r.status) for r in evaluate("pay_bill", CLEAN, Broken())] == [("C0", "block")]


def test_crashing_check_blocks_under_its_id(db):
    change(db, "UPDATE bills SET vendor_id = 'V-9'")  # no such vendor: C4 and C8 can't run
    assert blocked(run(db)) >= {"C4", "C8"}


@pytest.mark.parametrize("name", ["bakery.db", "bakery.db#frag", "bake?ry.db"])
def test_source_is_read_only(tmp_path, name):
    path = tmp_path / name
    seed(path)
    with SqliteSource(path) as source, pytest.raises(sqlite3.OperationalError, match="readonly"):
        source.conn.execute("DELETE FROM bills")


def test_source_never_creates_a_database(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        SqliteSource(tmp_path / "absent.db#x")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("to_account", ["9876543210", ["000123454471x"], {"n": "000123454471"}])
def test_results_hold_no_full_account_number(db, to_account):
    with SqliteSource(db) as source:
        results = evaluate("pay_bill", {**CLEAN, "to_account": to_account}, source)
    text = repr([(r.title, r.inputs) for r in results])
    assert not re.search(r"\d{8,}", text)
    assert "••4471" in text
    assert {r.id for r in results if r.status == "block"} == {"C4"}


def test_package_exports_evaluate():
    import checks

    assert checks.evaluate is evaluate


def test_cli_exit_code(db):
    cmd = [sys.executable, "-m", "checks", "pay_bill", "--db", str(db)]
    clean = subprocess.run(
        [*cmd, '{"bill_id": "BILL-07", "amount_cents": 80000, "to_account": "000123454471"}'],
        check=False,
    )
    fraud = subprocess.run(
        [*cmd, '{"bill_id": "BILL-07", "amount_cents": 80000, "to_account": "9876543210"}'],
        check=False,
        capture_output=True,
    )
    assert (clean.returncode, fraud.returncode) == (0, 1)
    assert b"C4" in fraud.stdout
