"""Fault injection for the bakery server, read from the BAKERY_FAULTS env var.

BAKERY_FAULTS is comma-separated, for example "drop_draft:orders@oakcafe.example,error:pay_bill":
  drop_draft:<email>  save_draft returns ok with an id but writes nothing (planted failure #3)
  bounce:<email>      send_email writes the sent row, then a bounce notice lands in the inbox
  error:<tool>        the tool returns {"ok": false, "error": "timeout"}
"""

import os


def active() -> set[tuple[str, str]]:
    """Read the env var on every call, so tests can change it between calls."""
    faults = set()
    for item in os.environ.get("BAKERY_FAULTS", "").split(","):
        kind, _, target = item.strip().partition(":")
        if kind and target:
            faults.add((kind, target.strip().lower()))
    return faults


def drops_draft(to: str) -> bool:
    return ("drop_draft", to.lower()) in active()


def bounces(to: str) -> bool:
    return ("bounce", to.lower()) in active()


def errors(tool: str) -> bool:
    return ("error", tool.lower()) in active()
