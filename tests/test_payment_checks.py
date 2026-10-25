import json
import subprocess
import sys
from pathlib import Path

import pytest

from checks import payment

FIXTURE = Path(__file__).parent.parent / "docs" / "mock" / "order_receipt.json"


def blocked() -> dict:
    """The sample: Flour Co's payment was stopped by the guard."""
    return json.loads(FIXTURE.read_text())


def paid() -> dict:
    """The same order, paid to the account on file before the due date."""
    r = blocked()
    r["payment"].update(status="sent", payment_id="pay_1", requested_to_account="******4471")
    next(e for e in r["events"] if e["stage"] == "payment_sent")["status"] = "done"
    return r


def unbilled() -> dict:
    """The same order before the supplier has billed it."""
    r = blocked()
    r["bill"] = None
    r["payment"]["status"] = "not_started"
    for e in r["events"][-3:]:
        e.update(status="not_reached", at=None)
    return r


def statuses(r: dict) -> dict[str, str]:
    return {res.id: res.status for res in payment.run(r)}


def event(r: dict, stage: str) -> dict:
    return next(e for e in r["events"] if e["stage"] == stage)


@pytest.mark.parametrize("receipt", [blocked, paid, unbilled])
def test_clean_receipt_has_no_fails(receipt):
    assert "fail" not in statuses(receipt()).values()
    assert "warn" not in statuses(receipt()).values()


def test_blocked_payment_skips_payee_and_due_date():
    s = statuses(blocked())
    assert s["PAY-PAYEE"] == s["PAY-ON-TIME"] == "skip"


# (name, how to break a paid receipt, the checks that must fail)
BREAKS = [
    ("item_total", lambda r: r["order"]["items"][0].update(total_cents=61000), "PAY-ITEMS-TOTAL"),
    ("subtotal", lambda r: r["order"].update(subtotal_cents=79000), "PAY-ITEMS-TOTAL"),
    ("tax", lambda r: r["order"].update(tax_cents=500), "PAY-ITEMS-TOTAL"),
    ("bill_order", lambda r: r["bill"].update(references_order="PO-2033"), "PAY-BILL-ORDER"),
    ("bill_vendor", lambda r: r["bill"].update(vendor_id="V-9"), "PAY-BILL-ORDER"),
    ("bill_amount", lambda r: r["bill"].update(amount_cents=90000), "PAY-BILL-ORDER PAY-AMOUNT"),
    ("payment_amount", lambda r: r["payment"].update(amount_cents=90000), "PAY-AMOUNT"),
    ("payee", lambda r: r["payment"].update(requested_to_account="******3210"), "PAY-PAYEE"),
    ("payee_missing", lambda r: r["payment"].pop("requested_to_account"), "PAY-PAYEE"),
    ("stage_swap", lambda r: r["events"].insert(0, r["events"].pop(3)), "PAY-STAGE-ORDER"),
    ("stage_twice", lambda r: r["events"].append(dict(r["events"][-1])), "PAY-STAGE-ORDER"),
    (
        "time_backwards",
        lambda r: event(r, "payment_ready").update(at="2026-10-26T09:00:00-07:00"),
        "PAY-STAGE-ORDER",
    ),
    (
        "paid_before_bill",
        lambda r: event(r, "bill_received").update(status="not_reached"),
        "PAY-STAGE-ORDER",
    ),
    (
        "status_stage",
        lambda r: event(r, "payment_sent").update(status="failed"),
        "PAY-STATUS-STAGE",
    ),
    ("no_stage", lambda r: r["events"].pop(), "PAY-STATUS-STAGE"),
    ("paid_without_bill", lambda r: r.update(bill=None), "PAY-BILL-ORDER"),
]


@pytest.mark.parametrize("name,breaks,check_ids", BREAKS, ids=[b[0] for b in BREAKS])
def test_break_fails_exactly_its_checks(name, breaks, check_ids):
    r = paid()
    breaks(r)
    assert {k for k, v in statuses(r).items() if v == "fail"} == set(check_ids.split())


def test_late_payment_warns():
    r = paid()
    for e in r["events"][-2:]:
        e["at"] = "2026-10-28T10:00:00-07:00"
    assert statuses(r)["PAY-ON-TIME"] == "warn"


def test_missing_section_fails_closed():
    r = paid()
    del r["bill"]
    failed = {k for k, v in statuses(r).items() if v == "fail"}
    assert failed == {"PAY-BILL-ORDER", "PAY-AMOUNT", "PAY-ON-TIME"}  # every check that reads it


def test_wrong_typed_payment_fails_closed():
    r = paid()
    r["payment"] = "sent"
    failed = {k for k, v in statuses(r).items() if v == "fail"}
    assert failed == {"PAY-AMOUNT", "PAY-PAYEE", "PAY-STATUS-STAGE", "PAY-ON-TIME"}  # read it


def test_unbilled_order_skips_bill_checks():
    s = statuses(unbilled())
    assert s["PAY-BILL-ORDER"] == s["PAY-AMOUNT"] == s["PAY-ON-TIME"] == "skip"


@pytest.mark.parametrize("receipt", [blocked, unbilled])
def test_dropped_bill_fails_when_events_say_it_arrived(receipt):
    r = receipt()
    r["bill"] = None
    event(r, "bill_received").update(status="done", at="2026-10-21T16:30:00-07:00")
    assert {k for k, v in statuses(r).items() if v == "fail"} == {"PAY-BILL-ORDER"}


def test_subtotal_and_tax_are_optional():
    r = paid()
    del r["order"]["subtotal_cents"], r["order"]["tax_cents"]
    assert statuses(r)["PAY-ITEMS-TOTAL"] == "pass"


def test_sent_payment_without_a_time_says_so():
    r = paid()
    event(r, "payment_sent")["at"] = None
    res = next(x for x in payment.run(r) if x.id == "PAY-ON-TIME")
    assert (res.status, res.title) == (
        "skip",
        "Payment was sent, but the receipt doesn't record when",
    )


def test_payee_match_claims_only_the_last_4_digits():
    res = next(x for x in payment.run(paid()) if x.id == "PAY-PAYEE")
    assert res.status == "pass" and "same 4 digits" in res.title


@pytest.mark.parametrize("receipt", [blocked, paid, unbilled])
def test_each_check_reports_its_registered_id(receipt):
    assert [check(receipt()).id for check in payment.CHECKS.values()] == list(payment.CHECKS)


def test_inputs_record_what_was_compared():
    r = paid()
    r["payment"]["requested_to_account"] = "******3210"
    res = next(x for x in payment.run(r) if x.id == "PAY-PAYEE")
    assert res.inputs == {"requested_to_account": "******3210", "account_on_file": "********4471"}
    assert "******3210" in res.title


def test_cli_exit_code(tmp_path):
    bad = paid()
    bad["payment"]["amount_cents"] = 1
    path = tmp_path / "receipt.json"
    for receipt, code in ((paid(), 0), (bad, 1)):
        path.write_text(json.dumps(receipt))
        cmd = [sys.executable, "-m", "checks.payment", str(path)]
        assert subprocess.run(cmd, check=False, capture_output=True).returncode == code
