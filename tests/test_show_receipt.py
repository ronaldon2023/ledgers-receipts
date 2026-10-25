import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "show_receipt.py"
TOOL = "mcp__bakery-local__pay_bill"
SESSION = "s-mine"
RECEIPT = {
    "verdict": "ISSUES_FOUND",
    "order": {"order_number": "PO-2038"},
    "bill": {"bill_id": "BILL-08"},
    "checks": [
        {"id": "C5", "status": "verified", "title": "Amount matches the bill"},
        {"id": "C4", "status": "blocked", "title": "Account ••3210 isn't on file"},
    ],
}


def stub_verify(project: Path, receipt: dict | None = RECEIPT, code: int = 0) -> None:
    """A fake .venv/bin/python that acts like receipts.verify: writes the receipt and exits."""
    python = project / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    body = [f"#!{sys.executable}", "import json, pathlib, sys"]
    if receipt is not None:
        order = receipt["order"]["order_number"]
        body += [
            "out = pathlib.Path('fixtures/portal')",
            "out.mkdir(parents=True, exist_ok=True)",
            f"(out / 'receipt_live_{order}.json').write_text({json.dumps(json.dumps(receipt))})",
            f"print('{order}: {receipt['verdict']} - stub')",
        ]
    body.append(f"sys.exit({code})")
    python.write_text("\n".join(body) + "\n")
    python.chmod(0o755)


def make_checkout(project: Path) -> None:
    """The markers the hook needs before it acts: receipts/verify.py and bakery-local in .mcp.json."""
    (project / "receipts").mkdir(exist_ok=True)
    (project / "receipts" / "verify.py").write_text("")
    (project / ".mcp.json").write_text(json.dumps({"mcpServers": {"bakery-local": {}}}))


def write_log(project: Path, *entries: dict) -> None:
    make_checkout(project)
    log = project / "logs" / "chain.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.writelines(json.dumps(e) + "\n" for e in entries)


def payment(session: str = SESSION, ts: float = 100.0, bill_id: str = "BILL-08") -> dict:
    tool_input = {"bill_id": bill_id, "amount_cents": 20000, "to_account": "••3210"}
    return {"ts": ts, "session": session, "tool": TOOL, "input": tool_input, "response": {}}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def listener():
    """A socket listening on a free port, standing in for a running portal."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        yield s.getsockname()[1]


def run_hook(project: Path, port: int, event: object = None, **extra: str) -> str:
    env = {
        **os.environ,
        "CLAUDE_PROJECT_DIR": str(project),
        "CLAUDE_PLUGIN_DATA": str(project / "plugin-data"),
        "RECEIPTS_PORTAL_PORT": str(port),
    }
    env.pop("RECEIPTS_LOG", None)
    env.update(extra)
    stdin = json.dumps(event if event is not None else {"session_id": SESSION})
    done = subprocess.run(
        [sys.executable, str(HOOK)],
        check=False,
        input=stdin,
        env=env,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def system_message(out: str) -> str:
    output = json.loads(out)
    assert set(output) == {"systemMessage"}
    return output["systemMessage"]


def test_payment_shows_verdict_and_link(tmp_path: Path, listener: int) -> None:
    stub_verify(tmp_path)
    write_log(tmp_path, payment())
    msg = system_message(run_hook(tmp_path, listener))
    assert msg.startswith("Receipt ready for PO-2038: ISSUES_FOUND (C4 blocked: Account")
    assert f"Open http://localhost:{listener}/?state=live" in msg
    assert "start it with" not in msg
    assert (tmp_path / "plugin-data" / "reported.json").is_file()


def test_clean_receipt_says_verified(tmp_path: Path, listener: int) -> None:
    clean = {**RECEIPT, "verdict": "VERIFIED", "checks": [RECEIPT["checks"][0]]}
    stub_verify(tmp_path, clean)
    write_log(tmp_path, payment())
    msg = system_message(run_hook(tmp_path, listener))
    assert (
        msg == f"Receipt ready for PO-2038: VERIFIED. Open http://localhost:{listener}/?state=live"
    )


def test_default_port_is_8000(tmp_path: Path) -> None:
    stub_verify(tmp_path)
    write_log(tmp_path, payment())
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    env["CLAUDE_PLUGIN_DATA"] = str(tmp_path / "plugin-data")
    env.pop("RECEIPTS_PORTAL_PORT", None)
    done = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"session_id": SESSION}),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "http://localhost:8000/?state=live" in system_message(done.stdout)


def test_reports_only_this_sessions_bill(tmp_path: Path, listener: int) -> None:
    # Verify writes receipts for every session's bills; this one sorts first but isn't ours.
    other = {**RECEIPT, "verdict": "VERIFIED", "checks": []}
    other["order"], other["bill"] = {"order_number": "PO-2037"}, {"bill_id": "BILL-07"}
    portal = tmp_path / "fixtures" / "portal"
    portal.mkdir(parents=True)
    (portal / "receipt_live_PO-2037.json").write_text(json.dumps(other))
    stub_verify(tmp_path)
    write_log(tmp_path, payment(session="s-other", ts=50.0, bill_id="BILL-07"), payment())
    msg = system_message(run_hook(tmp_path, listener))
    assert msg.startswith("Receipt ready for PO-2038: ISSUES_FOUND")
    assert "PO-2037" not in msg


def test_free_port_adds_start_command(tmp_path: Path) -> None:
    stub_verify(tmp_path)
    write_log(tmp_path, payment())
    port = free_port()
    msg = system_message(run_hook(tmp_path, port))
    start = f"cd {tmp_path.resolve()} && .venv/bin/python -m render.portal --port {port}"
    assert start in msg


def test_other_pay_bill_tool_is_silent(tmp_path: Path, listener: int) -> None:
    stub_verify(tmp_path)
    write_log(tmp_path, {**payment(), "tool": "mcp__evil__pay_bill"})
    assert run_hook(tmp_path, listener) == ""


def test_plugin_tool_name_counts(tmp_path: Path, listener: int) -> None:
    stub_verify(tmp_path)
    write_log(
        tmp_path, {**payment(), "tool": "mcp__plugin_ledgers-receipts_bakery-local__pay_bill"}
    )
    assert "PO-2038" in system_message(run_hook(tmp_path, listener))


def test_matches_pretooluse_matcher() -> None:
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    matcher = hooks["PreToolUse"][0]["matcher"]
    hook_src = HOOK.read_text()
    assert f're.compile(r"{matcher}")' in hook_src


@pytest.mark.parametrize(
    "broken",
    ["no-verify", "no-mcp", "bad-mcp", "no-bakery-server"],
)
def test_not_a_receipts_checkout_is_silent(tmp_path: Path, listener: int, broken: str) -> None:
    stub_verify(tmp_path)
    write_log(tmp_path, payment())
    mcp = tmp_path / ".mcp.json"
    if broken == "no-verify":
        (tmp_path / "receipts" / "verify.py").unlink()
    elif broken == "no-mcp":
        mcp.unlink()
    elif broken == "bad-mcp":
        mcp.write_text("{nope")
    else:
        mcp.write_text(json.dumps({"mcpServers": {"other": {}}}))
    assert run_hook(tmp_path, listener) == ""
    assert not (tmp_path / "fixtures").exists()  # the stub verifier never ran


def test_session_without_payment_is_silent(tmp_path: Path, listener: int) -> None:
    stub_verify(tmp_path)
    write_log(tmp_path, {"ts": 1.0, "session": SESSION, "tool": "Read", "input": {}})
    assert run_hook(tmp_path, listener) == ""


def test_no_log_is_silent(tmp_path: Path, listener: int) -> None:
    assert run_hook(tmp_path, listener) == ""


def test_other_sessions_payment_is_silent(tmp_path: Path, listener: int) -> None:
    stub_verify(tmp_path)
    write_log(tmp_path, payment(session="s-other"))
    assert run_hook(tmp_path, listener) == ""


def test_stop_hook_active_is_silent(tmp_path: Path, listener: int) -> None:
    stub_verify(tmp_path)
    write_log(tmp_path, payment())
    event = {"session_id": SESSION, "stop_hook_active": True}
    assert run_hook(tmp_path, listener, event) == ""


def test_reported_once_then_again_for_a_new_payment(tmp_path: Path, listener: int) -> None:
    stub_verify(tmp_path)
    write_log(tmp_path, payment(ts=100.0))
    assert "PO-2038" in system_message(run_hook(tmp_path, listener))
    assert run_hook(tmp_path, listener) == ""
    write_log(tmp_path, payment(ts=200.0))
    assert "PO-2038" in system_message(run_hook(tmp_path, listener))


@pytest.mark.parametrize("code", [1, 2])
def test_verify_failure_still_exits_zero(tmp_path: Path, listener: int, code: int) -> None:
    stub_verify(tmp_path, receipt=None, code=code)
    write_log(tmp_path, payment())
    msg = system_message(run_hook(tmp_path, listener))
    assert msg == f"Receipts: couldn't build the receipt (the verifier exited with code {code})."
    # A failed build isn't recorded, so the next turn tries again.
    assert "couldn't build" in system_message(run_hook(tmp_path, listener))


def test_verify_crash_still_exits_zero(tmp_path: Path, listener: int) -> None:
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(f"#!{sys.executable}\nraise RuntimeError('boom')\n")
    python.chmod(0o755)
    write_log(tmp_path, payment())
    msg = system_message(run_hook(tmp_path, listener))
    assert msg.startswith("Receipts: couldn't build the receipt (")
    assert "boom" not in msg


def test_missing_venv_reports(tmp_path: Path, listener: int) -> None:
    write_log(tmp_path, payment())
    assert "no .venv/bin/python" in system_message(run_hook(tmp_path, listener))


def test_receipt_for_another_bill_reports(tmp_path: Path, listener: int) -> None:
    stub_verify(tmp_path)
    write_log(tmp_path, payment(bill_id="BILL-07"))
    msg = system_message(run_hook(tmp_path, listener))
    assert msg == "Receipts: couldn't build the receipt (no receipt was written for bill BILL-07)."


def test_bad_stdin_still_exits_zero(tmp_path: Path, listener: int) -> None:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    done = subprocess.run(
        [sys.executable, str(HOOK)],
        check=False,
        input="{nope",
        env=env,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0
    assert "wasn't valid JSON" in system_message(done.stdout)


def test_hooks_json_registers_stop() -> None:
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    (entry,) = hooks["Stop"][0]["hooks"]
    assert entry["command"] == 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/show_receipt.py"'
    assert entry["timeout"] == 30
