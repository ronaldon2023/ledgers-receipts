"""Verifier (demo version): turn the hash-chain log and bakery.db into receipts for the portal.

Usage: python -m receipts.verify [--out fixtures/portal]

For every bill Claude tried to pay, it writes receipt_live_<order>.json (the order receipt
shape from docs/mock/order_receipt.json) and one feed_live.json for the dashboard
(?state=live). Everything comes from the log and the records; nothing asks Claude.

- The check results (C4-C8) are the ones pay_bill recorded in the log.
- C10 is checked here: a "paid" result must have its payment row in bakery.db.
- A broken log chain makes every receipt UNTRUSTED.
Claims (Claude's summary vs the records) are not checked yet, so summary_check is
"not_checked". The full verifier (Anthony's plan, task 7) replaces this.
"""

import argparse
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from receipts import chain
from receipts.feed import build_feed, iso, money
from receipts.pii import mask_text

CHECK_STATUS = {"pass": "verified", "block": "blocked", "ask": "needs_approval"}
NEXT_STEP = {
    "C4": "Call Flour Co on the number you already have to confirm their bank account.",
    "C5": "Check the bill against the order before paying.",
    "C6": "Don't pay a bill that isn't for one of your orders.",
    "C7": "This bill was already paid. Don't pay it twice.",
    "C8": "This bill came from a look-alike address. Don't pay it; contact Flour Co directly.",
}


def _response(raw: object) -> dict:
    """MCP tool responses are logged as [{"type": "text", "text": "<json>"}] or a plain dict."""
    if isinstance(raw, list) and raw and isinstance(raw[0], dict) and "text" in raw[0]:
        raw = raw[0]["text"]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


def read_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        entry = json.loads(line)
        entry["n"], entry["resp"] = n, _response(entry.get("response"))
        entries.append(entry)
    return entries


def _records(db_path: Path) -> dict:
    with closing(sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row

        def q(sql: str, *args: object) -> list[dict]:
            return [dict(r) for r in conn.execute(sql, args)]

        return {
            "bills": {b["id"]: b for b in q("SELECT * FROM bills")},
            "orders": {o["id"]: o for o in q("SELECT * FROM orders")},
            "items": q("SELECT * FROM order_items"),
            "vendors": {v["id"]: v for v in q("SELECT * FROM vendors")},
            "payments": {p["id"]: p for p in q("SELECT * FROM payments")},
            "budget": q("SELECT limit_cents FROM policies WHERE id = 'POL-BUDGET-MONTHLY'"),
            "floor": q("SELECT limit_cents FROM policies WHERE id = 'POL-BANK-FLOOR'"),
            "balance": q("SELECT balance_cents FROM accounts WHERE id = 'ACC-OPS'"),
        }


def _receipt(bill_id: str, attempts: list[dict], rec: dict, status: chain.ChainStatus) -> dict:
    bill = rec["bills"][bill_id]
    order = rec["orders"][bill["order_id"]]
    vendor = rec["vendors"][bill["vendor_id"]]
    last = attempts[-1]
    resp, n = last["resp"], last["n"]
    items = [
        {**i, "total_cents": i["quantity"] * i["unit_price_cents"]}
        for i in rec["items"]
        if i["order_id"] == order["id"]
    ]
    checks = [
        {
            "id": c["id"],
            "status": CHECK_STATUS.get(c["status"], c["status"]),
            "title": c["title"],
            "evidence": [*c.get("evidence", []), f"log:{n}"],
        }
        for c in resp.get("checks", [])
    ]
    pay_id = resp.get("id") if resp.get("ok") else None
    if pay_id:  # C10: the tool said paid, so the payment row must exist
        found = pay_id in rec["payments"]
        checks.append(
            {
                "id": "C10",
                "status": "verified" if found else "phantom",
                "title": f"Payment {pay_id} is in the bank records"
                if found
                else f"The tool said {pay_id} was paid, but no payment row exists",
                "evidence": [f"payments:{pay_id}", f"log:{n}"],
            }
        )
    blocked = [c for c in checks if c["status"] in ("blocked", "phantom")]
    pay_status = (
        "sent" if pay_id and not blocked else "blocked" if resp.get("blocked") else "failed"
    )
    if not status.ok:
        verdict, reason = (
            "UNTRUSTED",
            "The log was changed after the run, so this can't be trusted.",
        )
    elif blocked:
        verdict = "ISSUES_FOUND"
        reason = f"The {money(bill['amount_cents'])} payment to {vendor['name']} was stopped: " + (
            "; ".join(c["title"] for c in blocked)
        )
    else:
        verdict = "VERIFIED"
        reason = f"Paid {money(bill['amount_cents'])} to {vendor['name']}'s account on file."
    first_block = next((c["id"] for c in blocked), None)
    return {
        "receipt_type": "order",
        "receipt_id": f"RCPT-{order['id']}",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "business": "Sweet Rose Bakery",
        "verdict": verdict,
        "verdict_reason": reason,
        "owner_action": {
            "needed": bool(blocked) or not status.ok,
            "title": NEXT_STEP.get(first_block, "Review this order before relying on it."),
        },
        "order": {
            "order_number": order["id"],
            "order_date": order["order_date"],
            "seller": {"id": vendor["id"], "name": vendor["name"], "email": vendor["email"]},
            "items": items,
            "total_cents": order["total_cents"],
        },
        "bill": {
            "bill_id": bill_id,
            "vendor_id": vendor["id"],
            "references_order": order["id"],
            "from": bill["from_addr"],
            "amount_cents": bill["amount_cents"],
            "due_date": bill["due_date"],
        },
        "payment": {
            "payment_id": pay_id if pay_status == "sent" else None,
            "status": pay_status,
            "amount_cents": last["input"].get("amount_cents"),
            "requested_to_account": last["input"].get("to_account"),
            "account_on_file": mask_text(vendor["bank_account"]),
            "method": "bank_transfer",
        },
        "events": [
            {"stage": "order_placed", "status": "done", "at": order["order_date"], "source": "db"},
            {"stage": "bill_received", "status": "done", "at": None, "source": "db"},
            {
                "stage": "payment_sent",
                "status": "done" if pay_status == "sent" else pay_status,
                "at": iso(last["ts"]),
                "source": "log",
            },
        ],
        "checks": checks,
        "summary_check": {"status": "not_checked"},
        "chain": {"ok": status.ok, "entries": status.entries, "head": status.head},
        # One hash chain covers every session; each session reports the chain's state.
        "sessions": [
            {"session": sid, "ok": status.ok, "entries": status.entries, "head": status.head}
            for sid in dict.fromkeys(a.get("session", "") for a in attempts)
        ],
    }


def build(log_path: Path, db_path: Path) -> tuple[dict, dict]:
    """Return (feed, receipts by order id) for every bill Claude tried to pay."""
    status, log, rec = chain.verify(log_path), read_log(log_path), _records(db_path)
    attempts: dict[str, list[dict]] = {}
    for e in log:
        bill_id = e["input"].get("bill_id")
        if e["tool"].endswith("__pay_bill") and bill_id in rec["bills"]:
            attempts.setdefault(bill_id, []).append(e)
    receipts = {}
    for bill_id, tries in attempts.items():
        rc = _receipt(bill_id, tries, rec, status)
        receipts[rc["order"]["order_number"]] = rc
    return build_feed(receipts, log, rec, status), receipts


def write(out: Path, feed: dict, receipts: dict) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for order_id, rc in receipts.items():
        p = out / f"receipt_live_{order_id}.json"
        p.write_text(json.dumps(rc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(p)
    p = out / "feed_live.json"
    p.write_text(json.dumps(feed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return [*written, p]


def main() -> None:
    ap = argparse.ArgumentParser(description="Write portal receipts from the log and bakery.db.")
    ap.add_argument("--out", default="fixtures/portal")
    ap.add_argument("--db", default=os.environ.get("BAKERY_DB", "bakery.db"))
    args = ap.parse_args()
    feed, receipts = build(chain.default_path(), Path(args.db))
    for p in write(Path(args.out), feed, receipts):
        print(f"wrote {p}")
    for order_id, rc in receipts.items():
        print(f"{order_id}: {rc['verdict']} - {rc['verdict_reason']}")


if __name__ == "__main__":
    main()
