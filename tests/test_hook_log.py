import io
import json
from pathlib import Path

import pytest

from receipts import chain, hook_log
from receipts.pii import mask, mask_text


@pytest.mark.parametrize(
    "raw, masked",
    [
        ("card 4111 1111 1111 1111", "card ************1111"),
        ("pay to account 9876543210 today", "pay to account ******3210 today"),
        ("ssn 123-45-6789", "ssn *****6789"),
        ("iban GB82 WEST 1234 5698 7654 32", "iban ******************5432"),
    ],
)
def test_mask_text(raw: str, masked: str) -> None:
    assert mask_text(raw) == masked


@pytest.mark.parametrize(
    "safe",
    ["INV-1043", "BILL-07", "out_12", "2026-10-25 14:05", "$800.00", "80000", "pay_3"],
)
def test_ids_dates_and_amounts_are_left_alone(safe: str) -> None:
    assert mask_text(safe) == safe


def test_mask_walks_nested_values() -> None:
    value = {"to_account": "000123454471", "amount_cents": 80000, "n": [123456789012]}
    assert mask(value) == {
        "to_account": "********4471",
        "amount_cents": 80000,
        "n": ["********9012"],
    }


def test_hook_writes_masked_entry_and_chain_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "chain.jsonl"
    monkeypatch.setenv("RECEIPTS_LOG", str(log))
    event = {
        "session_id": "s1",
        "tool_name": "mcp__bakery-local__pay_bill",
        "tool_input": {"bill_id": "BILL-07", "amount_cents": 80000, "to_account": "9876543210"},
        "tool_response": {"note": "card on file 4111111111111111"},
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    hook_log.main()

    record = json.loads(log.read_text())
    assert record["tool"] == "mcp__bakery-local__pay_bill"
    assert record["input"]["to_account"] == "******3210"
    assert record["response"]["note"] == "card on file ************1111"
    assert "9876543210" not in log.read_text()
    assert chain.verify(log).ok
