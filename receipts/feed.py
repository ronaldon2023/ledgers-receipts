"""The portal's dashboard feed (feed_live.json), built from the verifier's receipts and the log.

The shape follows fixtures/portal/feed_<state>.json in the owner portal (PR #11), which is
a proposed display shape, not a team contract.
"""

from datetime import datetime

from receipts import chain


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def build_feed(receipts: dict, log: list[dict], rec: dict, status: chain.ChainStatus) -> dict:
    steps, attention, events, orders = [], [], [], []
    for e in log:
        tool = e["tool"].split("__")[-1]
        r, bill_id = e["resp"], e["input"].get("bill_id")
        order_id = rec["bills"][bill_id]["order_id"] if bill_id in rec["bills"] else None
        if tool == "pay_bill":
            amount = money(e["input"].get("amount_cents") or 0)
            result = "done" if r.get("ok") else "blocked"
            text = f"Tried to pay {bill_id}: {amount} to {e['input'].get('to_account')}"
            call = f"pay_bill · bill={bill_id} · amount={amount}"
        else:
            result, text, call = "read", f"Called {tool}", tool
        steps.append(
            {
                "id": f"log:{e['n']}",
                "at": iso(e["ts"]),
                "actor": "claude",
                "text": text,
                "call": call,
                "result": result,
                "order": order_id,
            }
        )
        for c in r.get("checks", []):
            steps.append(
                {
                    "id": f"log:{e['n']}:{c['id']}",
                    "at": iso(e["ts"]),
                    "actor": "checks",
                    "text": c["title"],
                    "call": c["id"],
                    "result": "passed" if c["status"] == "pass" else "blocked",
                    "order": order_id,
                }
            )
    for order_id, rc in receipts.items():
        ids = [s["id"] for s in steps if s["order"] == order_id]
        bill, paid = rc["bill"], rc["payment"]["status"] == "sent"
        title = (
            f"Paid {money(bill['amount_cents'])} to Flour Co for {bill['bill_id']}"
            if paid
            else f"The {money(bill['amount_cents'])} payment for {bill['bill_id']} was not sent"
        )
        level = "done" if paid else "stop"
        at = rc["events"][-1]["at"]
        attention.append(
            {
                "id": f"att_{order_id}",
                "level": level,
                "context": "Payment",
                "at": at,
                "title": title,
                "body": rc["verdict_reason"],
                "next_step": rc["owner_action"]["title"] if rc["owner_action"]["needed"] else None,
                "actions": [{"label": "Open order receipt", "href": f"#order/{order_id}"}],
                "steps": ids,
            }
        )
        events.append(
            {
                "id": f"ev_{order_id}",
                "at": at,
                "level": level,
                "kind": "Payment",
                "order": order_id,
                "bill": bill["bill_id"],
                "title": title,
                "detail": rc["verdict_reason"],
                "steps": ids,
            }
        )
        o = rc["order"]
        orders.append(
            {
                "order_number": order_id,
                "seller": o["seller"]["name"],
                "summary": ", ".join(f"{i['quantity']} × {i['name']}" for i in o["items"]),
                "total_cents": o["total_cents"],
                "placed_at": o["order_date"],
                "seller_email": o["seller"]["email"],
                "items": o["items"],
                "bill_id": bill["bill_id"],
                "bill_due": bill["due_date"],
                "progress": [
                    {"label": "Order sent", "level": "done"},
                    {"label": "Bill matched", "level": "done"},
                    {
                        "label": "Payment sent" if paid else "Payment stopped",
                        "level": "done" if paid else "stop",
                    },
                ],
            }
        )
    paid_cents = sum(p["amount_cents"] for p in rec["payments"].values() if p["status"] == "sent")
    month = datetime.now().strftime("%Y-%m")
    used = sum(o["total_cents"] for o in rec["orders"].values() if o["order_date"][:7] == month)
    blocked_first = [o for o, rc in receipts.items() if rc["verdict"] != "VERIFIED"]
    shown = (blocked_first or list(receipts))[:1]
    return {
        "_note": "Written by python -m receipts.verify from the log and bakery.db.",
        "state": "live",
        "as_of": datetime.now().astimezone().isoformat(timespec="seconds"),
        "business": "Sweet Rose Bakery",
        "owner": "Rose",
        "chain_ok": status.ok,
        "receipt": f"receipt_live_{shown[0]}.json" if shown else None,
        "glance": {
            "budget": {
                "label": f"Supplies budget · {datetime.now():%B}",
                "used_cents": used,
                "limit_cents": rec["budget"][0]["limit_cents"] if rec["budget"] else 0,
            },
            "balance": {
                "balance_cents": (rec["balance"][0]["balance_cents"] if rec["balance"] else 0)
                - paid_cents,
                "floor_cents": rec["floor"][0]["limit_cents"] if rec["floor"] else 0,
                "note": f"after {money(paid_cents)} paid" if paid_cents else "nothing was paid",
            },
            "run": {
                "steps": len(log),
                "blocked": sum(
                    1 for s in steps if s["result"] == "blocked" and s["actor"] == "claude"
                ),
            },
        },
        "orders": orders,
        "attention": attention,
        "events": events,
        "steps": steps,
    }
