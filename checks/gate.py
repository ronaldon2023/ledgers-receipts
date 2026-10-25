"""Checks a write must pass before it runs: the plan's C4 to C8 for pay_bill.

The MCP server's write tool calls evaluate() first and writes only if no result is "block",
which is what allowed() tests. Each check reads the records through a Source and never trusts the agent's
arguments over them. Anything that goes wrong blocks (fail closed). Ids and statuses follow
docs/order-lifecycle-plan.md section 5; C1 to C3 need the owner's policy (issue #9).

Usage: python -m checks pay_bill '{"bill_id": "BILL-07", ...}' [--db bakery.db]   (see __main__)
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from checks.source import Source


@dataclass
class CheckResult:
    id: str
    status: str  # pass | block | ask | unknown
    title: str
    evidence: list[str] = field(default_factory=list)  # record refs, e.g. "bills:BILL-07"
    inputs: dict = field(default_factory=dict)  # the values compared, account numbers masked


def allowed(results: list[CheckResult]) -> bool:
    """Whether the write may go ahead. Only "block" stops it; "ask" is the approval hook's."""
    return not any(r.status == "block" for r in results)


def _account(value: object) -> str | None:
    """The account's digits, or None if it isn't one. ASCII spaces and dashes are formatting,
    so "0001 2345-4471" is the same account; anything else (a tab, a Unicode space or digit,
    a letter) isn't stripped, so the check can't pass a value the payment would store
    differently."""
    if not isinstance(value, str):
        return None
    digits = value.replace(" ", "").replace("-", "")
    return digits if re.fullmatch(r"[0-9]+", digits) else None


def _last4(account: object) -> str:
    if not isinstance(account, str):
        return "not text" if account is not None else "none"
    return f"••{account[-4:]}" if account else "none"


def _domain(addr: object) -> str:
    """The domain of a bare address, or "" for anything else, which C8 then blocks."""
    if not isinstance(addr, str) or addr.count("@") != 1 or re.search(r"[\s<>,;\"]", addr):
        return ""
    local, domain = addr.split("@")
    return domain.lower().rstrip(".") if local else ""


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


@dataclass
class Payment:
    """One pay_bill call with the records it touches, read once for every check."""

    args: dict
    bill: dict
    vendor: dict | None
    order: dict | None
    payments: list[dict]


def c4_account_on_file(p: Payment) -> CheckResult:
    """Both the account being paid and the account the bill asks for must be the one on file;
    a bill asking for a new account is the bank-change fraud even if the agent ignores it."""
    raw_to, raw_asked = p.args["to_account"], p.bill["pay_to_account"]
    to, asked, on_file = _account(raw_to), _account(raw_asked), _account(p.vendor["bank_account"])
    inputs = {
        "to_account": _last4(to or raw_to),
        "bill_asks": _last4(asked or raw_asked),
        "on_file": _last4(on_file),
    }
    ev = [f"bills:{p.bill['id']}", f"vendors:{p.vendor['id']}"]
    name = p.vendor["name"]
    if on_file is None:
        return CheckResult("C4", "block", f"{name} has no valid account on file", ev, inputs)
    if to is None:
        title = f"Account to pay {_last4(raw_to)} isn't a plain account number"
        return CheckResult("C4", "block", title, ev, inputs)
    if to != on_file:
        title = f"Account {_last4(to)} differs from {name}'s on file {_last4(on_file)}"
        if _last4(to) == _last4(on_file):
            title = f"Account {_last4(to)} is not {name}'s on file; only the last 4 digits match"
        return CheckResult("C4", "block", title, ev, inputs)
    if asked != on_file:
        shown = _last4(asked or raw_asked)
        title = f"The bill asks to pay {shown}, not {name}'s on file {_last4(on_file)}"
        return CheckResult("C4", "block", title, ev, inputs)
    return CheckResult("C4", "pass", f"Pays {name}'s account on file", ev, inputs)


def c5_amounts_agree(p: Payment) -> CheckResult:
    paying, billed = p.args["amount_cents"], p.bill["amount_cents"]
    ordered = p.order["total_cents"] if p.order else None
    inputs = {"amount_cents": paying, "bill_cents": billed, "order_cents": ordered}
    ev = [f"bills:{p.bill['id']}"] + ([f"orders:{p.order['id']}"] if p.order else [])
    if type(paying) is not int:  # bool is an int subclass; "80000" and 80000.0 aren't cents
        return CheckResult("C5", "block", "The amount must be whole cents", ev, inputs)
    if paying != billed:
        title = f"Paying {_money(paying)} against a bill for {_money(billed)}"
        return CheckResult("C5", "block", title, ev, inputs)
    if ordered is None:
        return CheckResult("C5", "unknown", "No order to compare the bill with", ev, inputs)
    if billed != ordered:
        title = f"Bill is {_money(billed)} but order {p.order['id']} totals {_money(ordered)}"
        return CheckResult("C5", "block", title, ev, inputs)
    return CheckResult("C5", "pass", f"Payment, bill and order all {_money(paying)}", ev, inputs)


def c6_bill_has_order(p: Payment) -> CheckResult:
    inputs = {"bill.order_id": p.bill["order_id"], "bill.vendor_id": p.bill["vendor_id"]}
    ev = [f"bills:{p.bill['id']}"]
    if p.order is None:
        title = f"Bill {p.bill['id']} names no known order"
        return CheckResult("C6", "block", title, ev, inputs)
    inputs["order.vendor_id"] = p.order["vendor_id"]
    ev.append(f"orders:{p.order['id']}")
    if p.order["vendor_id"] != p.bill["vendor_id"]:
        title = f"Bill {p.bill['id']} is from a different supplier than order {p.order['id']}"
        return CheckResult("C6", "block", title, ev, inputs)
    return CheckResult(
        "C6", "pass", f"Bill {p.bill['id']} is for order {p.order['id']}", ev, inputs
    )


def c7_not_paid_yet(p: Payment) -> CheckResult:
    live = [x for x in p.payments if x["status"] != "failed"]
    inputs = {"bill.status": p.bill["status"], "live_payments": [x["id"] for x in live]}
    ev = [f"bills:{p.bill['id']}"] + [f"payments:{x['id']}" for x in live]
    if live or p.bill["status"] == "paid":
        title = f"Bill {p.bill['id']} is already paid"
        return CheckResult("C7", "block", title, ev, inputs)
    return CheckResult("C7", "pass", f"No earlier payment for bill {p.bill['id']}", ev, inputs)


def c8_sender_domain(p: Payment) -> CheckResult:
    sent, on_file = _domain(p.bill["from_addr"]), _domain(p.vendor["email"])
    inputs = {"bill.from_domain": sent, "on_file_domain": on_file}
    ev = [f"bills:{p.bill['id']}", f"vendors:{p.vendor['id']}"]
    if not sent or sent != on_file:
        title = f"Bill came from {sent or 'no domain'}, not {p.vendor['name']}'s {on_file}"
        return CheckResult("C8", "block", title, ev, inputs)
    return CheckResult("C8", "pass", f"Bill came from {p.vendor['name']}'s domain", ev, inputs)


PAY_CHECKS: dict[str, Callable[[Payment], CheckResult]] = {
    "C4": c4_account_on_file,
    "C5": c5_amounts_agree,
    "C6": c6_bill_has_order,
    "C7": c7_not_paid_yet,
    "C8": c8_sender_domain,
}


PAY_ARGS = ("bill_id", "amount_cents", "to_account")


def _pay_bill(args: dict, source: Source) -> list[CheckResult]:
    missing = [a for a in PAY_ARGS if a not in args]
    if missing:
        return [CheckResult("C0", "block", f"pay_bill is missing {', '.join(missing)}")]
    bill = source.bill(args["bill_id"])
    if bill is None:
        title = f"No bill {args['bill_id']} on file"
        results = [CheckResult(i, "unknown", "No bill to check against") for i in PAY_CHECKS]
        results[list(PAY_CHECKS).index("C6")] = CheckResult("C6", "block", title)
        return results
    order = source.order(bill["order_id"]) if bill["order_id"] else None
    payment = Payment(
        args, bill, source.vendor(bill["vendor_id"]), order, source.payments_for_bill(bill["id"])
    )
    results = []
    for check_id, check in PAY_CHECKS.items():
        try:
            results.append(check(payment))
        except Exception as e:  # noqa: BLE001 - any crash must block, whatever its type
            results.append(CheckResult(check_id, "block", f"Check crashed: {type(e).__name__}"))
    return results


ACTIONS: dict[str, Callable[[dict, Source], list[CheckResult]]] = {"pay_bill": _pay_bill}


def evaluate(
    action: str, args: dict, source: Source, policy: dict | None = None
) -> list[CheckResult]:
    """Run the checks for one write. policy is unused until C1 to C3 land (issue #9)."""
    if action not in ACTIONS:
        return [CheckResult("C0", "block", f"No checks are defined for {action}")]
    try:
        return ACTIONS[action](args, source)
    except Exception as e:  # noqa: BLE001 - a broken source blocks
        # The type only: an exception's message can echo an argument, such as an account.
        return [CheckResult("C0", "block", f"Checks couldn't run: {type(e).__name__}")]
