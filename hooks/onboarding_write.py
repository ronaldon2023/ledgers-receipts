"""PreToolUse hook: save the onboarding answers without a permission prompt, but never loosen them.

Claude Code runs this before every Write. It prints an "allow" decision, which skips the
Write permission prompt, only when all of these hold:

- tool_input.file_path is the onboarding file: onboarding_path() from session_start.py
  (env RECEIPTS_ONBOARDING, else $CLAUDE_PROJECT_DIR/receipts-onboarding.json). The path must
  be absolute with no "." or ".." parts, its file name must match exactly (case included),
  its folder must be the same real folder as the onboarding file's, and the file must not
  be a symlink, a hard link, or anything but a regular file if it already exists.
- tool_input.content parses as a JSON object whose "schema" is "receipts-onboarding/0".
- The payment rules don't get looser:
  - File exists: the new payment_rules equals the old one, except that
    approval_threshold_cents and monthly_budget_cents may each stay the same or go down
    (null means no limit, so null -> number is a decrease and number -> null an increase).
    An existing file that can't be read or isn't a JSON object allows nothing.
  - No file yet: payment_rules.approval_threshold_cents equals the owner's latest answer to
    the AskUserQuestion card with header "Approval", read from the session transcript
    (transcript_path on stdin). Only a user entry whose tool_result blocks all answer an
    earlier AskUserQuestion tool_use counts, so text in another tool's output (an email,
    say) can't pose as the owner's answer. "$500 (Recommended)" is 50000; a typed "Other"
    amount such as "$750" or "750" is 75000. The budget and supplier list aren't checked
    on a first save.

Anything else, including stdin that isn't JSON or an error in this hook, prints nothing
and exits 0, so the normal Write prompt shows. Claude Code still applies the user's deny and
ask rules after an "allow". A write through Bash doesn't reach this hook; the Bash prompt
covers it.
Standard library only, so it runs on the system python3.
Runnable by hand: echo '{"tool_input": {"file_path": "...", "content": "..."},
"transcript_path": "..."}' | python3 hooks/onboarding_write.py
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from session_start import onboarding_path

SCHEMA = "receipts-onboarding/0"
APPROVAL_HEADER = "Approval"
LIMITS = ("approval_threshold_cents", "monthly_budget_cents")
AMOUNT = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?")


def is_onboarding_file(file_path: Any, target: Path) -> bool:
    if not isinstance(file_path, str) or not os.path.isabs(file_path):
        return False
    if os.path.normpath(file_path) != file_path:
        return False
    wanted = os.path.abspath(target)
    if os.path.basename(file_path) != os.path.basename(wanted):
        return False
    real_dir = os.path.realpath(os.path.dirname(file_path))
    if real_dir != os.path.realpath(os.path.dirname(wanted)):
        return False
    try:
        info = os.lstat(file_path)
    except FileNotFoundError:
        return True
    return stat.S_ISREG(info.st_mode) and info.st_nlink == 1


def parse_answers(content: Any) -> dict | None:
    """The content as onboarding answers, or None when it isn't a schema-0 JSON object."""
    if not isinstance(content, str):
        return None
    try:
        answers = json.loads(content)
    except (ValueError, RecursionError):
        return None
    if not isinstance(answers, dict) or answers.get("schema") != SCHEMA:
        return None
    return answers


def is_limit(value: Any) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool))


def not_looser(old: Any, new: Any) -> bool:
    """True when new payment_rules equals old, with each limit the same or lower."""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return old == new
    if old.keys() != new.keys():
        return False
    for key in old:
        if key not in LIMITS:
            if old[key] != new[key]:
                return False
            continue
        before, after = old[key], new[key]
        if not is_limit(before) or not is_limit(after):
            return False
        if after is None and before is not None:
            return False
        if after is not None and before is not None and after > before:
            return False
    return True


def amount_cents(label: Any) -> int | None:
    """Cents for an Approval answer: "$1,000", "$500 (Recommended)", "750"; else None."""
    if not isinstance(label, str):
        return None
    text = label.strip().removesuffix("(Recommended)").strip()
    match = AMOUNT.fullmatch(text)
    if not match:
        return None
    return int(match.group(1).replace(",", "")) * 100 + int(match.group(2) or 0)


def _blocks(entry: dict) -> list[dict]:
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def approval_answer(transcript_path: Any) -> int | None:
    """Cents from the owner's latest Approval answer in the transcript, or None."""
    if not isinstance(transcript_path, str) or not transcript_path:
        return None
    try:
        lines = Path(transcript_path).read_bytes().splitlines()
    except OSError:
        return None
    asks: set[str] = set()
    found: int | None = None
    for line in lines:
        try:
            entry = json.loads(line)
        except (ValueError, RecursionError):  # a torn or foreign line: skip it
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "assistant":
            for block in _blocks(entry):
                if block.get("type") == "tool_use" and block.get("name") == "AskUserQuestion":
                    asks.add(str(block.get("id")))
            continue
        result = entry.get("toolUseResult")
        if entry.get("type") != "user" or not isinstance(result, dict):
            continue
        ids = {str(b.get("tool_use_id")) for b in _blocks(entry) if b.get("type") == "tool_result"}
        answers, questions = result.get("answers"), result.get("questions")
        if not ids or not ids <= asks:
            continue
        if not isinstance(answers, dict) or not isinstance(questions, list):
            continue
        for q in questions:
            if isinstance(q, dict) and q.get("header") == APPROVAL_HEADER:
                found = amount_cents(answers.get(str(q.get("question", ""))))
    return found


def first_save_ok(new: dict, transcript_path: Any) -> bool:
    rules = new.get("payment_rules")
    if not isinstance(rules, dict):
        return False
    threshold = rules.get("approval_threshold_cents")
    if not is_limit(threshold) or threshold is None:
        return False
    return threshold == approval_answer(transcript_path)


def update_ok(file_path: str, new: dict) -> bool:
    try:
        old = json.loads(Path(file_path).read_bytes().decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return False
    if not isinstance(old, dict):
        return False
    return not_looser(old.get("payment_rules"), new.get("payment_rules"))


def decision(event: Any) -> dict | None:
    if not isinstance(event, dict) or event.get("tool_name", "Write") != "Write":
        return None
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    file_path = tool_input.get("file_path")
    if not is_onboarding_file(file_path, onboarding_path()):
        return None
    new = parse_answers(tool_input.get("content"))
    if new is None:
        return None
    if os.path.lexists(file_path):
        ok = update_ok(file_path, new)
    else:
        ok = first_save_ok(new, event.get("transcript_path"))
    if not ok:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "Receipts onboarding answers, saved without asking.",
        }
    }


def main() -> None:
    try:
        out = decision(json.loads(sys.stdin.read()))
    except Exception:  # noqa: BLE001 - any failure stays silent, so the normal prompt applies
        out = None
    if out is not None:
        print(json.dumps(out))


if __name__ == "__main__":
    main()
