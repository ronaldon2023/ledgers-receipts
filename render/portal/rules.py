"""Save the owner's payment rules from the portal into receipts-onboarding.json.

The same file Claude Code's onboarding skill writes and the approval hook reads. The portal only
replaces payment_rules; everything else in an existing file stays as it was.
"""

import json
import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

ONBOARDING = "receipts-onboarding.json"
SCHEMA = "receipts-onboarding/0"
MAX_SUPPLIERS = 50
MAX_TEXT = 100
_lock = threading.Lock()  # the server is threaded: one save at a time


def _cents(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**53:
        raise ValueError(f"{name} must be a whole number of cents")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be text")
    value = value.strip()
    if len(value) > MAX_TEXT:
        raise ValueError(f"{name} is too long")
    if re.search(r"\d{8,}", value):  # never store anything that looks like an account number
        raise ValueError(f"{name} looks like an account number")
    return value


def parse_rules(body: bytes) -> dict[str, Any]:
    """Check the portal's request body; raise ValueError with a plain reason if it's not usable."""
    try:
        data = json.loads(body)
    except (ValueError, RecursionError) as e:
        raise ValueError("the request isn't valid JSON") from e
    if not isinstance(data, dict):
        raise ValueError("the request must be a JSON object")  # noqa: TRY004 - a bad request, sent back as 400
    budget = data.get("monthly_budget_cents")
    names = data.get("approved_suppliers")
    if not isinstance(names, list) or len(names) > MAX_SUPPLIERS:
        raise ValueError(f"approved_suppliers must be a list of up to {MAX_SUPPLIERS} names")
    business = data.get("business_name")
    return {
        "approval_threshold_cents": _cents(
            data.get("approval_threshold_cents"), "approval_threshold_cents"
        ),
        "monthly_budget_cents": None if budget is None else _cents(budget, "monthly_budget_cents"),
        "approved_suppliers": [_text(n, "a supplier name") for n in names],
        "business_name": None if business is None else _text(business, "business_name"),
    }


def merge(existing: dict[str, Any] | None, rules: dict[str, Any], now: str) -> dict[str, Any]:
    """The file to write: the existing answers with new payment rules, or a new portal file.

    A supplier Claude already saved keeps its email_domain and account_last4; new names get null.
    """
    out = (
        dict(existing)
        if existing
        else {
            "schema": SCHEMA,
            "status": "portal",
            "created_at": now,
            "business": {"name": rules["business_name"], "from_smb_onboard": False},
            "integrations": {"bookkeeping": None, "payments": [], "email": None, "other": []},
        }
    )
    old = out.get("payment_rules") if isinstance(out.get("payment_rules"), dict) else {}
    known = {
        s["name"].casefold(): s
        for s in old.get("approved_suppliers") or []
        if isinstance(s, dict) and isinstance(s.get("name"), str)
    }
    suppliers = []
    for name in rules["approved_suppliers"]:
        prior = known.get(name.casefold(), {})
        suppliers.append(
            {
                "name": name,
                "email_domain": prior.get("email_domain"),
                "account_last4": prior.get("account_last4"),
            }
        )
    out["payment_rules"] = {
        **old,
        "approval_threshold_cents": rules["approval_threshold_cents"],
        "monthly_budget_cents": rules["monthly_budget_cents"],
        "approved_suppliers": suppliers,
    }
    return out


def save(folder: Path, rules: dict[str, Any]) -> Path:
    """Write the rules into folder/receipts-onboarding.json in one step (temp file, then rename).

    Refuses a symlink, and an existing file that can't be read, rather than overwrite it.
    """
    folder = folder.resolve()
    target = folder / ONBOARDING
    with _lock:
        if target.is_symlink():
            raise ValueError(f"{ONBOARDING} is a link; the portal won't write through it")
        existing = None
        if target.exists():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError, RecursionError) as e:
                raise ValueError(f"{ONBOARDING} can't be read; redo onboarding in Claude") from e
            if not isinstance(existing, dict):
                raise ValueError(f"{ONBOARDING} can't be read; redo onboarding in Claude")
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        text = json.dumps(merge(existing, rules, now), indent=2) + "\n"
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".receipts-onboarding.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    return target
