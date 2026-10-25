import json
import re
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest

from bakery.seed import seed
from checks.gate import PAY_CHECKS, CheckResult, allowed, evaluate
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
    *[
        (
            f"no_account_on_file_{i}",
            [
                f"UPDATE vendors SET bank_account = {blank}",
                f"UPDATE bills SET pay_to_account = {blank}",
            ],
            {"to_account": value},
            "C4",
        )
        for i, (blank, value) in enumerate([("''", ""), ("' '", " "), ("' - '", "-")])
    ],
    ("bill_asks_new_account", ["UPDATE bills SET pay_to_account = '000098763210'"], {}, "C4"),
    ("amount_drift", [], {"amount_cents": 90000}, "C5"),
    *[
        (f"amount_not_cents_{i}", [], {"amount_cents": v}, "C5")
        for i, v in enumerate(["80000", 80000.0, True])
    ],
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
    ("cancelled_order", ["UPDATE orders SET status = 'cancelled'"], {}, "C6"),
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
    *[
        (f"malformed_sender_{i}", [f"UPDATE bills SET from_addr = '{addr}'"], {}, "C8")
        for i, addr in enumerate(
            [
                "a@evil@flourco.example",
                "Flour Co <billing@flourco.example>",
                "@flourco.example",
                "flourco.example",
                "billing@flourco.example, x@evil.example",
            ]
        )
    ],
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


def test_received_order_passes_c6(db):
    change(db, "UPDATE orders SET status = 'received'")
    assert run(db)["C6"] == "pass"


def test_unknown_order_status_blocks_c6(db):
    """The schema allows only three statuses, so a fake source supplies a fourth."""

    class OddStatus(SqliteSource):
        def order(self, order_id):
            return {**super().order(order_id), "status": "void"}

    with OddStatus(db) as source:
        results = {r.id: r for r in evaluate("pay_bill", CLEAN, source)}
    assert results["C6"].status == "block"
    assert results["C6"].inputs["order.status"] == "void"


def test_orphan_bill_leaves_amount_unknown(db):
    change(db, "UPDATE bills SET order_id = NULL")
    assert run(db)["C5"] == "unknown"


@pytest.mark.parametrize("to_account", ["0001 2345 4471", "0001-2345-4471", " 000123454471 "])
def test_account_formatting_is_ignored(db, to_account):
    assert run(db, {**CLEAN, "to_account": to_account})["C4"] == "pass"


# Only ASCII spaces and dashes are formatting; anything else could be stored differently
@pytest.mark.parametrize(
    "to_account",
    ["000123454471\n", "0001\t23454471", "0001 23454471", "0001—2345-4471", "٠٠٠١٢٣٤٥٤٤٧١"],
)
def test_other_separators_and_digits_block(db, to_account):
    assert blocked(run(db, {**CLEAN, "to_account": to_account})) == {"C4"}


def test_malformed_account_on_the_bill_is_named_in_the_title(db):
    change(db, "UPDATE bills SET pay_to_account = '0001x2345'")
    with SqliteSource(db) as source:
        c4 = evaluate("pay_bill", CLEAN, source)[0]
    assert (c4.status, "••2345" in c4.title) == ("block", True)


def test_unknown_bill_blocks_on_c6(db):
    results = run(db, {**CLEAN, "bill_id": "BILL-99"})
    assert blocked(results) == {"C6"}
    assert set(results.values()) == {"block", "unknown"}


@pytest.mark.parametrize(
    "action,args", [("send_money", CLEAN), ("pay_bill", {"bill_id": "BILL-07"})]
)
def test_unknown_action_or_missing_argument_blocks(db, action, args):
    assert run(db, args, action) == {"C0": "block"}


def test_crashing_source_blocks_without_echoing_its_message():
    class Broken:
        def bill(self, bill_id):
            raise sqlite3.OperationalError(f"no row for account {CLEAN['to_account']}")

    results = evaluate("pay_bill", CLEAN, Broken())
    assert [(r.id, r.status) for r in results] == [("C0", "block")]
    assert not re.search(r"\d{8,}", results[0].title)


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


@pytest.mark.parametrize(
    "statuses,expected",
    [(["pass", "unknown", "ask"], True), (["pass", "block"], False), ([], True)],
)
def test_allowed_stops_only_on_block(statuses, expected):
    assert allowed([CheckResult(f"C{i}", s, "") for i, s in enumerate(statuses)]) is expected


def test_package_exports_evaluate_and_allowed():
    import checks

    assert (checks.evaluate, checks.allowed) == (evaluate, allowed)


def test_cli_exit_codes(db, tmp_path):
    def cli(args: str, path) -> subprocess.CompletedProcess:
        cmd = [sys.executable, "-m", "checks", "pay_bill", args, "--db", str(path)]
        return subprocess.run(cmd, check=False, capture_output=True, text=True)

    fraud = json.dumps({**CLEAN, "to_account": "9876543210"})
    empty = tmp_path / "empty.db"
    empty.touch()
    codes = [
        cli(json.dumps(CLEAN), db).returncode,
        cli(fraud, db).returncode,
        cli("{not json", db).returncode,
        cli("[" * 200_000, db).returncode,
        cli(json.dumps(CLEAN), tmp_path / "absent.db").returncode,
        cli(json.dumps(CLEAN), empty).returncode,
        cli("null", db).returncode,
        cli("[]", db).returncode,
    ]
    assert codes == [0, 1, 2, 2, 2, 2, 2, 2]
    assert "C4" in cli(fraud, db).stdout
