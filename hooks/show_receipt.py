"""Stop hook: after a turn that paid a bill, tell the owner where that payment's receipt is.

Claude Code runs this when Claude finishes a turn. It looks in the hash-chain log (env
RECEIPTS_LOG, else $CLAUDE_PROJECT_DIR/logs/chain.jsonl) for this session's newest pay_bill
call. When there is a new one, it runs the verifier the way `make receipt` does
(<project>/.venv/bin/python -m receipts.verify), reads the receipt it wrote for that bill
(fixtures/portal/receipt_live_<order>.json) and prints one systemMessage with the verdict and
the portal link. If nothing listens on the portal port (env RECEIPTS_PORTAL_PORT, else 8000),
the message also says how to start the portal. It never starts anything itself.

It only acts in a Receipts checkout (receipts/verify.py present and .mcp.json registering a
bakery-local server), and only counts calls to the bakery-local pay_bill tool by its exact
name. It stays silent when stop_hook_active is set, when this session paid nothing, and when this
session's newest payment was already reported. What was reported is kept per session in
reported.json under $CLAUDE_PLUGIN_DATA (else a folder in the system temp dir), so the owner
sees each link once. A failed build is not recorded, so the next turn tries again.
It never blocks Claude from stopping: on any error it exits 0 with a short "couldn't build"
message and no log contents.
Standard library only, so it runs on the system python3.
Runnable by hand: echo '{"session_id": "s1"}' | CLAUDE_PROJECT_DIR=. python3 hooks/show_receipt.py
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any

DEFAULT_PORT = 8000
VERIFY_TIMEOUT_S = 20
STATE_FILE = "reported.json"
PASSING = ("verified", "pass")
# Same pattern as the PreToolUse matcher in hooks/hooks.json. Used with fullmatch, because
# `$` alone also accepts a trailing newline.
PAY_BILL_TOOL = re.compile(r"^mcp__(plugin_ledgers-receipts_)?bakery-local__pay_bill$")
# Order numbers the portal opens as receipt_live_<order>.json (Portal.orderReceiptFile in
# render/portal/portal.js). Anything else links to the dashboard.
PORTAL_ORDER = re.compile(r"[A-Za-z0-9_-]{1,40}")


def is_receipts_checkout(project: Path) -> bool:
    """True when the folder has receipts/verify.py and a .mcp.json registering bakery-local.
    The plugin runs in every folder, so this keeps the hook from running a folder's own
    .venv/bin/python unless that folder is a Receipts checkout."""
    if not (project / "receipts" / "verify.py").is_file():
        return False
    try:
        config = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return False
    servers = config.get("mcpServers") if isinstance(config, dict) else None
    return isinstance(servers, dict) and "bakery-local" in servers


class BuildError(Exception):
    """The receipt couldn't be built; the message is the short reason the owner sees."""


def project_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()


def log_path(project: Path) -> Path:
    return Path(os.environ.get("RECEIPTS_LOG") or project / "logs" / "chain.jsonl")


def state_path() -> Path:
    base = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.join(
        tempfile.gettempdir(), "ledgers-receipts"
    )
    return Path(base) / STATE_FILE


def portal_port() -> int:
    raw = os.environ.get("RECEIPTS_PORTAL_PORT", "").strip()
    return int(raw) if raw.isdigit() else DEFAULT_PORT


def newest_payment(log: Path, session: str) -> dict[str, Any] | None:
    """This session's last pay_bill entry, or None. Lines that aren't JSON objects are skipped:
    they can't be tied to a session, and the verifier reports a damaged log itself."""
    if not log.is_file():
        return None
    newest = None
    with open(log, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if (
                isinstance(entry, dict)
                and entry.get("session") == session
                and PAY_BILL_TOOL.fullmatch(str(entry.get("tool", "")))
            ):
                newest = entry
    return newest


def _ts(entry: dict[str, Any]) -> float:
    ts = entry.get("ts")
    return float(ts) if isinstance(ts, (int, float)) and not isinstance(ts, bool) else 0.0


def _read_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def already_reported(session: str, ts: float) -> bool:
    last = _read_state(state_path()).get(session)
    return isinstance(last, (int, float)) and not isinstance(last, bool) and ts <= last


def mark_reported(session: str, ts: float) -> None:
    """Record ts for this session. Stop hooks of other sessions may run at the same moment, so
    the read-modify-write holds a lock, and the new file replaces the old one in one rename."""
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = _read_state(path)
        state[session] = ts
        tmp = path.with_suffix(f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, path)


def run_verify(project: Path) -> None:
    python = project / ".venv" / "bin" / "python"
    if not python.is_file():
        raise BuildError("no .venv/bin/python in the project folder")
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    try:
        done = subprocess.run(
            [str(python), "-m", "receipts.verify"],
            cwd=str(project),
            env=env,
            capture_output=True,
            check=False,
            text=True,
            timeout=VERIFY_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        raise BuildError(f"the verifier took over {VERIFY_TIMEOUT_S}s") from None
    except OSError as exc:
        raise BuildError(f"the verifier couldn't start: {type(exc).__name__}") from None
    if done.returncode != 0:
        raise BuildError(f"the verifier exited with code {done.returncode}")


def find_receipt(project: Path, bill_id: str, since: float) -> dict[str, Any]:
    """The receipt the verifier wrote for this bill (its bill.bill_id), from fixtures/portal.
    Only files modified at or after `since` (less 1s of slack) count, so a receipt left over
    from an earlier run can't stand in when this run skipped the bill."""
    for path in sorted((project / "fixtures" / "portal").glob("receipt_live_*.json")):
        try:
            if path.stat().st_mtime < since - 1:
                continue
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        bill = receipt.get("bill") if isinstance(receipt, dict) else None
        if isinstance(bill, dict) and bill.get("bill_id") == bill_id:
            return receipt
    raise BuildError(f"no receipt was written for bill {_safe(bill_id)}")


def _safe(text: Any, limit: int = 120) -> str:
    """One line of shown text: control, format and other category C* characters (C1 controls,
    bidi overrides) become spaces, and any run of 5+ digits is cut to its last 4."""
    text = "".join(" " if unicodedata.category(ch).startswith("C") else ch for ch in str(text))
    text = re.sub(r"\d{5,}", lambda m: "••" + m.group()[-4:], text)
    return text if len(text) <= limit else text[:limit] + "..."


def portal_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def message(project: Path, receipt: dict[str, Any], port: int) -> str:
    order = receipt.get("order") if isinstance(receipt.get("order"), dict) else {}
    order_id = _safe(order.get("order_number") or receipt.get("receipt_id") or "this order")
    text = f"Receipt ready for {order_id}: {_safe(receipt.get('verdict') or 'UNKNOWN')}"
    checks = receipt.get("checks") if isinstance(receipt.get("checks"), list) else []
    failed = next(
        (c for c in checks if isinstance(c, dict) and c.get("status") not in PASSING), None
    )
    if failed:
        text += f" ({_safe(failed.get('id'))} {_safe(failed.get('status'))}: "
        text += f"{_safe(failed.get('title'))})"
    text += f". Open http://localhost:{port}/?state=live"
    number = order.get("order_number")
    if isinstance(number, str) and PORTAL_ORDER.fullmatch(number):
        text += f"#order/{number}"  # straight to this order's receipt
    if not portal_listening(port):
        start = f"cd {shlex.quote(str(project))} && .venv/bin/python -m render.portal"
        text += f" (the portal isn't running; start it with: {start} --port {port})"
    return text


def report(event: Any) -> str | None:
    """The systemMessage to show, or None to stay silent."""
    if not isinstance(event, dict):
        raise BuildError("the Stop event wasn't a JSON object")
    if event.get("stop_hook_active"):
        return None
    session = str(event.get("session_id") or "")
    project = project_dir()
    if not is_receipts_checkout(project):
        return None
    payment = newest_payment(log_path(project), session) if session else None
    if payment is None:
        return None
    ts = _ts(payment)
    if already_reported(session, ts):
        return None
    tool_input = payment.get("input") if isinstance(payment.get("input"), dict) else {}
    started = time.time()
    run_verify(project)
    receipt = find_receipt(project, str(tool_input.get("bill_id", "")), started)
    text = message(project, receipt, portal_port())
    try:
        mark_reported(session, ts)
    except OSError:
        pass  # the receipt is still ready; at worst the owner sees this link again next turn
    return text


def main() -> None:
    try:
        try:
            event = json.loads(sys.stdin.read() or "null")
        except ValueError:
            raise BuildError("the Stop event wasn't valid JSON") from None
        text = report(event)
    except BuildError as exc:
        text = f"Receipts: couldn't build the receipt ({exc})."
    except Exception as exc:  # noqa: BLE001 - a Stop hook must never block or crash the turn
        text = f"Receipts: couldn't build the receipt ({type(exc).__name__})."
    if text is not None:
        print(json.dumps({"systemMessage": text}))
    sys.exit(0)


if __name__ == "__main__":
    main()
