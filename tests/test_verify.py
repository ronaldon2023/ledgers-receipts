import json
from pathlib import Path

import pytest

from bakery import server
from bakery.seed import seed
from receipts import chain, verify
from receipts.pii import mask

TOOL = "mcp__bakery-local__pay_bill"


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """The live demo without Claude: pay three bills through the server, log them like the hook."""
    db, log = tmp_path / "bakery.db", tmp_path / "chain.jsonl"
    seed(db)
    monkeypatch.setenv("BAKERY_DB", str(db))
    monkeypatch.delenv("BAKERY_FAULTS", raising=False)
    for n, (bill, amount, account) in enumerate(
        [
            ("BILL-07", 80000, "000123454471"),
            ("BILL-08", 20000, "9876543210"),
            ("BILL-09", 15000, "000123454471"),
        ]
    ):
        args = {"bill_id": bill, "amount_cents": amount, "to_account": account}
        result = server.pay_bill(**args)
        response = [{"type": "text", "text": json.dumps(result)}]
        chain.append(
            {
                "ts": 1792960000 + n,
                "session": "s1",
                "tool": TOOL,
                "input": mask(args),
                "response": response,
            },
            log,
        )
    return log, db


def test_receipts_match_the_live_run(run: tuple[Path, Path]) -> None:
    _, receipts = verify.build(*run)
    assert {o: r["verdict"] for o, r in receipts.items()} == {
        "PO-2041": "VERIFIED",
        "PO-2038": "ISSUES_FOUND",
        "PO-2039": "ISSUES_FOUND",
    }
    paid = receipts["PO-2041"]
    assert paid["payment"]["status"] == "sent"
    assert {c["id"]: c["status"] for c in paid["checks"]}["C10"] == "verified"
    blocked = {
        c["id"]
        for r in (receipts["PO-2038"], receipts["PO-2039"])
        for c in r["checks"]
        if c["status"] == "blocked"
    }
    assert blocked == {"C4", "C8"}
    assert receipts["PO-2038"]["payment"]["status"] == "blocked"
    assert "bank account" in receipts["PO-2038"]["owner_action"]["title"]


def test_feed_has_cards_and_shows_a_stopped_receipt(run: tuple[Path, Path]) -> None:
    feed, _ = verify.build(*run)
    assert [a["level"] for a in feed["attention"]] == ["done", "stop", "stop"]
    assert feed["receipt"] == "receipt_live_PO-2038.json"
    assert feed["glance"]["run"]["blocked"] == 2
    assert feed["chain_ok"] is True


def test_no_raw_account_numbers_in_output(run: tuple[Path, Path], tmp_path: Path) -> None:
    feed, receipts = verify.build(*run)
    written = verify.write(tmp_path / "out", feed, receipts)
    text = "".join(p.read_text() for p in written)
    assert "9876543210" not in text and "000123454471" not in text


def test_tampered_log_makes_receipts_untrusted(run: tuple[Path, Path]) -> None:
    log, db = run
    rows = log.read_text().splitlines()
    record = json.loads(rows[0])
    record["input"]["amount_cents"] = 1
    rows[0] = json.dumps(record)
    log.write_text("\n".join(rows) + "\n")
    _, receipts = verify.build(log, db)
    assert {r["verdict"] for r in receipts.values()} == {"UNTRUSTED"}


def test_paid_without_a_payment_row_is_phantom(run: tuple[Path, Path]) -> None:
    log, db = run
    response = [{"type": "text", "text": json.dumps({"ok": True, "id": "pay_99", "checks": []})}]
    args = {"bill_id": "BILL-08", "amount_cents": 20000, "to_account": "000123454471"}
    chain.append(
        {"ts": 1792960100, "session": "s1", "tool": TOOL, "input": args, "response": response}, log
    )
    _, receipts = verify.build(log, db)
    c10 = {c["id"]: c["status"] for c in receipts["PO-2038"]["checks"]}["C10"]
    assert c10 == "phantom"
    assert receipts["PO-2038"]["verdict"] == "ISSUES_FOUND"
