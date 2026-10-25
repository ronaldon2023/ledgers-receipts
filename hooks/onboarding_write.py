"""PreToolUse hook: save the onboarding answers without a permission prompt.

Claude Code runs this before every Write. It prints an "allow" decision, which skips the
Write permission prompt, only when both hold:

- tool_input.file_path is the onboarding file: onboarding_path() from session_start.py
  (env RECEIPTS_ONBOARDING, else $CLAUDE_PROJECT_DIR/receipts-onboarding.json). The path must
  be absolute with no "." or ".." parts, its file name must match exactly (case included),
  its folder must be the same real folder as the onboarding file's, and the file must not
  be a symlink, a hard link, or anything but a regular file if it already exists.
- tool_input.content parses as a JSON object whose "schema" is "receipts-onboarding/0".

Anything else, including stdin that isn't JSON or an error in this hook, prints nothing
and exits 0, so the normal permission rules decide. Claude Code still applies the user's
deny and ask rules after an "allow".
Standard library only, so it runs on the system python3.
Runnable by hand: echo '{"tool_input": {"file_path": "...", "content": "..."}}' |
python3 hooks/onboarding_write.py
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from session_start import onboarding_path

SCHEMA = "receipts-onboarding/0"


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


def is_onboarding_content(content: Any) -> bool:
    if not isinstance(content, str):
        return False
    try:
        answers = json.loads(content)
    except (ValueError, RecursionError):
        return False
    return isinstance(answers, dict) and answers.get("schema") == SCHEMA


def decision(event: Any) -> dict | None:
    if not isinstance(event, dict) or event.get("tool_name", "Write") != "Write":
        return None
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    if not is_onboarding_file(tool_input.get("file_path"), onboarding_path()):
        return None
    if not is_onboarding_content(tool_input.get("content")):
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
