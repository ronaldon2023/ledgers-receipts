"""SessionStart hook: start onboarding when Receipts isn't set up for this business yet.

Claude Code adds this hook's stdout to the session context. Standard library only, so it
runs on the system python3 before any plugin dependencies are installed.
Runnable by hand: CLAUDE_PROJECT_DIR=/some/folder python3 hooks/session_start.py
"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

ONBOARDING_SKILL = "/ledgers-receipts:onboarding"


def portal_command(path: Path) -> str:
    """Start the portal from the plugin's own folder, pointed at the folder holding the answers."""
    plugin = os.environ.get("CLAUDE_PLUGIN_ROOT") or str(Path(__file__).resolve().parent.parent)
    business = str(path.resolve().parent)
    return (
        f"cd {shlex.quote(plugin)} && python3 -m render.portal "
        f"--business-dir {shlex.quote(business)}"
    )


def onboarding_path() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or "."
    return Path(os.environ.get("RECEIPTS_ONBOARDING") or Path(root) / "receipts-onboarding.json")


def message(path: Path) -> str:
    if not path.exists():
        return (
            f"Receipts: this business isn't set up yet ({path.name} is missing). "
            "Before doing any money work, offer the owner two ways to set it up: answer a few "
            f"questions here (run the {ONBOARDING_SKILL} skill), or fill in the Your rules step "
            "of the owner portal in their browser. If they pick the portal, start it for them in "
            f"the background with `{portal_command(path)}`. Both save {path.name}."
        )
    try:
        answers = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        answers = None
    if not isinstance(answers, dict):
        return (
            f"Receipts: {path.name} exists but can't be read. Tell the owner, and run "
            f"{ONBOARDING_SKILL} to redo it."
        )
    return f"Receipts: onboarding answers on file in {path.name}."


def main() -> None:
    print(message(onboarding_path()))


if __name__ == "__main__":
    main()
