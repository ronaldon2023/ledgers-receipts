"""PreToolUse hook: make the owner approve any bakery payment over the approval threshold.

Claude Code runs this before the bakery MCP tool pay_bill. At or under the threshold (this
payment plus what's already paid on the bill) it prints nothing, which leaves the decision to
the normal rules. Over it, the owner approves in chat with an approval card:

- The hook reads the session transcript (the event's transcript_path), where Claude Code
  records the owner's AskUserQuestion answers. Only an answer whose tool_result points at an
  AskUserQuestion tool_use counts, so another tool's output can't pose as one.
- If, after the last earlier pay_bill call for this bill, the latest card with header
  "Approve payment" and exactly this payment's question (see card_question) was answered
  "Approve", it prints "allow". One approval releases one payment.
- Otherwise it prints "deny", and the reason tells Claude the exact card to ask with.
- A transcript it can't read, or with no usable entries, a malformed call, or an error in this
  hook prints "ask": Claude Code's own permission prompt decides, so it never silently allows.

The card question names the amount, the vendor, the pay-to account's last 4 and the bill, plus
any warning (account not on file, amount differs from the bill, already paid). A card counts
only when its question is that exact text (whitespace aside), so an approval for $800.00 or
account 4471 can't release $8,000.00 or account 3210. The ask reason is the payment details.

The threshold, in cents: env RECEIPTS_APPROVAL_CENTS when set (a non-number makes every payment
ask); else payment_rules.approval_threshold_cents in the onboarding answers (env
RECEIPTS_ONBOARDING, else $CLAUDE_PROJECT_DIR/receipts-onboarding.json); $500 when that file,
its payment_rules or the threshold key is missing. An onboarding file that can't be read, isn't
valid JSON, or holds a non-object or a bad value where those belong makes every payment ask. The reason says where the threshold came from.

The details come from bakery.db, opened read-only: env BAKERY_DB, else
$CLAUDE_PROJECT_DIR/bakery.db. If the bill can't be read, the card and the ask reason say so; if
earlier payments can't be read, it judges this payment alone. Account numbers are shown as their last 4 characters
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

DEFAULT_THRESHOLD_CENTS = 50000


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
    """Where the onboarding answers live: env RECEIPTS_ONBOARDING when set and non-empty, else
    receipts-onboarding.json in CLAUDE_PROJECT_DIR (or "." when that is unset or empty)."""
    root = os.environ.get("CLAUDE_PROJECT_DIR") or "."
    return Path(os.environ.get("RECEIPTS_ONBOARDING") or Path(root) / "receipts-onboarding.json")


def _from_onboarding() -> tuple[int | None, str]:
    """The onboarding threshold and its source label; None plus why when it can't be trusted."""
    unreadable = "the onboarding answers couldn't be read ({}), so every payment needs approval."
    try:
        raw = onboarding_path().read_bytes()
    except FileNotFoundError:
        return DEFAULT_THRESHOLD_CENTS, "default"
    except OSError:
        return None, unreadable.format("the file can't be opened")
    try:
        answers = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
        return None, unreadable.format("not valid JSON")
    if not isinstance(answers, dict):
        return None, unreadable.format("not a JSON object")
    if "payment_rules" not in answers:
        return DEFAULT_THRESHOLD_CENTS, "default"
    rules = answers["payment_rules"]
    if not isinstance(rules, dict):
        return None, unreadable.format("payment_rules isn't an object")
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


CARD_HEADER = "Approve payment"
APPROVE, DECLINE = "Approve", "Decline"
CARD_OPTIONS = [
    {"label": APPROVE, "description": "Send this payment now."},
    {"label": DECLINE, "description": "Don't pay it. Nothing is sent."},
]
NO_TRANSCRIPT = "\n(The in-chat approval couldn't be checked: {}. This prompt decides.)"


def card_question(tool_input: dict[str, Any], paid: int) -> str | None:
    """The exact card question for this payment, or None when the call is too malformed for one."""
    amount, bill_id = tool_input.get("amount_cents"), tool_input.get("bill_id")
    account = _normal(str(tool_input.get("to_account") or ""))
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        return None
    if not isinstance(bill_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", bill_id):
        return None
    if len(account) <= 4:
        return None
    bill = lookup_bill(bill_id)
    if bill is None:
        text = f"Pay {dollars(amount)} to account ending {account[-4:]}, for bill {bill_id}?"
        return text + " Receipts couldn't check this bill against its records."
    vendor = re.sub(r"\s+", " ", _clip(bill["vendor"], 60))
    text = f"Pay {dollars(amount)} to {vendor}, account ending {account[-4:]}, for bill {bill_id}?"
    on_file = _normal(str(bill["bank_account"]))
    if account != on_file:
        text += f" Warning: that isn't the account on file (ending {on_file[-4:]})."
    if amount != bill["amount_cents"]:
        text += f" Warning: the bill is for {dollars(bill['amount_cents'])}."
    if paid:
        text += f" Already paid on this bill: {dollars(paid)}."
    if bill["status"] == "paid":
        text += " Warning: this bill is already marked paid."
    return text


def _entries(path: Any) -> list[dict[str, Any]] | None:
    """The transcript's JSON objects in order, or None when it can't be read or has none."""
    if not isinstance(path, str) or not path:
        return None
    try:
        lines = Path(path).read_bytes().splitlines()
    except OSError:
        return None
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except (ValueError, RecursionError):  # a torn or foreign line: skip it
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries or None


def _blocks(entry: dict[str, Any]) -> list[dict[str, Any]]:
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def card_answer(entries: list[dict[str, Any]], bill_id: str, question: str, this_call: Any) -> str:
    """The owner's answer to the latest matching card since the last pay_bill for this bill.

    Returns the chosen label, "" when there is no matching card, or "other card" when a card
    with the header was answered after that pay_bill but asked a different question. Only
    answers Claude Code recorded for an AskUserQuestion tool_use count.
    """
    asks: set[str] = set()
    found = ""
    want = " ".join(question.split())
    for entry in entries:
        if entry.get("type") == "assistant":
            for block in _blocks(entry):
                if block.get("type") != "tool_use":
                    continue
                name, args = str(block.get("name", "")), block.get("input")
                if name == "AskUserQuestion":
                    asks.add(str(block.get("id")))
                elif (
                    name.endswith("bakery-local__pay_bill")
                    and block.get("id") != this_call
                    and isinstance(args, dict)
                    and args.get("bill_id") == bill_id
                ):
                    found = ""  # an earlier payment on this bill used up any card before it
        result = entry.get("toolUseResult")
        if entry.get("type") != "user" or not isinstance(result, dict):
            continue
        ids = {str(b.get("tool_use_id")) for b in _blocks(entry) if b.get("type") == "tool_result"}
        answers, questions = result.get("answers"), result.get("questions")
        if not ids & asks or not isinstance(answers, dict) or not isinstance(questions, list):
            continue
        for q in questions:
            if not isinstance(q, dict) or q.get("header") != CARD_HEADER:
                continue
            text = str(q.get("question", ""))
            if " ".join(text.split()) != want:
                found = "other card"
            else:
                chosen = answers.get(text)
                found = chosen if isinstance(chosen, str) else "unanswered"
    return found


def card_request(question: str, status: str) -> str:
    """The deny reason: why, then the exact AskUserQuestion input that would approve the call."""
    card = {"header": CARD_HEADER, "question": question}
    card.update(multiSelect=False, options=CARD_OPTIONS)
    return "\n".join(
        [
            f"Receipts: this payment needs the owner's approval in chat first. {status}",
            "Ask the owner with the AskUserQuestion tool, using exactly this input:",
            json.dumps({"questions": [card]}, ensure_ascii=False),
            f'If they choose "{APPROVE}", call pay_bill again with the same bill_id,'
            + " amount_cents and to_account. One approval covers one payment.",
            f'If they choose "{DECLINE}", don\'t retry; tell them the bill was not paid.',
        ]
    )


STATUS = {
    "": "No approval card for this payment was found.",
    DECLINE: "The owner declined it.",
    "other card": "The latest approval card doesn't match this payment's amount, account or bill.",
    "unanswered": "The approval card has no answer recorded.",
}


def decide(event: Any) -> tuple[str, str] | None:
    """The decision and its reason, or None to stay silent."""
    if not isinstance(event, dict) or not isinstance(event.get("tool_input"), dict):
        return "ask", "Receipts: malformed payment call (no tool input); couldn't check it."
    tool_input = event["tool_input"]
    amount = tool_input.get("amount_cents")
    threshold, source = threshold_cents()
    is_int = isinstance(amount, int) and not isinstance(amount, bool)
    paid = paid_on_bill(str(tool_input["bill_id"])) if "bill_id" in tool_input else 0
    if is_int and amount > 0 and threshold is not None and amount + max(paid, 0) <= threshold:
        return None
    details = reason(tool_input, threshold, source, paid)
    question = card_question(tool_input, paid)
    if question is None:
        return "ask", details + NO_TRANSCRIPT.format("the call is malformed")
    entries = _entries(event.get("transcript_path"))
    if entries is None:
        return "ask", details + NO_TRANSCRIPT.format("the session transcript couldn't be read")
    answer = card_answer(entries, tool_input["bill_id"], question, event.get("tool_use_id"))
    if answer == APPROVE:
        return "allow", "Receipts: the owner approved this payment in chat."
    status = STATUS.get(answer, f'The owner answered "{_clip(answer, 40)}", not "{APPROVE}".')
    return "deny", card_request(question, status)


def output(decision: str, text: str) -> str:
    out = {"hookEventName": "PreToolUse", "permissionDecision": decision}
    out["permissionDecisionReason"] = text
    return json.dumps({"hookSpecificOutput": out})


def main() -> None:
    try:
        result = decide(json.loads(sys.stdin.read() or "null"))
    except Exception as exc:  # noqa: BLE001 - any failure must prompt, never allow
        text = f"Receipts: the approval check failed ({type(exc).__name__}); review this payment."
        result = ("ask", text)
    if result is not None:
        print(output(*result))


if __name__ == "__main__":
    main()
