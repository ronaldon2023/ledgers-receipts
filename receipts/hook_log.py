"""PostToolUse hook: append every tool call Claude makes to the hash-chain log, masked.

Claude Code pipes the hook event as JSON on stdin (session_id, tool_name, tool_input,
tool_response). Configured in .claude/settings.json; also runnable by hand:
  echo '{"tool_name": "x", "tool_input": {}, "tool_response": {}}' | python -m receipts.hook_log
"""

import json
import sys
import time

from receipts import chain, pii


def entry_from_event(event: dict) -> dict:
    return {
        "ts": round(time.time(), 3),
        "session": event.get("session_id", ""),
        "tool": event.get("tool_name", ""),
        "input": pii.mask(event.get("tool_input", {})),
        "response": pii.mask(event.get("tool_response", {})),
    }


def main() -> None:
    try:
        chain.append(entry_from_event(json.load(sys.stdin)))
    except Exception as exc:  # noqa: BLE001 - a hook must report, not crash Claude's turn
        print(f"Receipts log hook failed: {exc}", file=sys.stderr)
        sys.exit(1)  # non-blocking error: Claude Code shows it, the tool result stands


if __name__ == "__main__":
    main()
