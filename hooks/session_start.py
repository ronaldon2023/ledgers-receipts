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
    root = os.environ.get("CLAUDE_PROJECT_DIR") or "."
    return Path(os.environ.get("RECEIPTS_POLICY") or Path(root) / "policy.json")


def message(path: Path) -> str:
    if not path.exists():
        return (
            f"Receipts: this business has no payment policy yet ({path.name} is missing). "
            f"Before doing any money work, run the {ONBOARDING_SKILL} skill with the owner."
        )
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        policy = None
    if not isinstance(policy, dict):
        return (
            f"Receipts: {path.name} exists but isn't a readable policy. Tell the owner, and "
            f"run {ONBOARDING_SKILL} to rewrite it. Receipts can't approve payments until then."
        )
    return f"Receipts: payment policy loaded from {path.name}."


def main() -> None:
    print(message(policy_path()))


if __name__ == "__main__":
    main()
