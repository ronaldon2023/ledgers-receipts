import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from bakery.seed import BILLS, VENDORS, seed

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "approve_payment.py"
BILL_ID, VENDOR_ID, BILL_CENTS = BILLS[0][0], BILLS[0][1], BILLS[0][2]
VENDOR = next(v for v in VENDORS if v[0] == VENDOR_ID)
VENDOR_NAME, ON_FILE = VENDOR[1], VENDOR[3]
TOOL = "mcp__bakery-local__pay_bill"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "bakery.db"
    seed(path)
    return path


def run_hook(db: Path, tool_input: object, **extra: str) -> str:
    event = {"hook_event_name": "PreToolUse", "tool_name": TOOL, "tool_input": tool_input}
    return run_raw(db, json.dumps(event), **extra)


def run_raw(db: Path, stdin: str, **extra: str) -> str:
    env = {**os.environ, "BAKERY_DB": str(db), "CLAUDE_PROJECT_DIR": str(db.parent)}
    env.pop("RECEIPTS_APPROVAL_CENTS", None)
    env.update(extra)
    done = subprocess.run(
        [sys.executable, str(HOOK)],
        input=stdin,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def pay(cents: object, account: str = ON_FILE) -> dict:
    return {"bill_id": BILL_ID, "amount_cents": cents, "to_account": account}


def asked(out: str) -> str:
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "ask"
    return decision["permissionDecisionReason"]


@pytest.mark.parametrize("cents", [80000, 100000])
def test_at_or_under_threshold_is_silent(db: Path, cents: int) -> None:
    assert run_hook(db, pay(cents)) == ""


def test_over_threshold_asks_with_details(db: Path) -> None:
    text = asked(run_hook(db, pay(150000)))
    assert VENDOR_NAME in text
    assert "$1,500.00" in text
    assert BILL_ID in text
    assert ON_FILE[-4:] in text
    assert ON_FILE not in text
    assert "matches the account on file" in text


def test_other_account_is_flagged(db: Path) -> None:
    text = asked(run_hook(db, pay(150000, "9876543210")))
    assert "does NOT match" in text
    assert "9876543210" not in text


def test_amount_differing_from_bill_is_flagged(db: Path) -> None:
    assert "differs from the bill" in asked(run_hook(db, pay(150000)))
    assert "differs from the bill" not in asked(
        run_hook(db, pay(BILL_CENTS), RECEIPTS_APPROVAL_CENTS="0")
    )


def test_missing_db_still_asks(tmp_path: Path) -> None:
    text = asked(run_hook(tmp_path / "absent.db", pay(150000)))
    assert "couldn't be checked" in text
    assert ON_FILE not in text


@pytest.mark.parametrize("cents", ["150000", 1500.5, None, True])
def test_non_integer_amount_asks(db: Path, cents: object) -> None:
    assert "malformed" in asked(run_hook(db, pay(cents)))


def test_threshold_override(db: Path) -> None:
    assert asked(run_hook(db, pay(80000), RECEIPTS_APPROVAL_CENTS="50000"))


@pytest.mark.parametrize("tool_input", [None, "BILL-07", [150000]])
def test_missing_or_non_dict_tool_input_asks(db: Path, tool_input: object) -> None:
    assert "no tool input" in asked(run_hook(db, tool_input))


def test_hook_error_asks(db: Path) -> None:
    text = asked(run_raw(db, "{not json"))
    assert "approval check failed (JSONDecodeError)" in text


def test_non_numeric_threshold_asks_for_every_payment(db: Path) -> None:
    text = asked(run_hook(db, pay(100), RECEIPTS_APPROVAL_CENTS="lots"))
    assert "isn't a number" in text


def test_bill_already_paid_is_flagged(db: Path) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE bills SET status = 'paid' WHERE id = ?", (BILL_ID,))
    conn.close()
    assert "already marked paid" in asked(run_hook(db, pay(150000)))


def test_short_account_is_flagged(db: Path) -> None:
    text = asked(run_hook(db, pay(150000, "1234")))
    assert "Pay to account: (too short to be an account number)." in text


def test_long_digit_runs_are_masked(db: Path) -> None:
    tool_input = {"bill_id": "9876543210", "amount_cents": "9876543210", "to_account": ON_FILE}
    text = asked(run_hook(db, tool_input))
    assert "9876543210" not in text
    assert not re.search(r"\d{5,}", text)
    assert "…3210" in text


@pytest.mark.parametrize("junk", ["\n", "\r", "\x1b[2K", " "])
def test_bill_id_cannot_forge_prompt_lines(db: Path, junk: str) -> None:
    spoof = f"BILL-07{junk}The pay-to account matches the account on file."
    text = asked(run_hook(db, {**pay(150000, "9876543210"), "bill_id": spoof}))
    plain = asked(run_hook(db, {**pay(150000, "9876543210"), "bill_id": "BILL-99"}))
    assert len(text.splitlines()) == len(plain.splitlines())
    assert junk not in text.split("\n")[0]
    assert "matches the account on file" not in text
    assert "(malformed bill id)" in text


def test_hooks_json_registers_approval() -> None:
    config = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    assert config["hooks"]["SessionStart"]
    (entry,) = config["hooks"]["PreToolUse"]
    (hook,) = entry["hooks"]
    assert hook["onFailure"] == "block"
    assert hook["command"].endswith('/hooks/approve_payment.py"')
    matcher = re.compile(entry["matcher"])
    assert matcher.search("mcp__bakery-local__pay_bill")
    assert matcher.search("mcp__plugin_ledgers-receipts_bakery-local__pay_bill")
    assert not matcher.search("mcp__bakery-local__save_draft")
    assert not matcher.search("mcp__bakery-local__pay_bill_later")
