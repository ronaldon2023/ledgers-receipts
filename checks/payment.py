"""Ledger checks for the payment stage of an order receipt.

The receipt records what happened; these rules decide whether it adds up. They read only the
receipt, so the same receipt always gives the same results, and a rule can change without
changing the receipt's shape. Comparing the receipt with bakery.db (reconciliation) is a
separate set of checks, not done here.

Usage: python -m checks.payment receipt.json   prints one line per check, exits 1 on a fail
"""

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

STAGES = (
    "order_placed",
    "order_sent",
    "fulfilled",
    "bill_received",
    "payment_ready",
    "payment_sent",
)

# payment.status and the payment_sent stage describe the same event and must agree.
PAYMENT_STAGE_STATUS = {
    "sent": "done",
    "blocked": "blocked",
    "failed": "failed",
    "not_started": "not_reached",
}


@dataclass
class Result:
    id: str
    status: str  # pass | fail | warn | skip
    title: str
    inputs: dict = field(default_factory=dict)  # the values compared, masked as in the receipt


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def items_add_up(r: dict) -> Result:
    order = r["order"]
    lines = [i["quantity"] * i["unit_price_cents"] for i in order["items"]]
    # The schema makes subtotal and tax optional: no tax means 0, no subtotal means the items.
    subtotal, tax = order.get("subtotal_cents", sum(lines)), order.get("tax_cents", 0)
    inputs = {
        "line_totals": [i["total_cents"] for i in order["items"]],
        "subtotal_cents": subtotal,
        "tax_cents": tax,
        "total_cents": order["total_cents"],
    }
    if lines != inputs["line_totals"]:
        title = f"An item's total isn't quantity times price on order {order['order_number']}"
        return Result("PAY-ITEMS-TOTAL", "fail", title, inputs)
    if sum(lines) != subtotal or subtotal + tax != order["total_cents"]:
        title = f"Order {order['order_number']}'s items and tax don't add up to its total"
        return Result("PAY-ITEMS-TOTAL", "fail", title, inputs)
    title = f"Order {order['order_number']}'s items add up to {_money(order['total_cents'])}"
    return Result("PAY-ITEMS-TOTAL", "pass", title, inputs)


def bill_matches_order(r: dict) -> Result:
    order, bill = r["order"], r["bill"]
    if bill is None:
        received = next((e["status"] for e in r["events"] if e["stage"] == "bill_received"), None)
        inputs = {"bill": None, "payment.status": r["payment"]["status"], "bill_received": received}
        if r["payment"]["status"] == "sent":
            title = f"A payment was sent, but order {order['order_number']} has no bill"
        elif received == "done":
            title = f"The events say a bill arrived, but order {order['order_number']} has none"
        else:
            return Result("PAY-BILL-ORDER", "skip", "No bill yet", inputs)
        return Result("PAY-BILL-ORDER", "fail", title, inputs)
    inputs = {
        "bill.references_order": bill["references_order"],
        "order.order_number": order["order_number"],
        "bill.vendor_id": bill["vendor_id"],
        "order.seller.id": order["seller"]["id"],
        "bill.amount_cents": bill["amount_cents"],
        "order.total_cents": order["total_cents"],
    }
    if bill["references_order"] != order["order_number"]:
        title = f"Bill {bill['bill_id']} is for a different order than {order['order_number']}"
    elif bill["vendor_id"] != order["seller"]["id"]:
        title = f"Bill {bill['bill_id']} is from a different vendor than the order's seller"
    elif bill["amount_cents"] != order["total_cents"]:
        title = (
            f"Bill {bill['bill_id']} is {_money(bill['amount_cents'])}, but order "
            f"{order['order_number']} totals {_money(order['total_cents'])}"
        )
    else:
        title = f"Bill {bill['bill_id']} matches order {order['order_number']}"
        return Result("PAY-BILL-ORDER", "pass", title, inputs)
    return Result("PAY-BILL-ORDER", "fail", title, inputs)


def payment_matches_bill(r: dict) -> Result:
    bill, payment = r["bill"], r["payment"]
    if bill is None:
        return Result("PAY-AMOUNT", "skip", "No bill yet", {"bill": None})
    inputs = {
        "payment.amount_cents": payment["amount_cents"],
        "bill.amount_cents": bill["amount_cents"],
    }
    if payment["amount_cents"] != bill["amount_cents"]:
        title = (
            f"Payment of {_money(payment['amount_cents'])} doesn't match bill {bill['bill_id']} "
            f"for {_money(bill['amount_cents'])}"
        )
        return Result("PAY-AMOUNT", "fail", title, inputs)
    title = f"Payment amount matches bill {bill['bill_id']}"
    return Result("PAY-AMOUNT", "pass", title, inputs)


def payee_on_file(r: dict) -> Result:
    """A sent payment went to the account on file. Masked numbers only show the last 4 digits,
    so a match here is consistent, not proof; reconciliation against bakery.db proves it."""
    payment = r["payment"]
    to, on_file = payment.get("requested_to_account"), payment.get("account_on_file")
    inputs = {"requested_to_account": to, "account_on_file": on_file}
    if payment["status"] != "sent":
        return Result("PAY-PAYEE", "skip", "No payment left the business", inputs)
    if not to or not on_file or to[-4:] != on_file[-4:]:
        title = f"Payment went to account {to}, not the account on file {on_file}"
        return Result("PAY-PAYEE", "fail", title, inputs)
    title = f"Payment account {to} ends in the same 4 digits as the account on file {on_file}"
    return Result("PAY-PAYEE", "pass", title, inputs)


def stages_in_order(r: dict) -> Result:
    stages = r["events"]
    names = [s["stage"] for s in stages]
    times = [datetime.fromisoformat(s["at"]) for s in stages if s["at"]]
    inputs = {"stages": names, "times": [s["at"] for s in stages]}
    if names != sorted(set(names), key=STAGES.index):
        return Result(
            "PAY-STAGE-ORDER", "fail", "Lifecycle stages are repeated or out of order", inputs
        )
    if times != sorted(times):
        return Result(
            "PAY-STAGE-ORDER", "fail", "A lifecycle stage is dated before an earlier one", inputs
        )
    status = {s["stage"]: s["status"] for s in stages}
    if status.get("payment_sent") == "done":
        missing = [n for n in ("bill_received", "payment_ready") if status.get(n) != "done"]
        if missing:
            title = f"Payment was sent before {' and '.join(missing)} was done"
            return Result("PAY-STAGE-ORDER", "fail", title, inputs)
    return Result("PAY-STAGE-ORDER", "pass", "Lifecycle stages happened in order", inputs)


def payment_matches_stage(r: dict) -> Result:
    status = r["payment"]["status"]
    stage = next((s["status"] for s in r["events"] if s["stage"] == "payment_sent"), "not_reached")
    inputs = {"payment.status": status, "payment_sent.status": stage}
    if PAYMENT_STAGE_STATUS.get(status) != stage:
        title = f"Payment says {status}, but its lifecycle stage says {stage}"
        return Result("PAY-STATUS-STAGE", "fail", title, inputs)
    return Result("PAY-STATUS-STAGE", "pass", "Payment status matches its lifecycle stage", inputs)


def paid_on_time(r: dict) -> Result:
    if r["bill"] is None:
        return Result("PAY-ON-TIME", "skip", "No bill yet", {"bill": None})
    due = r["bill"]["due_date"]
    sent = next((s["at"] for s in r["events"] if s["stage"] == "payment_sent"), None)
    inputs = {"bill.due_date": due, "payment_sent.at": sent}
    if r["payment"]["status"] != "sent":
        return Result("PAY-ON-TIME", "skip", "No payment was sent", inputs)
    if not sent:
        title = "Payment was sent, but the receipt doesn't record when"
        return Result("PAY-ON-TIME", "skip", title, inputs)
    if datetime.fromisoformat(sent).date() > date.fromisoformat(due):
        return Result(
            "PAY-ON-TIME", "warn", f"Payment was sent after the bill was due ({due})", inputs
        )
    return Result("PAY-ON-TIME", "pass", f"Payment was sent by the due date ({due})", inputs)


# Keyed by the id each check reports, so a check that can't run still fails under its id.
CHECKS: dict[str, Callable[[dict], Result]] = {
    "PAY-ITEMS-TOTAL": items_add_up,
    "PAY-BILL-ORDER": bill_matches_order,
    "PAY-AMOUNT": payment_matches_bill,
    "PAY-PAYEE": payee_on_file,
    "PAY-STAGE-ORDER": stages_in_order,
    "PAY-STATUS-STAGE": payment_matches_stage,
    "PAY-ON-TIME": paid_on_time,
}


def run(receipt: dict) -> list[Result]:
    """Run every payment check. A receipt missing a field a check needs fails that check."""
    results = []
    for check_id, check in CHECKS.items():
        try:
            results.append(check(receipt))
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            title = f"Receipt is missing what {check_id} needs: {type(e).__name__} {e}"
            results.append(Result(check_id, "fail", title))
    return results


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python -m checks.payment receipt.json")
    with open(sys.argv[1], encoding="utf-8") as f:
        results = run(json.load(f))
    for res in results:
        print(f"{res.status.upper():5} {res.id:17} {res.title}")
    sys.exit(1 if any(res.status == "fail" for res in results) else 0)


if __name__ == "__main__":
    main()
