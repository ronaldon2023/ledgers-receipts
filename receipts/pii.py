"""Mask sensitive numbers before anything is written to the log.

Pattern-based so it is fast and deterministic: the log hook runs on every tool call, and
loading Presidio's language model each time would add seconds. The guard uses Presidio to
scan outgoing email bodies; this module only keeps raw numbers out of the log.

Kept: the last 4 digits, e.g. "4111 1111 1111 1111" -> "************1111".
"""

import re

# Order matters: SSNs and IBANs first, then cards and long runs of digits (bank accounts).
PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # US SSN
    re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b"),  # IBAN
    re.compile(
        r"(?<![\w-])\d{4}(?:[ -]\d{4}){2,3}(?:[ -]\d{1,4})?(?![\w-])"
    ),  # card in groups of 4
    re.compile(r"(?<![\w-])\d{9,19}(?![\w-])"),  # 9 to 19 digits in a row (bank accounts)
]


def _mask_match(match: re.Match) -> str:
    chars = re.sub(r"[ -]", "", match.group())
    return "*" * (len(chars) - 4) + chars[-4:]


def mask_text(text: str) -> str:
    for pattern in PATTERNS:
        text = pattern.sub(_mask_match, text)
    return text


def mask(value: object) -> object:
    """Mask every string (and every 9+ digit integer) inside dicts and lists."""
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and len(str(abs(value))) >= 9:
        return mask_text(str(value))
    if isinstance(value, dict):
        return {k: mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v) for v in value]
    return value
