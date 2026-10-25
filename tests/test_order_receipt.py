"""Checks on the draft order receipt sample in docs/mock.

The schema catches shape and contradictions; the tests here also catch what JSON Schema
cannot express: dangling references, wrong sums, unmasked numbers and drift from the seed.
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
    checks = {c["id"]: c for c in receipt["checks"]}
    on_stage = {}
    for row in receipt["lifecycle"]:
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
    refs += [
        r for a in receipt.get("authorization", {}).get("approvals", []) for r in a["evidence"]
    ]
    refs += [p["where"] for p in receipt["pii"]]
    problems += [f"ref {r} has no evidence entry" for r in refs if r not in receipt["evidence"]]
    sessions = {s["session"] for s in receipt["sessions"]}
    for ref in receipt["evidence"]:
        session = re.match(r"(s\d+):log:", ref)
        if session and session.group(1) not in sessions:
            problems.append(f"ref {ref} names an unknown session")
    policies = {p["id"] for p in receipt.get("policies", [])}
    for check in checks.values():
        if "policy_id" in check and check["policy_id"] not in policies:
            problems.append(f"{check['id']} names unknown policy {check['policy_id']}")
    return problems


def test_schema_is_valid_and_sample_passes() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    assert schema_errors(SAMPLE) == []


def test_references_resolve() -> None:
    assert xref_problems(SAMPLE) == []


def test_dangling_evidence_ref_is_caught() -> None:
    broken = copy.deepcopy(SAMPLE)
    del broken["evidence"]["s2:log:6"]
    assert "ref s2:log:6 has no evidence entry" in xref_problems(broken)


def test_money_adds_up() -> None:
    order = SAMPLE["order"]
    for item in order["items"]:
        assert item["quantity"] * item["unit_price_cents"] == item["total_cents"]
    assert sum(i["total_cents"] for i in order["items"]) == order["subtotal_cents"]
    assert order["subtotal_cents"] + order["tax_cents"] == order["total_cents"]
    assert (
        SAMPLE["bill"]["amount_cents"] == order["total_cents"] == SAMPLE["payment"]["amount_cents"]
    )
    for check in SAMPLE["checks"]:
        m = check.get("measured", {})
        if "used_cents" in m:
            assert m["used_cents"] + order["total_cents"] == m["after_cents"]
        if "balance_cents" in m:
            assert m["balance_cents"] - order["total_cents"] == m["after_cents"]


def test_timestamps_parse() -> None:
    # The schema's date-time format is only enforced when a format checker is installed.
    stamps = [SAMPLE["generated_at"], SAMPLE["order"]["order_date"], SAMPLE["bill"]["received_at"]]
    stamps += [row["at"] for row in SAMPLE["lifecycle"] if row["at"]]
    stamps += [a["at"] for a in SAMPLE["authorization"]["approvals"]]
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


# Each case is a receipt that contradicts itself; the schema must reject every one.
CONTRADICTIONS = {
    "verified_with_red_check": _set("verdict", "VERIFIED"),
    "broken_chain_not_untrusted": _set("sessions.1.ok", False),
    "untrusted_with_intact_chains": _set("verdict", "UNTRUSTED"),
    "issues_found_all_green": _all_verified,
    "sent_without_payment_id": _set("payment.status", "sent"),
    "payment_id_while_blocked": _set("payment.payment_id", "pay_1"),
    "check_without_evidence": _set("checks.0.evidence", []),
    "logged_stage_without_checks": _set("lifecycle.0.checks", []),
    "logged_stage_without_time": _set("lifecycle.0.at", None),
    "approval_without_evidence": _set("authorization.approvals.0.evidence", []),
    "short_chain_head": _set("sessions.0.head", "f1204705a75493c8"),
    "unmasked_account": _set("payment.account_on_file", "000123454471"),
    "unknown_ref_shape": _set("checks.0.evidence", ["log:9"]),
}


@pytest.mark.parametrize("name", sorted(CONTRADICTIONS))
def test_contradiction_is_rejected(name: str) -> None:
    broken = copy.deepcopy(SAMPLE)
    CONTRADICTIONS[name](broken)
    assert schema_errors(broken), f"{name} validated"


def test_unchecked_summary_cannot_be_verified() -> None:
    receipt = copy.deepcopy(SAMPLE)
    _all_verified(receipt)
    receipt["verdict"] = "VERIFIED"
    assert schema_errors(receipt) == []
    receipt["summary_check"] = {"status": "error", "error": "extractor timed out"}
    assert schema_errors(receipt)
