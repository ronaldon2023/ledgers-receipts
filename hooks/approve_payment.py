"""PreToolUse hook: make the owner approve any bakery payment over the approval threshold.

Claude Code runs this before the bakery MCP tool pay_bill. When this payment plus
what's already paid on the bill is over the threshold, it prints an "ask" decision, so
Claude Code shows the owner its permission prompt with the payment details as the reason.
At or under the threshold it prints nothing, which leaves the decision to the normal rules.

The threshold, in cents: env RECEIPTS_APPROVAL_CENTS when set (a non-number makes every payment
ask); else payment_rules.approval_threshold_cents in the onboarding answers (env
RECEIPTS_ONBOARDING, else $CLAUDE_PROJECT_DIR/receipts-onboarding.json); $1,000 when that file
or key is missing. An onboarding file that can't be read or holds a bad value makes every
payment ask. The reason says where the threshold came from.

The details come from bakery.db, opened read-only: env BAKERY_DB, else
$CLAUDE_PROJECT_DIR/bakery.db. If the bill can't be read, it still asks and says so; if earlier
payments can't be read, it judges this payment alone. A bad call or an error in this hook
also asks; it never silently allows. Account numbers are shown as their last 4 characters
only, and so is any run of 5+ digits echoed from the call. A bill id is shown with anything outside [A-Za-z0-9._-] replaced by "?", so it can't forge prompt lines.
Standard library only, so it runs on the system python3.
Runnable by hand: echo '{"tool_input": {...}}' | python3 hooks/approve_payment.py
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

DEFAULT_THRESHOLD_CENTS = 100000


def dollars(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) // 100:,}.{abs(cents) % 100:02d}"


def last4(account: str) -> str:
    if len(account) <= 4:
        return "(too short to be an account number)"
    return f"ending {account[-4:]}"


def _normal(account: str) -> str:
    return "".join(ch for ch in account if ch.isalnum())


def _clip(text: Any, limit: int = 80) -> str:
    """Echoed free text, with any run of 5+ digits cut to its last 4, clipped to `limit`."""
    text = re.sub(r"\d{5,}", lambda m: "\u2026" + m.group()[-4:], str(text))
    return text if len(text) <= limit else text[:limit] + "..."


def _show_bill_id(tool_input: dict[str, Any]) -> str:
    """The bill id as safe to show: only [A-Za-z0-9._-], so it can't forge prompt lines."""
    if "bill_id" not in tool_input:
        return "(none given)"
    raw = str(tool_input["bill_id"])
    safe = re.sub(r"[^A-Za-z0-9._-]", "?", raw)
    return _clip(safe) + ("" if safe == raw and raw else " (malformed bill id)")


def onboarding_path() -> Path:
    """Where the onboarding answers live; the same lookup as hooks/session_start.py."""
    root = os.environ.get("CLAUDE_PROJECT_DIR") or "."
    return Path(os.environ.get("RECEIPTS_ONBOARDING") or Path(root) / "receipts-onboarding.json")


def _from_onboarding() -> tuple[int | None, str]:
    """The onboarding threshold and its source label; None plus why when it can't be trusted."""
    unreadable = "the onboarding answers couldn't be read ({}), so every payment needs approval."
    try:
        text = onboarding_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return DEFAULT_THRESHOLD_CENTS, "default"
    except (OSError, ValueError):
        return None, unreadable.format("the file can't be opened")
    try:
        answers = json.loads(text)
    except (ValueError, RecursionError):
        return None, unreadable.format("not valid JSON")
    rules = answers.get("payment_rules") if isinstance(answers, dict) else None
    if not isinstance(answers, dict) or not isinstance(rules, dict):
        return None, unreadable.format("no payment_rules object")
    value = rules.get("approval_threshold_cents")
    if value is None:
        return DEFAULT_THRESHOLD_CENTS, "default"
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None, unreadable.format("approval_threshold_cents isn't a whole number of cents")
    return value, "set in onboarding"


def threshold_cents() -> tuple[int | None, str]:
    """The threshold in cents and where it came from, or None and why every payment must ask.

    RECEIPTS_APPROVAL_CENTS wins when set (a test override); else the onboarding answers.
    """
    raw = os.environ.get("RECEIPTS_APPROVAL_CENTS", "").strip()
    if not raw:
        return _from_onboarding()
    try:
        return int(raw), "set by RECEIPTS_APPROVAL_CENTS"
    except ValueError:
        return None, "RECEIPTS_APPROVAL_CENTS isn't a number, so every payment needs approval."


def db_path() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or "."
    return Path(os.environ.get("BAKERY_DB") or Path(root) / "bakery.db")


def lookup_bill(bill_id: str) -> dict[str, Any] | None:
    """The bill joined with its vendor, or None when the database or the bill can't be read."""
    uri = Path(db_path()).resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT b.id, b.amount_cents, b.due_date, b.status, b.order_id,"
                " v.name AS vendor, v.bank_account FROM bills b"
                " JOIN vendors v ON v.id = b.vendor_id WHERE b.id = ?",
                (bill_id,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return dict(row) if row else None


def paid_on_bill(bill_id: str) -> int:
    """Cents already paid on the bill (payments not 'failed'), or 0 when the database can't be read."""
    uri = Path(db_path()).resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(amount_cents), 0) FROM payments"
                " WHERE bill_id = ? AND status != 'failed'",
                (bill_id,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return 0
    return row[0] if row and isinstance(row[0], int) else 0


def reason(tool_input: dict[str, Any], threshold: int | None, source: str, paid: int = 0) -> str:
    """The plain-text reason the owner sees in the permission prompt.

    `source` is where the threshold came from, or, when threshold is None, why there is none.
    """
    amount = tool_input.get("amount_cents")
    bill_id = _show_bill_id(tool_input)
    account = str(tool_input.get("to_account") or "")
    lines = []
    if isinstance(amount, int) and not isinstance(amount, bool):
        lines.append(f"Receipts: approve paying {dollars(amount)} on bill {bill_id}?")
        if threshold is None:
            lines.append(source[0].upper() + source[1:])
        else:
            lines.append(
                f"Payments over {dollars(threshold)} need the owner's approval ({source})."
            )
        if paid:
            total = dollars(paid + amount)
            lines.append(f"Already paid on this bill: {dollars(paid)}. With this one: {total}.")
    else:
        amount = None
        lines.append(f"Receipts: malformed payment call on bill {bill_id}.")
        lines.append(
            f"The amount isn't a whole number of cents: {_clip(repr(tool_input.get('amount_cents')))}."
        )
    lines.append(f"Pay to account: {last4(account) if account else '(none given)'}.")

    bill = lookup_bill(str(tool_input.get("bill_id", ""))) if "bill_id" in tool_input else None
    if bill is None:
        lines.append(f"WARNING: this bill couldn't be checked against {db_path().name}.")
        return "\n".join(lines)

    lines.append(f"Vendor: {bill['vendor']}.")
    lines.append(
        f"Bill {bill['id']}: {dollars(bill['amount_cents'])}, due {bill['due_date']}, {bill['status']}."
    )
    lines.append(f"Order: {bill['order_id'] or 'none linked'}.")
    on_file = str(bill["bank_account"])
    lines.append(f"Vendor's account on file: {last4(on_file)}.")
    if account and _normal(account) == _normal(on_file):
        lines.append("The pay-to account matches the account on file.")
    else:
        lines.append("WARNING: the pay-to account does NOT match the vendor's account on file.")
    if amount is not None and amount != bill["amount_cents"]:
        lines.append(
            f"WARNING: the amount differs from the bill ({dollars(bill['amount_cents'])})."
        )
    if bill["status"] == "paid":
        lines.append("WARNING: this bill is already marked paid.")
    return "\n".join(lines)


def decide(event: Any) -> str | None:
    """The reason to ask the owner, or None to stay silent."""
    if not isinstance(event, dict) or not isinstance(event.get("tool_input"), dict):
        return "Receipts: malformed payment call (no tool input); couldn't check it."
    tool_input = event["tool_input"]
    amount = tool_input.get("amount_cents")
    threshold, source = threshold_cents()
    is_int = isinstance(amount, int) and not isinstance(amount, bool)
    paid = paid_on_bill(str(tool_input["bill_id"])) if "bill_id" in tool_input else 0
    if is_int and amount > 0 and threshold is not None and amount + max(paid, 0) <= threshold:
        return None
    return reason(tool_input, threshold, source, paid)


def ask(text: str) -> str:
    output = {"hookEventName": "PreToolUse", "permissionDecision": "ask"}
    output["permissionDecisionReason"] = text
    return json.dumps({"hookSpecificOutput": output})


def main() -> None:
    try:
        text = decide(json.loads(sys.stdin.read() or "null"))
    except Exception as exc:  # noqa: BLE001 - any failure must prompt, never allow
        text = f"Receipts: the approval check failed ({type(exc).__name__}); review this payment."
    if text is not None:
        print(ask(text))


if __name__ == "__main__":
    main()
