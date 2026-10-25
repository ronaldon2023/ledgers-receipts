"""SessionStart hook: start onboarding when the business has no Receipts policy yet.

Claude Code adds this hook's stdout to the session context. Standard library only, so it
runs on the system python3 before any plugin dependencies are installed.
Runnable by hand: CLAUDE_PROJECT_DIR=/some/folder python3 hooks/session_start.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ONBOARDING_SKILL = "/ledgers-receipts:onboarding"


def policy_path() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    return Path(os.environ.get("RECEIPTS_POLICY", Path(root) / "policy.json"))


def message(path: Path) -> str:
    if not path.exists():
        return (
            f"Receipts: this business has no payment policy yet ({path.name} is missing). "
            f"Before doing any money work, run the {ONBOARDING_SKILL} skill with the owner."
        )
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return (
            f"Receipts: {path.name} exists but can't be read as JSON. Tell the owner, and "
            f"run {ONBOARDING_SKILL} to rewrite it. Payments are refused until it's fixed."
        )
    return f"Receipts: payment policy loaded from {path.name}."


def main() -> None:
    print(message(policy_path()))


if __name__ == "__main__":
    main()
