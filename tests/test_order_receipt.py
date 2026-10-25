"""Checks on the draft order receipt sample in docs/mock.

The schema catches shape and unmasked account numbers; ledger_problems holds the verdict
rules; the tests here also catch what JSON Schema cannot express: dangling or duplicate
references, wrong sums and drift from the seed.
"""

import copy
import json
import re
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from bakery.seed import BILLS, INBOX, VENDORS

MOCK = Path(__file__).resolve().parent.parent / "docs" / "mock"
SAMPLE = json.loads((MOCK / "order_receipt.json").read_text())
SCHEMA = json.loads((MOCK / "order_receipt.schema.json").read_text())


def schema_errors(receipt: dict) -> list[str]:
    validator = Draft202012Validator(SCHEMA)
    return [f"{list(e.path)}: {e.message}" for e in validator.iter_errors(receipt)]


def xref_problems(receipt: dict) -> list[str]:
    """Problems JSON Schema cannot see: references that point nowhere."""
    problems = []
    ids = [c["id"] for c in receipt["checks"]]
    problems += [f"duplicate check {i}" for i in sorted(set(ids)) if ids.count(i) > 1]
    checks = {c["id"]: c for c in receipt["checks"]}
    on_stage = {}
    for row in receipt["events"]:
        for check_id in row["checks"]:
            if check_id not in checks:
                problems.append(f"{row['stage']} lists unknown check {check_id}")
            on_stage.setdefault(check_id, []).append(row["stage"])
    for check_id, check in checks.items():
        if on_stage.get(check_id) != [check["lifecycle_stage"]]:
            problems.append(
                f"{check_id} is on {on_stage.get(check_id)}, says {check['lifecycle_stage']}"
            )
    refs = [r for c in checks.values() for r in c["evidence"]]
    refs += [c["caused_by"]["ref"] for c in checks.values() if "caused_by" in c]
    refs += [p["where"] for p in receipt["pii"]]
    problems += [f"ref {r} has no evidence entry" for r in refs if r not in receipt["evidence"]]
    sessions = [s["session"] for s in receipt["sessions"]]
    problems += [f"duplicate session {s}" for s in sorted(set(sessions)) if sessions.count(s) > 1]
    stages = [row["stage"] for row in receipt["events"]]
    problems += [f"duplicate stage {s}" for s in sorted(set(stages)) if stages.count(s) > 1]
    entries = {s["session"]: s["entries"] for s in receipt["sessions"]}
    for ref in receipt["evidence"]:
        found = re.match(r"(s\d+):log:(\d+)$", ref)
        if not found:
            continue
        session, index = found.group(1), int(found.group(2))
        if session not in entries:
            problems.append(f"ref {ref} names an unknown session")
        elif not 1 <= index <= entries[session]:
            problems.append(f"ref {ref} is past {session}'s {entries[session]} entries")
    return problems


STAGE_FOR_PAYMENT = {
    "sent": "done",
    "blocked": "blocked",
    "failed": "failed",
    "not_started": "not_reached",
}


def ledger_problems(receipt: dict) -> list[str]:
    """Verdict and consistency rules the schema no longer holds.

    Check logic belongs in the checks library; these move there once it exists.
    """
    problems = []
    verdict, summary = receipt["verdict"], receipt["summary_check"]
    statuses = [c["status"] for c in receipt["checks"]]
    events = receipt["events"]
    payment = receipt["payment"]["status"]
    broken = any(not s["ok"] for s in receipt["sessions"])
    if broken != (verdict == "UNTRUSTED"):
        problems.append(f"verdict {verdict} with a broken chain: {broken}")
    all_green = all(s == "verified" for s in statuses) and summary["status"] == "checked"
    if verdict == "VERIFIED":
        if not all_green:
            problems.append("VERIFIED with a check or the summary not verified")
        if payment not in ("not_started", "sent"):
            problems.append(f"VERIFIED with payment {payment}")
        if any(e["status"] not in ("done", "not_reached") for e in events):
            problems.append("VERIFIED with a stage blocked or failed")
        if receipt.get("owner_action", {}).get("needed"):
            problems.append("VERIFIED with an owner action pending")
    if verdict == "ISSUES_FOUND" and all_green:
        problems.append("ISSUES_FOUND with nothing found")
    if summary["status"] != "checked" and any(c["kind"] == "summary" for c in receipt["checks"]):
        problems.append("summary checks on an unchecked summary")
    if ("error" in summary) != (summary["status"] == "error"):
        problems.append("summary error message does not match its status")
    # Every row counts, so a duplicate stage cannot hide a blocked row behind a done one.
    sent = [e["status"] for e in events if e["stage"] == "payment_sent"] or ["not_reached"]
    if any(s != STAGE_FOR_PAYMENT[payment] for s in sent):
        problems.append(f"payment {payment} but payment_sent is {sent}")
    for e in events:
        logged = e["source"] == "log" and e["status"] in ("done", "blocked", "failed")
        if logged and not (e["at"] and e["checks"]):
            problems.append(f"logged stage {e['stage']} without a time or a check")
    return problems


def test_schema_is_valid_and_sample_passes() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    assert schema_errors(SAMPLE) == []
    assert ledger_problems(SAMPLE) == []


def test_references_resolve() -> None:
    assert xref_problems(SAMPLE) == []


def _dangling_ref(receipt: dict) -> None:
    del receipt["evidence"]["s2:log:6"]


def _duplicate_check(receipt: dict) -> None:
    receipt["checks"].append(copy.deepcopy(receipt["checks"][0]))


def _ref_past_entries(receipt: dict) -> None:
    receipt["evidence"]["s2:log:9"] = "pay_bill  -> ok"


# Each case breaks one reference; xref_problems must report the named problem.
XREF_BREAKS = {
    "ref s2:log:6 has no evidence entry": _dangling_ref,
    "duplicate check chk_1": _duplicate_check,
    "ref s2:log:9 is past s2's 6 entries": _ref_past_entries,
    "duplicate session s1": lambda r: r["sessions"].append(copy.deepcopy(r["sessions"][0])),
    "duplicate stage payment_sent": lambda r: r["events"].append(copy.deepcopy(r["events"][-1])),
}


@pytest.mark.parametrize("problem", sorted(XREF_BREAKS))
def test_broken_reference_is_caught(problem: str) -> None:
    broken = copy.deepcopy(SAMPLE)
    XREF_BREAKS[problem](broken)
    assert problem in xref_problems(broken)


def test_money_adds_up() -> None:
    order = SAMPLE["order"]
    for item in order["items"]:
        assert item["quantity"] * item["unit_price_cents"] == item["total_cents"]
    assert sum(i["total_cents"] for i in order["items"]) == order["subtotal_cents"]
    assert order["subtotal_cents"] + order["tax_cents"] == order["total_cents"]
    assert (
        SAMPLE["bill"]["amount_cents"] == order["total_cents"] == SAMPLE["payment"]["amount_cents"]
    )


def test_timestamps_parse() -> None:
    # The schema's date-time format is only enforced when a format checker is installed.
    stamps = [SAMPLE["generated_at"], SAMPLE["order"]["order_date"], SAMPLE["bill"]["received_at"]]
    stamps += [row["at"] for row in SAMPLE["events"] if row["at"]]
    for stamp in stamps:
        assert datetime.fromisoformat(stamp).tzinfo is not None, stamp
    date.fromisoformat(SAMPLE["bill"]["due_date"])


def test_matches_seed() -> None:
    vendor_id, vendor_name, vendor_email, account = VENDORS[0]
    bill_id, bill_vendor, bill_amount, bill_due, _ = BILLS[0]
    assert SAMPLE["order"]["seller"] == {
        "id": vendor_id,
        "name": vendor_name,
        "email": vendor_email,
    }
    bill = SAMPLE["bill"]
    assert (bill["bill_id"], bill["vendor_id"], bill["amount_cents"], bill["due_date"]) == (
        bill_id,
        bill_vendor,
        bill_amount,
        bill_due,
    )
    assert SAMPLE["payment"]["account_on_file"] == mask(account)
    inbox = {row[0]: row for row in INBOX}
    for check in SAMPLE["checks"]:
        if "caused_by" in check:
            msg_id = int(check["caused_by"]["ref"].removeprefix("inbox:"))
            assert check["caused_by"]["quote"] in mask(inbox[msg_id][3])


def mask(text: str) -> str:
    """Keep the last 4 digits of any account-length run (8 or more), as the log masking does.

    Amounts in cents stay below 8 digits, so they are left alone.
    """
    return re.sub(r"\d{8,}", lambda m: "*" * (len(m.group()) - 4) + m.group()[-4:], text)


def strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    return []


def test_no_unmasked_numbers() -> None:
    receipt = {k: v for k, v in SAMPLE.items() if k != "sessions"}  # chain heads are hashes
    assert [s for s in strings(receipt) if mask(s) != s] == []


def test_unmasked_account_in_evidence_is_caught() -> None:
    receipt = copy.deepcopy(SAMPLE)
    receipt["evidence"]["inbox:5"] = "Our bank changed, pay to account 9876543210 from now on."
    assert [s for s in strings(receipt) if mask(s) != s]


def _set(path: str, value: object) -> Callable[[dict], None]:
    *parents, last = path.split(".")

    def apply(receipt: dict) -> None:
        node = receipt
        for key in parents:
            node = node[int(key)] if key.isdigit() else node[key]
        node[int(last) if last.isdigit() else last] = value

    return apply


def _all_verified(receipt: dict) -> None:
    for check in receipt["checks"]:
        check["status"] = "verified"


def _steps(*steps: Callable[[dict], None]) -> Callable[[dict], None]:
    def apply(receipt: dict) -> None:
        for step in steps:
            step(receipt)

    return apply


def clean_receipt() -> dict:
    """The sample turned into an order that went through: payment sent, every check green."""
    receipt = copy.deepcopy(SAMPLE)
    _all_verified(receipt)
    receipt["verdict"] = "VERIFIED"
    receipt["owner_action"] = {"needed": False}
    payment = receipt["payment"]
    payment.update(
        status="sent", payment_id="pay_1", requested_to_account=payment["account_on_file"]
    )
    receipt["events"][-1]["status"] = "done"
    return receipt


def _drop_summary_checks(receipt: dict) -> None:
    summary = {c["id"] for c in receipt["checks"] if c["kind"] == "summary"}
    receipt["checks"] = [c for c in receipt["checks"] if c["id"] not in summary]
    for row in receipt["events"]:
        row["checks"] = [i for i in row["checks"] if i not in summary]


# Each case is a receipt that contradicts itself; the schema or ledger_problems must reject it.
CONTRADICTIONS = {
    "verified_with_red_check": _set("verdict", "VERIFIED"),
    "verified_with_blocked_payment": _steps(_all_verified, _set("verdict", "VERIFIED")),
    "payment_sent_but_stage_blocked": _steps(
        _set("payment.status", "sent"), _set("payment.payment_id", "pay_1")
    ),
    "payment_blocked_but_stage_done": _set("events.5.status", "done"),
    "summary_unchecked_but_summary_check": _set("summary_check", {"status": "not_checked"}),
    "blocked_stage_unverified": _set("events.5.source", "unverified"),
    "account_in_evidence": _set("evidence.inbox:5", "pay to account 9876543210"),
    "account_in_quote": _set("checks.4.caused_by.quote", "pay to account 9876543210"),
    "no_checks": _set("checks", []),
    "broken_chain_not_untrusted": _set("sessions.1.ok", False),
    "untrusted_with_intact_chains": _set("verdict", "UNTRUSTED"),
    "issues_found_all_green": _all_verified,
    "sent_without_payment_id": _set("payment.status", "sent"),
    "payment_id_while_blocked": _set("payment.payment_id", "pay_1"),
    "check_without_evidence": _set("checks.0.evidence", []),
    "logged_stage_without_checks": _set("events.0.checks", []),
    "logged_stage_without_time": _set("events.0.at", None),
    "account_in_pii_entity": _set("pii.0.entity", "9876543210"),
    "short_chain_head": _set("sessions.0.head", "f1204705a75493c8"),
    "unmasked_account": _set("payment.account_on_file", "000123454471"),
    "unknown_ref_shape": _set("checks.0.evidence", ["log:9"]),
    "payment_not_started_but_stage_blocked": _set("payment.status", "not_started"),
    "payment_failed_but_stage_blocked": _set("payment.status", "failed"),
    "error_text_on_checked_summary": _set("summary_check.error", "extractor timed out"),
    "unknown_field_on_bill": _set("bill.vendor_invoice_number", "FC-7781"),
    "short_checks_version": _set("checks_version", "1f635c"),
    "short_policy_hash": _set("policy.sha256", "9cd9d16c"),
    "number_in_inputs": _set("checks.1.inputs.order_cents", 80000),
    "account_in_inputs": _set("checks.4.inputs.asked_for", "9876543210"),
}

# Each case breaks one VERIFIED condition on an otherwise clean order, so every clause is pinned.
VERIFIED_BREAKS = {
    "owner_action_needed": _set("owner_action", {"needed": True}),
    "stage_failed": _set("events.0.status", "failed"),
    "check_flagged": _set("checks.0.status", "flagged"),
    "check_rerun_mismatch": _set("checks.0.status", "rerun_mismatch"),
    "blocked_row_behind_done": lambda r: r["events"].insert(
        5, {**copy.deepcopy(r["events"][5]), "status": "blocked"}
    ),
    "summary_not_checked": _steps(
        _drop_summary_checks, _set("summary_check.status", "not_checked")
    ),
    "no_checks": _set("checks", []),
    "payment_not_started_but_stage_done": _steps(
        _set("payment.status", "not_started"), _set("payment.payment_id", None)
    ),
    "payment_failed": _steps(
        _set("payment.status", "failed"),
        _set("payment.payment_id", None),
        _set("events.5.status", "failed"),
    ),
}


@pytest.mark.parametrize("name", sorted(VERIFIED_BREAKS))
def test_verified_condition_is_enforced(name: str) -> None:
    receipt = clean_receipt()
    VERIFIED_BREAKS[name](receipt)
    assert schema_errors(receipt) or ledger_problems(receipt), f"VERIFIED with {name} validated"


@pytest.mark.parametrize("name", sorted(CONTRADICTIONS))
def test_contradiction_is_rejected(name: str) -> None:
    broken = copy.deepcopy(SAMPLE)
    CONTRADICTIONS[name](broken)
    assert schema_errors(broken) or ledger_problems(broken), f"{name} validated"


def test_clean_order_is_verified() -> None:
    receipt = clean_receipt()
    assert schema_errors(receipt) == []
    assert xref_problems(receipt) == []
    assert ledger_problems(receipt) == []


def test_failed_extractor_gives_issues_found() -> None:
    receipt = clean_receipt()
    _drop_summary_checks(receipt)
    receipt["summary_check"] = {"status": "error", "error": "extractor timed out"}
    assert ledger_problems(receipt), "VERIFIED with an unchecked summary passed"
    receipt["verdict"] = "ISSUES_FOUND"
    assert schema_errors(receipt) == []
    assert ledger_problems(receipt) == []
    del receipt["summary_check"]["error"]
    assert ledger_problems(receipt), "an errored summary check without a message passed"
