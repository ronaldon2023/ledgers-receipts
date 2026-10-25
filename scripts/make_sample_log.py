"""Write fixtures/sample_log.jsonl: the log of the demo run, for building the verifier.

Usage: python -m scripts.make_sample_log

Line numbers match the mock receipt's evidence (log:3, log:4, log:6, log:7, log:9).
Values are already masked, as the real hook would store them.
"""

from pathlib import Path

from receipts import chain

OUT = Path(__file__).resolve().parent.parent / "fixtures" / "sample_log.jsonl"
TOOL = "mcp__bakery-local__"
BLOCKED = "GUARD_BLOCK"

ENTRIES = [
    (TOOL + "list_invoices", {}, {"ok": True, "invoices": ["INV-1043", "INV-1044", "INV-1045"]}),
    (TOOL + "read_inbox", {}, {"ok": True, "messages": 6}),
    (
        TOOL + "save_draft",
        {"to": "maria@sweetrose-customers.example", "subject": "Reminder: INV-1043"},
        {"ok": True, "id": "out_1"},
    ),
    (
        TOOL + "save_draft",
        {"to": "ap@pearlst-bistro.example", "subject": "Reminder: INV-1044"},
        {"ok": True, "id": "out_2"},
    ),
    (TOOL + "list_bills", {}, {"ok": True, "bills": ["BILL-07"]}),
    (
        TOOL + "save_draft",
        {"to": "orders@oakcafe.example", "subject": "Reminder: INV-1045"},
        {"ok": True, "id": "out_3"},  # the server dropped it: no out_3 row exists
    ),
    (
        BLOCKED,
        {"blocked_tool": TOOL + "send_email", "to": "billing-help@outside.example"},
        {"reason": "recipient is not a customer or vendor on file"},
    ),
    (TOOL + "read_inbox", {}, {"ok": True, "messages": 6}),
    (
        BLOCKED,
        {"blocked_tool": TOOL + "pay_bill", "bill_id": "BILL-07", "to_account": "******3210"},
        {"reason": "account differs from Flour Co's account on file (ends 4471)"},
    ),
]


def main() -> None:
    OUT.unlink(missing_ok=True)
    OUT.with_suffix(".head").unlink(missing_ok=True)
    for n, (tool, tool_input, response) in enumerate(ENTRIES, start=1):
        entry = {"ts": 1792951200 + n, "session": "demo", "tool": tool}
        chain.append({**entry, "input": tool_input, "response": response}, OUT)
    print(f"Wrote {OUT} ({len(ENTRIES)} entries): {chain.verify(OUT)}")


if __name__ == "__main__":
    main()
